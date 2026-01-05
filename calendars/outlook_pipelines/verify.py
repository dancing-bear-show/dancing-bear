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


@dataclass
class VerificationContext:
    """Context for verifying a single event."""

    idx: int
    nev: Dict[str, Any]
    subj: str
    byday: List[str]


class OutlookVerifyProcessor(SafeProcessor[OutlookVerifyRequest, OutlookVerifyResult]):
    def __init__(self, config_loader=None) -> None:
        self._config_loader = config_loader

    def _process_safe(self, payload: OutlookVerifyRequest) -> OutlookVerifyResult:
        items = load_events_config(payload.config_path, self._config_loader)
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
            result = self._verify_single_event(payload, i, nev, subj, byday, logs)
            if result == "duplicate":
                duplicates += 1
            elif result == "missing":
                missing += 1
        return OutlookVerifyResult(logs=logs, total=total, duplicates=duplicates, missing=missing)

    def _verify_single_event_from_context(
        self,
        payload: OutlookVerifyRequest,
        context: VerificationContext,
        logs: List[str],
    ) -> Optional[str]:
        """Verify a single recurring event using VerificationContext."""
        cal_name = payload.calendar or context.nev.get("calendar")
        win = compute_window(context.nev)
        if not win:
            return None
        start_iso, end_iso = win
        try:
            from calendars.outlook_service import ListEventsRequest
            events = payload.service.list_events_in_range(ListEventsRequest(
                start_iso=start_iso,
                end_iso=end_iso,
                calendar_name=cal_name,
                subject_filter=context.subj,
            ))
        except Exception as e:
            logs.append(f"[{context.idx}] Unable to list events for '{context.subj}': {e}")
            return None
        want_start = (context.nev.get("start_time") or "").strip()
        want_end = (context.nev.get("end_time") or "").strip()
        matches = filter_events_by_day_time(events, byday=context.byday, start_time=want_start, end_time=want_end)
        cal_display = cal_name or "<primary>"
        if matches:
            logs.append(f"[{context.idx}] duplicate: {context.subj} {','.join(context.byday)} {want_start}-{want_end} in '{cal_display}'")
            return "duplicate"
        logs.append(f"[{context.idx}] missing:   {context.subj} {','.join(context.byday)} {want_start}-{want_end} in '{cal_display}'")
        return "missing"

    def _verify_single_event(
        self,
        payload: OutlookVerifyRequest,
        idx: int,
        nev: Dict[str, Any],
        subj: str,
        byday: List[str],
        logs: List[str],
    ) -> Optional[str]:
        """Verify a single recurring event (legacy signature)."""
        context = VerificationContext(idx=idx, nev=nev, subj=subj, byday=byday)
        return self._verify_single_event_from_context(payload, context, logs)


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
