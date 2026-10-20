import uuid
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver

from planner.agents.graph import build_graph
from planner.api.schemas import PlanQuestion, PlanRequest
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
    def start_plan(body: PlanRequest) -> PlanQuestion:
        """Start planning a day: returns the first question of the graph."""
        thread_id = str(uuid.uuid4())  # una conversazione nuova per ogni frase
        config = {"configurable": {"thread_id": thread_id}}
        start = {"user_input": body.text, "day": DayConfig(), "day_date": body.day_date}
        result = app.state.graph.invoke(start, config)
        (question,) = result["__interrupt__"]
        return PlanQuestion(
            thread_id=thread_id, step=question.value["step"], question=question.value
        )

    return app


app = create_app()
