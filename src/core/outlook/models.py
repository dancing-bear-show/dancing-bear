"""Data models for Outlook calendar and mail operations."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CalendarRef:
    """Calendar identifier - either by ID or name."""

    calendar_id: str | None = None
    calendar_name: str | None = None


@dataclass
class DateRange:
    """ISO date/datetime range."""

    start_iso: str
    end_iso: str


@dataclass
class ReminderSettings:
    """Reminder configuration for events."""

    no_reminder: bool = False
    reminder_minutes: int | None = None


@dataclass
class EventCreationParams:
    """Parameters for creating a one-time Outlook event.

    Supports both new (calendar_ref, reminder) and legacy (calendar_id, calendar_name, no_reminder, reminder_minutes) initialization.
    """

    subject: str
    start_iso: str
    end_iso: str
    calendar_ref: CalendarRef | None = None
    tz: str | None = None
    body_html: str | None = None
    all_day: bool = False
    location: str | None = None
    reminder: ReminderSettings | None = None

    # Legacy field support for backwards compatibility
    calendar_id: str | None = None
    calendar_name: str | None = None
    no_reminder: bool = False
    reminder_minutes: int | None = None

    def __post_init__(self):
        """Handle legacy field initialization."""
        # Convert legacy calendar fields to new structure if needed
        if self.calendar_ref is None and (self.calendar_id or self.calendar_name):
            self.calendar_ref = CalendarRef(calendar_id=self.calendar_id, calendar_name=self.calendar_name)

        # Convert legacy reminder fields to new structure if needed
        if self.reminder is None and (self.no_reminder or self.reminder_minutes):
            self.reminder = ReminderSettings(no_reminder=self.no_reminder, reminder_minutes=self.reminder_minutes)


@dataclass
class RecurrencePattern:
    """Recurrence pattern specification."""

    repeat: str  # daily|weekly|monthly
    interval: int = 1
    byday: list[str] | None = None  # For weekly: ["MO", "WE", "FR"]


@dataclass
class RecurrenceRange:
    """Recurrence date range."""

    range_start_date: str
    range_until: str | None = None
    count: int | None = None


@dataclass
class RecurringEventCreationParams:
    """Parameters for creating a recurring Outlook event.

    Supports both new (calendar_ref, reminder) and legacy (calendar_id, calendar_name, no_reminder, reminder_minutes) initialization.
    """

    subject: str
    start_time: str
    end_time: str
    repeat: str
    calendar_ref: CalendarRef | None = None
    tz: str | None = None
    interval: int = 1
    byday: list[str] | None = None
    range_start_date: str | None = None
    range_until: str | None = None
    count: int | None = None
    body_html: str | None = None
    location: str | None = None
    exdates: list[str] | None = None
    reminder: ReminderSettings | None = None

    # Legacy field support for backwards compatibility
    calendar_id: str | None = None
    calendar_name: str | None = None
    no_reminder: bool = False
    reminder_minutes: int | None = None

    def __post_init__(self):
        """Handle legacy field initialization."""
        # Convert legacy calendar fields to new structure if needed
        if self.calendar_ref is None and (self.calendar_id or self.calendar_name):
            self.calendar_ref = CalendarRef(calendar_id=self.calendar_id, calendar_name=self.calendar_name)

        # Convert legacy reminder fields to new structure if needed
        if self.reminder is None and (self.no_reminder or self.reminder_minutes):
            self.reminder = ReminderSettings(no_reminder=self.no_reminder, reminder_minutes=self.reminder_minutes)


@dataclass
class EventSettingsPatch:
    """Settings to patch on an existing event.

    Supports both new (calendar_ref) and legacy (calendar_id, calendar_name) initialization.
    """

    event_id: str
    calendar_ref: CalendarRef | None = None
    categories: list[str] | None = None
    show_as: str | None = None
    sensitivity: str | None = None
    is_reminder_on: bool | None = None
    reminder_minutes: int | None = None

    # Legacy field support for backwards compatibility
    calendar_id: str | None = None
    calendar_name: str | None = None

    def __post_init__(self):
        """Handle legacy field initialization."""
        # Convert legacy calendar fields to new structure if needed
        if self.calendar_ref is None and (self.calendar_id or self.calendar_name):
            self.calendar_ref = CalendarRef(calendar_id=self.calendar_id, calendar_name=self.calendar_name)


@dataclass
class ListEventsRequest:
    """Parameters for listing events in a date range.

    Uses lower default page size (50) for targeted queries with filters.
    For bulk operations without filters, consider ListCalendarViewRequest.

    Supports both new (date_range, calendar_ref) and legacy (start_iso, end_iso, calendar_id, calendar_name) initialization.
    """

    date_range: DateRange | None = None
    calendar_ref: CalendarRef | None = None
    subject_filter: str | None = None  # Optional subject substring filter
    top: int = 50  # Page size for targeted queries

    # Legacy field support for backwards compatibility
    start_iso: str | None = None
    end_iso: str | None = None
    calendar_id: str | None = None
    calendar_name: str | None = None

    def __post_init__(self):
        """Handle legacy field initialization."""
        # Convert legacy fields to new structure if needed
        if self.date_range is None and self.start_iso and self.end_iso:
            self.date_range = DateRange(start_iso=self.start_iso, end_iso=self.end_iso)

        if self.calendar_ref is None and (self.calendar_id or self.calendar_name):
            self.calendar_ref = CalendarRef(calendar_id=self.calendar_id, calendar_name=self.calendar_name)


@dataclass
class UpdateEventReminderRequest:
    """Parameters for updating event reminder settings.

    Supports both new (calendar_ref) and legacy (calendar_id, calendar_name) initialization.
    """

    event_id: str
    is_on: bool
    calendar_ref: CalendarRef | None = None
    minutes_before_start: int | None = None

    # Legacy field support for backwards compatibility
    calendar_id: str | None = None
    calendar_name: str | None = None

    def __post_init__(self):
        """Handle legacy field initialization."""
        # Convert legacy calendar fields to new structure if needed
        if self.calendar_ref is None and (self.calendar_id or self.calendar_name):
            self.calendar_ref = CalendarRef(calendar_id=self.calendar_id, calendar_name=self.calendar_name)


@dataclass
class ListCalendarViewRequest:
    """Parameters for listing calendar view (low-level pagination).

    Uses higher default page size (200) for bulk operations like deduplication
    that need to process all event occurrences without filters.

    Supports both new (date_range, calendar_ref) and legacy (start_iso, end_iso, calendar_id) initialization.
    """

    date_range: DateRange | None = None
    calendar_ref: CalendarRef | None = None
    select: str = "subject,start,end,seriesMasterId,type,createdDateTime,location"
    top: int = 200  # Larger page size for bulk operations

    # Legacy field support for backwards compatibility
    start_iso: str | None = None
    end_iso: str | None = None
    calendar_id: str | None = None

    def __post_init__(self):
        """Handle legacy field initialization."""
        # Convert legacy fields to new structure if needed
        if self.date_range is None and self.start_iso and self.end_iso:
            self.date_range = DateRange(start_iso=self.start_iso, end_iso=self.end_iso)

        if self.calendar_ref is None and self.calendar_id:
            self.calendar_ref = CalendarRef(calendar_id=self.calendar_id)


@dataclass
class SearchParams:
    """Parameters for inbox search."""

    search_query: str
    days: int | None = None
    top: int = 25
    pages: int = 2
    use_cache: bool = True
    ttl: int = 300


@dataclass
class MessageSearchQuery:
    """Parameters for search_messages (KQL-based mail search).

    Groups query terms (query, sender) with pagination (top, pages)
    and filtering (after, only_inbox).
    """

    query: str
    top: int = 50
    pages: int = 3
    after: str | None = None
    sender: str | None = None
    only_inbox: bool = False


@dataclass
class UpdateEventLocationRequest:
    """Parameters for updating an event's location."""

    event_id: str
    location_str: str
    calendar_id: str | None = None
    calendar_name: str | None = None


@dataclass
class UpdateEventSubjectRequest:
    """Parameters for updating an event's subject/title."""

    event_id: str
    subject: str
    calendar_id: str | None = None
    calendar_name: str | None = None
