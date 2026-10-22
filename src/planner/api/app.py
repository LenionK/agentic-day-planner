import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from ollama import Client
from pydantic import ValidationError

from planner.agents.approval import approval, plan_summary
from planner.agents.graph import all_warnings, build_graph
from planner.api.schemas import (
    PlanQuestion,
    PlanRequest,
    PlanResult,
    ResumeRequest,
    SavedDayView,
)
from planner.config import Settings
from planner.db.migrate import upgrade_database
from planner.db.preferences import SavedPreference
from planner.db.repository import PostgresPlanRepository, PostgresPreferenceRepository
from planner.export.ics import day_to_ics
from planner.llm.factory import build_embedder, build_llm_client
from planner.llm.ollama_models import ModelDownloads, start_model_check
from planner.messages import LANGUAGES, Language, say
from planner.solver.models import DayConfig, fmt_time

STATIC = Path(__file__).parent / "static"  # la pagina web: index.html, app.js, style.css
DEFAULT_LANGUAGE: Language = "en"  # se il client non chiede una lingua che conosciamo


def request_language(request: Request) -> Language:
    """The language the client asks for in Accept-Language, English if none is supported.

    The header lists languages with an optional weight, the preferred first:
    "it-IT,it;q=0.9,en;q=0.8" -> "it". Only the main part of each tag counts (it-IT -> it).
    """
    ranked = []
    for position, part in enumerate(request.headers.get("accept-language", "").split(",")):
        tag, _, weight = part.strip().partition(";")
        try:
            quality = float(weight.strip().removeprefix("q=")) if weight else 1.0
        except ValueError:
            quality = 0.0  # un peso scritto male non deve far fallire la richiesta
        ranked.append((-quality, position, tag.strip().lower().split("-")[0]))
    for _, _, code in sorted(ranked):
        if code in LANGUAGES:
            return code
    return DEFAULT_LANGUAGE


def database_available(url: str) -> bool:
    """Whether PostgreSQL answers now (the API works without it, without saving)."""
    try:
        with psycopg.connect(url, connect_timeout=3):
            return True
    except psycopg.OperationalError:
        return False


def build_planner_graph(settings: Settings, repository, preferences):
    """The graph with Ollama; with saving and memory if the repositories are given."""
    return build_graph(
        build_llm_client(settings),
        checkpointer=InMemorySaver(),
        repository=repository,
        embedder=build_embedder(settings),
        preferences=preferences,
    )


def reply(thread_id: str, result: dict) -> PlanQuestion | PlanResult:
    """What the caller sees: the question the graph is waiting on, or the finished plan."""
    if "__interrupt__" in result:
        (question,) = result["__interrupt__"]
        return PlanQuestion(
            thread_id=thread_id, step=question.value["step"], question=question.value
        )
    plan = plan_summary(result["schedule"], result["tasks"], all_warnings(result))
    plan.pop("step")  # il piano finito non è una domanda
    confirmed = approval(result["tasks"], result["rejected"], [])
    slots = {
        item.task_id: f"{fmt_time(item.start_min)}–{fmt_time(item.end_min)}"
        for item in result["schedule"].scheduled
    }
    candidates = result.get("preference_candidates")
    return PlanResult(
        thread_id=thread_id,
        plan=plan,
        critique=result["critique"],
        tasks=[{**task, "slot": slots.get(task["id"])} for task in confirmed["tasks"]],
        rejected=confirmed["rejected"],
        save_result=result.get("save_result"),
        preference_result=result.get("preference_result"),
        preference_candidates=None if candidates is None else len(candidates),
    )


def available(store, language: Language):
    """The repository, or 503 if the API runs without the database."""
    if store is None:
        raise HTTPException(status_code=503, detail=say("database_unavailable", language))
    return store


def models_not_ready(downloads: ModelDownloads | None, language: Language) -> str | None:
    """Why a new plan cannot start yet (Ollama down, a model downloading), or None."""
    if downloads is None:
        return None  # i test passano un grafo con un LLM finto: nessun modello da aspettare
    if downloads.snapshot()["ollama"] is False:
        return say("ollama_down", language)
    waiting = downloads.waiting_for()
    if waiting is None:
        return None
    model, state = waiting
    if state["state"] == "error":
        return say("model_error", language, model=model, error=state["error"])
    if state["state"] == "downloading":
        return say("model_downloading", language, model=model, percent=state["percent"])
    return say("models_checking", language)


def create_app(graph=None, repository=None, preferences=None, models=None) -> FastAPI:
    """Create the API application.

    Tests pass their own graph and repositories (and, to test the wait, the model
    downloads); otherwise everything is built at startup: the database is brought to the
    last revision, and the Ollama models are checked and downloaded in the background.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = Settings()
        # qui e non al primo download: un fuso scritto male in .env si scopre all'avvio
        app.state.timezone = ZoneInfo(settings.timezone)
        if graph is None:
            app.state.database = database_available(settings.database_url)
            url = settings.database_url
            app.state.repository = PostgresPlanRepository(url) if app.state.database else None
            app.state.preferences = (
                PostgresPreferenceRepository(url) if app.state.database else None
            )
            app.state.graph = build_planner_graph(
                settings, app.state.repository, app.state.preferences
            )
            if app.state.database:
                upgrade_database(url)  # le tabelle mancanti: niente `alembic upgrade head` a mano
            # all'avvio si cancellano le giornate più vecchie di 2 settimane
            app.state.purged = app.state.repository.purge_old_days() if app.state.database else 0
            # i modelli mancanti si scaricano in sottofondo: l'API risponde già, e /health dice
            # a che punto sono (il primo download di qwen2.5:7b richiede minuti)
            app.state.models = ModelDownloads([settings.llm_model, settings.embed_model])
            start_model_check(Client(host=settings.ollama_host), app.state.models)
        else:
            app.state.database = repository is not None
            app.state.graph = graph
            app.state.repository = repository
            app.state.preferences = preferences
            app.state.purged = 0
            app.state.models = models
        yield  # da qui l'app serve le richieste; dopo yield, la chiusura

    app = FastAPI(title="Agentic Day Planner", lifespan=lifespan)
    # app.js e style.css della pagina; la pagina stessa è servita su "/"
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def revalidate_page_files(request: Request, call_next):
        # senza Cache-Control il browser può riusare un app.js vecchio con un index.html nuovo:
        # lo script cerca bottoni che non ci sono più, va in errore e la pagina non risponde.
        # no-cache = "ricontrolla sempre": con l'ETag invariato il server risponde 304, senza
        # rimandare il file, quindi resta veloce ma non usa mai una versione vecchia
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.exception_handler(psycopg.OperationalError)
    def database_down(request: Request, exc: psycopg.OperationalError) -> JSONResponse:
        # il database si è spento dopo l'avvio: un 503 chiaro invece di un errore del server
        detail = say("database_down", request_language(request))
        return JSONResponse(status_code=503, content={"detail": detail})

    @app.exception_handler(ConnectionError)
    def ollama_down(request: Request, exc: ConnectionError) -> JSONResponse:
        # Ollama si è spento durante una pianificazione: un 503 chiaro, non un errore del server
        detail = say("ollama_down", request_language(request))
        return JSONResponse(status_code=503, content={"detail": detail})

    @app.get("/health")
    def health() -> dict:
        """Whether the API is up, the database answered, old days were purged, the models are ready.

        "models" tells for each Ollama model whether it is ready, downloading (with the
        percent) or failed; "ollama" whether Ollama answers (None before the first check).
        """
        models = app.state.models.snapshot() if app.state.models else {"ollama": None, "models": {}}
        return {
            "status": "ok",
            "database": app.state.database,
            "purged": app.state.purged,
            **models,
        }

    @app.get("/", include_in_schema=False)
    def page() -> FileResponse:
        """The web page to use the planner from a browser."""
        return FileResponse(STATIC / "index.html")

    @app.post("/plans")
    def start_plan(body: PlanRequest, request: Request) -> PlanQuestion | PlanResult:
        """Start planning a day: returns the first question of the graph.

        The messages of the plan (warnings, saving) are in the language of Accept-Language.
        """
        language = request_language(request)
        # i modelli si stanno ancora scaricando, o Ollama non risponde: lo si dice subito
        reason = models_not_ready(app.state.models, language)
        if reason:
            raise HTTPException(status_code=503, detail=reason)
        thread_id = str(uuid.uuid4())  # una conversazione nuova per ogni frase
        config = {"configurable": {"thread_id": thread_id, "language": language}}
        start = {"user_input": body.text, "day": DayConfig(), "day_date": body.day_date}
        result = app.state.graph.invoke(start, config)
        return reply(thread_id, result)

    @app.post("/plans/{thread_id}/resume")
    def resume_plan(
        thread_id: str, body: ResumeRequest, request: Request
    ) -> PlanQuestion | PlanResult:
        """Answer the question the graph is waiting on: returns the next one, or the plan."""
        language = request_language(request)
        # la lingua di questa richiesta: cambiata a metà, i messaggi scritti da qui in poi la seguono
        config = {"configurable": {"thread_id": thread_id, "language": language}}
        snapshot = app.state.graph.get_state(config)
        if not snapshot.values:
            raise HTTPException(status_code=404, detail=say("plan_not_found", language))
        if not snapshot.next:
            raise HTTPException(status_code=409, detail=say("plan_finished", language))
        try:
            result = app.state.graph.invoke(Command(resume=body.answer), config)
        except ValidationError as err:
            # risposta non valida: il grafo resta in pausa e il client può riprovare
            detail = err.errors(include_url=False, include_context=False)
            raise HTTPException(status_code=422, detail=detail) from err
        return reply(thread_id, result)

    @app.get("/days")
    def history(request: Request) -> list[SavedDayView]:
        """The saved days, most recent first, each with its plan."""
        repository = available(app.state.repository, request_language(request))
        plans = repository.history_plans()
        return [
            SavedDayView(
                day_date=day.day_date,
                user_input=day.user_input,
                day_minutes=day.day_minutes,
                busy_minutes=day.busy_minutes,
                free_minutes=day.day_minutes - day.busy_minutes,
                scheduled=[
                    {"title": s.title, "start": fmt_time(s.start_min), "end": fmt_time(s.end_min)}
                    for s in plans.get(day.day_date, [])
                ],
            )
            for day in repository.history()
        ]

    @app.get("/days/{day_date}/plan.ics")
    def export_day(day_date: date, request: Request) -> Response:
        """The saved plan of a day as an iCalendar file, to import into a calendar app."""
        language = request_language(request)
        saved = available(app.state.repository, language).load(day_date)
        if saved is None:
            detail = say("no_saved_plan", language, day=day_date.isoformat())
            raise HTTPException(status_code=404, detail=detail)
        return Response(
            content=day_to_ics(saved, app.state.timezone),
            media_type="text/calendar",
            headers={"Content-Disposition": f'attachment; filename="piano-{day_date}.ics"'},
        )

    @app.get("/preferences")
    def remembered_preferences(request: Request) -> list[SavedPreference]:
        """The remembered preferences, used by the critic for the next days."""
        return available(app.state.preferences, request_language(request)).all()

    @app.delete("/preferences/{pref_id}", status_code=204)
    def forget_preference(pref_id: int, request: Request) -> None:
        """Delete a remembered preference that no longer holds."""
        language = request_language(request)
        if not available(app.state.preferences, language).delete(pref_id):
            raise HTTPException(status_code=404, detail=say("preference_not_found", language))

    return app


app = create_app()
