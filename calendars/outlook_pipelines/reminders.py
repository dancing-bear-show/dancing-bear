"""Outlook Reminders Pipeline."""

from __future__ import annotations

from ._base import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    dataclass,
    BaseProducer,
    DateWindowResolver,
    RequestConsumer,
    SafeProcessor,
    check_service_required,
    MSG_PREVIEW_COMPLETE,
    LOG_DRY_RUN,
)
from ._context import ReminderUpdateContext

__all__ = [
    "OutlookRemindersRequest",
    "OutlookRemindersRequestConsumer",
    "OutlookRemindersResult",
    "OutlookRemindersProcessor",
    "OutlookRemindersProducer",
]


@dataclass
class OutlookRemindersRequest:
    service: Any
    calendar: Optional[str]
    from_date: Optional[str]
    to_date: Optional[str]
    dry_run: bool
    all_occurrences: bool
    set_off: bool
    minutes: Optional[int] = None


OutlookRemindersRequestConsumer = RequestConsumer[OutlookRemindersRequest]


@dataclass
class OutlookRemindersResult:
    logs: List[str]
    updated: int
    dry_run: bool
    set_off: bool


class OutlookRemindersProcessor(SafeProcessor[OutlookRemindersRequest, OutlookRemindersResult]):
    def __init__(self, today_factory=None) -> None:
        self._window = DateWindowResolver(today_factory)

    def _process_safe(self, payload: OutlookRemindersRequest) -> OutlookRemindersResult:
        check_service_required(payload.service)
        svc = payload.service

        calendar_name = payload.calendar
        cal_id = None
        if calendar_name:
            cal_id = svc.get_calendar_id_by_name(calendar_name)
            if not cal_id:
                raise ValueError(f"Calendar not found: {calendar_name}")

        start_iso, end_iso = self._window.resolve(payload.from_date, payload.to_date)
        from calendars.outlook_service import ListEventsRequest
        events = svc.list_events_in_range(ListEventsRequest(
            start_iso=start_iso,
            end_iso=end_iso,
            calendar_id=cal_id,
        ))

        series_ids: set[str] = set()
        occurrence_ids: set[str] = set()
        single_ids: set[str] = set()
        for ev in events or []:
            et = (ev.get("type") or "").lower()
            eid = ev.get("id")
            sid = ev.get("seriesMasterId")
            if et == "seriesmaster" and eid:
                series_ids.add(eid)
            elif et == "occurrence":
                if payload.all_occurrences and eid:
                    occurrence_ids.add(eid)
                if sid:
                    series_ids.add(sid)
            else:
                if eid:
                    single_ids.add(eid)

        logs: List[str] = []
        updated = 0

        ctx = ReminderUpdateContext(ids=sorted(series_ids), label="series master", cal_id=cal_id, logs=logs)
        updated += self._update_ids(ctx, svc, payload)

        if payload.all_occurrences:
            ctx = ReminderUpdateContext(ids=sorted(occurrence_ids), label="occurrence", cal_id=cal_id, logs=logs)
            updated += self._update_ids(ctx, svc, payload)

        ctx = ReminderUpdateContext(ids=sorted(single_ids), label="single", cal_id=cal_id, logs=logs)
        updated += self._update_ids(ctx, svc, payload)

        result = OutlookRemindersResult(logs=logs, updated=updated, dry_run=payload.dry_run, set_off=payload.set_off)
        return result

    def _update_ids(
        self,
        ctx: ReminderUpdateContext,
        svc,
        payload: OutlookRemindersRequest,
    ) -> int:
        if not ctx.ids:
            return 0
        updated = 0
        for eid in ctx.ids:
            if payload.dry_run:
                if payload.set_off:
                    ctx.logs.append(f"{LOG_DRY_RUN} would disable reminder for {ctx.label} {eid}")
                else:
                    ctx.logs.append(
                        f"{LOG_DRY_RUN} would set reminderMinutesBeforeStart={payload.minutes} for {ctx.label} {eid}"
                    )
                continue
            try:
                if payload.set_off:
                    from calendars.outlook_service import UpdateEventReminderRequest
                    svc.update_event_reminder(UpdateEventReminderRequest(
                        event_id=eid,
                        calendar_id=ctx.cal_id,
                        calendar_name=payload.calendar,
                        is_on=False,
                    ))
                else:
                    from calendars.outlook_service import UpdateEventReminderRequest
                    svc.update_event_reminder(UpdateEventReminderRequest(
                        event_id=eid,
                        calendar_id=ctx.cal_id,
                        calendar_name=payload.calendar,
                        is_on=True,
                        minutes_before_start=payload.minutes,
                    ))
                updated += 1
            except Exception as exc:
                ctx.logs.append(f"Failed to update {ctx.label} {eid}: {exc}")
        return updated


class OutlookRemindersProducer(BaseProducer):
    def _produce_success(self, payload: OutlookRemindersResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        self.print_logs(payload.logs)
        if payload.dry_run:
            print(MSG_PREVIEW_COMPLETE)
        else:
            if payload.set_off:
                print(f"Disabled reminders on {payload.updated} item(s).")
            else:
                print(f"Updated reminders on {payload.updated} item(s).")
