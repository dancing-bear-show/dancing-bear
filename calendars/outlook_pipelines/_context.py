"""Context dataclasses for Outlook pipeline helper methods."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class EventProcessingContext:
    """Context for processing a single calendar event in add pipeline."""

    idx: int
    nev: Dict[str, Any]
    subj: str
    no_rem: bool
    rem_minutes: Optional[int]
    logs: List[str]


@dataclass
class DedupSelectionContext:
    """Context for selecting which duplicate series to keep/delete."""

    sorted_sids: List[str]
    std: List[str]
    non: List[str]
    newest: str
    oldest: str


@dataclass
class ReminderUpdateContext:
    """Context for updating reminders on a batch of events."""

    ids: Sequence[str]
    label: str
    cal_id: Optional[str]
    logs: List[str]


@dataclass
class EventMatchingCriteria:
    """Criteria for matching calendar events in remove pipeline."""

    single_start: str
    single_end: str
    subject_only: bool
    want_days: set[str]
    start_time: str
    end_time: str


@dataclass
class ScheduleImportContext:
    """Context for schedule import operations."""

    svc: Any
    cal_id: str
    cal_name: str
    logs: List[str]


__all__ = [
    "EventProcessingContext",
    "DedupSelectionContext",
    "ReminderUpdateContext",
    "EventMatchingCriteria",
    "ScheduleImportContext",
]
