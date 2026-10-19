from datetime import date

from planner.agents.merge import merge_with_saved, pin_for_solver
from planner.db.store import SavedDay
from planner.solver.cpsat_scheduler import schedule
from planner.solver.models import DayConfig, ScheduledTask, Task

DAY = DayConfig(day_start_min=480, day_end_min=1080)  # 08:00-18:00


def saved_day(*tasks: Task, scheduled: list[ScheduledTask], sources=None) -> SavedDay:
    return SavedDay(
        id=1,
        day_date=date(2026, 11, 3),
        user_input="palestra alle 16",
        day=DAY,
        tasks=list(tasks),
        sources=sources or {},
        scheduled=scheduled,
    )


GYM = Task(id="t1", title="Palestra", duration_min=60, fixed_start_min=960)
CALL = Task(id="t2", title="Chiamata", duration_min=30)
SAVED = saved_day(
    GYM,
    CALL,
    scheduled=[ScheduledTask(task_id="t1", title="Palestra", start_min=960, end_min=1020)],
    sources={"t1": "palestra alle 16"},
)


def test_new_tasks_get_ids_after_the_saved_ones_with_their_sources():
    new = [
        Task(id="t1", title="Studio", duration_min=120),
        Task(id="t2", title="Spesa", duration_min=30),
    ]

    tasks, sources, _ = merge_with_saved(SAVED, new, {"t1": "studiare", "t2": "la spesa"})

    assert [(t.id, t.title) for t in tasks] == [
        ("t1", "Palestra"),
        ("t2", "Chiamata"),
        ("t3", "Studio"),
        ("t4", "Spesa"),
    ]
    assert sources == {"t1": "palestra alle 16", "t3": "studiare", "t4": "la spesa"}


def test_renumbering_starts_after_the_highest_saved_id_not_after_the_count():
    saved = saved_day(
        Task(id="t2", title="A", duration_min=10),
        Task(id="t7", title="B", duration_min=10),
        scheduled=[],
    )

    tasks, _, _ = merge_with_saved(saved, [Task(id="t1", title="Nuovo", duration_min=10)], {})

    assert [t.id for t in tasks] == ["t2", "t7", "t8"]


def test_info_lists_the_saved_tasks_and_pins_only_the_scheduled_ones():
    _, _, info = merge_with_saved(SAVED, [], {})

    assert info == {
        "day_date": "2026-11-03",
        "user_input": "palestra alle 16",
        "task_ids": ["t1", "t2"],
        "pinned": {"t1": 960},  # la chiamata non era nel piano: non è bloccata
        "replaced": False,
    }


def test_pinning_works_on_copies():
    pinned = pin_for_solver([CALL], {"t2": 600})

    assert (pinned[0].fixed_start_min, pinned[0].required) == (600, True)
    assert (CALL.fixed_start_min, CALL.required) == (None, False)  # l'originale non cambia


def test_scheduler_keeps_pinned_tasks_and_fills_the_free_time():
    study = Task(id="t3", title="Studio", duration_min=120, priority=5)
    long_task = Task(id="t4", title="Progetto", duration_min=480, priority=1)
    tasks = [GYM, study, long_task]

    plan = schedule(pin_for_solver(tasks, {"t1": 960}), DAY)

    by_id = {item.task_id: item.start_min for item in plan.scheduled}
    assert by_id["t1"] == 960  # la palestra resta alle 16
    assert "t3" in by_id  # lo studio entra in uno spazio libero
    assert plan.unscheduled == ["t4"]  # 8 ore non entrano nelle 9 libere meno lo studio
