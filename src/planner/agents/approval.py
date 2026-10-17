from typing import Literal

from pydantic import BaseModel, ConfigDict

from planner.agents.parser import RejectedTask
from planner.solver.models import Schedule, Task, fmt_time

# il campo "step" di ogni riepilogo dice al chiamante a quale domanda sta rispondendo
CONFIRM_TASKS = "confirm_tasks"
REVIEW_PLAN = "review_plan"


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
    step: Literal["confirm_tasks"] = CONFIRM_TASKS
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


class ScheduledSummary(BaseModel):
    title: str
    start: str
    end: str


class PlanReviewSummary(BaseModel):
    """The plan as shown to the user before accepting it: times as 'HH:MM', titles not ids."""

    step: Literal["review_plan"] = REVIEW_PLAN
    status: str
    scheduled: list[ScheduledSummary]  # in ordine di orario
    unscheduled: list[str]
    conflicts: list[str]
    warnings: list[str]


class PlanReviewResponse(BaseModel):
    """The user's answer to the plan: accept it, or go back to edit the tasks."""

    model_config = ConfigDict(extra="forbid")

    accept: bool


def plan_summary(plan: Schedule, tasks: list[Task], warnings: list[str]) -> dict:
    """Build the plan the user reviews, as plain JSON data."""
    titles = {task.id: task.title for task in tasks}
    scheduled = []
    for item in sorted(plan.scheduled, key=lambda item: item.start_min):
        scheduled.append(
            ScheduledSummary(
                title=item.title, start=fmt_time(item.start_min), end=fmt_time(item.end_min)
            )
        )

    summary = PlanReviewSummary(
        status=plan.status,
        scheduled=scheduled,
        unscheduled=[titles[task_id] for task_id in plan.unscheduled],
        conflicts=[titles[task_id] for task_id in plan.conflicts],
        warnings=warnings,
    )
    return summary.model_dump(mode="json")
