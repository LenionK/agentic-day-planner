from typing import Literal

from pydantic import BaseModel, ConfigDict

from planner.agents.parser import RejectedTask
from planner.solver.models import Schedule, Task, fmt_time

# il campo "step" di ogni riepilogo dice al chiamante a quale domanda sta rispondendo
CONFIRM_TASKS = "confirm_tasks"
RESOLVE_CONFLICT = "resolve_conflict"
REVIEW_PLAN = "review_plan"
SUGGEST_ACTIVITIES = "suggest_activities"
CONFIRM_PREFERENCES = "confirm_preferences"


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


def _task_summary(t: Task) -> TaskSummary:
    return TaskSummary(
        id=t.id,
        title=t.title,
        duration_min=t.duration_min,
        priority=t.priority,
        required=t.required,
        fixed_start=_optional_time(t.fixed_start_min),
        earliest_start=_optional_time(t.earliest_start_min),
        deadline=_optional_time(t.deadline_min),
    )


def approval(tasks: list[Task], rejected: list[RejectedTask], warnings: list[str]) -> dict:
    """Build the summary the user reviews before scheduling, as plain JSON data.

    It becomes the value of the interrupt, so it must be readable by any client:
    times as 'HH:MM', no Pydantic objects. Sources are left out: they only ground the parser.
    """
    task_summaries = []
    for t in tasks:
        task_summaries.append(_task_summary(t))

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


class ConflictSummary(BaseModel):
    """The required tasks that make the day impossible, in the same format as the confirmation.

    The answer uses the same edit format, so the editor applies it like any other correction.
    """

    step: Literal["resolve_conflict"] = RESOLVE_CONFLICT
    tasks: list[TaskSummary]
    warnings: list[str]


def conflict_summary(plan: Schedule, tasks: list[Task], warnings: list[str]) -> dict:
    """Build the question about a conflict: only the conflicting tasks, as plain JSON data."""
    conflicting = set(plan.conflicts)
    summary = ConflictSummary(
        tasks=[_task_summary(t) for t in tasks if t.id in conflicting],
        warnings=warnings,
    )
    return summary.model_dump(mode="json")


class SavedDaySummary(BaseModel):
    """The day already saved for the date, as shown in the task confirmation."""

    day_date: str
    user_input: str
    replaced: bool  # True: l'utente ha scelto di sostituirlo, i suoi task non ci sono più
    scheduled: list[ScheduledSummary]  # dove restano i task già in agenda
    unscheduled: list[str]


def saved_day_summary(saved: dict, tasks: list[Task]) -> dict:
    """Build the summary of the saved day from the state, as plain JSON data."""
    by_id = {task.id: task for task in tasks}
    pinned = saved["pinned"]
    scheduled = []
    for task_id, start in sorted(pinned.items(), key=lambda item: item[1]):
        task = by_id[task_id]
        scheduled.append(
            ScheduledSummary(
                title=task.title, start=fmt_time(start), end=fmt_time(start + task.duration_min)
            )
        )
    summary = SavedDaySummary(
        day_date=saved["day_date"],
        user_input=saved["user_input"],
        replaced=saved["replaced"],
        scheduled=scheduled,
        unscheduled=[by_id[i].title for i in saved["task_ids"] if i not in pinned],
    )
    return summary.model_dump(mode="json")
