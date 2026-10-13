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
    assert not overlaps(
        s["study"].start_min, s["study"].end_min, s["gym"].start_min, s["gym"].end_min
    )


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


def test_fixed_start_is_respected():
    day = DayConfig(day_start_min=480, day_end_min=1080)
    tasks = [
        Task(id="dentist", title="Dentista", duration_min=60, fixed_start_min=900),
        Task(id="study", title="Studio", duration_min=120),
    ]

    result = schedule(tasks, day)

    s = by_id(result)
    assert s["dentist"].start_min == 900
    assert s["dentist"].end_min == 960


def test_deadline_is_respected():
    day = DayConfig(day_start_min=480, day_end_min=1080)
    tasks = [
        # la riunione occupa 08:00-10:00, quindi la chiamata deve stare tra 10:00 e 11:00
        Task(id="meeting", title="Riunione", duration_min=120, fixed_start_min=480),
        Task(id="call", title="Chiamata", duration_min=60, deadline_min=660),
    ]

    result = schedule(tasks, day)

    s = by_id(result)
    assert s["call"].end_min <= 660
    assert (s["call"].start_min, s["call"].end_min) == (600, 660)


def test_earliest_start_is_respected():
    day = DayConfig(day_start_min=480, day_end_min=1080)  # 08:00-18:00
    tasks = [
        # può iniziare solo dalle 17:00, quindi l'unica posizione è 17:00-18:00
        Task(id="gym", title="Palestra", duration_min=60, earliest_start_min=1020),
    ]

    result = schedule(tasks, day)

    s = by_id(result)
    assert (s["gym"].start_min, s["gym"].end_min) == (1020, 1080)


def test_impossible_task_is_unscheduled():
    day = DayConfig(day_start_min=480, day_end_min=1080)  # 08:00-18:00
    tasks = [
        Task(id="study", title="Studio", duration_min=60),
        # deve finire entro le 07:00, ma la giornata inizia alle 08:00
        Task(id="early", title="Troppo presto", duration_min=60, deadline_min=420),
    ]

    result = schedule(tasks, day)

    assert result.unscheduled == ["early"]
    assert set(by_id(result)) == {"study"}


def test_required_task_is_kept_over_normal_tasks():
    day = DayConfig(day_start_min=480, day_end_min=600)  # 120 minuti
    tasks = [
        Task(id="lunch", title="Pranzo", duration_min=60, priority=1, required=True),
        Task(id="n1", title="Normale 1", duration_min=60, priority=5),
        Task(id="n2", title="Normale 2", duration_min=60, priority=5),
    ]

    result = schedule(tasks, day)

    assert "lunch" in by_id(result)
    assert len(result.unscheduled) == 1


def test_required_task_outside_the_day_makes_the_plan_infeasible():
    day = DayConfig(day_start_min=480, day_end_min=1080)  # 08:00-18:00
    tasks = [
        Task(id="study", title="Studio", duration_min=60),
        # obbligatorio alle 07:00, ma la giornata inizia alle 08:00
        Task(id="dentist", title="Dentista", duration_min=60, fixed_start_min=420, required=True),
    ]

    result = schedule(tasks, day)

    assert result.status == "INFEASIBLE"
    assert result.conflicts == ["dentist"]
    assert result.scheduled == []


def test_overlapping_required_tasks_are_reported_as_conflict():
    day = DayConfig(day_start_min=480, day_end_min=1080)
    tasks = [
        Task(id="lunch", title="Pranzo", duration_min=60, fixed_start_min=780, required=True),
        Task(id="gym", title="Palestra", duration_min=60, required=True),
        Task(id="call", title="Chiamata", duration_min=60, fixed_start_min=810, required=True),
        Task(id="study", title="Studio", duration_min=120),
    ]

    result = schedule(tasks, day)

    assert result.status == "INFEASIBLE"
    # la palestra entra comunque: il conflitto è solo tra pranzo e chiamata
    assert result.conflicts == ["lunch", "call"]


def test_feasible_plan_has_no_conflicts():
    day = DayConfig(day_start_min=480, day_end_min=600)
    tasks = [Task(id="a", title="A", duration_min=60, required=True)]

    result = schedule(tasks, day)

    assert result.status == "OPTIMAL"
    assert result.conflicts == []
