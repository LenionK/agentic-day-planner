from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


def fmt_time(minutes: int) -> str:
    """570 -> '09:30'"""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


class Period(str, Enum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


class Interval(BaseModel):
    """Fascia oraria non disponibile (pranzo, impegni fissi...)."""

    start_min: int = Field(ge=0, le=1440)
    end_min: int = Field(ge=0, le=1440)

    @model_validator(mode="after")
    def check_order(self) -> Interval:
        if self.end_min <= self.start_min:
            raise ValueError("end_min must be greater than start_min")
        return self


class Task(BaseModel):
    id: str
    title: str = Field(min_length=1)
    required: bool = False
    duration_min: int = Field(gt=0, le=720)
    priority: int = Field(default=3, ge=1, le=5)  # 5 = più importante
    earliest_start_min: int | None = Field(default=None, ge=0, le=1440)
    deadline_min: int | None = Field(default=None, ge=0, le=1440)  # deve finire entro
    fixed_start_min: int | None = Field(default=None, ge=0, le=1440)  # orario imposto
    preferred_period: Period | None = None  # preferenza morbida

    @model_validator(mode="after")
    def check_window(self) -> Task:
        if self.earliest_start_min is not None and self.deadline_min is not None:
            if self.deadline_min - self.earliest_start_min < self.duration_min:
                raise ValueError("time window is shorter than the task duration")
        if self.fixed_start_min is not None and self.deadline_min is not None:
            if self.fixed_start_min + self.duration_min > self.deadline_min:
                raise ValueError("fixed start makes the task end after its deadline")
        return self


class DayConfig(BaseModel):
    day_start_min: int = Field(default=8 * 60, ge=0, le=1440)
    day_end_min: int = Field(default=22 * 60, ge=0, le=1440)
    slot_min: int = Field(default=15, gt=0, le=60)
    free_time_min: int = Field(default=0, ge=0, le=1440)
    blocked: list[Interval] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_day(self) -> DayConfig:
        if self.day_end_min <= self.day_start_min:
            raise ValueError("day_end_min must be greater than day_start_min")
        if self.free_time_min > self.day_end_min - self.day_start_min:
            raise ValueError("free_time_min cannot exceed the length of the day")
        return self


class ScheduledTask(BaseModel):
    task_id: str
    title: str
    start_min: int
    end_min: int

    @property
    def label(self) -> str:
        return f"{fmt_time(self.start_min)}-{fmt_time(self.end_min)} {self.title}"


class Schedule(BaseModel):
    status: str  # OPTIMAL | FEASIBLE | INFEASIBLE
    scheduled: list[ScheduledTask] = Field(default_factory=list)
    unscheduled: list[str] = Field(default_factory=list)  # id dei task esclusi
    # id dei task obbligatori che rendono la giornata impossibile (solo se INFEASIBLE)
    conflicts: list[str] = Field(default_factory=list)
    objective: float | None = None
