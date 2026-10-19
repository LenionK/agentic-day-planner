"""Preferences after the plan is saved: extracted, judged, confirmed by the user, stored."""

import json
from datetime import date

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from planner.agents.graph import build_graph
from planner.solver.models import DayConfig
from tests.fakes import (
    FakeClient,
    FakeEmbedder,
    FakePlanRepository,
    FakePreferenceRepository,
    unit,
)

DAY = DayConfig(day_start_min=480, day_end_min=1080)
SENTENCE = "studio 2 ore, la sera mi concentro meglio"
PARSED = json.dumps({"tasks": [{"source": "studio 2 ore", "title": "Studio", "duration_min": 120}]})
DAY_IS_FINE = json.dumps({"assessment": "Va bene.", "too_empty": False, "suggestions": []})
EVENING = "preferisce studiare la sera"
MORNING = "preferisce studiare la mattina"


def extracted(*texts: str) -> str:
    prefs = [{"source": "la sera mi concentro meglio", "cue": "meglio", "text": t} for t in texts]
    return json.dumps({"preferences": prefs})


def judge(same: bool) -> str:
    return json.dumps({"reasoning": "confronto", "same": same})


def run(llm_answers: list[str], memory: FakePreferenceRepository, vectors: dict, *, saved=True):
    """Run the graph through confirmation and critic; return graph, config, memory, result."""
    plans = FakePlanRepository()
    plans.conflict_on_save = not saved
    graph = build_graph(
        FakeClient([PARSED, DAY_IS_FINE, *llm_answers]),
        checkpointer=InMemorySaver(),
        repository=plans,
        embedder=FakeEmbedder(vectors),
        preferences=memory,
    )
    config = {"configurable": {"thread_id": "t"}}
    graph.invoke({"user_input": SENTENCE, "day": DAY, "day_date": date(2026, 10, 25)}, config)
    result = graph.invoke(Command(resume={"edits": {}}), config)
    return graph, config, result


def pending(result: dict) -> dict:
    (interrupt_,) = result["__interrupt__"]
    return interrupt_.value


def test_new_preference_is_asked_and_kept_when_confirmed():
    memory = FakePreferenceRepository()
    graph, config, paused = run([extracted(EVENING)], memory, {EVENING: unit(2)})

    question = pending(paused)
    assert question == {
        "step": "confirm_preferences",
        "preferences": [
            {"index": 0, "text": EVENING, "source": "la sera mi concentro meglio", "similar": []}
        ],
    }
    assert memory.texts() == []  # niente salvato prima della risposta

    final = graph.invoke(Command(resume={"keep": [0]}), config)

    assert memory.texts() == [EVENING]
    assert final["preference_result"]["message"] == "Preferenze: ricordate 1."


def test_close_saved_preference_is_shown_and_can_be_deleted():
    memory = FakePreferenceRepository()
    morning_id = memory.add(MORNING, "la mattina", unit(5), unit(1))
    close = [0.0] * len(unit(1))
    close[1], close[2] = 0.93, (1 - 0.93**2) ** 0.5
    graph, config, paused = run([extracted(EVENING), judge(False)], memory, {EVENING: close})

    (shown,) = pending(paused)["preferences"]
    assert shown["similar"] == [{"id": morning_id, "text": MORNING}]

    graph.invoke(Command(resume={"keep": [0], "delete": [morning_id]}), config)

    assert memory.texts() == [EVENING]  # la sera sostituisce la mattina, per scelta dell'utente


def test_rejecting_the_preference_saves_nothing():
    memory = FakePreferenceRepository()
    graph, config, _ = run([extracted(EVENING)], memory, {EVENING: unit(2)})

    final = graph.invoke(Command(resume={"keep": []}), config)

    assert memory.texts() == []
    assert "__interrupt__" not in final


def test_duplicate_is_counted_without_asking():
    memory = FakePreferenceRepository()
    morning_id = memory.add(MORNING, "la mattina", unit(5), unit(1))
    _, _, final = run(
        [extracted("la mattina studia meglio"), judge(True)],
        memory,
        {"la mattina studia meglio": unit(1)},
    )

    assert "__interrupt__" not in final  # nessuna domanda: è già nota
    assert memory.rows[morning_id]["times_seen"] == 2
    assert final["preference_result"]["message"] == "Preferenze: già note 1."


def test_sentence_without_preferences_ends_without_questions():
    memory = FakePreferenceRepository()
    _, _, final = run([extracted()], memory, {})

    assert "__interrupt__" not in final
    assert "preference_result" not in final
    assert final["save_result"]["saved"] is True


def test_preferences_are_not_looked_for_if_the_plan_was_not_saved():
    memory = FakePreferenceRepository()
    _, _, final = run([], memory, {}, saved=False)  # nessuna risposta LLM in più disponibile

    assert final["save_result"]["saved"] is False
    assert "preference_candidates" not in final


def test_invalid_answer_keeps_the_graph_paused():
    memory = FakePreferenceRepository()
    graph, config, _ = run([extracted(EVENING)], memory, {EVENING: unit(2)})

    with pytest.raises(ValidationError):
        graph.invoke(Command(resume={"keep": "tutte"}), config)
    assert graph.get_state(config).next == ("confirm_preferences",)


def test_without_embedder_the_graph_ends_after_saving():
    graph = build_graph(
        FakeClient([PARSED, DAY_IS_FINE]),
        checkpointer=InMemorySaver(),
        repository=FakePlanRepository(),
    )
    config = {"configurable": {"thread_id": "t"}}
    graph.invoke({"user_input": SENTENCE, "day": DAY, "day_date": date(2026, 10, 25)}, config)

    final = graph.invoke(Command(resume={"edits": {}}), config)

    assert final["save_result"]["saved"] is True
    assert "preference_candidates" not in final
