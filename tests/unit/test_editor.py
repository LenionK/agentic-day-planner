import pytest
from pydantic import ValidationError

from planner.agents.editor import ApprovalResponse, apply_edits
from planner.solver.models import Task


def make_tasks() -> list[Task]:
    return [
        Task(id="t1", title="Studio", duration_min=120, priority=4),
        Task(
            id="t2",
            title="Spesa",
            duration_min=50,
            priority=4,
            earliest_start_min=600,
            deadline_min=660,
        ),
    ]


def respond(edits: dict) -> ApprovalResponse:
    return ApprovalResponse.model_validate({"edits": edits})


def test_empty_edits_confirm_everything():
    tasks = make_tasks()

    edited, warnings = apply_edits(tasks, respond({}))

    assert edited == tasks
    assert warnings == []


def test_edit_changes_only_given_fields_of_given_task():
    tasks = make_tasks()

    edited, warnings = apply_edits(tasks, respond({"t2": {"priority": 2}}))

    assert [t.id for t in edited] == ["t1", "t2"]
    assert edited[0] == tasks[0]
    assert (edited[1].priority, edited[1].duration_min, edited[1].deadline_min) == (2, 50, 660)
    assert warnings == []


def test_apply_edits_does_not_modify_input_tasks():
    tasks = make_tasks()

    apply_edits(tasks, respond({"t1": {"duration_min": 30}}))

    assert tasks[0].duration_min == 120


def test_edit_for_unknown_id_is_skipped_with_warning():
    tasks = make_tasks()

    edited, warnings = apply_edits(tasks, respond({"t9": {"priority": 1}}))

    assert edited == tasks
    assert len(warnings) == 1
    assert "t9" in warnings[0]


def test_edit_that_breaks_time_window_is_skipped_as_a_whole():
    tasks = make_tasks()

    # 90 minuti non entrano tra 10:00 e 11:00: si scarta anche la priorità
    edited, warnings = apply_edits(tasks, respond({"t2": {"duration_min": 90, "priority": 1}}))

    assert edited[1] == tasks[1]
    assert len(warnings) == 1
    assert warnings[0].startswith("t2:")


def test_explicit_null_is_skipped_with_warning():
    tasks = make_tasks()

    edited, warnings = apply_edits(tasks, respond({"t1": {"priority": None}}))

    assert edited[0] == tasks[0]
    assert warnings[0].startswith("t1:")


def test_task_made_required_gets_top_priority():
    tasks = make_tasks()

    edited, _ = apply_edits(tasks, respond({"t1": {"required": True, "priority": 2}}))

    assert edited[0].required is True
    assert edited[0].priority == 5


@pytest.mark.parametrize(
    "payload",
    [
        {"edits": {"t1": {"priority": 0}}},
        {"edits": {"t1": {"priority": 6}}},
        {"edits": {"t1": {"duration_min": -30}}},
        {"edits": {"t1": {"priorty": 3}}},
        {"edits": {"t1": {"fixed_start": "25:00"}}},
        {"edits": {"t1": {"deadline": "alle tre"}}},
        {},
    ],
)
def test_invalid_response_is_rejected(payload):
    with pytest.raises(ValidationError):
        ApprovalResponse.model_validate(payload)


def test_time_edit_is_converted_to_minutes():
    tasks = make_tasks()

    edited, warnings = apply_edits(tasks, respond({"t1": {"fixed_start": "09:45"}}))

    assert edited[0].fixed_start_min == 585
    assert warnings == []


def test_null_time_removes_the_constraint():
    tasks = make_tasks()

    # t2 aveva la finestra 10:00-11:00: togliendo la scadenza i 90 minuti ci stanno
    edited, warnings = apply_edits(tasks, respond({"t2": {"deadline": None, "duration_min": 90}}))

    assert edited[1].deadline_min is None
    assert edited[1].earliest_start_min == 600
    assert edited[1].duration_min == 90
    assert warnings == []


def test_time_edit_that_breaks_the_window_is_skipped():
    tasks = make_tasks()

    # inizio fisso alle 10:30 con 50 minuti: finirebbe dopo la scadenza delle 11:00
    edited, warnings = apply_edits(tasks, respond({"t2": {"fixed_start": "10:30"}}))

    assert edited[1] == tasks[1]
    assert warnings[0].startswith("t2:")
