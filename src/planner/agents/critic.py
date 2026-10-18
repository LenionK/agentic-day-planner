from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from planner.llm.base import LLMClient
from planner.solver.models import DayConfig, Interval, Schedule, fmt_time

# buchi più corti non servono a proporre attività
MIN_GAP_MIN = 15
MAX_SUGGESTIONS = 3

Category = Literal["attività fisica", "studio", "riposo", "svago", "commissioni"]


def free_slots(plan: Schedule, day: DayConfig, min_gap: int = MIN_GAP_MIN) -> list[Interval]:
    """Free time of the day not covered by the plan, in time order.

    These are facts for the critic: computed here, so the LLM never has to count minutes.
    Gaps shorter than `min_gap` are left out.
    """
    slots = []
    cursor = day.day_start_min  # fin dove la giornata è già occupata
    for item in sorted(plan.scheduled, key=lambda item: item.start_min):
        if item.start_min - cursor >= min_gap:
            slots.append(Interval(start_min=cursor, end_min=item.start_min))
        cursor = max(cursor, item.end_min)
    if day.day_end_min - cursor >= min_gap:
        slots.append(Interval(start_min=cursor, end_min=day.day_end_min))
    return slots


def free_minutes(slots: list[Interval]) -> int:
    return sum(slot.end_min - slot.start_min for slot in slots)


class Suggestion(BaseModel):
    title: str = Field(min_length=1)
    category: Category
    duration_min: int = Field(gt=0, le=240)
    reason: str


class CriticReview(BaseModel):
    """The critic's answer.

    Field order matters: the LLM writes the fields in schema order, so it describes
    the day (assessment) before deciding (too_empty) and only then proposes activities.
    """

    assessment: str = Field(min_length=1)
    too_empty: bool
    suggestions: list[Suggestion] = Field(default_factory=list, max_length=MAX_SUGGESTIONS)


class SuggestionsResponse(BaseModel):
    """The user's answer to the suggestions: positions of the accepted ones, [] = none."""

    model_config = ConfigDict(extra="forbid")

    accepted: list[int]


SYSTEM_PROMPT = """Sei il critico di un'agenda giornaliera. Ricevi il piano della giornata \
e i suoi intervalli liberi, già calcolati. Rispondi solo con il JSON richiesto.

Compila i campi in quest'ordine:

- assessment: una o due frasi che descrivono la giornata usando solo i dati ricevuti: \
quante ore sono occupate su quelle totali e qual è l'intervallo libero più lungo. \
Non nominare impegni che non sono nel piano.
- too_empty: true se la giornata ti sembra troppo vuota e varrebbe la pena aggiungere qualcosa; \
false se è già abbastanza piena o equilibrata.
- suggestions: solo se too_empty è true, da 1 a 3 attività da aggiungere; altrimenti lista vuota.
  Per ogni attività:
  - title: titolo breve
  - category: una tra "attività fisica", "studio", "riposo", "svago", "commissioni"
  - duration_min: durata in minuti, che deve stare in uno degli intervalli liberi
  - reason: una frase sul perché è utile in questa giornata
  Varia le categorie e tieni conto di quello che c'è già nel piano: per esempio, \
niente altro studio se la giornata è già piena di studio.

Usa gli intervalli liberi così come sono, senza ricalcolarli."""


def duration_text(minutes: int) -> str:
    """150 -> '2 h 30 min'"""
    hours, mins = divmod(minutes, 60)
    parts = [f"{hours} h"] if hours else []
    if mins or not hours:
        parts.append(f"{mins} min")
    return " ".join(parts)


def day_facts(slots: list[Interval], day: DayConfig) -> dict:
    """Numbers about the day's free time, computed once: the LLM and the user see the same ones."""
    total = day.day_end_min - day.day_start_min
    free = free_minutes(slots)
    longest = max(slots, key=lambda slot: slot.end_min - slot.start_min, default=None)
    return {
        "total_minutes": total,
        "busy_minutes": total - free,
        "free_minutes": free,
        "busy_percent": round(100 * (total - free) / total),
        "longest_slot": None
        if longest is None
        else {"start": fmt_time(longest.start_min), "end": fmt_time(longest.end_min)},
    }


def critic_messages(plan: Schedule, slots: list[Interval], day: DayConfig) -> list[dict]:
    """The prompt for the critic: the plan and the facts about free time, computed in Python.

    Busy time and the longest slot are spelled out: a 7B model misjudges them if it has
    to work them out from the list (it called a day with one meeting "very busy").
    """
    lines = ["Piano:"]
    items = sorted(plan.scheduled, key=lambda item: item.start_min)
    lines += [f"- {fmt_time(i.start_min)}-{fmt_time(i.end_min)} {i.title}" for i in items]
    if not items:
        lines.append("- nessun impegno")

    lines.append("Intervalli liberi:")
    for slot in slots:
        length = duration_text(slot.end_min - slot.start_min)
        lines.append(f"- {fmt_time(slot.start_min)}-{fmt_time(slot.end_min)} ({length})")
    if not slots:
        lines.append("- nessuno")
    facts = day_facts(slots, day)
    lines.append(f"Tempo libero totale: {duration_text(facts['free_minutes'])}")
    lines.append(
        f"Tempo occupato: {duration_text(facts['busy_minutes'])} su "
        f"{duration_text(facts['total_minutes'])} ({facts['busy_percent']}%)"
    )
    if facts["longest_slot"]:
        longest = facts["longest_slot"]
        lines.append(f"Intervallo libero più lungo: {longest['start']}-{longest['end']}")

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


def check_suggestions(
    review: CriticReview, slots: list[Interval]
) -> tuple[list[Suggestion], list[str]]:
    """Keep only the suggestions that fit in a real free slot, with a warning for each other one.

    If the critic says the day is fine, its suggestions (if any) are ignored.
    """
    if not review.too_empty:
        return [], []

    longest = max((slot.end_min - slot.start_min for slot in slots), default=0)
    valid, warnings = [], []
    for suggestion in review.suggestions:
        if suggestion.duration_min <= longest:
            valid.append(suggestion)
        else:
            warnings.append(
                f"Proposta scartata: {suggestion.title} ({suggestion.duration_min} min) "
                "non entra in nessun intervallo libero"
            )
    return valid, warnings


def critique(plan: Schedule, day: DayConfig, client: LLMClient) -> dict:
    """Ask the critic about the plan; returns plain JSON data for the state and the interface."""
    slots = free_slots(plan, day)
    review = client.generate(critic_messages(plan, slots, day), CriticReview)
    suggestions, warnings = check_suggestions(review, slots)
    return {
        "assessment": review.assessment,  # opinione del modello
        "too_empty": review.too_empty,
        **day_facts(slots, day),  # fatti calcolati: l'interfaccia li mostra come dati
        "suggestions": [s.model_dump(mode="json") for s in suggestions],
        "warnings": warnings,
    }
