"""Data models for Outlook calendar and mail operations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class CalendarRef:
    """Calendar identifier - either by ID or name."""

    calendar_id: Optional[str] = None
    calendar_name: Optional[str] = None


@dataclass
class DateRange:
    """ISO date/datetime range."""

    start_iso: str
    end_iso: str


@dataclass
class ReminderSettings:
    """Reminder configuration for events."""

    no_reminder: bool = False
    reminder_minutes: Optional[int] = None


@dataclass
class EventCreationParams:
    """Parameters for creating a one-time Outlook event."""

    subject: str
    start_iso: str
    end_iso: str
    calendar_id: Optional[str] = None
    calendar_name: Optional[str] = None
    tz: Optional[str] = None
    body_html: Optional[str] = None
    all_day: bool = False
    location: Optional[str] = None
    no_reminder: bool = False
    reminder_minutes: Optional[int] = None


@dataclass
class RecurrencePattern:
    """Recurrence pattern specification."""

    repeat: str  # daily|weekly|monthly
    interval: int = 1
    byday: Optional[List[str]] = None  # For weekly: ["MO", "WE", "FR"]


@dataclass
class RecurrenceRange:
    """Recurrence date range."""

    range_start_date: str
    range_until: Optional[str] = None
    count: Optional[int] = None


@dataclass
class RecurringEventCreationParams:
    """Parameters for creating a recurring Outlook event."""

    subject: str
    start_time: str
    end_time: str
    repeat: str
    calendar_id: Optional[str] = None
    calendar_name: Optional[str] = None
    tz: Optional[str] = None
    interval: int = 1
    byday: Optional[List[str]] = None
    range_start_date: Optional[str] = None
    range_until: Optional[str] = None
    count: Optional[int] = None
    body_html: Optional[str] = None
    location: Optional[str] = None
    exdates: Optional[List[str]] = None
    no_reminder: bool = False
    reminder_minutes: Optional[int] = None


@dataclass
class EventSettingsPatch:
    """Settings to patch on an existing event."""

    event_id: str
    calendar_id: Optional[str] = None
    calendar_name: Optional[str] = None
    categories: Optional[List[str]] = None
    show_as: Optional[str] = None
    sensitivity: Optional[str] = None
    is_reminder_on: Optional[bool] = None
    reminder_minutes: Optional[int] = None


@dataclass
class SearchParams:
    """Parameters for inbox search."""

    query: str
    days: Optional[int] = None
    top: int = 25
    pages: int = 2
    use_cache: bool = True
    ttl: int = 300
