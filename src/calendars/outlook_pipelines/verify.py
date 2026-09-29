"""Outlook Verify Pipeline - check for duplicate/missing calendar events."""

from dataclasses import field

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
from calendars.selection import filter_events_in_window, window_bounds_utc


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
    pending: list[VerificationContext] = field(default_factory=list)


@dataclass
class _CalendarFetch:
    """One calendarView query covering every pending check on a calendar."""

    cal_name: str | None
    start_iso: str
    end_iso: str
    events: list[dict[str, Any]] | None = None
    error: Exception | None = None


def _fetch_key(ctx: VerificationContext) -> tuple:
    """Group checks by calendar; a check with an unparseable window queries alone."""
    if window_bounds_utc(ctx.start_iso, ctx.end_iso) is None:
        return (ctx.cal_name, ctx.start_iso, ctx.end_iso)
    return (ctx.cal_name,)


def _plan_fetches(pending: list[VerificationContext]) -> dict[tuple, _CalendarFetch]:
    """Collapse per-event windows into one covering window per fetch key."""
    fetches: dict[tuple, _CalendarFetch] = {}
    for ctx in pending:
        key = _fetch_key(ctx)
        cur = fetches.get(key)
        if cur is None:
            fetches[key] = _CalendarFetch(ctx.cal_name, ctx.start_iso, ctx.end_iso)
            continue
        bounds = window_bounds_utc(ctx.start_iso, ctx.end_iso)
        cur_bounds = window_bounds_utc(cur.start_iso, cur.end_iso)
        if bounds is None or cur_bounds is None:
            continue
        # Keep the caller's original strings: they go into the Graph URL as-is.
        if bounds[0] < cur_bounds[0]:
            cur.start_iso = ctx.start_iso
        if bounds[1] > cur_bounds[1]:
            cur.end_iso = ctx.end_iso
    return fetches


class OutlookVerifyProcessor(EventIterationProcessor):
    """Report each weekly config entry as duplicate (present) or missing.

    Issues one ``calendarView`` query per calendar, spanning the union of every
    entry's window, then narrows per entry in memory: window overlap, subject
    substring, weekday and time. That reproduces the per-entry query it
    replaces while costing one Graph round trip per calendar instead of one
    per entry.
    """

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
        win = compute_window(nev)
        if not win:
            return
        accumulator.pending.append(VerificationContext(
            idx=idx,
            nev=nev,
            subj=subj,
            byday=byday,
            cal_name=payload.calendar or nev.get("calendar"),
            start_iso=win[0],
            end_iso=win[1],
        ))

    def _finalize_result(self, payload: OutlookVerifyRequest, accumulator: _VerifyAccumulator) -> OutlookVerifyResult:
        fetches = _plan_fetches(accumulator.pending)
        for fetch in fetches.values():
            self._run_fetch(payload, fetch)
        for ctx in accumulator.pending:
            result = self._classify(ctx, fetches[_fetch_key(ctx)], accumulator.logs)
            if result == "duplicate":
                accumulator.duplicates += 1
            elif result == "missing":
                accumulator.missing += 1
        return OutlookVerifyResult(
            logs=accumulator.logs,
            total=accumulator.total,
            duplicates=accumulator.duplicates,
            missing=accumulator.missing,
        )

    @staticmethod
    def _run_fetch(payload: OutlookVerifyRequest, fetch: _CalendarFetch) -> None:
        from calendars.outlook_service import ListEventsRequest
        try:
            fetch.events = payload.service.list_events_in_range(ListEventsRequest(
                start_iso=fetch.start_iso,
                end_iso=fetch.end_iso,
                calendar_name=fetch.cal_name,
            ))
        except Exception as e:  # reported per entry by _classify, as the per-entry query did
            fetch.error = e

    @staticmethod
    def _candidates(ctx: VerificationContext, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Narrow a calendar-wide fetch to what a per-entry query would have returned."""
        bounds = window_bounds_utc(ctx.start_iso, ctx.end_iso)
        in_window = events if bounds is None else filter_events_in_window(events, *bounds)
        needle = ctx.subj.lower()
        return [ev for ev in in_window if needle in (ev.get("subject") or "").lower()]

    def _classify(self, ctx: VerificationContext, fetch: _CalendarFetch, logs: list[str]) -> str | None:
        if fetch.error is not None:
            logs.append(f"[{ctx.idx}] Unable to list events for '{ctx.subj}': {fetch.error}")
            return None
        want_start = (ctx.nev.get("start_time") or "").strip()
        want_end = (ctx.nev.get("end_time") or "").strip()
        matches = filter_events_by_day_time(
            self._candidates(ctx, fetch.events or []),
            byday=ctx.byday,
            start_time=want_start,
            end_time=want_end,
            tz=(ctx.nev.get("tz") or "").strip() or None,
        )
        cal_display = ctx.cal_name or "<primary>"
        if matches:
            logs.append(f"[{ctx.idx}] duplicate: {ctx.subj} {','.join(ctx.byday)} {want_start}-{want_end} in '{cal_display}'")
            return "duplicate"
        logs.append(f"[{ctx.idx}] missing:   {ctx.subj} {','.join(ctx.byday)} {want_start}-{want_end} in '{cal_display}'")
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
