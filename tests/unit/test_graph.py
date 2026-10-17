import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from planner.agents.graph import ACCEPT, EDIT, build_graph, route_after_review
from planner.solver.models import DayConfig
from tests.fakes import FakeClient


def llm_answer(*drafts: dict) -> str:
    return json.dumps({"tasks": [{"source": d["title"], **d} for d in drafts]})


def test_graph_parses_and_schedules():
    client = FakeClient(
        [
            llm_answer(
                {
                    "source": "devo studiare 2 ore",
                    "title": "Studio",
                    "duration_min": 120,
                    "priority": 5,
                },
                {
                    "source": "dentista alle 15",
                    "title": "Dentista",
                    "duration_min": 60,
                    "required": True,
                    "fixed_start": "15:00",
                },
            )
        ]
    )
    graph = build_graph(client, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "studio-dentista"}}
    day = DayConfig(day_start_min=480, day_end_min=1080)

    paused = graph.invoke(
        {"user_input": "devo studiare 2 ore, dentista alle 15", "day": day}, config
    )

    # il grafo si ferma alla conferma: i task ci sono, il piano non ancora
    assert "__interrupt__" in paused
    assert "schedule" not in paused
    assert [task.title for task in paused["tasks"]] == ["Studio", "Dentista"]

    # il chiamante riceve il riepilogo da mostrare all'utente
    (shown,) = paused["__interrupt__"]
    assert [(t["id"], t["fixed_start"]) for t in shown.value["tasks"]] == [
        ("t1", None),
        ("t2", "15:00"),
    ]

    final = graph.invoke(Command(resume={"edits": {}}), config)

    # la risposta dell'utente arriva nello stato, non viene persa
    assert final["user_response"] == {"edits": {}}
    plan = {item.title: item for item in final["schedule"].scheduled}
    assert set(plan) == {"Studio", "Dentista"}
    assert plan["Dentista"].start_min == 900
    assert final["rejected"] == []
    assert final["warnings"] == []


def test_graph_keeps_parser_warnings_and_rejected_tasks():
    client = FakeClient(
        [
            llm_answer(
                {"title": "Giro in bici", "duration_min": 60, "earliest_start": "10:30"},
                {
                    "source": "cena alle 25",
                    "title": "Cena",
                    "duration_min": 60,
                    "fixed_start": "25:00",
                },
            )
        ]
    )
    graph = build_graph(client, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "bici-cena"}}
    day = DayConfig(day_start_min=480, day_end_min=1080)

    paused = graph.invoke(
        {"user_input": "magari un giro in bici, cena alle 25", "day": day}, config
    )
    assert "schedule" not in paused

    final = graph.invoke(Command(resume={"edits": {}}), config)

    assert [item.title for item in final["schedule"].scheduled] == ["Giro in bici"]
    assert len(final["warnings"]) == 1
    assert [r.draft.title for r in final["rejected"]] == ["Cena"]


def paused_study_graph(thread_id: str):
    """A graph stopped at the confirmation, with one 120-minute task t1."""
    client = FakeClient(
        [llm_answer({"source": "studiare 2 ore", "title": "Studio", "duration_min": 120})]
    )
    graph = build_graph(client, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": thread_id}}
    day = DayConfig(day_start_min=480, day_end_min=1080)
    graph.invoke({"user_input": "studiare 2 ore", "day": day}, config)
    return graph, config


def test_graph_applies_user_edits_before_scheduling():
    graph, config = paused_study_graph("modifiche")

    final = graph.invoke(
        Command(resume={"edits": {"t1": {"duration_min": 45}, "t9": {"priority": 1}}}), config
    )

    (studio,) = final["schedule"].scheduled
    assert studio.end_min - studio.start_min == 45
    assert final["warnings"] == []  # avvisi del parser
    assert len(final["edit_warnings"]) == 1
    assert "t9" in final["edit_warnings"][0]


def test_graph_stays_paused_on_invalid_response_and_accepts_a_retry():
    graph, config = paused_study_graph("riprova")

    with pytest.raises(ValidationError):
        graph.invoke(Command(resume={"edits": {"t1": {"priority": 9}}}), config)
    assert graph.get_state(config).next == ("ask_approval",)

    final = graph.invoke(Command(resume={"edits": {"t1": {"priority": 2}}}), config)

    assert final["tasks"][0].priority == 2
    assert "schedule" in final


def pending(result: dict) -> dict:
    """The value of the interrupt the graph stopped at."""
    (interrupt_,) = result["__interrupt__"]
    return interrupt_.value


def test_the_two_questions_are_distinguishable():
    graph, config = paused_study_graph("domande")
    (first_interrupt,) = graph.get_state(config).interrupts
    first = first_interrupt.value

    second = pending(graph.invoke(Command(resume={"edits": {}}), config))

    assert first["step"] == "confirm_tasks"
    assert "tasks" in first
    assert second["step"] == "review_plan"
    assert second["scheduled"] == [{"title": "Studio", "start": "08:00", "end": "10:00"}]


def test_accepting_the_plan_ends_the_graph():
    graph, config = paused_study_graph("accetta")
    graph.invoke(Command(resume={"edits": {}}), config)

    final = graph.invoke(Command(resume={"accept": True}), config)

    assert "__interrupt__" not in final
    assert graph.get_state(config).next == ()
    assert final["plan_accepted"] is True
    assert len(final["schedule"].scheduled) == 1


def test_editing_again_starts_from_the_already_edited_tasks():
    graph, config = paused_study_graph("ciclo")
    graph.invoke(Command(resume={"edits": {"t1": {"duration_min": 45}}}), config)

    # al piano l'utente sceglie di correggere ancora: si torna alla conferma dei task
    back = pending(graph.invoke(Command(resume={"accept": False}), config))
    assert back["step"] == "confirm_tasks"
    assert back["tasks"][0]["duration_min"] == 45  # la correzione del primo giro è rimasta

    graph.invoke(Command(resume={"edits": {"t1": {"priority": 1}}}), config)
    final = graph.invoke(Command(resume={"accept": True}), config)

    # il piano finale riflette entrambi i giri di correzioni
    assert (final["tasks"][0].duration_min, final["tasks"][0].priority) == (45, 1)
    (studio,) = final["schedule"].scheduled
    assert studio.end_min - studio.start_min == 45


def test_only_the_last_round_of_edit_warnings_is_kept():
    graph, config = paused_study_graph("avvisi")
    graph.invoke(Command(resume={"edits": {"t9": {"priority": 1}}}), config)
    graph.invoke(Command(resume={"accept": False}), config)

    review = pending(graph.invoke(Command(resume={"edits": {}}), config))

    assert review["warnings"] == []


def test_invalid_plan_review_keeps_the_graph_paused():
    graph, config = paused_study_graph("revisione-errata")
    graph.invoke(Command(resume={"edits": {}}), config)

    with pytest.raises(ValidationError):
        graph.invoke(Command(resume={"accept": "forse", "extra": 1}), config)
    assert graph.get_state(config).next == ("review_plan",)


@pytest.mark.parametrize(("accepted", "label"), [(True, ACCEPT), (False, EDIT)])
def test_route_after_review(accepted, label):
    assert route_after_review({"plan_accepted": accepted}) == label
