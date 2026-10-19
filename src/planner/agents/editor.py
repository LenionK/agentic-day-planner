from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from planner.agents.parser import to_minutes
from planner.solver.models import Task

TIME_FIELDS = ("fixed_start", "earliest_start", "deadline")


class TaskEdit(BaseModel):
    """The user's correction to one task. Every field is optional: only what is set changes.

    Times are 'HH:MM' strings, like in the summary; null removes the time.
    For the other fields an explicit null passes here but is rejected when the Task is rebuilt.
    """

    model_config = ConfigDict(extra="forbid")  # un campo scritto male è un errore, non un no-op

    priority: int | None = Field(default=None, ge=1, le=5)
    required: bool | None = None
    duration_min: int | None = Field(default=None, gt=0, le=720)
    fixed_start: str | None = None
    earliest_start: str | None = None
    deadline: str | None = None

    @field_validator(*TIME_FIELDS)
    @classmethod
    def check_time_format(cls, value: str | None) -> str | None:
        if value is not None:
            to_minutes(value)  # ValueError -> ValidationError: il grafo resta in pausa
        return value


class ApprovalResponse(BaseModel):
    """What the caller sends to resume the graph. {"edits": {}} confirms everything.

    The same format works for a form filled in by the user and, in the future,
    for edits proposed by an agent.
    """

    model_config = ConfigDict(extra="forbid")

    edits: dict[str, TaskEdit]
    # solo se la data ha già un piano salvato: True lo sostituisce invece di unirlo
    replace_saved: bool = False


def _short_error(err: ValidationError) -> str:
    return "; ".join(error["msg"] for error in err.errors())


def _to_task_fields(changes: dict) -> dict:
    """Rename the time fields to the Task ones and turn 'HH:MM' into minutes."""
    fields = dict(changes)
    for name in TIME_FIELDS:
        if name in fields:
            value = fields.pop(name)
            fields[f"{name}_min"] = None if value is None else to_minutes(value)
    return fields


def apply_edits(tasks: list[Task], response: ApprovalResponse) -> tuple[list[Task], list[str]]:
    """Apply the corrections and return the new tasks plus one warning per skipped edit.

    The input tasks are not modified and keep their order; tasks without edits are returned as is.
    An edit for an id that does not exist is skipped with a warning.
    Times arrive as 'HH:MM' and are converted to minutes here, for the scheduler.
    An edit that would make its task invalid (e.g. a duration longer than its time window)
    is skipped as a whole with a warning: the task stays as it was.
    A task that ends up required gets the top priority, as in the parser.
    """
    known_ids = {task.id for task in tasks}
    warnings = []
    for task_id in response.edits:
        if task_id not in known_ids:
            warnings.append(f"{task_id}: correzione ignorata (task inesistente)")

    edited = []
    for task in tasks:
        edit = response.edits.get(task.id)
        if edit is None:
            edited.append(task)
            continue

        changes = edit.model_dump(exclude_unset=True)  # solo i campi scritti dall'utente
        data = {**task.model_dump(), **_to_task_fields(changes)}
        if data["required"]:
            data["priority"] = 5  # obbligatorio => priorità 5, come nel parser
        try:
            # model_validate, non model_copy: i validator di Task devono girare
            edited.append(Task.model_validate(data))
        except ValidationError as err:
            warnings.append(f"{task.id}: correzione ignorata ({_short_error(err)})")
            edited.append(task)

    return edited, warnings
