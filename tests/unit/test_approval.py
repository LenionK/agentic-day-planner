import json

from planner.agents.approval import approval, plan_summary
from planner.agents.parser import RejectedTask, TaskDraft
from planner.solver.models import Schedule, ScheduledTask, Task


def test_summary_shows_times_as_hhmm_with_leading_zero():
    task = Task(
        id="t4",
        title="Esame",
        duration_min=90,
        priority=2,
        required=True,
        fixed_start_min=570,
        deadline_min=1005,
    )

    summary = approval([task], [], [])

    assert summary["tasks"] == [
        {
            "id": "t4",
            "title": "Esame",
            "duration_min": 90,
            "priority": 2,
            "required": True,
            "fixed_start": "09:30",
            "earliest_start": None,
            "deadline": "16:45",
        }
    ]


def test_summary_without_times_shows_none_not_midnight():
    task = Task(id="t1", title="Spesa", duration_min=45)

    shown = approval([task], [], [])["tasks"][0]

    assert (shown["fixed_start"], shown["earliest_start"], shown["deadline"]) == (None, None, None)


def test_summary_includes_rejected_and_warnings_and_is_json():
    task = Task(id="t1", title="Corsa", duration_min=40)
    rejected = RejectedTask(
        draft=TaskDraft(source="cena alle 25", title="Cena", duration_min=60, fixed_start="25:00"),
        reason="hours out of range: '25:00'",
    )
    warnings = ["Corsa: ignorato deadline 11:00 (non compare nella frase)"]

    summary = approval([task], [rejected], warnings)

    assert summary["rejected"] == [{"title": "Cena", "reason": "hours out of range: '25:00'"}]
    assert summary["warnings"] == warnings
    assert json.loads(json.dumps(summary)) == summary


def test_plan_summary_sorts_by_time_and_shows_titles_not_ids():
    tasks = [
        Task(id="t1", title="Palestra", duration_min=60),
        Task(id="t2", title="Studio", duration_min=90),
        Task(id="t3", title="Spesa", duration_min=30),
        Task(id="t4", title="Cena", duration_min=60, required=True),
    ]
    plan = Schedule(
        status="FEASIBLE",
        scheduled=[
            ScheduledTask(task_id="t1", title="Palestra", start_min=1080, end_min=1140),
            ScheduledTask(task_id="t2", title="Studio", start_min=545, end_min=635),
        ],
        unscheduled=["t3"],
        conflicts=["t4"],
    )

    summary = plan_summary(plan, tasks, ["un avviso"])

    assert summary == {
        "step": "review_plan",
        "status": "FEASIBLE",
        "scheduled": [
            {"title": "Studio", "start": "09:05", "end": "10:35"},
            {"title": "Palestra", "start": "18:00", "end": "19:00"},
        ],
        "unscheduled": ["Spesa"],
        "conflicts": ["Cena"],
        "warnings": ["un avviso"],
    }
    assert json.loads(json.dumps(summary)) == summary
