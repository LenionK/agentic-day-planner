"""A saved day as an iCalendar file (.ics), to import into any calendar app."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event

from planner.db.store import SavedDay

PRODID = "-//agentic-day-planner//IT"


def at(day: date, minutes: int, tz: ZoneInfo) -> datetime:
    """Minutes from midnight on `day` as a time in `tz` (570 -> 09:30)."""
    return datetime.combine(day, time(0, 0), tzinfo=tz) + timedelta(minutes=minutes)


def day_to_ics(saved: SavedDay, tz: ZoneInfo, now: datetime | None = None) -> bytes:
    """The scheduled tasks of a saved day as calendar events, in time order.

    The UID comes from the date and the task id, so importing the file again updates the
    events instead of duplicating them. `now` is the creation time (DTSTAMP): fixed in tests.
    """
    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    stamp = now or datetime.now(UTC)
    for item in saved.scheduled:
        event = Event()
        event.add("uid", f"{saved.day_date.isoformat()}-{item.task_id}@agentic-day-planner")
        event.add("dtstamp", stamp)
        event.add("summary", item.title)
        event.add("dtstart", at(saved.day_date, item.start_min, tz))
        event.add("dtend", at(saved.day_date, item.end_min, tz))
        if item.task_id in saved.sources:
            event.add("description", saved.sources[item.task_id])
        calendar.add_component(event)
    calendar.add_missing_timezones()  # il blocco VTIMEZONE che descrive il fuso
    return calendar.to_ical()
