"""Outlook Schedule Import Pipeline.

Provides pipeline components for importing schedules into Outlook calendars.
"""

from __future__ import annotations

from ._base import (
    dataclass,
    Any,
    Dict,
    List,
    Optional,
    Processor,
    ResultEnvelope,
    BaseProducer,
    RequestConsumer,
    check_service_required,
    MSG_PREVIEW_COMPLETE,
)


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


class OutlookScheduleImportProcessor(
    Processor[OutlookScheduleImportRequest, ResultEnvelope[OutlookScheduleImportResult]]
):
    def __init__(self, schedule_loader=None) -> None:
        self._schedule_loader = schedule_loader

    def process(self, payload: OutlookScheduleImportRequest) -> ResultEnvelope[OutlookScheduleImportResult]:
        if err := check_service_required(payload.service):
            return err
        svc = payload.service
        cal_name = payload.calendar or "Imported Schedules"

        cal_id, err = self._ensure_calendar(svc, cal_name)
        if err:
            return err

        items, err = self._load_items(payload)
        if err:
            return err
        if not items:
            return ResultEnvelope(
                status="success",
                payload=OutlookScheduleImportResult(logs=["No schedule items parsed."], created=0, dry_run=payload.dry_run, calendar=cal_name),
            )

        logs: List[str] = []
        created = 0
        for item in items:
            result = self._process_item(item, svc, cal_id, cal_name, payload, logs)
            created += result
        return ResultEnvelope(
            status="success",
            payload=OutlookScheduleImportResult(logs=logs, created=created, dry_run=payload.dry_run, calendar=cal_name),
        )

    def _ensure_calendar(self, svc, cal_name: str):
        try:
            cal_id = svc.ensure_calendar_exists(cal_name)
            return cal_id, None
        except Exception as exc:
            return None, ResultEnvelope(status="error", diagnostics={"message": f"Failed to ensure calendar '{cal_name}': {exc}", "code": 3})

    def _load_items(self, payload: OutlookScheduleImportRequest):
        loader = self._schedule_loader
        if loader is None:
            from calendars.importer import load_schedule as default_loader
            loader = default_loader
        try:
            return loader(payload.source, kind=payload.kind), None
        except (ValueError, NotImplementedError) as exc:
            return None, ResultEnvelope(status="error", diagnostics={"message": str(exc), "code": 4})
        except Exception as exc:
            return None, ResultEnvelope(status="error", diagnostics={"message": f"Failed to load schedule: {exc}", "code": 4})

    def _process_item(self, item, svc, cal_id: str, cal_name: str, payload: OutlookScheduleImportRequest, logs: List[str]) -> int:
        # One-off event
        if item.start_iso and item.end_iso:
            return self._create_one_off(item, svc, cal_id, cal_name, payload, logs)

        # Recurring event
        rec = item.recurrence or ("weekly" if item.byday else None)
        if rec in ("weekly", "daily", "monthly") and item.start_time and item.end_time and item.range_start:
            return self._create_recurring(item, svc, cal_id, cal_name, payload, logs, rec)

        logs.append(f"Skip non-recurring or incomplete row: {item.subject}")
        return 0

    def _create_one_off(self, item, svc, cal_id: str, cal_name: str, payload: OutlookScheduleImportRequest, logs: List[str]) -> int:
        if payload.dry_run:
            logs.append(f"[dry-run] would create one-off '{item.subject}' {item.start_iso}->{item.end_iso} cal='{cal_name}'")
            return 1
        try:
            svc.create_event(
                calendar_id=cal_id, calendar_name=None, subject=item.subject,
                start_iso=item.start_iso, end_iso=item.end_iso, tz=payload.tz,
                body_html=item.notes, all_day=False, location=item.location,
                no_reminder=payload.no_reminder,
            )
            logs.append(f"Created one-off '{item.subject}'")
            return 1
        except Exception as exc:
            logs.append(f"Failed to create one-off '{item.subject}': {exc}")
            return 0

    def _create_recurring(self, item, svc, cal_id: str, cal_name: str, payload: OutlookScheduleImportRequest, logs: List[str], rec: str) -> int:
        range_until = payload.until or item.range_until
        if payload.dry_run:
            extra = f" {','.join(item.byday or [])}" if item.byday else ""
            logs.append(f"[dry-run] would create {rec} '{item.subject}'{extra} {item.start_time}-{item.end_time} start={item.range_start} cal='{cal_name}'")
            return 1
        try:
            svc.create_recurring_event(
                calendar_id=cal_id, calendar_name=None, subject=item.subject,
                start_time=item.start_time, end_time=item.end_time, tz=payload.tz,
                repeat=rec, interval=1, byday=item.byday, range_start_date=item.range_start,
                range_until=range_until, count=item.count, body_html=item.notes,
                location=item.location, no_reminder=payload.no_reminder,
            )
            logs.append(f"Created recurring '{item.subject}'")
            return 1
        except Exception as exc:
            logs.append(f"Failed to create recurring '{item.subject}': {exc}")
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
