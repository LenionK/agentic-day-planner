import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from planner.agents.graph import build_graph
from planner.api.app import create_app
from tests.fakes import FakeClient


def parser_answer(*titles: str) -> str:
    """What the fake LLM answers to the parser: one 45-minute task per title."""
    return json.dumps(
        {"tasks": [{"source": t.lower(), "title": t, "duration_min": 45} for t in titles]}
    )


def start_api(llm: FakeClient) -> TestClient:
    """The API with a graph on the fake LLM. Use it in a `with`: that runs the lifespan."""
    return TestClient(create_app(build_graph(llm, checkpointer=InMemorySaver())))


def test_each_plan_gets_its_own_thread_and_question():
    llm = FakeClient([parser_answer("Dentista", "Palestra"), parser_answer("Spesa")])
    with start_api(llm) as client:
        first = client.post(
            "/plans", json={"text": "dentista e palestra", "day_date": "2026-11-03"}
        )
        second = client.post("/plans", json={"text": "spesa", "day_date": "2026-11-04"})

    assert first.status_code == 200
    assert first.json()["step"] == "confirm_tasks"
    assert [t["title"] for t in first.json()["question"]["tasks"]] == ["Dentista", "Palestra"]
    assert [t["title"] for t in second.json()["question"]["tasks"]] == ["Spesa"]
    assert first.json()["thread_id"] != second.json()["thread_id"]


def test_sentence_and_date_reach_the_graph():
    llm = FakeClient([parser_answer("Studio")])
    with start_api(llm) as client:
        reply = client.post("/plans", json={"text": "studio tre ore", "day_date": "2026-11-03"})
        config = {"configurable": {"thread_id": reply.json()["thread_id"]}}
        state = client.app.state.graph.get_state(config).values

    assert llm.calls[0][-1] == {"role": "user", "content": "studio tre ore"}
    assert state["day_date"] == date(2026, 11, 3)


@pytest.mark.parametrize(
    "body",
    [
        {"day_date": "2026-11-03"},
        {"text": "", "day_date": "2026-11-03"},
        {"text": "studio", "day_date": "domani"},
        {"text": "studio"},
    ],
)
def test_invalid_request_is_rejected_before_the_graph(body):
    llm = FakeClient([])
    with start_api(llm) as client:
        reply = client.post("/plans", json=body)

    assert reply.status_code == 422
    assert llm.calls == []
