"""Where the graph saves plans, without knowing it is PostgreSQL.

The graph receives any object with these methods (a Protocol: no inheritance needed),
like it receives any LLMClient. Tests pass an in-memory fake.
"""

from datetime import date
from typing import Protocol

import psycopg

from planner.db.store import SavedDay, load_day, replace_day, save_day
from planner.solver.models import DayConfig, Schedule, Task


class DayAlreadySaved(Exception):
    """The date was saved by someone else between the check and the save."""


class PlanRepository(Protocol):
    def load(self, day_date: date) -> SavedDay | None:
        """The day saved for that date, or None."""
        ...

    def save(
        self,
        day_date: date,
        user_input: str,
        day: DayConfig,
        tasks: list[Task],
        plan: Schedule,
        sources: dict[str, str],
        *,
        replace: bool = False,
    ) -> int:
        """Save the day and return its id; with replace=True it takes the place of the old one.

        Raises DayAlreadySaved if replace is False and the date is already saved.
        """
        ...


class PostgresPlanRepository:
    """One connection per operation, committed at the end of the `with` block."""

    def __init__(self, conninfo: str) -> None:
        self.conninfo = conninfo

    def load(self, day_date: date) -> SavedDay | None:
        with psycopg.connect(self.conninfo) as conn:
            return load_day(conn, day_date)

    def save(
        self,
        day_date: date,
        user_input: str,
        day: DayConfig,
        tasks: list[Task],
        plan: Schedule,
        sources: dict[str, str],
        *,
        replace: bool = False,
    ) -> int:
        write = replace_day if replace else save_day
        try:
            with psycopg.connect(self.conninfo) as conn:
                return write(conn, day_date, user_input, day, tasks, plan, sources)
        except psycopg.errors.UniqueViolation as err:
            # il grafo non deve conoscere gli errori di psycopg
            raise DayAlreadySaved(day_date.isoformat()) from err
