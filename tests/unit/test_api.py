import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from planner.agents.graph import build_graph
from planner.api.app import create_app
from tests.fakes import FakeClient, FakePlanRepository

RUN = {"title": "Corsa", "category": "attività fisica", "duration_min": 45, "reason": "muoversi"}


def parser_answer(*titles: str) -> str:
    """What the fake LLM answers to the parser: one 45-minute task per title."""
    return json.dumps(
        {"tasks": [{"source": t.lower(), "title": t, "duration_min": 45} for t in titles]}
    )


def critic_answer(*suggestions: dict) -> str:
    """The critic's answer: with suggestions the day is too empty, without it is fine."""
    return json.dumps(
        {
            "assessment": "Giornata vuota." if suggestions else "Giornata equilibrata.",
            "too_empty": bool(suggestions),
            "suggestions": list(suggestions),
        }
    )


def start_api(llm: FakeClient, repository: FakePlanRepository | None = None) -> TestClient:
    """The API with a graph on the fake LLM. Use it in a `with`: that runs the lifespan."""
    graph = build_graph(llm, checkpointer=InMemorySaver(), repository=repository)
    return TestClient(create_app(graph))


def new_plan(client: TestClient, text: str = "studio") -> str:
    """Start a plan for 3 November 2026 and return its thread_id."""
    reply = client.post("/plans", json={"text": text, "day_date": "2026-11-03"})
    return reply.json()["thread_id"]


def answer(client: TestClient, thread_id: str, response: dict):
    return client.post(f"/plans/{thread_id}/resume", json={"answer": response})


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


def test_answer_with_edits_runs_the_plan_to_the_end():
    llm = FakeClient([parser_answer("Studio"), critic_answer()])
    with start_api(llm) as client:
        thread_id = new_plan(client)
        edits = {"t1": {"duration_min": 90, "fixed_start": "10:00"}}
        reply = answer(client, thread_id, {"edits": edits})

    assert reply.status_code == 200
    result = reply.json()
    assert result["step"] == "done"
    assert result["thread_id"] == thread_id
    # le correzioni sono arrivate allo scheduler: 90 minuti dalle 10
    assert result["plan"]["scheduled"] == [{"title": "Studio", "start": "10:00", "end": "11:30"}]
    assert result["critique"]["assessment"] == "Giornata equilibrata."
    assert result["save_result"] is None  # senza archivio non si salva


def test_each_answer_gets_the_next_question():
    llm = FakeClient([parser_answer("Studio"), critic_answer(RUN)])
    with start_api(llm) as client:
        thread_id = new_plan(client)
        suggestions = answer(client, thread_id, {"edits": {}})
        final = answer(client, thread_id, {"accepted": []})

    assert suggestions.json()["step"] == "suggest_activities"
    assert [s["title"] for s in suggestions.json()["question"]["suggestions"]] == ["Corsa"]
    assert final.json()["step"] == "done"


def test_invalid_answer_keeps_the_question_and_a_retry_works():
    llm = FakeClient([parser_answer("Studio"), critic_answer()])
    with start_api(llm) as client:
        thread_id = new_plan(client)
        wrong = answer(client, thread_id, {"edits": {"t1": {"fixed_start": "alle tre"}}})
        retry = answer(client, thread_id, {"edits": {}})

    assert wrong.status_code == 422
    assert wrong.json()["detail"][0]["loc"] == ["edits", "t1", "fixed_start"]
    assert retry.status_code == 200
    assert retry.json()["step"] == "done"


def test_empty_answer_is_rejected_before_the_graph():
    llm = FakeClient([parser_answer("Studio")])
    with start_api(llm) as client:
        thread_id = new_plan(client)
        answer(client, thread_id, {"edits": {"t1": {"priority": 9}}})
        empty = answer(client, thread_id, {})
        config = {"configurable": {"thread_id": thread_id}}
        waiting = client.app.state.graph.get_state(config).next

    # l'errore è sul corpo, non la risposta sbagliata di prima ripresentata dal grafo
    assert empty.status_code == 422
    assert empty.json()["detail"][0]["loc"] == ["body", "answer"]
    assert waiting == ("ask_approval",)


def test_answer_to_an_unknown_plan_is_not_found():
    llm = FakeClient([])
    with start_api(llm) as client:
        reply = answer(client, "nessuno", {"edits": {}})

    assert reply.status_code == 404
    assert llm.calls == []


def test_answer_after_the_end_is_a_conflict():
    llm = FakeClient([parser_answer("Studio"), critic_answer()])
    with start_api(llm) as client:
        thread_id = new_plan(client)
        answer(client, thread_id, {"edits": {}})
        again = answer(client, thread_id, {"edits": {}})

    assert again.status_code == 409
    assert len(llm.calls) == 2  # parser e critico, nient'altro


def test_plan_is_saved_for_the_date_of_the_request():
    repository = FakePlanRepository()
    llm = FakeClient([parser_answer("Studio"), critic_answer()])
    with start_api(llm, repository) as client:
        thread_id = new_plan(client)
        reply = answer(client, thread_id, {"edits": {}})

    assert reply.json()["save_result"]["saved"] is True
    assert list(repository.days) == [date(2026, 11, 3)]
    assert [task.title for task in repository.days[date(2026, 11, 3)].tasks] == ["Studio"]
