import uuid
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from planner.agents.approval import plan_summary
from planner.agents.graph import all_warnings, build_graph
from planner.api.schemas import PlanQuestion, PlanRequest, PlanResult, ResumeRequest
from planner.config import Settings
from planner.db.repository import PostgresPlanRepository, PostgresPreferenceRepository
from planner.llm.factory import build_embedder, build_llm_client
from planner.solver.models import DayConfig


def database_available(url: str) -> bool:
    """Whether PostgreSQL answers now (the API works without it, without saving)."""
    try:
        with psycopg.connect(url, connect_timeout=3):
            return True
    except psycopg.OperationalError:
        return False


def build_planner_graph(settings: Settings, with_database: bool):
    """The graph with Ollama, and with saving and memory if the database is there."""
    return build_graph(
        build_llm_client(settings),
        checkpointer=InMemorySaver(),
        repository=PostgresPlanRepository(settings.database_url) if with_database else None,
        embedder=build_embedder(settings),
        preferences=PostgresPreferenceRepository(settings.database_url) if with_database else None,
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
    return PlanResult(
        thread_id=thread_id,
        plan=plan,
        critique=result["critique"],
        save_result=result.get("save_result"),
        preference_result=result.get("preference_result"),
    )


def create_app(graph=None) -> FastAPI:
    """Create the API application. Tests pass their own graph; otherwise it is built at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if graph is None:
            settings = Settings()
            app.state.database = database_available(settings.database_url)
            app.state.graph = build_planner_graph(settings, app.state.database)
        else:
            app.state.database = False
            app.state.graph = graph
        yield  # da qui l'app serve le richieste; dopo yield, la chiusura

    app = FastAPI(title="Agentic Day Planner", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        """Whether the API is up"""
        return {"status": "ok", "database": app.state.database}

    @app.post("/plans")
    def start_plan(body: PlanRequest) -> PlanQuestion | PlanResult:
        """Start planning a day: returns the first question of the graph."""
        thread_id = str(uuid.uuid4())  # una conversazione nuova per ogni frase
        config = {"configurable": {"thread_id": thread_id}}
        start = {"user_input": body.text, "day": DayConfig(), "day_date": body.day_date}
        result = app.state.graph.invoke(start, config)
        return reply(thread_id, result)

    @app.post("/plans/{thread_id}/resume")
    def resume_plan(thread_id: str, body: ResumeRequest) -> PlanQuestion | PlanResult:
        """Answer the question the graph is waiting on: returns the next one, or the plan."""
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = app.state.graph.get_state(config)
        if not snapshot.values:
            raise HTTPException(status_code=404, detail="Pianificazione inesistente.")
        if not snapshot.next:
            raise HTTPException(status_code=409, detail="Pianificazione già conclusa.")
        try:
            result = app.state.graph.invoke(Command(resume=body.answer), config)
        except ValidationError as err:
            # risposta non valida: il grafo resta in pausa e il client può riprovare
            detail = err.errors(include_url=False, include_context=False)
            raise HTTPException(status_code=422, detail=detail) from err
        return reply(thread_id, result)

    return app


app = create_app()
