"""Outlook Reminders Pipeline."""

from __future__ import annotations

from ._base import (
    Any,
    dataclass,
    BaseProducer,
    DateWindowResolver,
    RequestConsumer,
    SafeProcessor,
    check_service_required,
    MSG_PREVIEW_COMPLETE,
    LOG_DRY_RUN,
)
from ._context import EventClassification, ReminderUpdateContext

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
    calendar: str | None
    from_date: str | None
    to_date: str | None
    dry_run: bool
    all_occurrences: bool
    set_off: bool
    minutes: int | None = None


OutlookRemindersRequestConsumer = RequestConsumer[OutlookRemindersRequest]


@dataclass
class OutlookRemindersResult:
    logs: list[str]
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

        classified = self._classify_events(events or [], payload.all_occurrences)

        logs: list[str] = []
        updated = 0

        ctx = ReminderUpdateContext(ids=sorted(classified.series_ids), label="series master", cal_id=cal_id, logs=logs)
        updated += self._update_ids(ctx, svc, payload)

        if payload.all_occurrences:
            ctx = ReminderUpdateContext(ids=sorted(classified.occurrence_ids), label="occurrence", cal_id=cal_id, logs=logs)
            updated += self._update_ids(ctx, svc, payload)

        ctx = ReminderUpdateContext(ids=sorted(classified.single_ids), label="single", cal_id=cal_id, logs=logs)
        updated += self._update_ids(ctx, svc, payload)

        result = OutlookRemindersResult(logs=logs, updated=updated, dry_run=payload.dry_run, set_off=payload.set_off)
        return result

    def _classify_one_event(
        self, ev: dict[str, Any], all_occurrences: bool, classification: EventClassification
    ) -> None:
        """Bucket a single event's id(s) into the running classification."""
        et = (ev.get("type") or "").lower()
        eid = ev.get("id")
        sid = ev.get("seriesMasterId")
        if et == "seriesmaster":
            if eid:
                classification.series_ids.add(eid)
            return
        if et == "occurrence":
            if all_occurrences and eid:
                classification.occurrence_ids.add(eid)
            if sid:
                classification.series_ids.add(sid)
            return
        if eid:
            classification.single_ids.add(eid)

    def _classify_events(self, events: list[dict[str, Any]], all_occurrences: bool) -> EventClassification:
        """Classify events into series masters, occurrences, and single events."""
        classification = EventClassification(series_ids=set(), occurrence_ids=set(), single_ids=set())
        for ev in events:
            self._classify_one_event(ev, all_occurrences, classification)
        return classification

    def _build_reminder_request(self, payload: OutlookRemindersRequest, cal_id: str | None, eid: str):
        from calendars.outlook_service import UpdateEventReminderRequest
        if payload.set_off:
            return UpdateEventReminderRequest(
                event_id=eid,
                calendar_id=cal_id,
                calendar_name=payload.calendar,
                is_on=False,
            )
        return UpdateEventReminderRequest(
            event_id=eid,
            calendar_id=cal_id,
            calendar_name=payload.calendar,
            is_on=True,
            minutes_before_start=payload.minutes,
        )

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
                svc.update_event_reminder(self._build_reminder_request(payload, ctx.cal_id, eid))
                updated += 1
            except Exception as exc:
                ctx.logs.append(f"Failed to update {ctx.label} {eid}: {exc}")
        return updated


class OutlookRemindersProducer(BaseProducer):
    def _produce_success(self, payload: OutlookRemindersResult, diagnostics: dict[str, Any] | None) -> None:
        self.print_logs(payload.logs)
        if payload.dry_run:
            print(MSG_PREVIEW_COMPLETE)
        else:
            if payload.set_off:
                print(f"Disabled reminders on {payload.updated} item(s).")
            else:
                print(f"Updated reminders on {payload.updated} item(s).")
