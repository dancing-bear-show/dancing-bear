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

        if nev.get("repeat"):
            return self._create_recurring(idx, nev, subj, no_rem, rem_minutes, payload, logs)
        return self._create_single(idx, nev, subj, no_rem, rem_minutes, payload, logs)

    def _resolve_reminder(self, nev: Dict[str, Any], payload: OutlookAddRequest) -> Tuple[bool, Optional[int]]:
        yaml_is_off = (nev.get("is_reminder_on") is False)
        rem_minutes = nev.get("reminder_minutes")
        no_rem = payload.force_no_reminder or yaml_is_off
        if rem_minutes is not None:
            no_rem = False
        return no_rem, rem_minutes

    def _create_recurring(self, idx: int, nev: Dict[str, Any], subj: str, no_rem: bool, rem_minutes, payload: OutlookAddRequest, logs: List[str]) -> int:
        cal_name = nev.get("calendar")
        if payload.dry_run:
            logs.append(
                f"{LOG_DRY_RUN}[{idx}] would create recurring: subj='{subj}', cal='{cal_name or '<primary>'}', "
                f"byday={nev.get('byday')}, time={nev.get('start_time')}-{nev.get('end_time')}, range={nev.get('range')}"
            )
            return 1
        try:
            evt = payload.service.create_recurring_event(
                calendar_id=None, calendar_name=cal_name, subject=subj,
                start_time=nev.get("start_time"), end_time=nev.get("end_time"), tz=nev.get("tz"),
                repeat=nev.get("repeat"), interval=int(nev.get("interval", 1) or 1), byday=nev.get("byday"),
                range_start_date=(nev.get("range") or {}).get("start_date"),
                range_until=(nev.get("range") or {}).get("until"), count=nev.get("count"),
                body_html=nev.get("body_html"), location=nev.get("location"),
                exdates=nev.get("exdates") or [], no_reminder=no_rem, reminder_minutes=rem_minutes,
            )
            logs.append(f"[{idx}] Created series: {evt.get('id')} {subj}")
            return 1
        except Exception as exc:
            logs.append(f"[{idx}] Failed to create series '{subj}': {exc}")
            return 0

    def _create_single(self, idx: int, nev: Dict[str, Any], subj: str, no_rem: bool, rem_minutes, payload: OutlookAddRequest, logs: List[str]) -> int:
        cal_name = nev.get("calendar")
        start_iso = nev.get("start")
        end_iso = nev.get("end")
        if not (start_iso and end_iso):
            logs.append(f"[{idx}] Skipping one-time event '{subj}': missing start/end")
            return 0
        if payload.dry_run:
            logs.append(
                f"{LOG_DRY_RUN}[{idx}] would create single: subj='{subj}', cal='{cal_name or '<primary>'}', "
                f"start={start_iso}, end={end_iso}"
            )
            return 1
        try:
            evt = payload.service.create_event(
                calendar_id=None, calendar_name=cal_name, subject=subj,
                start_iso=to_iso_str(start_iso), end_iso=to_iso_str(end_iso), tz=nev.get("tz"),
                body_html=nev.get("body_html"), all_day=bool(nev.get("all_day") or nev.get("allDay")),
                location=nev.get("location"), no_reminder=no_rem, reminder_minutes=rem_minutes,
            )
            logs.append(f"[{idx}] Created event: {evt.get('id')} {subj}")
            return 1
        except Exception as exc:
            logs.append(f"[{idx}] Failed to create event '{subj}': {exc}")
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
