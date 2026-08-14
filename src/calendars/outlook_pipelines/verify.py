"""Outlook Verify Pipeline - check for duplicate/missing calendar events."""

from ._base import (
    dataclass,
    Path,
    Any,
    EventIterationProcessor,
    compute_window,
    filter_events_by_day_time,
    BaseProducer,
    RequestConsumer,
)
from ._context import VerificationContext


@dataclass
class OutlookVerifyRequest:
    config_path: Path
    calendar: str | None
    service: Any


# Type alias for backward compatibility
OutlookVerifyRequestConsumer = RequestConsumer[OutlookVerifyRequest]


@dataclass
class OutlookVerifyResult:
    logs: list[str]
    total: int
    duplicates: int
    missing: int


@dataclass
class _VerifyAccumulator:
    """Per-run accumulator for OutlookVerifyProcessor's template method."""

    logs: list[str]
    total: int
    duplicates: int
    missing: int


class OutlookVerifyProcessor(EventIterationProcessor):
    def __init__(self, config_loader=None) -> None:
        self._config_loader = config_loader

    def _init_accumulator(self, payload: OutlookVerifyRequest) -> _VerifyAccumulator:
        return _VerifyAccumulator(logs=[], total=0, duplicates=0, missing=0)

    def _handle_event(
        self, payload: OutlookVerifyRequest, idx: int, nev: dict[str, Any], accumulator: _VerifyAccumulator
    ) -> None:
        subj = (nev.get("subject") or "").strip()
        byday = nev.get("byday") or []
        rt = nev.get("repeat") or ""
        if not (subj and rt == "weekly" and byday):
            return
        accumulator.total += 1
        context = VerificationContext(idx=idx, nev=nev, subj=subj, byday=byday)
        result = self._verify_single_event_from_context(payload, context, accumulator.logs)
        if result == "duplicate":
            accumulator.duplicates += 1
        elif result == "missing":
            accumulator.missing += 1

    def _finalize(self, accumulator: _VerifyAccumulator) -> OutlookVerifyResult:
        return OutlookVerifyResult(
            logs=accumulator.logs,
            total=accumulator.total,
            duplicates=accumulator.duplicates,
            missing=accumulator.missing,
        )

    def _verify_single_event_from_context(
        self,
        payload: OutlookVerifyRequest,
        context: VerificationContext,
        logs: list[str],
    ) -> str | None:
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


class OutlookVerifyProducer(BaseProducer):
    def _produce_success(self, payload: OutlookVerifyResult, diagnostics: dict[str, Any] | None) -> None:
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
