from pydantic import BaseModel, Field

from planner.llm.base import LLMClient
from planner.solver.models import Task


def to_minutes(hhmm: str) -> int:
    """Convert a 'HH:MM' time into minutes from midnight ('15:30' -> 930)."""
    parts = hhmm.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"invalid time format: {hhmm!r}, expected 'HH:MM'")

    hours, minutes = int(parts[0]), int(parts[1])
    if not 0 <= hours <= 23:
        raise ValueError(f"hours out of range: {hhmm!r}")
    if not 0 <= minutes <= 59:
        raise ValueError(f"minutes out of range: {hhmm!r}")

    return hours * 60 + minutes


class TaskDraft(BaseModel):
    """A task as extracted by the LLM: times are 'HH:MM' strings, not minutes."""

    title: str
    duration_min: int = Field(gt=0, le=720)
    priority: int = Field(default=3, ge=1, le=5)
    required: bool = False
    fixed_start: str | None = None
    earliest_start: str | None = None
    deadline: str | None = None


class ParsedDay(BaseModel):
    tasks: list[TaskDraft]


def _optional_minutes(value: str | None) -> int | None:
    return None if value is None else to_minutes(value)


def draft_to_task(draft: TaskDraft, index: int) -> Task:
    """Turn an LLM draft into a Task. Raises ValueError if times are invalid or inconsistent."""
    return Task(
        id=f"t{index}",
        title=draft.title,
        duration_min=draft.duration_min,
        priority=draft.priority,
        required=draft.required,
        fixed_start_min=_optional_minutes(draft.fixed_start),
        earliest_start_min=_optional_minutes(draft.earliest_start),
        deadline_min=_optional_minutes(draft.deadline),
    )


SYSTEM_PROMPT = """Estrai i task dalla frase dell'utente. Rispondi solo con il JSON richiesto.

Per ogni task:
- title: titolo breve
- duration_min: durata in minuti; se non è indicata, stima una durata ragionevole
- priority: 5 se l'utente usa "devo", "assolutamente", "urgente"; 1 se usa "se riesco", "magari", "se avanza tempo"; 3 negli altri casi. Non usare l'ordine dei task per decidere.
- required: true solo per impegni con un orario preciso o che l'utente dice di non poter saltare
- fixed_start: orario "HH:MM" se il task è a un'ora precisa ("alle 15" -> "15:00")
- earliest_start: orario "HH:MM" se il task non può iniziare prima ("dopo le 17" -> "17:00")
- deadline: orario "HH:MM" se il task deve finire entro un'ora ("entro le 11" -> "11:00")

Usa sempre il formato 24 ore. Lascia gli orari a null se non sono indicati: non inventarli."""


class RejectedTask(BaseModel):
    draft: TaskDraft
    reason: str


class ParseResult(BaseModel):
    tasks: list[Task]
    rejected: list[RejectedTask]


def parse_day(text: str, client: LLMClient) -> ParseResult:
    """Extract tasks from free text. Drafts that cannot become valid Tasks are rejected, not lost."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    parsed = client.generate(messages, ParsedDay)

    tasks: list[Task] = []
    rejected: list[RejectedTask] = []
    for index, draft in enumerate(parsed.tasks, start=1):
        try:
            tasks.append(draft_to_task(draft, index))
        except ValueError as err:
            rejected.append(RejectedTask(draft=draft, reason=str(err)))

    return ParseResult(tasks=tasks, rejected=rejected)
