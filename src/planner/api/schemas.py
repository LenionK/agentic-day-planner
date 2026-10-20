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
    save_result: dict | None = None  # None senza database
    preference_result: dict | None = None  # None se non c'erano preferenze da ricordare
