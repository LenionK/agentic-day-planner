import json

import pytest

from planner.agents.parser import TaskDraft, draft_to_task, parse_day, to_minutes
from tests.fakes import FakeClient


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


def test_draft_to_task_converts_times_and_assigns_id():
    draft = TaskDraft(
        title="Dentista",
        duration_min=60,
        priority=4,
        required=True,
        fixed_start="15:30",
    )

    task = draft_to_task(draft, index=2)

    assert task.id == "t2"
    assert task.title == "Dentista"
    assert task.fixed_start_min == 930
    assert task.earliest_start_min is None
    assert task.deadline_min is None
    assert task.priority == 4
    assert task.required is True


def test_draft_with_invalid_time_raises():
    draft = TaskDraft(title="Cena", duration_min=60, fixed_start="25:00")

    with pytest.raises(ValueError):
        draft_to_task(draft, index=1)


def test_draft_with_inconsistent_window_raises():
    # 3 ore di lavoro in una finestra di un'ora (9:00-10:00)
    draft = TaskDraft(
        title="Relazione",
        duration_min=180,
        earliest_start="09:00",
        deadline="10:00",
    )

    with pytest.raises(ValueError):
        draft_to_task(draft, index=1)


def llm_answer(*drafts: dict) -> str:
    """Build the JSON the LLM would return for these drafts."""
    return json.dumps({"tasks": list(drafts)})


def test_parse_day_returns_tasks():
    client = FakeClient(
        [
            llm_answer(
                {"title": "Studio", "duration_min": 120, "priority": 5},
                {"title": "Dentista", "duration_min": 60, "required": True, "fixed_start": "15:00"},
            )
        ]
    )

    result = parse_day("devo studiare 2 ore, dentista alle 15", client)

    assert [t.id for t in result.tasks] == ["t1", "t2"]
    assert result.tasks[1].fixed_start_min == 900
    assert result.rejected == []


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


def test_parse_day_sends_system_prompt_and_user_text():
    client = FakeClient([llm_answer()])

    parse_day("palestra dopo le 17", client)

    messages = client.calls[0]
    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "palestra dopo le 17"}
