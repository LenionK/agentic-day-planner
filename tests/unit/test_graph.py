import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from planner.agents.graph import (
    ACCEPT,
    CONFLICT,
    DONE,
    EDIT,
    REVIEW,
    SUGGEST,
    build_graph,
    route_after_critic,
    route_after_review,
    route_after_schedule,
)
from planner.solver.models import DayConfig, Schedule
from tests.fakes import FakeClient


def llm_answer(*drafts: dict) -> str:
    return json.dumps({"tasks": [{"source": d["title"], **d} for d in drafts]})


def critic_answer(*suggestions: dict) -> str:
    """The critic's answer: with suggestions the day is too empty, without it is fine."""
    return json.dumps(
        {
            "assessment": "Giornata vuota." if suggestions else "Giornata equilibrata.",
            "too_empty": bool(suggestions),
            "suggestions": list(suggestions),
        }
    )


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
            ),
            critic_answer(),
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
            ),
            critic_answer(),
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
        [
            llm_answer({"source": "studiare 2 ore", "title": "Studio", "duration_min": 120}),
            critic_answer(),
        ]
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


def paused_graph(thread_id: str, text: str, *drafts: dict, critic: str | None = None):
    """A graph stopped at the task confirmation, on a 08:00-18:00 day (600 minutes).

    `critic` is the critic's answer, if the test reaches it; by default the day is fine.
    """
    client = FakeClient([llm_answer(*drafts), critic or critic_answer()])
    graph = build_graph(client, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": thread_id}}
    day = DayConfig(day_start_min=480, day_end_min=1080)
    graph.invoke({"user_input": text, "day": day}, config)
    return graph, config


def paused_crowded_graph(thread_id: str):
    """Studio (120 min, priority 3) and Progetto (540 min, priority 1) don't fit together."""
    return paused_graph(
        thread_id,
        "studio e progetto",
        {"title": "Studio", "duration_min": 120},
        {"title": "Progetto", "duration_min": 540, "priority": 1},
    )


def paused_conflict_graph(thread_id: str):
    """Two required tasks both at 15:00, plus a normal one."""
    return paused_graph(
        thread_id,
        "dentista alle 15, riunione alle 15, spesa",
        {"title": "Dentista", "duration_min": 60, "required": True, "fixed_start": "15:00"},
        {"title": "Riunione", "duration_min": 60, "required": True, "fixed_start": "15:00"},
        {"title": "Spesa", "duration_min": 30},
    )


def test_plan_with_all_tasks_ends_without_more_questions():
    graph, config = paused_study_graph("tutto-inserito")

    final = graph.invoke(Command(resume={"edits": {}}), config)

    assert "__interrupt__" not in final
    assert graph.get_state(config).next == ()
    assert [item.title for item in final["schedule"].scheduled] == ["Studio"]


def test_plan_with_tasks_left_out_asks_for_review():
    graph, config = paused_crowded_graph("esclusi")

    review = pending(graph.invoke(Command(resume={"edits": {}}), config))

    assert review["step"] == "review_plan"
    assert review["unscheduled"] == ["Progetto"]
    assert review["scheduled"] == [{"title": "Studio", "start": "08:00", "end": "10:00"}]


def test_accepting_the_plan_ends_the_graph():
    graph, config = paused_crowded_graph("accetta")
    graph.invoke(Command(resume={"edits": {}}), config)

    final = graph.invoke(Command(resume={"accept": True}), config)

    assert "__interrupt__" not in final
    assert graph.get_state(config).next == ()
    assert final["plan_accepted"] is True
    assert final["schedule"].unscheduled == ["t2"]


def test_editing_again_starts_from_the_already_edited_tasks():
    graph, config = paused_crowded_graph("ciclo")
    graph.invoke(Command(resume={"edits": {"t1": {"priority": 4}}}), config)

    # Progetto resta fuori: l'utente sceglie di correggere ancora
    back = pending(graph.invoke(Command(resume={"accept": False}), config))
    assert back["step"] == "confirm_tasks"
    assert back["tasks"][0]["priority"] == 4  # la correzione del primo giro è rimasta

    # accorciato, Progetto entra: piano completo, il grafo finisce da solo
    final = graph.invoke(Command(resume={"edits": {"t2": {"duration_min": 60}}}), config)

    assert "__interrupt__" not in final
    assert (final["tasks"][0].priority, final["tasks"][1].duration_min) == (4, 60)
    assert final["schedule"].unscheduled == []


def test_only_the_last_round_of_edit_warnings_is_kept():
    graph, config = paused_crowded_graph("avvisi")
    graph.invoke(Command(resume={"edits": {"t9": {"priority": 1}}}), config)
    graph.invoke(Command(resume={"accept": False}), config)

    review = pending(graph.invoke(Command(resume={"edits": {}}), config))

    assert review["warnings"] == []


def test_invalid_plan_review_keeps_the_graph_paused():
    graph, config = paused_crowded_graph("revisione-errata")
    graph.invoke(Command(resume={"edits": {}}), config)

    with pytest.raises(ValidationError):
        graph.invoke(Command(resume={"accept": "forse", "extra": 1}), config)
    assert graph.get_state(config).next == ("review_plan",)


def test_conflict_asks_only_about_the_conflicting_tasks():
    graph, config = paused_conflict_graph("conflitto")

    question = pending(graph.invoke(Command(resume={"edits": {}}), config))

    assert question["step"] == "resolve_conflict"
    assert [(t["id"], t["fixed_start"]) for t in question["tasks"]] == [
        ("t1", "15:00"),
        ("t2", "15:00"),
    ]


def test_resolving_the_conflict_goes_back_to_the_scheduler():
    graph, config = paused_conflict_graph("risolto")
    graph.invoke(Command(resume={"edits": {}}), config)

    # la riunione si sposta alle 17: tutti i task entrano e il grafo finisce
    final = graph.invoke(Command(resume={"edits": {"t2": {"fixed_start": "17:00"}}}), config)

    assert "__interrupt__" not in final
    plan = {item.title: item.start_min for item in final["schedule"].scheduled}
    assert (plan["Dentista"], plan["Riunione"]) == (900, 1020)
    assert "Spesa" in plan


def test_making_a_conflicting_task_optional_leads_to_review():
    graph, config = paused_conflict_graph("non-obbligatoria")
    graph.invoke(Command(resume={"edits": {}}), config)

    # non più obbligatoria ma sempre alle 15: non entra, e l'utente lo deve sapere
    review = pending(graph.invoke(Command(resume={"edits": {"t2": {"required": False}}}), config))

    assert review["step"] == "review_plan"
    assert review["unscheduled"] == ["Riunione"]


def test_unresolved_conflict_asks_again():
    graph, config = paused_conflict_graph("non-risolto")
    graph.invoke(Command(resume={"edits": {}}), config)

    again = pending(graph.invoke(Command(resume={"edits": {}}), config))

    assert again["step"] == "resolve_conflict"
    assert graph.get_state(config).next == ("resolve_conflict",)


@pytest.mark.parametrize(
    ("plan", "label"),
    [
        (Schedule(status="OPTIMAL", unscheduled=[]), DONE),
        (Schedule(status="OPTIMAL", unscheduled=["t2"]), REVIEW),
        (Schedule(status="INFEASIBLE", unscheduled=["t1", "t2"], conflicts=["t1", "t2"]), CONFLICT),
    ],
)
def test_route_after_schedule(plan, label):
    assert route_after_schedule({"schedule": plan}) == label


@pytest.mark.parametrize(("accepted", "label"), [(True, ACCEPT), (False, EDIT)])
def test_route_after_review(accepted, label):
    assert route_after_review({"plan_accepted": accepted}) == label


RUN = {"title": "Corsa", "category": "attività fisica", "duration_min": 45, "reason": "muoversi"}


def test_full_plan_goes_to_the_critic_and_ends_when_the_day_is_fine():
    graph, config = paused_study_graph("critico-ok")

    final = graph.invoke(Command(resume={"edits": {}}), config)

    assert "__interrupt__" not in final
    assert final["critique"]["too_empty"] is False
    assert final["critique"]["suggestions"] == []
    assert final["critique"]["free_minutes"] == 480  # 600 della giornata - 120 di studio


def test_too_empty_day_stops_with_the_suggestions():
    graph, config = paused_graph(
        "critico-vuota",
        "studio",
        {"title": "Studio", "duration_min": 60},
        critic=critic_answer(RUN),
    )

    question = pending(graph.invoke(Command(resume={"edits": {}}), config))

    assert question["step"] == "suggest_activities"
    assert question["assessment"] == "Giornata vuota."
    assert [s["title"] for s in question["suggestions"]] == ["Corsa"]
    # il piano commentato arriva insieme alla critica, per mostrarlo all'utente
    assert question["plan"]["scheduled"] == [{"title": "Studio", "start": "08:00", "end": "09:00"}]
    assert graph.get_state(config).next == ("suggest_activities",)


def test_critic_runs_after_the_review_is_accepted():
    graph, config = paused_graph(
        "critico-dopo-revisione",
        "studio e progetto",
        {"title": "Studio", "duration_min": 120},
        {"title": "Progetto", "duration_min": 540, "priority": 1},
        critic=critic_answer(RUN),
    )
    graph.invoke(Command(resume={"edits": {}}), config)

    question = pending(graph.invoke(Command(resume={"accept": True}), config))

    assert question["step"] == "suggest_activities"


def test_critic_is_not_called_again_when_resuming_the_suggestions():
    client = FakeClient([llm_answer({"title": "Studio", "duration_min": 60}), critic_answer(RUN)])
    graph = build_graph(client, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "una-chiamata"}}
    day = DayConfig(day_start_min=480, day_end_min=1080)
    graph.invoke({"user_input": "studio", "day": day}, config)
    graph.invoke(Command(resume={"edits": {}}), config)

    final = graph.invoke(Command(resume={"accepted": []}), config)

    assert "__interrupt__" not in final  # il grafo è davvero ripartito ed è finito
    assert graph.get_state(config).next == ()
    assert len(client.calls) == 2  # parser + critico, nessuna chiamata rifatta alla ripresa


def test_invalid_answer_to_the_suggestions_keeps_the_graph_paused():
    graph, config = paused_graph(
        "proposte-errate",
        "studio",
        {"title": "Studio", "duration_min": 60},
        critic=critic_answer(RUN),
    )
    graph.invoke(Command(resume={"edits": {}}), config)

    with pytest.raises(ValidationError):
        graph.invoke(Command(resume={"accepted": "tutte"}), config)
    assert graph.get_state(config).next == ("suggest_activities",)


@pytest.mark.parametrize(("suggestions", "label"), [([], DONE), ([RUN], SUGGEST)])
def test_route_after_critic(suggestions, label):
    assert route_after_critic({"critique": {"suggestions": suggestions}}) == label
