from datetime import date

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
