from planner.solver.cpsat_scheduler import schedule
from planner.solver.models import DayConfig, Task


def by_id(result):
    """Trasforma la lista dei task schedulati in un dizionario id -> ScheduledTask."""
    return {s.task_id: s for s in result.scheduled}


def overlaps(a_start, a_end, b_start, b_end):
    """Due intervalli [a_start, a_end) e [b_start, b_end) si sovrappongono?"""
    return a_start < b_end and b_start < a_end


def test_tasks_that_fit_are_all_scheduled_without_overlap():
    day = DayConfig(day_start_min=480, day_end_min=720)  # 08:00-12:00
    tasks = [
        Task(id="study", title="Studio", duration_min=120),
        Task(id="gym", title="Palestra", duration_min=60),
    ]

    result = schedule(tasks, day)

    assert result.status == "OPTIMAL"
    assert result.unscheduled == []
    s = by_id(result)
    assert set(s) == {"study", "gym"}
    for task in tasks:
        item = s[task.id]
        assert item.end_min - item.start_min == task.duration_min
        assert day.day_start_min <= item.start_min
        assert item.end_min <= day.day_end_min
    assert not overlaps(s["study"].start_min, s["study"].end_min,
                        s["gym"].start_min, s["gym"].end_min)


def test_lowest_priority_task_is_dropped_when_day_is_full():
    day = DayConfig(day_start_min=480, day_end_min=600)  # 120 minuti
    tasks = [
        Task(id="a", title="A", duration_min=60, priority=2),
        Task(id="b", title="B", duration_min=90, priority=5),
        Task(id="c", title="C", duration_min=30, priority=3),
    ]

    result = schedule(tasks, day)

    assert result.unscheduled == ["a"]
    assert set(by_id(result)) == {"b", "c"}