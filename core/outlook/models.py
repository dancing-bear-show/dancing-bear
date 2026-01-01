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
class ListEventsRequest:
    """Parameters for listing events in a date range.

    Uses lower default page size (50) for targeted queries with filters.
    For bulk operations without filters, consider ListCalendarViewRequest.
    """

    start_iso: str  # ISO datetime for range start
    end_iso: str  # ISO datetime for range end
    calendar_id: Optional[str] = None
    calendar_name: Optional[str] = None
    subject_filter: Optional[str] = None  # Optional subject substring filter
    top: int = 50  # Page size for targeted queries


@dataclass
class UpdateEventReminderRequest:
    """Parameters for updating event reminder settings."""

    event_id: str
    is_on: bool
    calendar_id: Optional[str] = None
    calendar_name: Optional[str] = None
    minutes_before_start: Optional[int] = None


@dataclass
class ListCalendarViewRequest:
    """Parameters for listing calendar view (low-level pagination).

    Uses higher default page size (200) for bulk operations like deduplication
    that need to process all event occurrences without filters.
    """

    start_iso: str  # ISO datetime for range start
    end_iso: str  # ISO datetime for range end
    calendar_id: Optional[str] = None
    select: str = "subject,start,end,seriesMasterId,type,createdDateTime,location"
    top: int = 200  # Larger page size for bulk operations


@dataclass
class SearchParams:
    """Parameters for inbox search."""

    query: str
    days: Optional[int] = None
    top: int = 25
    pages: int = 2
    use_cache: bool = True
    ttl: int = 300
