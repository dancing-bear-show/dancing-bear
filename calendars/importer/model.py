"""Data model for schedule items."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ScheduleItem:
    """Schedule event specification supporting both one-off and recurring events."""

    subject: str

    # One-off support (ISO datetimes)
    start_iso: Optional[str] = None    # YYYY-MM-DDTHH:MM[:SS]
    end_iso: Optional[str] = None

    # Recurring support
    recurrence: Optional[str] = None   # weekly|daily|monthly
    byday: Optional[List[str]] = None  # e.g., ["MO","WE"] for weekly
    start_time: Optional[str] = None   # HH:MM (24h)
    end_time: Optional[str] = None
    range_start: Optional[str] = None  # YYYY-MM-DD
    range_until: Optional[str] = None
    count: Optional[int] = None

    # Location / notes
    location: Optional[str] = None     # Either name, or "Name (street, city, ST POSTAL)"
    notes: Optional[str] = None
