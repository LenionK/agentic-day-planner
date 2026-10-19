"""Integration tests: they need the PostgreSQL container (`docker compose up -d`).

Each test gets the `db` connection from conftest, rolled back at the end.
"""

from datetime import date

import psycopg
import pytest

from planner.db.store import day_summaries, load_day, replace_day, save_day, scheduled_by_day
from planner.solver.models import DayConfig, Schedule, ScheduledTask, Task

DAY_DATE = date(2026, 10, 20)
DAY = DayConfig(day_start_min=420, day_end_min=1200)  # 07:00-20:00, non il default

TASKS = [
    Task(id="t1", title="Studio", duration_min=120, priority=4, earliest_start_min=480),
    Task(
        id="t2", title="Dentista", duration_min=60, priority=5, required=True, fixed_start_min=900
    ),
    Task(id="t3", title="Spesa", duration_min=30, priority=1, deadline_min=1140),
]
PLAN = Schedule(
    status="OPTIMAL",
    scheduled=[
        ScheduledTask(task_id="t2", title="Dentista", start_min=900, end_min=960),
        ScheduledTask(task_id="t1", title="Studio", start_min=480, end_min=600),
    ],
    unscheduled=["t3"],
)
SOURCES = {"t1": "studiare 2 ore dopo le 8", "t2": "dentista alle 15"}  # t3 senza source


def save(conn, **changes) -> int:
    args = {
        "day_date": DAY_DATE,
        "user_input": "studiare 2 ore dopo le 8, dentista alle 15, se riesco la spesa",
        "day": DAY,
        "tasks": TASKS,
        "plan": PLAN,
        "sources": SOURCES,
    } | changes
    return save_day(conn, **args)


def test_saved_day_is_read_back_identical(db):
    day_id = save(db)

    saved = load_day(db, DAY_DATE)

    assert saved.id == day_id
    assert saved.day_date == DAY_DATE
    assert saved.user_input.startswith("studiare 2 ore")
    assert (saved.day.day_start_min, saved.day.day_end_min) == (420, 1200)
    assert saved.tasks == TASKS  # stessi Task, nello stesso ordine
    assert saved.sources == SOURCES
    # in ordine di orario; la spesa non è nel piano
    assert [(s.task_id, s.start_min, s.end_min) for s in saved.scheduled] == [
        ("t1", 480, 600),
        ("t2", 900, 960),
    ]


def test_order_of_tasks_is_the_insertion_order_not_alphabetical(db):
    tasks = [Task(id=f"t{i}", title=f"Task {i}", duration_min=10) for i in (1, 2, 10)]
    save(db, tasks=tasks, plan=Schedule(status="OPTIMAL"), sources={})

    assert [t.id for t in load_day(db, DAY_DATE).tasks] == ["t1", "t2", "t10"]


def test_unknown_date_returns_none(db):
    save(db)

    assert load_day(db, date(2026, 10, 21)) is None


def test_same_date_twice_is_rejected_and_the_first_day_stays(db):
    save(db)

    with pytest.raises(psycopg.errors.UniqueViolation):
        save(db, user_input="di nuovo il 20")

    assert load_day(db, DAY_DATE).user_input.startswith("studiare 2 ore")


def test_save_is_all_or_nothing(db):
    # la posizione nel piano dura 50 minuti ma il task 120: il vincolo la rifiuta
    wrong_plan = Schedule(
        status="OPTIMAL",
        scheduled=[ScheduledTask(task_id="t1", title="Studio", start_min=480, end_min=530)],
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        save(db, plan=wrong_plan)

    # senza transazione resterebbe una giornata senza task
    assert load_day(db, DAY_DATE) is None


def test_user_input_is_stored_as_data_never_run_as_sql(db):
    sentence = "studio'); DROP TABLE days; -- e l'apostrofo di dell'ora"

    save(db, user_input=sentence)

    assert load_day(db, DAY_DATE).user_input == sentence
    assert db.execute("SELECT to_regclass('days')").fetchone() == ("days",)


@pytest.mark.parametrize("attempt", [1, 2])
def test_each_test_starts_from_empty_tables(db, attempt):
    # due esecuzioni che salvano la stessa data: passano entrambe solo se
    # ogni test viene annullato alla fine
    save(db)

    assert db.execute("SELECT count(*) FROM days").fetchone() == (1,)


NEW_TASKS = [Task(id="t1", title="Palestra", duration_min=90, priority=3)]
NEW_PLAN = Schedule(
    status="OPTIMAL",
    scheduled=[ScheduledTask(task_id="t1", title="Palestra", start_min=1020, end_min=1110)],
)


def replace(conn, **changes) -> int:
    args = {
        "day_date": DAY_DATE,
        "user_input": "palestra un'ora e mezza",
        "day": DAY,
        "tasks": NEW_TASKS,
        "plan": NEW_PLAN,
        "sources": {"t1": "palestra un'ora e mezza"},
    } | changes
    return replace_day(conn, **args)


def test_replace_puts_the_new_day_in_place_of_the_old_one(db):
    old_id = save(db)

    new_id = replace(db)

    saved = load_day(db, DAY_DATE)
    assert new_id != old_id
    assert saved.user_input == "palestra un'ora e mezza"
    assert saved.tasks == NEW_TASKS  # i task vecchi sono spariti con ON DELETE CASCADE
    assert db.execute("SELECT count(*) FROM tasks").fetchone() == (1,)


def test_replace_on_a_new_date_is_a_normal_save(db):
    replace(db)

    assert load_day(db, DAY_DATE).tasks == NEW_TASKS


def test_failed_replace_keeps_the_old_day(db):
    save(db)
    wrong_plan = Schedule(
        status="OPTIMAL",
        scheduled=[ScheduledTask(task_id="t1", title="Palestra", start_min=1020, end_min=1030)],
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        replace(db, plan=wrong_plan)

    # cancellazione e inserimento nella stessa transazione: la vecchia giornata è ancora lì
    assert load_day(db, DAY_DATE).tasks == TASKS


def test_day_summary_counts_busy_time_and_keeps_days_without_tasks(db):
    # 07:00-20:00 = 780 minuti; nel piano studio (120) e dentista (60): 180 minuti, 23%
    save(db)
    save(db, day_date=date(2026, 10, 18), tasks=[], plan=Schedule(status="OPTIMAL"), sources={})

    summaries = day_summaries(db)

    assert [s.day_date for s in summaries] == [DAY_DATE, date(2026, 10, 18)]  # recenti prima
    full, empty = summaries
    assert full.weekday == 2  # 20 ottobre 2026: martedì
    assert (full.task_count, full.required_count) == (3, 1)
    assert (full.day_minutes, full.busy_minutes, full.busy_percent) == (780, 180, 23)
    assert (full.first_start_min, full.last_end_min) == (480, 960)
    # LEFT JOIN: la giornata senza task c'è, con zeri e nessun orario
    assert (empty.task_count, empty.busy_minutes, empty.busy_percent) == (0, 0, 0)
    assert empty.first_start_min is None


def test_day_summary_is_empty_without_saved_days(db):
    assert day_summaries(db) == []


def test_scheduled_by_day_returns_each_plan_in_time_order(db):
    save(db)  # 20/10: studio 8-10, dentista 15-16 (la spesa non è nel piano)
    save(db, day_date=date(2026, 10, 21), tasks=NEW_TASKS, plan=NEW_PLAN, sources={})

    plans = scheduled_by_day(db)

    assert list(plans) == [date(2026, 10, 21), DAY_DATE]  # recenti prima
    assert [(s.title, s.start_min) for s in plans[DAY_DATE]] == [("Studio", 480), ("Dentista", 900)]
    assert [s.title for s in plans[date(2026, 10, 21)]] == ["Palestra"]
