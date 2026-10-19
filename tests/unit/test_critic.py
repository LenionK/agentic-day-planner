import json
from datetime import date

import pytest
from pydantic import ValidationError

from planner.agents.critic import (
    CriticReview,
    check_suggestions,
    critic_messages,
    critique,
    day_facts,
    free_minutes,
    free_slots,
)
from planner.solver.models import DayConfig, Interval, Schedule, ScheduledTask
from tests.fakes import FakeClient


def plan_of(*spans: tuple[int, int]) -> Schedule:
    """A feasible plan with one task per (start, end) span, in minutes."""
    return Schedule(
        status="OPTIMAL",
        scheduled=[
            ScheduledTask(task_id=f"t{i}", title=f"Task {i}", start_min=start, end_min=end)
            for i, (start, end) in enumerate(spans, start=1)
        ],
    )


def as_pairs(slots) -> list[tuple[int, int]]:
    return [(slot.start_min, slot.end_min) for slot in slots]


DAY = DayConfig(day_start_min=480, day_end_min=1320)  # 08:00-22:00


def test_gaps_before_between_and_after_tasks():
    slots = free_slots(plan_of((540, 660), (900, 960)), DAY)  # 9-11, 15-16

    assert as_pairs(slots) == [(480, 540), (660, 900), (960, 1320)]
    assert free_minutes(slots) == 660  # 1 + 4 + 6 ore


def test_empty_plan_is_one_free_slot_for_the_whole_day():
    assert as_pairs(free_slots(plan_of(), DAY)) == [(480, 1320)]


def test_back_to_back_tasks_leave_no_gap_between_them():
    slots = free_slots(plan_of((540, 600), (600, 660)), DAY)

    assert as_pairs(slots) == [(480, 540), (660, 1320)]


def test_tasks_at_the_edges_of_the_day_leave_no_edge_gaps():
    slots = free_slots(plan_of((480, 600), (1200, 1320)), DAY)

    assert as_pairs(slots) == [(600, 1200)]


def test_full_day_has_no_free_time():
    slots = free_slots(plan_of((480, 1320)), DAY)

    assert slots == []
    assert free_minutes(slots) == 0


def test_gaps_shorter_than_the_minimum_are_left_out():
    # 10 minuti tra i due task: sotto la soglia di 15
    slots = free_slots(plan_of((480, 600), (610, 1320)), DAY)

    assert slots == []


def test_custom_minimum_gap():
    slots = free_slots(plan_of((480, 600), (630, 1320)), DAY, min_gap=60)

    assert slots == []


def test_order_of_the_plan_does_not_matter():
    slots = free_slots(plan_of((900, 960), (540, 660)), DAY)

    assert as_pairs(slots) == [(480, 540), (660, 900), (960, 1320)]


def test_uses_the_given_day_not_the_default():
    day = DayConfig(day_start_min=420, day_end_min=1200)  # 07:00-20:00

    assert as_pairs(free_slots(plan_of((600, 660)), day)) == [(420, 600), (660, 1200)]


def test_day_facts_for_a_day_with_one_meeting():
    slots = free_slots(plan_of((600, 660)), DAY)  # riunione 10-11

    assert day_facts(slots, DAY) == {
        "total_minutes": 840,
        "busy_minutes": 60,
        "free_minutes": 780,
        "busy_percent": 7,
        "longest_slot": {"start": "11:00", "end": "22:00"},
    }


def test_day_facts_for_a_full_day():
    facts = day_facts([], DAY)

    assert (facts["busy_minutes"], facts["busy_percent"], facts["longest_slot"]) == (840, 100, None)


def suggestion(title: str, duration_min: int, category: str = "svago") -> dict:
    return {"title": title, "category": category, "duration_min": duration_min, "reason": "x"}


def review(too_empty: bool, *suggestions: dict) -> CriticReview:
    return CriticReview.model_validate(
        {"assessment": "ok", "too_empty": too_empty, "suggestions": list(suggestions)}
    )


def test_reasoning_comes_before_the_decision_in_the_schema():
    # l'LLM genera i campi in quest'ordine: descrive, sceglie le preferenze che valgono,
    # poi decide e propone
    order = ["assessment", "applied_preferences", "too_empty", "suggestions"]
    assert list(CriticReview.model_fields) == order
    assert list(CriticReview.model_json_schema()["properties"]) == order


def test_messages_contain_the_plan_and_the_computed_free_slots():
    plan = plan_of((540, 660), (900, 960))
    slots = free_slots(plan, DAY)

    system, user = critic_messages(plan, slots, DAY)

    assert system["role"] == "system"
    assert user["content"].splitlines() == [
        "Piano:",
        "- 09:00-11:00 Task 1",
        "- 15:00-16:00 Task 2",
        "Intervalli liberi:",
        "- 08:00-09:00 (1 h)",
        "- 11:00-15:00 (4 h)",
        "- 16:00-22:00 (6 h)",
        "Tempo libero totale: 11 h",
        "Tempo occupato: 3 h su 14 h (21%)",
        "Intervallo libero più lungo: 16:00-22:00",
    ]


def test_messages_for_an_empty_plan_and_mixed_durations():
    plan = plan_of((480, 1275))  # 08:00-21:15
    _, user = critic_messages(plan, free_slots(plan, DAY), DAY)

    assert "- 21:15-22:00 (45 min)" in user["content"]
    assert "Tempo libero totale: 45 min" in user["content"]
    assert "Tempo occupato: 13 h 15 min su 14 h (95%)" in user["content"]

    _, user = critic_messages(plan_of(), [], DAY)
    assert "- nessun impegno" in user["content"]
    assert "- nessuno" in user["content"]
    assert "Intervallo libero più lungo" not in user["content"]


def test_suggestions_that_do_not_fit_any_slot_are_dropped_with_a_warning():
    slots = [Interval(start_min=600, end_min=660), Interval(start_min=900, end_min=990)]  # 60, 90

    valid, warnings = check_suggestions(
        review(True, suggestion("Corsa", 90), suggestion("Film", 120)), slots
    )

    assert [s.title for s in valid] == ["Corsa"]
    assert len(warnings) == 1
    assert "Film" in warnings[0]


def test_suggestions_are_ignored_when_the_day_is_fine():
    slots = [Interval(start_min=600, end_min=900)]

    assert check_suggestions(review(False, suggestion("Corsa", 30)), slots) == ([], [])


def test_review_rejects_more_than_three_suggestions_and_unknown_categories():
    with pytest.raises(ValidationError):
        review(True, *[suggestion(f"A{i}", 30) for i in range(4)])
    with pytest.raises(ValidationError):
        review(True, suggestion("Yoga", 30, category="benessere"))


def test_critique_asks_the_llm_and_returns_plain_data():
    answer = {
        "assessment": "Pomeriggio libero.",
        "too_empty": True,
        "suggestions": [suggestion("Corsa", 45, "attività fisica"), suggestion("Film", 200)],
    }
    client = FakeClient([json.dumps(answer)])

    # liberi solo 08:00-09:00 e 11:00-13:00: il buco più lungo è di 120 minuti
    result = critique(plan_of((540, 660), (780, 1320)), DAY, client)

    assert len(client.calls) == 1
    assert "Intervalli liberi:" in client.calls[0][1]["content"]
    assert result["assessment"] == "Pomeriggio libero."
    assert result["too_empty"] is True
    assert result["free_minutes"] == 180
    assert result["busy_minutes"] == 660
    assert result["longest_slot"] == {"start": "11:00", "end": "13:00"}
    assert [s["title"] for s in result["suggestions"]] == ["Corsa"]  # Film non entra
    assert len(result["warnings"]) == 1
    assert json.loads(json.dumps(result)) == result


def test_preferences_are_added_to_the_prompt_only_when_given():
    plan = plan_of((540, 660))
    slots = free_slots(plan, DAY)

    _, without = critic_messages(plan, slots, DAY)
    _, with_prefs = critic_messages(plan, slots, DAY, ["preferisce studiare la mattina"])

    assert "Preferenze" not in without["content"]
    assert with_prefs["content"].splitlines()[-2:] == [
        "Preferenze dell'utente:",
        "- preferisce studiare la mattina",
    ]


def test_only_given_preferences_can_be_applied():
    answer = {
        "assessment": "Giornata piena.",
        # una data (con maiuscole diverse), una inventata, una ripetuta
        "applied_preferences": [
            "Preferisce studiare la mattina",
            "ama la pizza",
            "preferisce studiare la mattina",
        ],
        "too_empty": False,
        "suggestions": [],
    }
    client = FakeClient([json.dumps(answer)])
    given = ["preferisce studiare la mattina", "fa la spesa il sabato"]

    result = critique(plan_of((540, 660)), DAY, client, given)

    assert result["applied_preferences"] == ["preferisce studiare la mattina"]
    assert "fa la spesa il sabato" in client.calls[0][1]["content"]


def test_weekday_from_the_calendar_is_the_first_line_of_the_prompt():
    plan = plan_of((540, 660))
    slots = free_slots(plan, DAY)

    _, without = critic_messages(plan, slots, DAY)
    _, with_day = critic_messages(plan, slots, DAY, day_date=date(2026, 10, 23))

    assert without["content"].startswith("Piano:")
    assert with_day["content"].splitlines()[:2] == ["Giorno: venerdì 23 ottobre 2026", "Piano:"]


def test_critique_returns_the_preferences_it_was_given():
    answer = {"assessment": "ok", "applied_preferences": [], "too_empty": False, "suggestions": []}
    given = ["preferisce studiare la mattina", "fa la spesa il sabato"]

    result = critique(plan_of((540, 660)), DAY, FakeClient([json.dumps(answer)]), given)

    # "considerate" nell'interfaccia: quelle date, anche se il modello non ne elenca nessuna
    assert result["recalled_preferences"] == given
