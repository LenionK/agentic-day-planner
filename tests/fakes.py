from datetime import date

from pydantic import BaseModel

from planner.db.repository import DayAlreadySaved
from planner.db.store import SavedDay
from planner.llm.base import LLMClient
from planner.solver.models import DayConfig, Schedule, Task


class FakeClient(LLMClient):
    """Returns prepared answers, one per call, and records the messages it receives."""

    def __init__(self, responses: list[str], max_retries: int = 2) -> None:
        super().__init__(max_retries)
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def _complete(self, messages: list[dict], schema: type[BaseModel]) -> str:
        self.calls.append(list(messages))
        return self.responses.pop(0)


class FakePlanRepository:
    """In-memory PlanRepository: days by date, and a record of every save."""

    def __init__(self, *days: SavedDay) -> None:
        self.days: dict[date, SavedDay] = {d.day_date: d for d in days}
        self.saves: list[tuple[date, bool]] = []  # (data, replace) di ogni salvataggio
        self.conflict_on_save = False  # simula un salvataggio concorrente della stessa data

    def load(self, day_date: date) -> SavedDay | None:
        return self.days.get(day_date)

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
        self.saves.append((day_date, replace))
        if self.conflict_on_save or (day_date in self.days and not replace):
            raise DayAlreadySaved(day_date.isoformat())
        day_id = len(self.saves)
        self.days[day_date] = SavedDay(
            id=day_id,
            day_date=day_date,
            user_input=user_input,
            day=day,
            tasks=tasks,
            sources=sources,
            scheduled=sorted(plan.scheduled, key=lambda item: item.start_min),
        )
        return day_id
