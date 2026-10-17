"""Turn the rows edited in the interface into the editor's response format.

No Streamlit here, so it can be tested on its own.
"""

from collections.abc import Mapping
from datetime import time

import pandas as pd


def to_time(hhmm: str | None) -> time | None:
    """'09:30' -> time(9, 30), for the time picker of the table."""
    return None if hhmm is None else time.fromisoformat(hhmm)


def _hhmm(value: time | str) -> str:
    return value.strftime("%H:%M") if isinstance(value, time) else str(value)


# campi modificabili e conversione in valori semplici: la tabella restituisce tipi numpy
# e orari come datetime.time, l'editor vuole int, bool e "HH:MM"
EDITABLE_FIELDS = {
    "priority": int,
    "required": bool,
    "duration_min": int,
    "fixed_start": _hhmm,
    "earliest_start": _hhmm,
    "deadline": _hhmm,
}


def _plain(value, convert):
    if pd.isna(value):  # None, NaN o NaT: la cella è vuota
        return None  # orario svuotato = vincolo tolto; per gli altri campi l'editor avvisa
    return convert(value)


def diff_edits(tasks: list[dict], edited: Mapping[str, Mapping]) -> dict:
    """Compare the summary tasks with the edited rows (task id -> fields), keep only the changes.

    The result is the value used to resume the graph: {"edits": {}} when nothing changed.
    """
    edits = {}
    for task in tasks:
        row = edited.get(task["id"])
        if row is None:
            continue
        changes = {}
        for field, convert in EDITABLE_FIELDS.items():
            value = _plain(row[field], convert)
            if value != task[field]:
                changes[field] = value
        if changes:
            edits[task["id"]] = changes
    return {"edits": edits}
