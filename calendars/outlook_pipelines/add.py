"""Outlook Add pipeline for calendar assistant."""

from __future__ import annotations

from ._base import (
    Any,
    dataclass,
    Dict,
    List,
    Optional,
    Path,
    Processor,
    ResultEnvelope,
    _load_yaml,
    normalize_event,
    BaseProducer,
    RequestConsumer,
    ERR_CONFIG_MUST_CONTAIN_EVENTS,
    to_iso_str,
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


class OutlookAddProcessor(Processor[OutlookAddRequest, ResultEnvelope[OutlookAddResult]]):
    def __init__(self, config_loader=None) -> None:
        self._config_loader = config_loader if config_loader is not None else _load_yaml

    def process(self, payload: OutlookAddRequest) -> ResultEnvelope[OutlookAddResult]:
        try:
            cfg = self._config_loader(str(payload.config_path))
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to read config: {exc}", "code": 2})
        items = cfg.get("events") if isinstance(cfg, dict) else None
        if not isinstance(items, list):
            return ResultEnvelope(status="error", diagnostics={"message": ERR_CONFIG_MUST_CONTAIN_EVENTS, "code": 2})
        svc = payload.service
        logs: List[str] = []
        created = 0
        for idx, ev in enumerate(items, start=1):
            if not isinstance(ev, dict):
                continue
            nev = normalize_event(ev)
            cal_name = nev.get("calendar")
            subj = (nev.get("subject") or "").strip()
            if not subj:
                logs.append(f"[{idx}] Skipping event: missing subject")
                continue
            yaml_is_off = (nev.get("is_reminder_on") is False)
            rem_minutes = nev.get("reminder_minutes")
            no_rem_effective = payload.force_no_reminder or yaml_is_off
            if rem_minutes is not None:
                no_rem_effective = False
            if nev.get("repeat"):
                if payload.dry_run:
                    logs.append(
                        f"[dry-run][{idx}] would create recurring: subj='{subj}', cal='{cal_name or '<primary>'}', "
                        f"byday={nev.get('byday')}, time={nev.get('start_time')}-{nev.get('end_time')}, range={nev.get('range')}"
                    )
                    created += 1
                    continue
                try:
                    evt = svc.create_recurring_event(
                        calendar_id=None,
                        calendar_name=cal_name,
                        subject=subj,
                        start_time=nev.get("start_time"),
                        end_time=nev.get("end_time"),
                        tz=nev.get("tz"),
                        repeat=nev.get("repeat"),
                        interval=int(nev.get("interval", 1) or 1),
                        byday=nev.get("byday"),
                        range_start_date=(nev.get("range") or {}).get("start_date"),
                        range_until=(nev.get("range") or {}).get("until"),
                        count=nev.get("count"),
                        body_html=nev.get("body_html"),
                        location=nev.get("location"),
                        exdates=nev.get("exdates") or [],
                        no_reminder=no_rem_effective,
                        reminder_minutes=rem_minutes,
                    )
                    created += 1
                    logs.append(f"[{idx}] Created series: {evt.get('id')} {subj}")
                except Exception as exc:
                    logs.append(f"[{idx}] Failed to create series '{subj}': {exc}")
                continue
            start_iso = nev.get("start")
            end_iso = nev.get("end")
            if not (start_iso and end_iso):
                logs.append(f"[{idx}] Skipping one-time event '{subj}': missing start/end")
                continue
            if payload.dry_run:
                logs.append(
                    f"[dry-run][{idx}] would create single: subj='{subj}', cal='{cal_name or '<primary>'}', "
                    f"start={start_iso}, end={end_iso}"
                )
                created += 1
                continue
            try:
                evt = svc.create_event(
                    calendar_id=None,
                    calendar_name=cal_name,
                    subject=subj,
                    start_iso=to_iso_str(start_iso),
                    end_iso=to_iso_str(end_iso),
                    tz=nev.get("tz"),
                    body_html=nev.get("body_html"),
                    all_day=bool(nev.get("all_day") or nev.get("allDay")),
                    location=nev.get("location"),
                    no_reminder=no_rem_effective,
                    reminder_minutes=rem_minutes,
                )
                created += 1
                logs.append(f"[{idx}] Created event: {evt.get('id')} {subj}")
            except Exception as exc:
                logs.append(f"[{idx}] Failed to create event '{subj}': {exc}")
        result = OutlookAddResult(logs=logs, created=created, dry_run=payload.dry_run)
        return ResultEnvelope(status="success", payload=result)


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
