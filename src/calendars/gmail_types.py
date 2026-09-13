"""Shared calendar data model for Gmail pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field

@dataclass(frozen=True)
class CalendarEvent:
    """Structured representation of a single calendar event.

    The first five fields (id, subject, start, end, calendar) are positional and
    required so that all existing call sites keep working unchanged.

    Optional recurrence fields mirror the canonical key names and semantics of
    ``normalize_event`` in ``calendars.model``:
    - byday: uppercase 2-char RRULE day codes (e.g. ["MO", "WE"])
    - interval: None / omitted when == 1; only set when > 1
    - range: {"start_date": "YYYY-MM-DD", "until": "YYYY-MM-DD"} or None
    - exdates / count: exclusion dates and occurrence count for bounded series
    """
    id: str
    subject: str
    start: str
    end: str
    calendar: str
    # Optional recurrence / metadata fields — all default to None / []
    tz: str | None = None
    location: str | None = None
    repeat: str | None = None
    interval: int | None = None
    byday: list[str] = field(default_factory=list)
    range: dict[str, str] | None = None
    start_time: str | None = None
    end_time: str | None = None
    exdates: list[str] = field(default_factory=list)
    count: int | None = None

