"""Base parser class for schedule importers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from .model import ScheduleItem
from calendars.gmail_pipelines import CalendarEvent


@runtime_checkable
class CalendarProvider(Protocol):
    """Aspirational protocol for calendar backends. NOT IMPLEMENTED.

    This Protocol has **no production implementors**. Its only conformant
    classes are the FakeGmailBackend/FakeOutlookBackend test stubs in
    tests/calendars_tests/outlook/test_outlook_scan_processor.py, so the
    conformance test certifies only that those stubs match this shape —
    it does not certify that any real backend does.

    The pattern actually in use is the core.pipeline Consumer -> Processor
    -> Producer triad, with the *plan file* (``{"events": [...]}`` YAML) as
    the abstraction seam rather than a provider interface. See
    calendars.outlook_pipelines.export (OutlookExportProcessor /
    OutlookExportProducer) for the producer side and
    calendars.outlook_pipelines.ics_draft (IcsDraftProcessor /
    IcsDraftProducer) for a consumer.

    Do not treat this Protocol as a contract any backend honours.
    """

    def list_events(self, date_range: tuple[str, str]) -> list[CalendarEvent]:
        """Return events within the given ISO date range (start, end)."""
        raise NotImplementedError

    def add_event(self, event: CalendarEvent) -> CalendarEvent:
        """Add a new event and return the persisted result."""
        raise NotImplementedError


class ScheduleParser(ABC):
    """Base class for schedule parsers."""

    @abstractmethod
    def parse(self, source: str) -> list[ScheduleItem]:
        """Parse schedule items from source.

        Args:
            source: Path to file or URL to parse

        Returns:
            List of ScheduleItem objects
        """
        pass

    @staticmethod
    def _get_field(row: dict[str, Any], *keys: str, default: str = '') -> str:
        """Get first non-empty field from row by trying multiple key variants.

        Supports both normalized rows (lowercase keys, e.g. from parse_csv) and
        original/mixed-case rows (e.g. from xlsx). For fully-lowercase dicts,
        uses a fast path with only lowercase lookups.
        """
        # Fast path: if all keys are already lowercase, only try lowercase variant
        lower_only = all(not isinstance(k, str) or k == k.lower() for k in row.keys())

        for k in keys:
            if lower_only:
                val = row.get(k.lower())
            else:
                val = row.get(k) or row.get(k.lower()) or row.get(k.title())
            if val is not None and str(val).strip():
                return str(val).strip()
        return default

    @staticmethod
    def _row_to_schedule_item(row: dict[str, Any]) -> ScheduleItem | None:
        """Convert a row dict to ScheduleItem, returning None if subject is empty."""
        get_field = ScheduleParser._get_field
        subj = get_field(row, 'subject', 'Subject')
        if not subj:
            return None

        byday_raw = get_field(row, 'byday', 'ByDay')
        byday = [s.strip().upper() for s in byday_raw.split(',') if s.strip()] if byday_raw else None

        count_raw = get_field(row, 'count', 'Count')
        count = int(count_raw) if count_raw.isdigit() else None

        return ScheduleItem(
            subject=subj,
            start_iso=get_field(row, 'start', 'Start') or None,
            end_iso=get_field(row, 'end', 'End') or None,
            recurrence=(get_field(row, 'recurrence', 'Recurrence', 'repeat', 'Repeat') or '').lower() or None,
            byday=byday,
            start_time=get_field(row, 'starttime', 'start_time', 'StartTime') or None,
            end_time=get_field(row, 'endtime', 'end_time', 'EndTime') or None,
            range_start=get_field(row, 'startdate', 'start_date', 'StartDate') or None,
            range_until=get_field(row, 'until', 'Until', 'enddate', 'EndDate') or None,
            count=count,
            location=get_field(row, 'location', 'Location', 'address', 'Address') or None,
            notes=get_field(row, 'notes', 'Notes') or None,
        )
