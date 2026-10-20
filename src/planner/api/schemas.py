from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    """A new plan: the sentence describing the day and its date."""

    text: str = Field(min_length=1)
    day_date: date


class PlanQuestion(BaseModel):
    """The graph is paused: `step` says which question, `question` holds what to show."""

    thread_id: str
    step: str
    question: dict


class ResumeRequest(BaseModel):
    """The answer to the question the graph is waiting on, in the format its step asks for."""

    # {} non riprende il grafo (e dopo una risposta sbagliata la ripresenterebbe): rifiutato qui
    answer: dict = Field(min_length=1)


class PlanResult(BaseModel):
    """The graph is finished: the plan, the critic's review and what was saved."""

    thread_id: str
    step: Literal["done"] = "done"
    plan: dict
    critique: dict
    # i task confermati, ognuno con "slot" ("09:00–10:30", None se rimasto fuori dal piano):
    # confermato non vuol dire inserito
    tasks: list[dict]
    rejected: list[dict]  # scartati dal parser, con il motivo
    save_result: dict | None = None  # None senza database
    preference_result: dict | None = None  # None se non c'erano preferenze da ricordare
    # quante preferenze c'erano nella frase; None se il passo non c'è stato (senza database)
    preference_candidates: int | None = None


class SavedDayView(BaseModel):
    """A saved day in the history: what the user wrote, how full it is, its plan."""

    day_date: date
    user_input: str
    day_minutes: int
    busy_minutes: int
    free_minutes: int
    scheduled: list[dict]  # {"title", "start", "end"} in ordine di orario
