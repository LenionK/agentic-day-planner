"""Dates in Italian, written by hand: strftime("%A") depends on the system language."""

from datetime import date

WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MONTHS = [
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
]


def long_italian_date(day: date) -> str:
    """date(2026, 10, 23) -> 'venerdì 23 ottobre 2026'"""
    return f"{WEEKDAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]} {day.year}"
