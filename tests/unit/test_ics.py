from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from icalendar import Calendar

from planner.db.store import SavedDay
from planner.export.ics import day_to_ics
from planner.solver.models import DayConfig, ScheduledTask, Task

ROME = ZoneInfo("Europe/Rome")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def saved_day(day_date: date = date(2026, 11, 3), title: str = "Studio") -> SavedDay:
    """Study 9:30-11:00 (with its sentence), dentist 15:00-16:00, gym left out of the plan."""
    return SavedDay(
        id=7,
        day_date=day_date,
        user_input="studio, dentista e se riesco palestra",
        day=DayConfig(),
        tasks=[
            Task(id="t1", title=title, duration_min=90),
            Task(id="t2", title="Dentista", duration_min=60, required=True, fixed_start_min=900),
            Task(id="t3", title="Palestra", duration_min=60, priority=1),
        ],
        sources={"t1": "studio un'ora e mezza", "t3": "se riesco palestra"},
        scheduled=[
            ScheduledTask(task_id="t1", title=title, start_min=570, end_min=660),
            ScheduledTask(task_id="t2", title="Dentista", start_min=900, end_min=960),
        ],
    )


def events(raw: bytes) -> list:
    return Calendar.from_ical(raw).walk("VEVENT")


def test_each_scheduled_task_becomes_an_event_at_its_time_in_rome():
    found = events(day_to_ics(saved_day(), ROME, NOW))

    assert [str(e["SUMMARY"]) for e in found] == ["Studio", "Dentista"]
    assert found[0].decoded("DTSTART") == datetime(2026, 11, 3, 9, 30, tzinfo=ROME)
    assert found[0].decoded("DTEND") == datetime(2026, 11, 3, 11, 0, tzinfo=ROME)
    assert found[1].decoded("DTSTART") == datetime(2026, 11, 3, 15, 0, tzinfo=ROME)
    # a novembre Roma è un'ora avanti rispetto a UTC: l'orario non è "fluttuante"
    assert found[0].decoded("DTSTART").utcoffset() == timedelta(hours=1)


def test_summer_days_use_daylight_saving_time():
    found = events(day_to_ics(saved_day(date(2026, 7, 1)), ROME, NOW))

    assert found[0].decoded("DTSTART").utcoffset() == timedelta(hours=2)


def test_tasks_left_out_of_the_plan_are_not_exported():
    raw = day_to_ics(saved_day(), ROME, NOW)

    assert "Palestra" not in [str(e["SUMMARY"]) for e in events(raw)]
    assert b"palestra" not in raw.lower()  # neanche la sua frase


def test_description_is_the_users_sentence_when_there_is_one():
    study, dentist = events(day_to_ics(saved_day(), ROME, NOW))

    assert str(study["DESCRIPTION"]) == "studio un'ora e mezza"
    assert "DESCRIPTION" not in dentist


def test_uids_are_unique_and_stable_across_exports():
    first = events(day_to_ics(saved_day(), ROME, NOW))
    later = events(day_to_ics(saved_day(), ROME, NOW + timedelta(days=1)))

    uids = [str(e["UID"]) for e in first]
    assert uids == ["2026-11-03-t1@agentic-day-planner", "2026-11-03-t2@agentic-day-planner"]
    assert [str(e["UID"]) for e in later] == uids  # reimportato: aggiorna, non duplica
    assert later[0].decoded("DTSTAMP") == NOW + timedelta(days=1)


def test_the_file_declares_its_timezone():
    calendar = Calendar.from_ical(day_to_ics(saved_day(), ROME, NOW))

    assert [str(tz["TZID"]) for tz in calendar.walk("VTIMEZONE")] == ["Europe/Rome"]
    assert calendar["PRODID"] == "-//agentic-day-planner//IT"
    assert calendar["VERSION"] == "2.0"


def test_commas_and_semicolons_are_escaped_and_read_back():
    title = "Studio, capitolo 2; esercizi"
    raw = day_to_ics(saved_day(title=title), ROME, NOW)

    assert b"SUMMARY:Studio\\, capitolo 2\\; esercizi" in raw
    assert str(events(raw)[0]["SUMMARY"]) == title


def test_lines_end_with_crlf_as_the_standard_requires():
    raw = day_to_ics(saved_day(), ROME, NOW)

    assert raw.startswith(b"BEGIN:VCALENDAR\r\n")
    assert b"\n" not in raw.replace(b"\r\n", b"")


def test_a_day_without_scheduled_tasks_is_an_empty_calendar():
    empty = saved_day().model_copy(update={"scheduled": []})

    assert events(day_to_ics(empty, ROME, NOW)) == []
