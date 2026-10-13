import re

from pydantic import BaseModel, Field

from planner.llm.base import LLMClient
from planner.solver.models import Task

TIME_FIELDS = ("fixed_start", "earliest_start", "deadline")

# numeri da 1 o 2 cifre che NON sono seguiti da un'unità di durata ("2 ore", "30 minuti")
_HOUR_IN_TEXT = re.compile(r"\b(\d{1,2})\b(?!\s*(?:ore|ora|h|minuti|min)\b)")


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
    """A task as extracted by the LLM: times are 'HH:MM' strings, not minutes.

    `source` comes first on purpose: the LLM generates fields in schema order,
    so it isolates the part of the sentence about this task before deciding the rest.
    """

    source: str = Field(min_length=1)
    title: str
    duration_min: int = Field(gt=0, le=720)
    priority: int = Field(default=3, ge=1, le=5)
    required: bool = False
    fixed_start: str | None = None
    earliest_start: str | None = None
    deadline: str | None = None


class ParsedDay(BaseModel):
    tasks: list[TaskDraft]


def _hour_is_mentioned(hhmm: str, text: str) -> bool:
    """True if the hour of `hhmm` appears in `text`, in 24h or 12h form ('15:00' -> 15 or 3)."""
    try:
        hour = int(hhmm.strip().split(":")[0])
    except ValueError:
        return True  # formato non leggibile: lo lasciamo a to_minutes, che lo rifiuterà

    candidates = {hour, hour % 12 or 12}
    numbers = {int(n) for n in _HOUR_IN_TEXT.findall(text)}
    return bool(candidates & numbers)


def _same_time(a: str, b: str) -> bool:
    try:
        return to_minutes(a) == to_minutes(b)
    except ValueError:
        return False


def clean_times(draft: TaskDraft, text: str) -> tuple[TaskDraft, list[str]]:
    """Remove times the LLM made up, and explain each removal.

    1. A time whose hour does not appear anywhere in the user's sentence is dropped.
    2. An earliest_start equal to the deadline is dropped: a zero-length window
       is a model artifact, never what the user meant.
    Real inconsistencies (two different times both in the sentence) are kept,
    so draft_to_task can reject them.

    Returns the cleaned copy of the draft and one warning per removed time.
    """
    times = {field: getattr(draft, field) for field in TIME_FIELDS}
    warnings: list[str] = []

    for field, value in times.items():
        if value is not None and not _hour_is_mentioned(value, text):
            times[field] = None
            warnings.append(f"{draft.title}: ignorato {field} {value} (non compare nella frase)")

    earliest, deadline = times["earliest_start"], times["deadline"]
    if earliest is not None and deadline is not None and _same_time(earliest, deadline):
        times["earliest_start"] = None
        warnings.append(f"{draft.title}: ignorato earliest_start {earliest} (uguale alla scadenza)")

    return draft.model_copy(update=times), warnings


def _optional_minutes(value: str | None) -> int | None:
    return None if value is None else to_minutes(value)


def draft_to_task(draft: TaskDraft, index: int) -> Task:
    """Turn an LLM draft into a Task. Raises ValueError if times are invalid or inconsistent.

    Required tasks always get the top priority.
    """
    return Task(
        id=f"t{index}",
        title=draft.title,
        duration_min=draft.duration_min,
        priority=5 if draft.required else draft.priority,
        required=draft.required,
        fixed_start_min=_optional_minutes(draft.fixed_start),
        earliest_start_min=_optional_minutes(draft.earliest_start),
        deadline_min=_optional_minutes(draft.deadline),
    )


SYSTEM_PROMPT = """Estrai i task dalla frase dell'utente. Rispondi solo con il JSON richiesto.

Per ogni task compila i campi in quest'ordine:

- source: copia parola per parola TUTTA la parte della frase che riguarda questo task,
  dall'inizio del task fino all'inizio del task successivo. Includi durata, scadenze e vincoli,
  anche se vengono dopo una virgola. Non riassumere e non aggiungere parole.
  Poi decidi tutti gli altri campi guardando SOLO il source di questo task.

- title: titolo breve.
- duration_min: durata in minuti. Se non è indicata nel source, stima una durata ragionevole.

- priority: quanto è importante il task, da 1 a 5.
  - 5 se il source esprime urgenza o necessità ("devo", "assolutamente", "urgente" o espressioni equivalenti).
  - 1 se il source indica che il task è facoltativo ("se riesco", "magari", "se avanza tempo" o espressioni equivalenti).
  - 3 in tutti gli altri casi, anche con "dovrei".

- required: se il task NON può essere saltato. È una cosa diversa dalla priorità.
  - true se il source dice esplicitamente che non si può saltare ("non posso saltare", "irrinunciabile", "è obbligatorio" o espressioni equivalenti).
  - true se il task INIZIA a un orario preciso (fixed_start), a meno che il source lo indichi come facoltativo.
  - false in tutti gli altri casi. Una scadenza ("entro le", "prima delle") o un "dopo le" NON rendono il task obbligatorio. "Devo" da solo NON rende il task obbligatorio.

- fixed_start: orario "HH:MM" se il source dice che il task inizia a un'ora precisa ("alle 15" -> "15:00").
- earliest_start: orario "HH:MM" solo se il source dice che il task non può iniziare prima ("dopo le 17", "dalle 17" -> "17:00").
- deadline: orario "HH:MM" se il source dice che il task deve finire entro un'ora ("entro le 11", "prima delle 11" -> "11:00").

Usa sempre il formato 24 ore ("alle 4 del pomeriggio" -> "16:00").
Un orario vale solo per il task nel cui source compare. Se un orario non è nel source, lascialo a null.
Riporta durate e orari esattamente come li dice l'utente, anche se ti sembrano incoerenti.

Esempio:
Frase: "il report va finito entro le 17 e richiede due ore, alle 18 ho la cena con gli amici e non posso perderla, se riesco una corsa dopo le 20"
Task:
- source "il report va finito entro le 17 e richiede due ore": duration_min 120, priority 3, required false, deadline "17:00"
- source "alle 18 ho la cena con gli amici e non posso perderla": required true, fixed_start "18:00"
- source "se riesco una corsa dopo le 20": priority 1, required false, earliest_start "20:00\""""


class RejectedTask(BaseModel):
    draft: TaskDraft
    reason: str


class ParseResult(BaseModel):
    tasks: list[Task]
    rejected: list[RejectedTask]
    sources: dict[str, str] = Field(default_factory=dict)  # task id -> source
    warnings: list[str] = Field(default_factory=list)


def parse_day(text: str, client: LLMClient) -> ParseResult:
    """Extract tasks from free text.

    Made-up times are removed with a warning; drafts that cannot become valid Tasks
    are rejected, not lost. Rejected drafts are kept as the LLM wrote them.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    parsed = client.generate(messages, ParsedDay)

    tasks: list[Task] = []
    rejected: list[RejectedTask] = []
    sources: dict[str, str] = {}
    warnings: list[str] = []
    for index, draft in enumerate(parsed.tasks, start=1):
        cleaned, draft_warnings = clean_times(draft, text)
        warnings.extend(draft_warnings)
        try:
            task = draft_to_task(cleaned, index)
        except ValueError as err:
            rejected.append(RejectedTask(draft=draft, reason=str(err)))
            continue
        tasks.append(task)
        sources[task.id] = draft.source

    return ParseResult(tasks=tasks, rejected=rejected, sources=sources, warnings=warnings)
