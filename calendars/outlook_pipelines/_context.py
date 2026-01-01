"""Context dataclasses for Outlook pipeline helper methods."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

if TYPE_CHECKING:
    from calendars.outlook_service import OutlookService


@dataclass
class EventProcessingContext:
    """Context for processing a single calendar event in add pipeline."""

    idx: int  # Event index in config file (1-based for logging)
    nev: Dict[str, Any]  # Normalized event dictionary from config
    subj: str  # Event subject/title (already validated as non-empty)
    no_rem: bool  # True if reminders should be disabled
    rem_minutes: Optional[int]  # Reminder minutes before start (None = use default)
    logs: List[str]  # Accumulated log messages


@dataclass
class DedupSelectionContext:
    """Context for selecting which duplicate series to keep/delete."""

    sorted_sids: List[str]  # Series IDs sorted by creation date (oldest first)
    std: List[str]  # Series with standardized locations (address or parens)
    non: List[str]  # Series without standardized locations
    newest: str  # Most recently created series ID
    oldest: str  # Oldest created series ID


@dataclass
class ReminderUpdateContext:
    """Context for updating reminders on a batch of events."""

    ids: Sequence[str]  # Event/series IDs to update
    label: str  # Event type label for logging (e.g., "series master", "occurrence")
    cal_id: Optional[str]  # Calendar ID (None = primary calendar)
    logs: List[str]  # Accumulated log messages


@dataclass
class EventMatchingCriteria:
    """Criteria for matching calendar events in remove pipeline."""

    single_start: str  # ISO datetime for single event matching
    single_end: str  # ISO datetime for single event matching
    subject_only: bool  # If True, match by subject only (skip time/day checks)
    want_days: set[str]  # Lowercase weekday codes (mo, tu, we, th, fr, sa, su)
    start_time: str  # HH:MM format for recurring events
    end_time: str  # HH:MM format for recurring events


@dataclass
class ScheduleImportContext:
    """Context for schedule import operations.

    Groups service, calendar, and logging state for event creation helpers.
    """

    svc: "OutlookService"  # Outlook service instance for API calls
    cal_id: str  # Target calendar ID (already ensured to exist)
    cal_name: str  # Target calendar name for logging
    logs: List[str]  # Accumulated log messages


__all__ = [
    "EventProcessingContext",
    "DedupSelectionContext",
    "ReminderUpdateContext",
    "EventMatchingCriteria",
    "ScheduleImportContext",
]
