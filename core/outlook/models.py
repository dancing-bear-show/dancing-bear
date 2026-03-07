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


class LegacyCalendarRefMixin:
    """Mixin to auto-convert legacy calendar_id/calendar_name to calendar_ref."""

    def _migrate_calendar_ref(self) -> None:
        """Convert legacy fields to calendar_ref if needed."""
        calendar_id = getattr(self, 'calendar_id', None)
        calendar_name = getattr(self, 'calendar_name', None)
        if self.calendar_ref is None and (calendar_id or calendar_name):
            self.calendar_ref = CalendarRef(
                calendar_id=calendar_id,
                calendar_name=calendar_name
            )


class LegacyDateRangeMixin:
    """Mixin to auto-convert legacy start_iso/end_iso to date_range."""

    def _migrate_date_range(self) -> None:
        """Convert legacy fields to date_range if needed."""
        start_iso = getattr(self, 'start_iso', None)
        end_iso = getattr(self, 'end_iso', None)
        if self.date_range is None and (start_iso or end_iso):
            self.date_range = DateRange(
                start_iso=start_iso,
                end_iso=end_iso
            )


@dataclass
class EventCreationParams(LegacyCalendarRefMixin):
    """Parameters for creating a one-time Outlook event.

    Supports both new (calendar_ref, reminder) and legacy (calendar_id, calendar_name, no_reminder, reminder_minutes) initialization.
    """

    subject: str
    start_iso: str
    end_iso: str
    calendar_ref: Optional[CalendarRef] = None
    tz: Optional[str] = None
    body_html: Optional[str] = None
    all_day: bool = False
    location: Optional[str] = None
    reminder: Optional[ReminderSettings] = None

    # Legacy field support for backwards compatibility
    calendar_id: Optional[str] = None
    calendar_name: Optional[str] = None
    no_reminder: bool = False
    reminder_minutes: Optional[int] = None

    def __post_init__(self):
        """Handle legacy field initialization."""
        # Convert legacy calendar fields to new structure if needed
        self._migrate_calendar_ref()

        # Convert legacy reminder fields to new structure if needed
        if self.reminder is None and (self.no_reminder or self.reminder_minutes):
            self.reminder = ReminderSettings(no_reminder=self.no_reminder, reminder_minutes=self.reminder_minutes)


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
class RecurringEventCreationParams(LegacyCalendarRefMixin):
    """Parameters for creating a recurring Outlook event.

    Supports both new (calendar_ref, reminder) and legacy (calendar_id, calendar_name, no_reminder, reminder_minutes) initialization.
    """

    subject: str
    start_time: str
    end_time: str
    repeat: str
    calendar_ref: Optional[CalendarRef] = None
    tz: Optional[str] = None
    interval: int = 1
    byday: Optional[List[str]] = None
    range_start_date: Optional[str] = None
    range_until: Optional[str] = None
    count: Optional[int] = None
    body_html: Optional[str] = None
    location: Optional[str] = None
    exdates: Optional[List[str]] = None
    reminder: Optional[ReminderSettings] = None

    # Legacy field support for backwards compatibility
    calendar_id: Optional[str] = None
    calendar_name: Optional[str] = None
    no_reminder: bool = False
    reminder_minutes: Optional[int] = None

    def __post_init__(self):
        """Handle legacy field initialization."""
        # Convert legacy calendar fields to new structure if needed
        self._migrate_calendar_ref()

        # Convert legacy reminder fields to new structure if needed
        if self.reminder is None and (self.no_reminder or self.reminder_minutes):
            self.reminder = ReminderSettings(no_reminder=self.no_reminder, reminder_minutes=self.reminder_minutes)


@dataclass
class EventSettingsPatch(LegacyCalendarRefMixin):
    """Settings to patch on an existing event.

    Supports both new (calendar_ref) and legacy (calendar_id, calendar_name) initialization.
    """

    event_id: str
    calendar_ref: Optional[CalendarRef] = None
    categories: Optional[List[str]] = None
    show_as: Optional[str] = None
    sensitivity: Optional[str] = None
    is_reminder_on: Optional[bool] = None
    reminder_minutes: Optional[int] = None

    # Legacy field support for backwards compatibility
    calendar_id: Optional[str] = None
    calendar_name: Optional[str] = None

    def __post_init__(self):
        """Handle legacy field initialization."""
        # Convert legacy calendar fields to new structure if needed
        self._migrate_calendar_ref()


@dataclass
class ListEventsRequest(LegacyDateRangeMixin, LegacyCalendarRefMixin):
    """Parameters for listing events in a date range.

    Uses lower default page size (50) for targeted queries with filters.
    For bulk operations without filters, consider ListCalendarViewRequest.

    Supports both new (date_range, calendar_ref) and legacy (start_iso, end_iso, calendar_id, calendar_name) initialization.
    """

    date_range: Optional[DateRange] = None
    calendar_ref: Optional[CalendarRef] = None
    subject_filter: Optional[str] = None  # Optional subject substring filter
    top: int = 50  # Page size for targeted queries

    # Legacy field support for backwards compatibility
    start_iso: Optional[str] = None
    end_iso: Optional[str] = None
    calendar_id: Optional[str] = None
    calendar_name: Optional[str] = None

    def __post_init__(self):
        """Handle legacy field initialization."""
        # Convert legacy fields to new structure if needed
        self._migrate_date_range()
        self._migrate_calendar_ref()


@dataclass
class UpdateEventReminderRequest(LegacyCalendarRefMixin):
    """Parameters for updating event reminder settings.

    Supports both new (calendar_ref) and legacy (calendar_id, calendar_name) initialization.
    """

    event_id: str
    is_on: bool
    calendar_ref: Optional[CalendarRef] = None
    minutes_before_start: Optional[int] = None

    # Legacy field support for backwards compatibility
    calendar_id: Optional[str] = None
    calendar_name: Optional[str] = None

    def __post_init__(self):
        """Handle legacy field initialization."""
        # Convert legacy calendar fields to new structure if needed
        self._migrate_calendar_ref()


@dataclass
class ListCalendarViewRequest(LegacyDateRangeMixin, LegacyCalendarRefMixin):
    """Parameters for listing calendar view (low-level pagination).

    Uses higher default page size (200) for bulk operations like deduplication
    that need to process all event occurrences without filters.

    Supports both new (date_range, calendar_ref) and legacy (start_iso, end_iso, calendar_id) initialization.
    """

    date_range: Optional[DateRange] = None
    calendar_ref: Optional[CalendarRef] = None
    select: str = "subject,start,end,seriesMasterId,type,createdDateTime,location"
    top: int = 200  # Larger page size for bulk operations

    # Legacy field support for backwards compatibility
    start_iso: Optional[str] = None
    end_iso: Optional[str] = None
    calendar_id: Optional[str] = None

    def __post_init__(self):
        """Handle legacy field initialization."""
        # Convert legacy fields to new structure if needed
        self._migrate_date_range()
        self._migrate_calendar_ref()


@dataclass
class SearchParams:
    """Parameters for inbox search."""

    search_query: str
    days: Optional[int] = None
    top: int = 25
    pages: int = 2
    use_cache: bool = True
    ttl: int = 300
