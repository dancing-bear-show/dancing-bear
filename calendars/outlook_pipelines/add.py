"""Outlook Add pipeline for calendar assistant."""

from __future__ import annotations

from ._base import (
    Any,
    dataclass,
    Dict,
    List,
    Optional,
    Path,
    Tuple,
    SafeProcessor,
    normalize_event,
    BaseProducer,
    RequestConsumer,
    load_events_config,
    to_iso_str,
    LOG_DRY_RUN,
)
from ._context import EventProcessingContext
from ..outlook_service import EventCreationParams, RecurringEventCreationParams


@dataclass
class OutlookAddRequest:
    config_path: Path
    dry_run: bool
    force_no_reminder: bool
    service: Any


OutlookAddRequestConsumer = RequestConsumer[OutlookAddRequest]


@dataclass
class OutlookAddResult:
    logs: List[str]
    created: int
    dry_run: bool


class OutlookAddProcessor(SafeProcessor[OutlookAddRequest, OutlookAddResult]):
    def __init__(self, config_loader=None) -> None:
        self._config_loader = config_loader

    def _process_safe(self, payload: OutlookAddRequest) -> OutlookAddResult:
        items = load_events_config(payload.config_path, self._config_loader)

        logs: List[str] = []
        created = 0
        for idx, ev in enumerate(items, start=1):
            if not isinstance(ev, dict):
                continue
            result = self._process_event(idx, ev, payload, logs)
            created += result

        return OutlookAddResult(logs=logs, created=created, dry_run=payload.dry_run)

    def _process_event(self, idx: int, ev: Dict[str, Any], payload: OutlookAddRequest, logs: List[str]) -> int:
        nev = normalize_event(ev)
        subj = (nev.get("subject") or "").strip()
        if not subj:
            logs.append(f"[{idx}] Skipping event: missing subject")
            return 0

        no_rem, rem_minutes = self._resolve_reminder(nev, payload)
        ctx = EventProcessingContext(
            idx=idx, nev=nev, subj=subj, no_rem=no_rem, rem_minutes=rem_minutes, logs=logs
        )

        if nev.get("repeat"):
            return self._create_recurring(ctx, payload)
        return self._create_single(ctx, payload)

    def _resolve_reminder(self, nev: Dict[str, Any], payload: OutlookAddRequest) -> Tuple[bool, Optional[int]]:
        yaml_is_off = (nev.get("is_reminder_on") is False)
        rem_minutes = nev.get("reminder_minutes")
        no_rem = payload.force_no_reminder or yaml_is_off
        if rem_minutes is not None:
            no_rem = False
        return no_rem, rem_minutes

    def _create_recurring(self, ctx: EventProcessingContext, payload: OutlookAddRequest) -> int:
        cal_name = ctx.nev.get("calendar")
        if payload.dry_run:
            ctx.logs.append(
                f"{LOG_DRY_RUN}[{ctx.idx}] would create recurring: subj='{ctx.subj}', cal='{cal_name or '<primary>'}', "
                f"byday={ctx.nev.get('byday')}, time={ctx.nev.get('start_time')}-{ctx.nev.get('end_time')}, range={ctx.nev.get('range')}"
            )
            return 1
        try:
            params = RecurringEventCreationParams(
                subject=ctx.subj,
                start_time=ctx.nev.get("start_time"),
                end_time=ctx.nev.get("end_time"),
                repeat=ctx.nev.get("repeat"),
                calendar_id=None,
                calendar_name=cal_name,
                tz=ctx.nev.get("tz"),
                interval=int(ctx.nev.get("interval", 1) or 1),
                byday=ctx.nev.get("byday"),
                range_start_date=(ctx.nev.get("range") or {}).get("start_date"),
                range_until=(ctx.nev.get("range") or {}).get("until"),
                count=ctx.nev.get("count"),
                body_html=ctx.nev.get("body_html"),
                location=ctx.nev.get("location"),
                exdates=ctx.nev.get("exdates") or [],
                no_reminder=ctx.no_rem,
                reminder_minutes=ctx.rem_minutes,
            )
            evt = payload.service.create_recurring_event(params)
            ctx.logs.append(f"[{ctx.idx}] Created series: {evt.get('id')} {ctx.subj}")
            return 1
        except Exception as exc:
            ctx.logs.append(f"[{ctx.idx}] Failed to create series '{ctx.subj}': {exc}")
            return 0

    def _create_single(self, ctx: EventProcessingContext, payload: OutlookAddRequest) -> int:
        cal_name = ctx.nev.get("calendar")
        start_iso = ctx.nev.get("start")
        end_iso = ctx.nev.get("end")
        if not (start_iso and end_iso):
            ctx.logs.append(f"[{ctx.idx}] Skipping one-time event '{ctx.subj}': missing start/end")
            return 0
        if payload.dry_run:
            ctx.logs.append(
                f"{LOG_DRY_RUN}[{ctx.idx}] would create single: subj='{ctx.subj}', cal='{cal_name or '<primary>'}', "
                f"start={start_iso}, end={end_iso}"
            )
            return 1
        try:
            params = EventCreationParams(
                subject=ctx.subj,
                start_iso=to_iso_str(start_iso),
                end_iso=to_iso_str(end_iso),
                calendar_id=None,
                calendar_name=cal_name,
                tz=ctx.nev.get("tz"),
                body_html=ctx.nev.get("body_html"),
                all_day=bool(ctx.nev.get("all_day") or ctx.nev.get("allDay")),
                location=ctx.nev.get("location"),
                no_reminder=ctx.no_rem,
                reminder_minutes=ctx.rem_minutes,
            )
            evt = payload.service.create_event(params)
            ctx.logs.append(f"[{ctx.idx}] Created event: {evt.get('id')} {ctx.subj}")
            return 1
        except Exception as exc:
            ctx.logs.append(f"[{ctx.idx}] Failed to create event '{ctx.subj}': {exc}")
            return 0


class OutlookAddProducer(BaseProducer):
    def _produce_success(self, payload: OutlookAddResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        self.print_logs(payload.logs)
        suffix = " (dry-run)" if payload.dry_run else ""
        print(f"Planned {payload.created} events/series from config{suffix}")


__all__ = [
    "OutlookAddRequest",
    "OutlookAddRequestConsumer",
    "OutlookAddResult",
    "OutlookAddProcessor",
    "OutlookAddProducer",
]
