"""Merge a new sentence into a day that is already saved.

The saved tasks stay where they are: for the solver they are pinned (fixed start, required),
but only on copies, so their own data is saved back unchanged. The new tasks get ids
after the saved ones and fill the free time if they fit.
"""

import re

from planner.db.store import SavedDay
from planner.solver.models import Task

_TASK_KEY = re.compile(r"t(\d+)")


def _next_index(keys: list[str]) -> int:
    numbers = [int(m.group(1)) for key in keys if (m := _TASK_KEY.fullmatch(key))]
    return max(numbers, default=0) + 1


def merge_with_saved(
    saved: SavedDay, tasks: list[Task], sources: dict[str, str]
) -> tuple[list[Task], dict[str, str], dict]:
    """Saved tasks first, then the new ones renumbered after them (t1..t3 saved -> t4, t5...).

    Returns all the tasks, all the sources and the info about the saved day for the state:
    which tasks come from it (read only) and where each scheduled one is pinned.
    """
    start = _next_index([task.id for task in saved.tasks])
    renamed = {task.id: f"t{start + i}" for i, task in enumerate(tasks)}
    new_tasks = [task.model_copy(update={"id": renamed[task.id]}) for task in tasks]
    new_sources = {renamed[key]: text for key, text in sources.items() if key in renamed}

    info = {
        "day_date": saved.day_date.isoformat(),
        "user_input": saved.user_input,
        "task_ids": [task.id for task in saved.tasks],
        "pinned": {item.task_id: item.start_min for item in saved.scheduled},
        "replaced": False,  # True se l'utente sceglie di sostituire il piano salvato
    }
    return saved.tasks + new_tasks, saved.sources | new_sources, info


def pin_for_solver(tasks: list[Task], pinned: dict[str, int]) -> list[Task]:
    """Copies of the tasks where the pinned ones have a fixed start and are required.

    model_copy is fine here: the saved positions already satisfied every constraint.
    """
    return [
        task.model_copy(update={"fixed_start_min": pinned[task.id], "required": True})
        if task.id in pinned
        else task
        for task in tasks
    ]
