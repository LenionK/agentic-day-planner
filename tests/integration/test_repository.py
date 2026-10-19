"""PostgresPlanRepository opens its own connections and commits: tables are emptied after each test."""

from datetime import date

import psycopg
import pytest

from planner.db.repository import DayAlreadySaved, PostgresPlanRepository
from planner.solver.models import DayConfig, Schedule, ScheduledTask, Task

DAY_DATE = date(2026, 10, 22)
DAY = DayConfig(day_start_min=480, day_end_min=1080)
TASKS = [Task(id="t1", title="Studio", duration_min=60)]
PLAN = Schedule(
    status="OPTIMAL",
    scheduled=[ScheduledTask(task_id="t1", title="Studio", start_min=480, end_min=540)],
)


@pytest.fixture
def repository(db_url):
    yield PostgresPlanRepository(db_url)
    with psycopg.connect(db_url) as conn:
        conn.execute("DELETE FROM days")  # i task vanno via con ON DELETE CASCADE


def save(repository, user_input: str = "studio", **kwargs) -> int:
    return repository.save(DAY_DATE, user_input, DAY, TASKS, PLAN, {"t1": "studio"}, **kwargs)


def test_save_is_committed_and_visible_to_a_new_connection(repository):
    save(repository)

    # load apre un'altra connessione: vede il dato solo se il salvataggio è stato confermato
    assert repository.load(DAY_DATE).tasks == TASKS


def test_same_date_raises_day_already_saved_not_a_psycopg_error(repository):
    save(repository)

    with pytest.raises(DayAlreadySaved):
        save(repository, user_input="di nuovo")


def test_replace_takes_the_place_of_the_saved_day(repository):
    old_id = save(repository)

    new_id = save(repository, user_input="di nuovo", replace=True)

    assert new_id != old_id
    assert repository.load(DAY_DATE).user_input == "di nuovo"


def test_unknown_date_loads_none(repository):
    assert repository.load(date(2030, 1, 1)) is None
