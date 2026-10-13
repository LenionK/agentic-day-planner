import json

import pytest

from planner.agents.parser import (
    TaskDraft,
    clean_times,
    draft_to_task,
    parse_day,
    to_minutes,
)
from tests.fakes import FakeClient


def make_draft(**fields) -> TaskDraft:
    """A valid draft with sensible defaults; override only the fields a test cares about."""
    values = {"source": "frase di prova", "title": "Task", "duration_min": 60}
    values.update(fields)
    return TaskDraft(**values)


def llm_answer(*drafts: dict) -> str:
    """Build the JSON the LLM would return; adds a source when a test does not care about it."""
    return json.dumps({"tasks": [{"source": d["title"], **d} for d in drafts]})


# --- to_minutes ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("15:30", 930),
        ("08:00", 480),
        ("8:00", 480),
        ("00:00", 0),
        ("23:59", 1439),
        (" 15:30 ", 930),
    ],
)
def test_to_minutes_valid(text, expected):
    assert to_minutes(text) == expected


@pytest.mark.parametrize(
    "text",
    ["25:00", "10:75", "-1:00", "alle tre", "15", "15:30:00", ""],
)
def test_to_minutes_invalid(text):
    with pytest.raises(ValueError):
        to_minutes(text)


# --- clean_times ---


@pytest.mark.parametrize(
    ("text", "field", "value"),
    [
        ("alle 3 del pomeriggio parrucchiere", "fixed_start", "15:00"),
        ("la visita medica alle 9 e mezza", "fixed_start", "09:30"),
        ("chiamare il commercialista prima delle 12", "deadline", "12:00"),
        ("palestra dopo le 18", "earliest_start", "18:00"),
        ("corso di sicurezza dalle 14 per 3 ore", "fixed_start", "14:00"),
    ],
)
def test_clean_times_keeps_times_mentioned_in_the_sentence(text, field, value):
    draft = make_draft(**{field: value})

    cleaned, warnings = clean_times(draft, text)

    assert getattr(cleaned, field) == value
    assert warnings == []


def test_clean_times_keeps_time_in_sentence_even_if_missing_from_source():
    # il source è stato tagliato dal modello, ma la scadenza è nella frase: non va persa
    draft = make_draft(source="devo scrivere la relazione", deadline="10:00")
    text = "devo scrivere la relazione, va consegnata entro le 10"

    cleaned, warnings = clean_times(draft, text)

    assert cleaned.deadline == "10:00"
    assert warnings == []


def test_clean_times_drops_time_not_in_sentence_with_warning():
    draft = make_draft(title="Giro in bici", earliest_start="10:30")
    text = "la visita alle 9 e mezza, poi magari un giro in bici"

    cleaned, warnings = clean_times(draft, text)

    assert cleaned.earliest_start is None
    assert len(warnings) == 1
    assert "Giro in bici" in warnings[0]
    assert "10:30" in warnings[0]


def test_clean_times_ignores_numbers_that_are_durations():
    # il 2 di "2 ore" non deve giustificare un orario inventato alle 2 o alle 14
    draft = make_draft(fixed_start="14:00")

    cleaned, warnings = clean_times(draft, "devo studiare 2 ore")

    assert cleaned.fixed_start is None
    assert len(warnings) == 1


def test_clean_times_drops_earliest_equal_to_deadline_with_warning():
    draft = make_draft(title="Progetto", earliest_start="12:00", deadline="12:00")

    cleaned, warnings = clean_times(draft, "consegnare il progetto entro le 12")

    assert cleaned.earliest_start is None
    assert cleaned.deadline == "12:00"
    assert len(warnings) == 1
    assert "scadenza" in warnings[0]


def test_clean_times_keeps_real_inconsistencies():
    draft = make_draft(duration_min=180, earliest_start="09:00", deadline="10:00")
    text = "devo scrivere la relazione, posso iniziare dalle 9 e va consegnata entro le 10"

    cleaned, warnings = clean_times(draft, text)

    assert (cleaned.earliest_start, cleaned.deadline) == ("09:00", "10:00")
    assert warnings == []
    with pytest.raises(ValueError):
        draft_to_task(cleaned, index=1)


def test_clean_times_does_not_modify_the_original_draft():
    draft = make_draft(earliest_start="10:30")

    clean_times(draft, "un giro in bici")

    assert draft.earliest_start == "10:30"


# --- draft_to_task ---


def test_draft_to_task_converts_times_and_assigns_id():
    draft = make_draft(title="Dentista", priority=4, fixed_start="15:30")

    task = draft_to_task(draft, index=2)

    assert task.id == "t2"
    assert task.title == "Dentista"
    assert task.fixed_start_min == 930
    assert task.earliest_start_min is None
    assert task.deadline_min is None
    assert task.priority == 4


def test_draft_with_invalid_time_raises():
    draft = make_draft(title="Cena", fixed_start="25:00")

    with pytest.raises(ValueError):
        draft_to_task(draft, index=1)


def test_draft_with_inconsistent_window_raises():
    draft = make_draft(
        title="Relazione", duration_min=180, earliest_start="09:00", deadline="10:00"
    )

    with pytest.raises(ValueError):
        draft_to_task(draft, index=1)


def test_required_task_always_gets_top_priority():
    draft = make_draft(title="Dentista", priority=2, required=True)

    task = draft_to_task(draft, index=1)

    assert task.priority == 5
    assert task.required is True


def test_normal_task_keeps_its_priority():
    draft = make_draft(title="Spesa", priority=2)

    task = draft_to_task(draft, index=1)

    assert task.priority == 2


def test_draft_requires_a_non_empty_source():
    with pytest.raises(ValueError):
        make_draft(source="")


# --- parse_day ---


def test_parse_day_returns_tasks_and_their_sources():
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

    result = parse_day("devo studiare 2 ore, dentista alle 15", client)

    assert [t.id for t in result.tasks] == ["t1", "t2"]
    assert result.tasks[1].fixed_start_min == 900
    assert result.sources == {"t1": "devo studiare 2 ore", "t2": "dentista alle 15"}
    assert result.rejected == []
    assert result.warnings == []


def test_parse_day_rejects_invalid_drafts_but_keeps_the_others():
    client = FakeClient(
        [
            llm_answer(
                {"title": "Studio", "duration_min": 120},
                {"title": "Cena", "duration_min": 60, "fixed_start": "25:00"},
            )
        ]
    )

    result = parse_day("studio 2 ore, cena alle 25", client)

    assert [t.title for t in result.tasks] == ["Studio"]
    assert len(result.rejected) == 1
    assert result.rejected[0].draft.title == "Cena"
    assert "25:00" in result.rejected[0].reason
    assert "t2" not in result.sources


def test_parse_day_reports_made_up_times_as_warnings():
    client = FakeClient(
        [
            llm_answer(
                {"title": "Giro in bici", "duration_min": 60, "earliest_start": "10:30"},
            )
        ]
    )

    result = parse_day("magari un giro in bici", client)

    assert result.tasks[0].earliest_start_min is None
    assert len(result.warnings) == 1


def test_parse_day_sends_system_prompt_and_user_text():
    client = FakeClient([llm_answer()])

    parse_day("palestra dopo le 17", client)

    messages = client.calls[0]
    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "palestra dopo le 17"}
