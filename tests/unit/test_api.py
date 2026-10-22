import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import psycopg
import pytest
from fastapi.testclient import TestClient
from icalendar import Calendar
from langgraph.checkpoint.memory import InMemorySaver
from starlette.requests import Request

from planner.agents.graph import build_graph
from planner.api.app import create_app, request_language
from tests.fakes import (
    FakeClient,
    FakeEmbedder,
    FakePlanRepository,
    FakePreferenceRepository,
    unit,
)
from tests.unit.test_ics import saved_day

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


def start_api(
    llm: FakeClient,
    repository: FakePlanRepository | None = None,
    preferences: FakePreferenceRepository | None = None,
) -> TestClient:
    """The API with a graph on the fake LLM. Use it in a `with`: that runs the lifespan.

    The repositories, if given, are shared by the graph (saving, memory) and the app
    (export, history, preferences); with both, the graph remembers preferences.
    """
    embedder = FakeEmbedder() if preferences is not None else None
    graph = build_graph(
        llm,
        checkpointer=InMemorySaver(),
        repository=repository,
        embedder=embedder,
        preferences=preferences,
    )
    return TestClient(create_app(graph, repository, preferences))


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


def ics_events(content: bytes) -> list[tuple[str, datetime]]:
    """(title, start) of each event in an .ics file."""
    return [
        (str(e["SUMMARY"]), e.decoded("DTSTART"))
        for e in Calendar.from_ical(content).walk("VEVENT")
    ]


def test_saved_day_downloads_as_a_calendar_file():
    with start_api(FakeClient([]), FakePlanRepository(saved_day())) as client:
        reply = client.get("/days/2026-11-03/plan.ics")

    assert reply.status_code == 200
    assert reply.headers["content-type"].startswith("text/calendar")
    assert reply.headers["content-disposition"] == 'attachment; filename="piano-2026-11-03.ics"'
    assert ics_events(reply.content) == [
        ("Studio", datetime(2026, 11, 3, 9, 30, tzinfo=ZoneInfo("Europe/Rome"))),
        ("Dentista", datetime(2026, 11, 3, 15, 0, tzinfo=ZoneInfo("Europe/Rome"))),
    ]


def test_plan_saved_through_the_api_can_be_exported():
    repository = FakePlanRepository()
    llm = FakeClient([parser_answer("Studio"), critic_answer()])
    with start_api(llm, repository) as client:
        thread_id = new_plan(client)
        answer(client, thread_id, {"edits": {"t1": {"fixed_start": "17:15"}}})
        reply = client.get("/days/2026-11-03/plan.ics")

    assert ics_events(reply.content) == [
        ("Studio", datetime(2026, 11, 3, 17, 15, tzinfo=ZoneInfo("Europe/Rome")))
    ]


@pytest.mark.parametrize(
    ("accept_language", "detail"),
    [
        ("it-IT,it;q=0.9", "Nessun piano salvato per il 2026-11-04."),
        ("en-GB,en;q=0.9", "No plan saved for 2026-11-04."),
    ],
)
def test_day_without_a_saved_plan_is_not_found(accept_language, detail):
    with start_api(FakeClient([]), FakePlanRepository(saved_day())) as client:
        reply = client.get(
            "/days/2026-11-04/plan.ics", headers={"Accept-Language": accept_language}
        )

    assert reply.status_code == 404
    assert reply.json()["detail"] == detail


def test_export_without_database_is_unavailable():
    with start_api(FakeClient([])) as client:
        reply = client.get("/days/2026-11-03/plan.ics")

    assert reply.status_code == 503


def test_export_needs_a_real_date():
    with start_api(FakeClient([]), FakePlanRepository(saved_day())) as client:
        reply = client.get("/days/domani/plan.ics")

    assert reply.status_code == 422


def test_final_result_lists_the_confirmed_tasks_and_where_they_ended():
    tasks = [
        # 200 + 700 minuti: più delle 14 ore della giornata, il progetto resta fuori
        {"source": "studio", "title": "Studio", "duration_min": 200, "priority": 5},
        {"source": "progetto", "title": "Progetto", "duration_min": 700, "priority": 1},
    ]
    llm = FakeClient([json.dumps({"tasks": tasks}), critic_answer()])
    with start_api(llm) as client:
        thread_id = new_plan(client)
        review = answer(client, thread_id, {"edits": {}})
        final = answer(client, thread_id, {"accept": True}).json()

    assert review.json()["step"] == "review_plan"
    # confermati non vuol dire inseriti: il progetto c'è, ma senza orario
    assert [(t["title"], t["slot"]) for t in final["tasks"]] == [
        ("Studio", "08:00–11:20"),
        ("Progetto", None),
    ]
    assert final["rejected"] == []
    assert final["preference_candidates"] is None  # senza memoria il passo non c'è


def test_final_result_says_when_the_sentence_had_no_preferences():
    llm = FakeClient([parser_answer("Studio"), critic_answer(), json.dumps({"preferences": []})])
    with start_api(llm, FakePlanRepository(), FakePreferenceRepository()) as client:
        thread_id = new_plan(client)
        final = answer(client, thread_id, {"edits": {}}).json()

    assert final["preference_candidates"] == 0
    assert final["preference_result"] is None


def test_page_and_its_files_are_served_outside_the_api_docs():
    with start_api(FakeClient([])) as client:
        page = client.get("/")
        script = client.get("/static/app.js")
        style = client.get("/static/style.css")
        paths = client.get("/openapi.json").json()["paths"]

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert 'id="new-plan"' in page.text
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert style.status_code == 200
    assert "/" not in paths  # la pagina non fa parte dell'API


def test_health_says_whether_there_is_a_database():
    with start_api(FakeClient([])) as without:
        alone = without.get("/health").json()
    with start_api(FakeClient([]), FakePlanRepository()) as with_db:
        saving = with_db.get("/health").json()

    assert alone == {"status": "ok", "database": False, "purged": 0}
    assert saving["database"] is True


def test_history_lists_the_saved_days_with_their_plan():
    repository = FakePlanRepository(saved_day(), saved_day(date(2026, 11, 1)))
    with start_api(FakeClient([]), repository) as client:
        days = client.get("/days").json()

    assert [d["day_date"] for d in days] == ["2026-11-03", "2026-11-01"]  # la più recente prima
    assert days[0]["user_input"] == "studio, dentista e se riesco palestra"
    assert days[0]["free_minutes"] == 840 - 150  # giornata 8-22, studio 90 + dentista 60
    assert days[0]["scheduled"] == [
        {"title": "Studio", "start": "09:30", "end": "11:00"},
        {"title": "Dentista", "start": "15:00", "end": "16:00"},
    ]


def test_preferences_can_be_listed_and_forgotten():
    preferences = FakePreferenceRepository()
    morning = preferences.add("preferisce studiare la mattina", "studio la mattina", unit(1))
    preferences.add("evita riunioni il venerdì", "odio le riunioni del venerdì", unit(2))
    with start_api(FakeClient([]), FakePlanRepository(), preferences) as client:
        before = client.get("/preferences").json()
        deleted = client.delete(f"/preferences/{morning}")
        again = client.delete(f"/preferences/{morning}")
        after = client.get("/preferences").json()

    assert [p["text"] for p in before] == [
        "preferisce studiare la mattina",
        "evita riunioni il venerdì",
    ]
    assert before[0]["last_seen"] == "2026-11-03"
    assert deleted.status_code == 204
    assert again.status_code == 404
    assert [p["text"] for p in after] == ["evita riunioni il venerdì"]


@pytest.mark.parametrize(
    ("method", "url"),
    [("GET", "/days"), ("GET", "/preferences"), ("DELETE", "/preferences/1")],
)
def test_history_and_preferences_need_the_database(method, url):
    with start_api(FakeClient([])) as client:
        reply = client.request(method, url)

    assert reply.status_code == 503


class DownRepository(FakePlanRepository):
    """A repository whose database stopped answering after the API started."""

    def history(self):
        raise psycopg.OperationalError("connection refused")


def test_database_going_down_after_startup_is_a_clear_503():
    with start_api(FakeClient([]), DownRepository()) as client:
        english = client.get("/days")
        italian = client.get("/days", headers={"Accept-Language": "it"})

    assert english.status_code == 503
    assert english.json() == {"detail": "The database does not answer."}
    assert italian.json() == {"detail": "Database non raggiungibile."}


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "en"),  # nessuna richiesta: la lingua di default dell'API
        ("it-IT,it;q=0.9,en;q=0.8", "it"),
        ("en-US,en;q=0.9,it;q=0.8", "en"),
        ("fr-FR,fr;q=0.9,it;q=0.5", "it"),  # il francese non c'è: la prima lingua che conosciamo
        ("en;q=0.2,it;q=0.8", "it"),  # conta il peso, non l'ordine
        ("de-DE", "en"),
        ("it;q=abc,en", "en"),  # un peso scritto male vale zero, non è un errore
    ],
)
def test_the_language_comes_from_accept_language(header, expected):
    request = Request(
        {
            "type": "http",
            "headers": [] if header is None else [(b"accept-language", header.encode())],
        }
    )

    assert request_language(request) == expected


@pytest.mark.parametrize(
    ("accept_language", "warning", "saved"),
    [
        ("it", "Studio: ignorato fixed_start 18:00 (non compare nella frase)", "Piano salvato."),
        ("en", "Studio: fixed_start 18:00 ignored (not in the sentence)", "Plan saved."),
    ],
)
def test_the_messages_of_a_plan_are_in_the_language_asked(accept_language, warning, saved):
    # l'LLM inventa un orario che nella frase non c'è: il parser lo toglie e avvisa
    drafted = {"source": "studio", "title": "Studio", "duration_min": 60, "fixed_start": "18:00"}
    llm = FakeClient([json.dumps({"tasks": [drafted]}), critic_answer()])
    headers = {"Accept-Language": accept_language}
    with start_api(llm, FakePlanRepository()) as client:
        question = client.post(
            "/plans", json={"text": "studio", "day_date": "2026-11-03"}, headers=headers
        ).json()
        final = answer_in(client, question["thread_id"], {"edits": {}}, headers).json()

    assert question["question"]["warnings"] == [warning]
    assert final["save_result"]["message"] == saved


def test_messages_follow_a_language_changed_in_the_middle_of_a_plan():
    llm = FakeClient([parser_answer("Studio"), critic_answer()])
    with start_api(llm, FakePlanRepository()) as client:
        question = client.post(
            "/plans",
            json={"text": "studio", "day_date": "2026-11-03"},
            headers={"Accept-Language": "en"},
        ).json()
        final = answer_in(client, question["thread_id"], {"edits": {}}, {"Accept-Language": "it"})

    assert final.json()["save_result"]["message"] == "Piano salvato."


def answer_in(client: TestClient, thread_id: str, response: dict, headers: dict):
    return client.post(f"/plans/{thread_id}/resume", json={"answer": response}, headers=headers)
