"""Save planned days to PostgreSQL and read them back.

The functions receive an open connection instead of opening one: the caller decides
the transaction (the graph commits, the tests roll back). Every query is parametrized:
values travel apart from the SQL, so the user's sentence is never run as SQL.
"""

from datetime import date

import psycopg
from psycopg.rows import class_row, dict_row
from pydantic import BaseModel

from planner.solver.models import DayConfig, Schedule, ScheduledTask, Task

_INSERT_DAY = """
    INSERT INTO days (day_date, user_input, day_start_min, day_end_min)
    VALUES (%s, %s, %s, %s)
    RETURNING id
"""

_INSERT_TASK = """
    INSERT INTO tasks (
        day_id, task_key, title, source, duration_min, priority, required,
        fixed_start_min, earliest_start_min, deadline_min,
        scheduled_start_min, scheduled_end_min
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_SELECT_DAY = """
    SELECT id, day_date, user_input, day_start_min, day_end_min
    FROM days
    WHERE day_date = %s
"""

# ORDER BY id: l'ordine di inserimento, cioè quello del parser
# (task_key in ordine alfabetico metterebbe "t10" prima di "t2")
_SELECT_TASKS = """
    SELECT task_key, title, source, duration_min, priority, required,
           fixed_start_min, earliest_start_min, deadline_min,
           scheduled_start_min, scheduled_end_min
    FROM tasks
    WHERE day_id = %s
    ORDER BY id
"""


class SavedDay(BaseModel):
    """A day as stored: what the user wrote, the confirmed tasks and where the plan put them."""

    id: int
    day_date: date
    user_input: str
    day: DayConfig
    tasks: list[Task]
    sources: dict[str, str]  # task id -> source, only for tasks that have one
    scheduled: list[ScheduledTask]  # in ordine di orario; i task assenti non sono nel piano


def save_day(
    conn: psycopg.Connection,
    day_date: date,
    user_input: str,
    day: DayConfig,
    tasks: list[Task],
    plan: Schedule,
    sources: dict[str, str],
) -> int:
    """Save a day with its tasks and their place in the plan; return the id of the day.

    All or nothing: if any row is rejected, nothing of this day is saved.
    Raises psycopg.errors.UniqueViolation if the date is already saved.
    """
    positions = {item.task_id: item for item in plan.scheduled}
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(_INSERT_DAY, (day_date, user_input, day.day_start_min, day.day_end_min))
        (day_id,) = cur.fetchone()
        cur.executemany(
            _INSERT_TASK,
            [
                (
                    day_id,
                    task.id,
                    task.title,
                    sources.get(task.id),
                    task.duration_min,
                    task.priority,
                    task.required,
                    task.fixed_start_min,
                    task.earliest_start_min,
                    task.deadline_min,
                    positions[task.id].start_min if task.id in positions else None,
                    positions[task.id].end_min if task.id in positions else None,
                )
                for task in tasks
            ],
        )
    return day_id


def replace_day(
    conn: psycopg.Connection,
    day_date: date,
    user_input: str,
    day: DayConfig,
    tasks: list[Task],
    plan: Schedule,
    sources: dict[str, str],
) -> int:
    """Save a day in place of the one already saved for that date (if any).

    Delete and insert happen in one transaction: if the new day is rejected,
    the old one is still there. The old tasks go with ON DELETE CASCADE.
    """
    with conn.transaction():
        conn.execute("DELETE FROM days WHERE day_date = %s", (day_date,))
        # dentro una transazione aperta, quella di save_day diventa un savepoint
        return save_day(conn, day_date, user_input, day, tasks, plan, sources)


def load_day(conn: psycopg.Connection, day_date: date) -> SavedDay | None:
    """Read back a saved day, or None if that date was never saved."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_SELECT_DAY, (day_date,))
        day_row = cur.fetchone()
        if day_row is None:
            return None
        cur.execute(_SELECT_TASKS, (day_row["id"],))
        task_rows = cur.fetchall()

    tasks, sources, scheduled = [], {}, []
    for row in task_rows:
        task = Task(
            id=row["task_key"],
            title=row["title"],
            duration_min=row["duration_min"],
            priority=row["priority"],
            required=row["required"],
            fixed_start_min=row["fixed_start_min"],
            earliest_start_min=row["earliest_start_min"],
            deadline_min=row["deadline_min"],
        )
        tasks.append(task)
        if row["source"] is not None:
            sources[task.id] = row["source"]
        if row["scheduled_start_min"] is not None:
            scheduled.append(
                ScheduledTask(
                    task_id=task.id,
                    title=task.title,
                    start_min=row["scheduled_start_min"],
                    end_min=row["scheduled_end_min"],
                )
            )

    return SavedDay(
        id=day_row["id"],
        day_date=day_row["day_date"],
        user_input=day_row["user_input"],
        # solo inizio e fine sono salvati: gli altri campi di DayConfig hanno i default
        day=DayConfig(day_start_min=day_row["day_start_min"], day_end_min=day_row["day_end_min"]),
        tasks=tasks,
        sources=sources,
        scheduled=sorted(scheduled, key=lambda item: item.start_min),
    )


class DaySummary(BaseModel):
    """One row of the day_summary view: how full a saved day is."""

    id: int
    day_date: date
    weekday: int  # 1 = lunedì ... 7 = domenica
    user_input: str
    day_minutes: int
    task_count: int
    required_count: int
    busy_minutes: int
    busy_percent: int
    first_start_min: int | None  # None se la giornata non ha task
    last_end_min: int | None


def day_summaries(conn: psycopg.Connection) -> list[DaySummary]:
    """All saved days, most recent first, as computed by the day_summary view."""
    # class_row: ogni riga diventa direttamente un DaySummary, campo per colonna
    with conn.cursor(row_factory=class_row(DaySummary)) as cur:
        cur.execute("SELECT * FROM day_summary ORDER BY day_date DESC")
        return cur.fetchall()


def scheduled_by_day(conn: psycopg.Connection) -> dict[date, list[ScheduledTask]]:
    """The plan of every saved day, in time order: one query for all days, not one per day."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT d.day_date, t.task_key, t.title, t.scheduled_start_min, t.scheduled_end_min
            FROM days d JOIN tasks t ON t.day_id = d.id
            WHERE t.scheduled_start_min IS NOT NULL
            ORDER BY d.day_date DESC, t.scheduled_start_min
            """
        )
        plans: dict[date, list[ScheduledTask]] = {}
        for row in cur:
            plans.setdefault(row["day_date"], []).append(
                ScheduledTask(
                    task_id=row["task_key"],
                    title=row["title"],
                    start_min=row["scheduled_start_min"],
                    end_min=row["scheduled_end_min"],
                )
            )
        return plans


KEEP_DAYS = 14  # le giornate più vecchie di due settimane si cancellano


def purge_old_days(conn: psycopg.Connection, keep_days: int = KEEP_DAYS) -> int:
    """Delete the days older than keep_days with the purge_old_days procedure.

    Returns how many days were deleted: CALL returns nothing, so they are counted first
    with the same condition, in the same transaction.
    """
    with conn.transaction():
        # ::integer: "data - intero" esiste solo per integer, psycopg potrebbe mandare smallint
        (count,) = conn.execute(
            "SELECT count(*) FROM days WHERE day_date < current_date - %s::integer", (keep_days,)
        ).fetchone()
        conn.execute("CALL purge_old_days(%s::integer)", (keep_days,))
    return count
