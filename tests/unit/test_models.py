import pytest
from pydantic import ValidationError

from planner.solver.models import DayConfig, Task, fmt_time


def test_fmt_time():
    assert fmt_time(570) == "09:30"
    assert fmt_time(0) == "00:00"


def test_valid_task_defaults():
    t = Task(id="t1", title="Studio", duration_min=120)
    assert t.priority == 3
    assert t.deadline_min is None


def test_negative_duration_rejected():
    with pytest.raises(ValidationError):
        Task(id="t1", title="x", duration_min=-10)


def test_window_shorter_than_duration_rejected():
    with pytest.raises(ValidationError):
        Task(id="t1", title="x", duration_min=120, earliest_start_min=600, deadline_min=660)


def test_day_end_before_start_rejected():
    with pytest.raises(ValidationError):
        DayConfig(day_start_min=600, day_end_min=500)
