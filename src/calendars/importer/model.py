"""Data model for schedule items."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScheduleItem:
    """Schedule event specification supporting both one-off and recurring events."""

    subject: str

    # One-off support (ISO datetimes)
    start_iso: str | None = None    # YYYY-MM-DDTHH:MM[:SS]
    end_iso: str | None = None

    # Recurring support
    recurrence: str | None = None   # weekly|daily|monthly
    byday: list[str] | None = None  # e.g., ["MO","WE"] for weekly
    start_time: str | None = None   # HH:MM (24h)
    end_time: str | None = None
    range_start: str | None = None  # YYYY-MM-DD
    range_until: str | None = None
    count: int | None = None

    # Location / notes
    location: str | None = None     # Either name, or "Name (street, city, ST POSTAL)"
    notes: str | None = None
