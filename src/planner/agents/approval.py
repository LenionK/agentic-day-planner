from pydantic import BaseModel

from planner.agents.parser import RejectedTask
from planner.solver.models import Task, fmt_time


class TaskSummary(BaseModel):
    """A task as shown to the user: times as 'HH:MM', not minutes."""

    id: str
    title: str
    duration_min: int
    priority: int
    required: bool
    fixed_start: str | None
    earliest_start: str | None
    deadline: str | None


class RejectedSummary(BaseModel):
    title: str
    reason: str


class PlanSummary(BaseModel):
    tasks: list[TaskSummary]
    rejected: list[RejectedSummary]
    warnings: list[str]


def _optional_time(minutes: int | None) -> str | None:
    return None if minutes is None else fmt_time(minutes)


def approval(tasks: list[Task], rejected: list[RejectedTask], warnings: list[str]) -> dict:
    """Build the summary the user reviews before scheduling, as plain JSON data.

    It becomes the value of the interrupt, so it must be readable by any client:
    times as 'HH:MM', no Pydantic objects. Sources are left out: they only ground the parser.
    """
    task_summaries = []
    for t in tasks:
        task_summaries.append(
            TaskSummary(
                id=t.id,
                title=t.title,
                duration_min=t.duration_min,
                priority=t.priority,
                required=t.required,
                fixed_start=_optional_time(t.fixed_start_min),
                earliest_start=_optional_time(t.earliest_start_min),
                deadline=_optional_time(t.deadline_min),
            )
        )

    rejected_summaries = []
    for r in rejected:
        rejected_summaries.append(RejectedSummary(title=r.draft.title, reason=r.reason))

    summary = PlanSummary(tasks=task_summaries, rejected=rejected_summaries, warnings=warnings)
    return summary.model_dump(mode="json")
