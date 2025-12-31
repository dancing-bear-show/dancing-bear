"""Outlook Verify Pipeline - check for duplicate/missing calendar events."""

from ._base import (
    dataclass,
    Path,
    Any,
    Dict,
    List,
    Optional,
    SafeProcessor,
    normalize_event,
    compute_window,
    filter_events_by_day_time,
    BaseProducer,
    RequestConsumer,
    load_events_config,
)


@dataclass
class OutlookVerifyRequest:
    config_path: Path
    calendar: Optional[str]
    service: Any


# Type alias for backward compatibility
OutlookVerifyRequestConsumer = RequestConsumer[OutlookVerifyRequest]


@dataclass
class OutlookVerifyResult:
    logs: List[str]
    total: int
    duplicates: int
    missing: int


class OutlookVerifyProcessor(SafeProcessor[OutlookVerifyRequest, OutlookVerifyResult]):
    def __init__(self, config_loader=None) -> None:
        self._config_loader = config_loader

    def _process_safe(self, payload: OutlookVerifyRequest) -> OutlookVerifyResult:
        items = load_events_config(payload.config_path, self._config_loader)
        svc = payload.service
        logs: List[str] = []
        total = duplicates = missing = 0
        for i, ev in enumerate(items, start=1):
            if not isinstance(ev, dict):
                continue
            nev = normalize_event(ev)
            subj = (nev.get("subject") or "").strip()
            byday = nev.get("byday") or []
            rt = nev.get("repeat") or ""
            if not (subj and rt == "weekly" and byday):
                continue
            total += 1
            cal_name = payload.calendar or nev.get("calendar")
            win = compute_window(nev)
            if not win:
                continue
            start_iso, end_iso = win
            try:
                events = svc.list_events_in_range(calendar_name=cal_name, start_iso=start_iso, end_iso=end_iso, subject_filter=subj)
            except Exception as e:
                logs.append(f"[{i}] Unable to list events for '{subj}': {e}")
                continue
            want_start = (nev.get("start_time") or "").strip()
            want_end = (nev.get("end_time") or "").strip()
            matches = filter_events_by_day_time(events, byday=byday, start_time=want_start, end_time=want_end)
            if matches:
                duplicates += 1
                logs.append(f"[{i}] duplicate: {subj} {','.join(byday)} {want_start}-{want_end} in '{cal_name or '<primary>'}'")
            else:
                missing += 1
                logs.append(f"[{i}] missing:   {subj} {','.join(byday)} {want_start}-{want_end} in '{cal_name or '<primary>'}'")
        result = OutlookVerifyResult(logs=logs, total=total, duplicates=duplicates, missing=missing)
        return result


class OutlookVerifyProducer(BaseProducer):
    def _produce_success(self, payload: OutlookVerifyResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        self.print_logs(payload.logs)
        print(
            f"Checked {payload.total} recurring entries. "
            f"Duplicates: {payload.duplicates}, Missing: {payload.missing}."
        )


__all__ = [
    "OutlookVerifyRequest",
    "OutlookVerifyRequestConsumer",
    "OutlookVerifyResult",
    "OutlookVerifyProcessor",
    "OutlookVerifyProducer",
]
