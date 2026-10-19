"""Saving the plan, with an in-memory repository.

If the date is already saved, its tasks join the new ones right after the parser,
pinned at their times; the user can replace the saved day instead of merging.
"""

import json
from datetime import date

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from planner.agents.graph import build_graph
from planner.db.store import SavedDay
from planner.solver.models import DayConfig, ScheduledTask, Task
from tests.fakes import FakeClient, FakePlanRepository

DAY_DATE = date(2026, 10, 20)
DAY = DayConfig(day_start_min=480, day_end_min=1080)  # 08:00-18:00

DAY_IS_FINE = json.dumps({"assessment": "Va bene.", "too_empty": False, "suggestions": []})


def parsed(*drafts: dict) -> str:
    return json.dumps({"tasks": [{"source": d["title"].lower(), **d} for d in drafts]})


STUDY = parsed({"title": "Studio", "duration_min": 120})

OLD_DAY = SavedDay(
    id=7,
    day_date=DAY_DATE,
    user_input="palestra alle 16",
    day=DAY,
    tasks=[Task(id="t1", title="Palestra", duration_min=60, fixed_start_min=960)],
    sources={"t1": "palestra alle 16"},
    scheduled=[ScheduledTask(task_id="t1", title="Palestra", start_min=960, end_min=1020)],
)


def start(repository, thread_id: str, llm_answer: str = STUDY, *, with_date: bool = True):
    """Run the graph until the task confirmation; return graph, config, client, question."""
    client = FakeClient([llm_answer, DAY_IS_FINE])
    graph = build_graph(client, checkpointer=InMemorySaver(), repository=repository)
    config = {"configurable": {"thread_id": thread_id}}
    first = {"user_input": "studiare 2 ore", "day": DAY}
    if with_date:
        first["day_date"] = DAY_DATE
    paused = graph.invoke(first, config)
    (question,) = paused["__interrupt__"]
    return graph, config, client, question.value


def confirm(graph, config, **answer):
    return graph.invoke(Command(resume={"edits": {}} | answer), config)


def test_new_date_is_saved_without_questions():
    repository = FakePlanRepository()
    graph, config, _, question = start(repository, "nuova")

    final = confirm(graph, config)

    assert question["saved_day"] is None
    assert "__interrupt__" not in final
    assert final["save_result"] == {"saved": True, "day_id": 1, "message": "Piano salvato."}
    assert repository.saves == [(DAY_DATE, False)]
    saved = repository.days[DAY_DATE]
    assert [(t.title, s.start_min) for t, s in zip(saved.tasks, saved.scheduled, strict=True)] == [
        ("Studio", 480)
    ]


def test_without_a_date_the_plan_is_not_saved():
    repository = FakePlanRepository(OLD_DAY)
    graph, config, _, question = start(repository, "senza-data", with_date=False)

    final = confirm(graph, config)

    assert question["saved_day"] is None  # senza data non si cerca niente
    assert final["save_result"]["saved"] is False
    assert repository.saves == []


def test_without_a_repository_nothing_is_checked_or_saved():
    graph, config, _, question = start(None, "senza-archivio")

    final = confirm(graph, config)

    assert question["saved_day"] is None
    assert "save_result" not in final


def test_saved_date_is_shown_in_the_confirmation_with_the_new_tasks_apart():
    repository = FakePlanRepository(OLD_DAY)

    _, _, _, question = start(repository, "sovrapposta")

    assert question["saved_day"] == {
        "day_date": "2026-10-20",
        "user_input": "palestra alle 16",
        "replaced": False,
        "scheduled": [{"title": "Palestra", "start": "16:00", "end": "17:00"}],
        "unscheduled": [],
    }
    # solo i task nuovi sono modificabili, già rinumerati dopo quelli salvati
    assert [(t["id"], t["title"]) for t in question["tasks"]] == [("t2", "Studio")]
    assert repository.saves == []  # niente è scritto prima della fine


def test_merge_keeps_the_saved_tasks_in_place_and_saves_the_whole_day():
    repository = FakePlanRepository(OLD_DAY)
    graph, config, client, _ = start(repository, "unisci")

    final = confirm(graph, config)

    assert final["save_result"]["message"] == "Piano unito a quello già salvato."
    assert repository.saves == [(DAY_DATE, True)]  # la giornata salvata viene riscritta
    saved = repository.days[DAY_DATE]
    assert [t.title for t in saved.tasks] == ["Palestra", "Studio"]
    assert {s.title: s.start_min for s in saved.scheduled} == {"Palestra": 960, "Studio": 480}
    assert saved.user_input == "palestra alle 16 · studiare 2 ore"
    assert saved.tasks[0].required is False  # bloccata solo per il solver, non nei dati
    # il Critico ha visto la giornata intera, non solo i task nuovi
    assert "Palestra" in client.calls[1][1]["content"]


def test_replace_drops_the_saved_tasks():
    repository = FakePlanRepository(OLD_DAY)
    graph, config, client, _ = start(repository, "sostituisci")

    final = confirm(graph, config, replace_saved=True)

    assert final["save_result"]["message"] == "Piano salvato al posto di quello precedente."
    assert repository.saves == [(DAY_DATE, True)]
    saved = repository.days[DAY_DATE]
    assert [t.title for t in saved.tasks] == ["Studio"]
    assert saved.user_input == "studiare 2 ore"
    assert "Palestra" not in client.calls[1][1]["content"]


def test_saved_tasks_cannot_be_edited():
    repository = FakePlanRepository(OLD_DAY)
    graph, config, _, _ = start(repository, "bloccati")

    final = graph.invoke(Command(resume={"edits": {"t1": {"duration_min": 30}}}), config)

    assert any("t1" in w and "agenda" in w for w in final["edit_warnings"])
    assert repository.days[DAY_DATE].tasks[0].duration_min == 60


def test_new_task_that_does_not_fit_goes_to_review_and_saved_task_stays():
    repository = FakePlanRepository(OLD_DAY)
    too_long = parsed({"title": "Progetto", "duration_min": 600, "priority": 1})
    graph, config, _, _ = start(repository, "non-entra", too_long)

    paused = confirm(graph, config)

    (review,) = paused["__interrupt__"]
    assert review.value["step"] == "review_plan"
    assert review.value["unscheduled"] == ["Progetto"]
    assert review.value["scheduled"] == [{"title": "Palestra", "start": "16:00", "end": "17:00"}]


def test_date_saved_in_the_meantime_becomes_a_message_not_a_crash():
    repository = FakePlanRepository()
    repository.conflict_on_save = True
    graph, config, _, _ = start(repository, "concorrente")

    final = confirm(graph, config)

    assert final["save_result"]["saved"] is False
    assert "nel frattempo" in final["save_result"]["message"]
