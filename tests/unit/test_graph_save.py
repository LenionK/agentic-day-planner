"""Saving the plan at the end of the graph, with an in-memory repository."""

import json
from datetime import date

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from planner.agents.graph import (
    ASK,
    KEEP,
    REPLACE,
    SAVE,
    SKIP,
    build_graph,
    route_after_existing_day,
    route_before_save,
)
from planner.db.store import SavedDay
from planner.solver.models import DayConfig, ScheduledTask, Task
from tests.fakes import FakeClient, FakePlanRepository

DAY_DATE = date(2026, 10, 20)
DAY = DayConfig(day_start_min=480, day_end_min=1080)

PARSED = json.dumps(
    {"tasks": [{"source": "studiare 2 ore", "title": "Studio", "duration_min": 120}]}
)
DAY_IS_FINE = json.dumps({"assessment": "Va bene.", "too_empty": False, "suggestions": []})

OLD_DAY = SavedDay(
    id=7,
    day_date=DAY_DATE,
    user_input="palestra alle 18",
    day=DAY,
    tasks=[Task(id="t1", title="Palestra", duration_min=60, fixed_start_min=1020)],
    sources={"t1": "palestra alle 18"},
    scheduled=[ScheduledTask(task_id="t1", title="Palestra", start_min=1020, end_min=1080)],
)


def run_until_save(repository, thread_id: str, *, with_date: bool = True) -> tuple:
    """Run the graph through confirmation and critic; return graph, config and the result."""
    graph = build_graph(
        FakeClient([PARSED, DAY_IS_FINE]), checkpointer=InMemorySaver(), repository=repository
    )
    config = {"configurable": {"thread_id": thread_id}}
    start = {"user_input": "studiare 2 ore", "day": DAY}
    if with_date:
        start["day_date"] = DAY_DATE
    graph.invoke(start, config)
    result = graph.invoke(Command(resume={"edits": {}}), config)
    return graph, config, result


def test_new_date_is_saved_without_questions():
    repository = FakePlanRepository()

    _, _, final = run_until_save(repository, "nuova")

    assert "__interrupt__" not in final
    assert final["save_result"]["saved"] is True
    assert repository.saves == [(DAY_DATE, False)]
    saved = repository.days[DAY_DATE]
    assert [t.title for t in saved.tasks] == ["Studio"]
    assert [(s.start_min, s.end_min) for s in saved.scheduled] == [(480, 600)]
    assert saved.sources == {"t1": "studiare 2 ore"}


def test_without_a_date_the_plan_is_not_saved():
    repository = FakePlanRepository()

    _, _, final = run_until_save(repository, "senza-data", with_date=False)

    assert final["save_result"]["saved"] is False
    assert "data" in final["save_result"]["message"]
    assert repository.saves == []


def test_without_a_repository_the_graph_ends_after_the_critic():
    _, _, final = run_until_save(None, "senza-archivio")

    assert "__interrupt__" not in final
    assert "save_result" not in final


def test_existing_date_shows_both_plans_and_asks():
    repository = FakePlanRepository(OLD_DAY)

    _, _, paused = run_until_save(repository, "esistente")

    (question,) = paused["__interrupt__"]
    assert question.value["step"] == "existing_day"
    assert question.value["day_date"] == "2026-10-20"
    assert question.value["saved"]["user_input"] == "palestra alle 18"
    assert question.value["saved"]["scheduled"] == [
        {"title": "Palestra", "start": "17:00", "end": "18:00"}
    ]
    assert question.value["new"]["scheduled"] == [
        {"title": "Studio", "start": "08:00", "end": "10:00"}
    ]
    assert repository.saves == []  # niente è stato scritto prima della risposta


def test_replace_saves_the_new_day_in_place_of_the_old_one():
    repository = FakePlanRepository(OLD_DAY)
    graph, config, _ = run_until_save(repository, "sostituisci")

    final = graph.invoke(Command(resume={"choice": "replace"}), config)

    assert final["save_result"]["saved"] is True
    assert "precedente" in final["save_result"]["message"]
    assert repository.saves == [(DAY_DATE, True)]
    assert [t.title for t in repository.days[DAY_DATE].tasks] == ["Studio"]


def test_keep_leaves_the_saved_day_untouched():
    repository = FakePlanRepository(OLD_DAY)
    graph, config, _ = run_until_save(repository, "mantieni")

    final = graph.invoke(Command(resume={"choice": "keep"}), config)

    assert "__interrupt__" not in final
    assert final["save_result"]["saved"] is False
    assert repository.saves == []
    assert repository.days[DAY_DATE] == OLD_DAY


def test_invalid_choice_keeps_the_graph_paused():
    repository = FakePlanRepository(OLD_DAY)
    graph, config, _ = run_until_save(repository, "scelta-errata")

    with pytest.raises(ValidationError):
        graph.invoke(Command(resume={"choice": "merge"}), config)  # non ancora disponibile
    assert graph.get_state(config).next == ("ask_existing_day",)


def test_date_saved_in_the_meantime_becomes_a_message_not_a_crash():
    repository = FakePlanRepository()
    repository.conflict_on_save = True

    _, _, final = run_until_save(repository, "concorrente")

    assert final["save_result"]["saved"] is False
    assert "nel frattempo" in final["save_result"]["message"]


@pytest.mark.parametrize(
    ("state", "label"),
    [
        ({"existing_day": None}, SKIP),
        ({"day_date": DAY_DATE, "existing_day": None}, SAVE),
        ({"day_date": DAY_DATE, "existing_day": {"user_input": "x"}}, ASK),
    ],
)
def test_route_before_save(state, label):
    assert route_before_save(state) == label


@pytest.mark.parametrize(("choice", "label"), [("replace", REPLACE), ("keep", KEEP)])
def test_route_after_existing_day(choice, label):
    assert route_after_existing_day({"save_choice": choice}) == label
