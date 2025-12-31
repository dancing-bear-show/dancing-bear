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
    ERR_CODE_CALENDAR,
    ERR_CODE_API,
    LOG_DRY_RUN,
)

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
        if err := check_service_required(payload.service):
            return err
        svc = payload.service

        calendar_name = payload.calendar
        cal_id = None
        if calendar_name:
            cal_id = svc.get_calendar_id_by_name(calendar_name)
            if not cal_id:
                return ResultEnvelope(
                    status="error",
                    diagnostics={"message": f"Calendar not found: {calendar_name}", "code": ERR_CODE_CALENDAR},
                )

        start_iso, end_iso = self._window.resolve(payload.from_date, payload.to_date)
        try:
            events = svc.list_events_in_range(calendar_id=cal_id, start_iso=start_iso, end_iso=end_iso)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to list events: {exc}", "code": ERR_CODE_API})

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
        updated += self._update_ids(sorted(series_ids), "series master", cal_id, svc, payload, logs)
        if payload.all_occurrences:
            updated += self._update_ids(sorted(occurrence_ids), "occurrence", cal_id, svc, payload, logs)
        updated += self._update_ids(sorted(single_ids), "single", cal_id, svc, payload, logs)

        result = OutlookRemindersResult(logs=logs, updated=updated, dry_run=payload.dry_run, set_off=payload.set_off)
        return result

    def _update_ids(
        self,
        ids: Sequence[str],
        label: str,
        cal_id: Optional[str],
        svc,
        payload: OutlookRemindersRequest,
        logs: List[str],
    ) -> int:
        if not ids:
            return 0
        updated = 0
        for eid in ids:
            if payload.dry_run:
                if payload.set_off:
                    logs.append(f"{LOG_DRY_RUN} would disable reminder for {label} {eid}")
                else:
                    logs.append(
                        f"{LOG_DRY_RUN} would set reminderMinutesBeforeStart={payload.minutes} for {label} {eid}"
                    )
                continue
            try:
                if payload.set_off:
                    svc.update_event_reminder(
                        event_id=eid,
                        calendar_id=cal_id,
                        calendar_name=payload.calendar,
                        is_on=False,
                    )
                else:
                    svc.update_event_reminder(
                        event_id=eid,
                        calendar_id=cal_id,
                        calendar_name=payload.calendar,
                        is_on=True,
                        minutes_before_start=payload.minutes,
                    )
                updated += 1
            except Exception as exc:
                logs.append(f"Failed to update {label} {eid}: {exc}")
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
