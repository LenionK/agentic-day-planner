import json
from datetime import time

import numpy as np
import pandas as pd

from planner.ui.edits import diff_edits, to_time

TIMES = ("fixed_start", "earliest_start", "deadline")


def summary_tasks() -> list[dict]:
    return [
        {
            "id": "t1",
            "title": "Studio",
            "duration_min": 120,
            "priority": 4,
            "required": False,
            "fixed_start": None,
            "earliest_start": None,
            "deadline": None,
        },
        {
            "id": "t2",
            "title": "Dentista",
            "duration_min": 50,
            "priority": 4,
            "required": False,
            "fixed_start": "15:30",
            "earliest_start": None,
            "deadline": None,
        },
    ]


def rows(**changes: dict) -> dict:
    """Edited rows as the table returns them: times as datetime.time, plus the given changes."""
    result = {}
    for task in summary_tasks():
        row = dict(task)
        for field in TIMES:
            row[field] = to_time(row[field])
        result[task["id"]] = row
    for task_id, fields in changes.items():
        result[task_id].update(fields)
    return result


def test_to_time_reads_hhmm():
    assert to_time("09:05") == time(9, 5)
    assert to_time(None) is None


def test_no_changes_confirms_everything():
    assert diff_edits(summary_tasks(), rows()) == {"edits": {}}


def test_only_changed_field_of_changed_task_is_sent():
    edited = rows(t2={"priority": 2})

    assert diff_edits(summary_tasks(), edited) == {"edits": {"t2": {"priority": 2}}}


def test_changes_on_several_tasks_stay_separate():
    edited = rows(t1={"duration_min": 90}, t2={"required": True, "priority": 1})

    assert diff_edits(summary_tasks(), edited) == {
        "edits": {"t1": {"duration_min": 90}, "t2": {"required": True, "priority": 1}}
    }


def test_numpy_values_become_plain_python():
    edited = rows(
        t1={"duration_min": np.int64(120), "priority": np.int64(4), "required": np.bool_(False)},
        t2={"priority": np.int64(2), "required": np.bool_(True)},
    )

    result = diff_edits(summary_tasks(), edited)

    assert result == {"edits": {"t2": {"priority": 2, "required": True}}}
    assert type(result["edits"]["t2"]["priority"]) is int
    assert type(result["edits"]["t2"]["required"]) is bool
    json.dumps(result)


def test_emptied_number_cell_is_sent_as_null():
    edited = rows(t1={"duration_min": float("nan")})

    assert diff_edits(summary_tasks(), edited) == {"edits": {"t1": {"duration_min": None}}}


def test_new_and_changed_times_are_sent_as_hhmm():
    edited = rows(t1={"deadline": time(18, 0)}, t2={"fixed_start": time(9, 5)})

    result = diff_edits(summary_tasks(), edited)

    assert result == {"edits": {"t1": {"deadline": "18:00"}, "t2": {"fixed_start": "09:05"}}}
    json.dumps(result)


def test_emptied_time_removes_it():
    for empty in (None, pd.NaT, float("nan")):
        edited = rows(t2={"fixed_start": empty})

        assert diff_edits(summary_tasks(), edited) == {"edits": {"t2": {"fixed_start": None}}}


def test_times_edited_in_the_browser_come_as_iso_strings():
    # il TimeColumn restituisce stringhe con secondi e millisecondi, non datetime.time
    edited = rows(t1={"deadline": "17:00:00.000"}, t2={"fixed_start": "09:05:00"})

    result = diff_edits(summary_tasks(), edited)

    assert result == {"edits": {"t1": {"deadline": "17:00"}, "t2": {"fixed_start": "09:05"}}}


def test_unchanged_time_as_string_is_not_an_edit():
    # "15:30" salvato, "15:30:00.000" dal browser: stesso orario, nessuna correzione
    edited = rows(t2={"fixed_start": "15:30:00.000"})

    assert diff_edits(summary_tasks(), edited) == {"edits": {}}
