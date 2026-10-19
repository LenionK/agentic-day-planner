from datetime import date

import pytest

from planner.dates import long_italian_date


@pytest.mark.parametrize(
    ("day", "text"),
    [
        (date(2026, 10, 23), "venerdì 23 ottobre 2026"),
        (date(2026, 10, 19), "lunedì 19 ottobre 2026"),
        (date(2027, 1, 3), "domenica 3 gennaio 2027"),  # cambio d'anno
        (date(2028, 2, 29), "martedì 29 febbraio 2028"),  # anno bisestile
    ],
)
def test_long_italian_date(day, text):
    assert long_italian_date(day) == text
