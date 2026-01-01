"""Outlook Schedule Import Pipeline.

Provides pipeline components for importing schedules into Outlook calendars.
"""

from __future__ import annotations

from ._base import (
    Any,
    BaseProducer,
    DEFAULT_IMPORT_CALENDAR,
    Dict,
    List,
    LOG_DRY_RUN,
    MSG_PREVIEW_COMPLETE,
    Optional,
    RequestConsumer,
    SafeProcessor,
    check_service_required,
    dataclass,
)
from ._context import ScheduleImportContext
from ..outlook_service import EventCreationParams, RecurringEventCreationParams


@dataclass
class OutlookScheduleImportRequest:
    source: str
    kind: Optional[str]
    calendar: Optional[str]
    tz: Optional[str]
    until: Optional[str]
    dry_run: bool
    no_reminder: bool
    service: Any


OutlookScheduleImportRequestConsumer = RequestConsumer[OutlookScheduleImportRequest]


@dataclass
class OutlookScheduleImportResult:
    logs: List[str]
    created: int
    dry_run: bool
    calendar: str


class OutlookScheduleImportProcessor(SafeProcessor[OutlookScheduleImportRequest, OutlookScheduleImportResult]):
    def __init__(self, schedule_loader=None) -> None:
        self._schedule_loader = schedule_loader

    def _process_safe(self, payload: OutlookScheduleImportRequest) -> OutlookScheduleImportResult:
        check_service_required(payload.service)
        svc = payload.service
        cal_name = payload.calendar or DEFAULT_IMPORT_CALENDAR

        cal_id = self._ensure_calendar(svc, cal_name)
        items = self._load_items(payload)

        if not items:
            return OutlookScheduleImportResult(logs=["No schedule items parsed."], created=0, dry_run=payload.dry_run, calendar=cal_name)

        logs: List[str] = []
        ctx = ScheduleImportContext(svc=svc, cal_id=cal_id, cal_name=cal_name, logs=logs)
        created = 0
        for item in items:
            result = self._process_item(item, ctx, payload)
            created += result
        return OutlookScheduleImportResult(logs=logs, created=created, dry_run=payload.dry_run, calendar=cal_name)

    def _ensure_calendar(self, svc, cal_name: str) -> str:
        """Ensure calendar exists and return its ID."""
        cal_id = svc.ensure_calendar_exists(cal_name)
        return cal_id

    def _load_items(self, payload: OutlookScheduleImportRequest) -> List:
        """Load schedule items from source."""
        loader = self._schedule_loader
        if loader is None:
            from calendars.importer import load_schedule as default_loader
            loader = default_loader
        return loader(payload.source, kind=payload.kind)

    def _process_item(self, item, ctx: ScheduleImportContext, payload: OutlookScheduleImportRequest) -> int:
        # One-off event
        if item.start_iso and item.end_iso:
            return self._create_one_off(item, ctx, payload)

        # Recurring event
        rec = item.recurrence or ("weekly" if item.byday else None)
        if rec in ("weekly", "daily", "monthly") and item.start_time and item.end_time and item.range_start:
            return self._create_recurring(item, ctx, payload, rec)

        ctx.logs.append(f"Skip non-recurring or incomplete row: {item.subject}")
        return 0

    def _create_one_off(self, item, ctx: ScheduleImportContext, payload: OutlookScheduleImportRequest) -> int:
        if payload.dry_run:
            ctx.logs.append(f"{LOG_DRY_RUN} would create one-off '{item.subject}' {item.start_iso}->{item.end_iso} cal='{ctx.cal_name}'")
            return 1
        try:
            params = EventCreationParams(
                subject=item.subject,
                start_iso=item.start_iso,
                end_iso=item.end_iso,
                calendar_id=ctx.cal_id,
                calendar_name=None,
                tz=payload.tz,
                body_html=item.notes,
                all_day=False,
                location=item.location,
                no_reminder=payload.no_reminder,
            )
            ctx.svc.create_event(params)
            ctx.logs.append(f"Created one-off '{item.subject}'")
            return 1
        except Exception as exc:
            ctx.logs.append(f"Failed to create one-off '{item.subject}': {exc}")
            return 0

    def _create_recurring(self, item, ctx: ScheduleImportContext, payload: OutlookScheduleImportRequest, rec: str) -> int:
        range_until = payload.until or item.range_until
        if payload.dry_run:
            extra = f" {','.join(item.byday or [])}" if item.byday else ""
            ctx.logs.append(f"{LOG_DRY_RUN} would create {rec} '{item.subject}'{extra} {item.start_time}-{item.end_time} start={item.range_start} cal='{ctx.cal_name}'")
            return 1
        try:
            params = RecurringEventCreationParams(
                subject=item.subject,
                start_time=item.start_time,
                end_time=item.end_time,
                repeat=rec,
                calendar_id=ctx.cal_id,
                calendar_name=None,
                tz=payload.tz,
                interval=1,
                byday=item.byday,
                range_start_date=item.range_start,
                range_until=range_until,
                count=item.count,
                body_html=item.notes,
                location=item.location,
                no_reminder=payload.no_reminder,
            )
            ctx.svc.create_recurring_event(params)
            ctx.logs.append(f"Created recurring '{item.subject}'")
            return 1
        except Exception as exc:
            ctx.logs.append(f"Failed to create recurring '{item.subject}': {exc}")
            return 0


class OutlookScheduleImportProducer(BaseProducer):
    def _produce_success(self, payload: OutlookScheduleImportResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        self.print_logs(payload.logs)
        if payload.dry_run:
            print(MSG_PREVIEW_COMPLETE)
        else:
            print(f"Created {payload.created} event series in '{payload.calendar}'.")


__all__ = [
    "OutlookScheduleImportRequest",
    "OutlookScheduleImportRequestConsumer",
    "OutlookScheduleImportResult",
    "OutlookScheduleImportProcessor",
    "OutlookScheduleImportProducer",
]
