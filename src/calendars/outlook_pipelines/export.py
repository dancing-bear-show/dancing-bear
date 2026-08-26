"""Outlook Export Plan Pipeline - export calendar events to a plan YAML."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

from ._base import (
    dataclass as _dc,  # noqa: F401 - unused but kept for symmetry with _base imports
    Path,
    Any,
    SafeProcessor,
    BaseProducer,
    DateWindowResolver,
    RequestConsumer,
    check_service_required,
)

# Graph recurrence pattern types we can reverse
_SUPPORTED_PATTERNS = {"daily", "weekly", "absolutemonthly"}

# Map Graph lowercase full day names to RRULE 2-char uppercase codes
_GRAPH_DAY_MAP: dict[str, str] = {
    "monday": "MO",
    "tuesday": "TU",
    "wednesday": "WE",
    "thursday": "TH",
    "friday": "FR",
    "saturday": "SA",
    "sunday": "SU",
}

# Map Graph repeat type to plan repeat value
_REPEAT_MAP: dict[str, str] = {
    "daily": "daily",
    "weekly": "weekly",
    "absolutemonthly": "monthly",
}


@dataclass
class OutlookExportRequest:
    service: Any
    calendar: str | None
    from_date: str | None
    to_date: str | None
    out_path: Path | None
    dry_run: bool = False
    verbose: bool = False


OutlookExportRequestConsumer = RequestConsumer[OutlookExportRequest]


@dataclass
class OutlookExportResult:
    events: list[dict[str, Any]]
    skipped: list[dict[str, Any]]
    out_path: Path | None
    dry_run: bool
    verbose: bool

    @property
    def event_count(self) -> int:
        return len(self.events)


@dataclass
class _ExportAccumulator:
    events: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    seen_masters: set[str] = field(default_factory=set)


def _extract_time(dt_str: str) -> str:
    """Extract HH:MM from a dateTime string like '2026-03-10T09:00:00'."""
    if "T" in dt_str:
        return dt_str.split("T", 1)[1][:5]
    return ""


def _is_all_day(ev: dict[str, Any]) -> bool:
    """Return True if the event uses date-only start (all-day)."""
    start = ev.get("start") or {}
    return "date" in start and "dateTime" not in start


def _resolve_tz(start: dict[str, Any], svc: Any) -> str | None:
    """Resolve timezone from the event start block, mailbox, or fallback."""
    tz = (start.get("timeZone") or "").strip()
    if tz:
        return tz
    mbx = None
    try:
        mbx = svc.get_mailbox_timezone()
    except Exception:  # nosec B110 - best-effort mailbox tz lookup, non-fatal
        pass
    if mbx:
        return mbx
    warnings.warn("No timezone found; falling back to America/Toronto", stacklevel=2)
    return "America/Toronto"


def _reverse_recurrence(
    master: dict[str, Any],
    svc: Any,
) -> dict[str, Any] | None:
    """Reverse a Graph series master into a plan event dict.

    Returns None (caller appends to skipped) when the pattern is unsupported.
    Raises ValueError for malformed masters (missing_interval).
    """
    recurrence = master.get("recurrence") or {}
    pattern = recurrence.get("pattern") or {}
    rng = recurrence.get("range") or {}

    ptype = (pattern.get("type") or "").lower()
    if ptype not in _SUPPORTED_PATTERNS:
        return None  # caller records unsupported_pattern skip

    ev: dict[str, Any] = {}
    subject = master.get("subject") or ""
    if subject:
        ev["subject"] = subject

    # repeat
    ev["repeat"] = _REPEAT_MAP[ptype]

    # interval — omit if 1, fail loudly if key missing
    if "interval" not in pattern:
        raise ValueError("missing_interval")
    interval = int(pattern["interval"])
    if interval > 1:
        ev["interval"] = interval

    # byday (only meaningful for weekly)
    if ptype == "weekly":
        raw_days = pattern.get("daysOfWeek") or []
        byday = [_GRAPH_DAY_MAP[d.lower()] for d in raw_days if d.lower() in _GRAPH_DAY_MAP]
        if byday:
            ev["byday"] = byday

    # start_time / end_time from master start/end
    master_start = master.get("start") or {}
    master_end = master.get("end") or {}
    start_dt = master_start.get("dateTime") or ""
    end_dt = master_end.get("dateTime") or ""
    if start_dt:
        ev["start_time"] = _extract_time(start_dt)
    if end_dt:
        ev["end_time"] = _extract_time(end_dt)

    # tz
    tz = _resolve_tz(master_start, svc)
    if tz:
        ev["tz"] = tz

    # range
    range_type = (rng.get("type") or "").lower()
    start_date = rng.get("startDate") or ""
    range_dict: dict[str, Any] = {}
    if start_date:
        range_dict["start_date"] = start_date
    if range_type == "enddate":
        end_date = rng.get("endDate") or ""
        if end_date:
            range_dict["until"] = end_date
    elif range_type == "numbered":
        count = rng.get("numberOfOccurrences")
        if count is not None:
            ev["count"] = int(count)
    # noEnd: just start_date, no until/count

    if range_dict:
        ev["range"] = range_dict

    # location
    loc = ((master.get("location") or {}).get("displayName") or "").strip()
    if loc:
        ev["location"] = loc

    return ev


def _convert_one_off(ev: dict[str, Any], svc: Any) -> dict[str, Any]:
    """Convert a Graph single-instance event to a plan dict."""
    result: dict[str, Any] = {}
    subject = ev.get("subject") or ""
    if subject:
        result["subject"] = subject

    start = ev.get("start") or {}
    end_block = ev.get("end") or {}

    if _is_all_day(ev):
        # All-day: use date strings, no start_time/end_time/tz
        start_date = start.get("date") or ""
        end_date = end_block.get("date") or ""
        if start_date:
            result["start"] = start_date
        if end_date:
            result["end"] = end_date
    else:
        start_dt = start.get("dateTime") or ""
        end_dt = end_block.get("dateTime") or ""
        if start_dt:
            result["start"] = start_dt
        if end_dt:
            result["end"] = end_dt
        tz = _resolve_tz(start, svc)
        if tz:
            result["tz"] = tz

    loc = ((ev.get("location") or {}).get("displayName") or "").strip()
    if loc:
        result["location"] = loc

    return result


class OutlookExportProcessor(SafeProcessor[OutlookExportRequest, OutlookExportResult]):
    def __init__(self, today_factory=None) -> None:
        self._window = DateWindowResolver(today_factory)

    def _is_one_off(self, ev: dict[str, Any]) -> bool:
        etype = (ev.get("type") or "").lower()
        return etype == "singleinstance" or not ev.get("seriesMasterId")

    def _process_safe(self, payload: OutlookExportRequest) -> OutlookExportResult:
        check_service_required(payload.service)
        svc = payload.service
        start_iso, end_iso = self._window.resolve(payload.from_date, payload.to_date)

        from calendars.outlook_service import ListEventsRequest
        all_events = svc.list_events_in_range(ListEventsRequest(
            start_iso=start_iso,
            end_iso=end_iso,
            calendar_name=payload.calendar,
        ))

        acc = _ExportAccumulator()

        # Partition events
        one_offs: list[dict[str, Any]] = []
        by_master: dict[str, list[dict[str, Any]]] = {}

        for ev in (all_events or []):
            if self._is_one_off(ev):
                one_offs.append(ev)
            else:
                mid = ev.get("seriesMasterId") or ""
                if mid:
                    by_master.setdefault(mid, []).append(ev)

        # Process one-offs
        for ev in one_offs:
            plan_ev = _convert_one_off(ev, svc)
            acc.events.append(plan_ev)

        # Process recurring series
        for master_id, occurrences in by_master.items():
            if master_id in acc.seen_masters:
                continue
            acc.seen_masters.add(master_id)

            # Pick representative occurrence for subject/error reporting
            rep = occurrences[0] if occurrences else {}
            subject = rep.get("subject") or ""

            # Fetch series master
            master = svc.get_event(master_id)
            if master is None:
                acc.skipped.append({
                    "seriesMasterId": master_id,
                    "subject": subject,
                    "reason": "orphaned_master",
                })
                continue

            recurrence = master.get("recurrence") or {}
            pattern = recurrence.get("pattern") or {}
            ptype_raw = pattern.get("type") or ""
            ptype = ptype_raw.lower()

            if ptype not in _SUPPORTED_PATTERNS:
                acc.skipped.append({
                    "seriesMasterId": master_id,
                    "subject": subject,
                    "pattern_type": ptype_raw,  # preserve original casing from Graph
                    "reason": "unsupported_pattern",
                })
                continue

            if "interval" not in pattern:
                acc.skipped.append({
                    "seriesMasterId": master_id,
                    "subject": subject,
                    "reason": "missing_interval",
                })
                continue

            try:
                plan_ev = _reverse_recurrence(master, svc)
            except ValueError as exc:
                reason = str(exc)
                acc.skipped.append({
                    "seriesMasterId": master_id,
                    "subject": subject,
                    "reason": reason,
                })
                continue

            if plan_ev is None:
                acc.skipped.append({
                    "seriesMasterId": master_id,
                    "subject": subject,
                    "pattern_type": ptype_raw,
                    "reason": "unsupported_pattern",
                })
                continue

            # Collect cancelled/exception occurrences as exdates
            exdates = []
            for occ in occurrences:
                if occ.get("isCancelled") or (occ.get("type") or "").lower() == "exceptionoccurrence":
                    st = (occ.get("originalStart") or (occ.get("start") or {}).get("dateTime") or "")
                    date_only = st.split("T", 1)[0] if "T" in st else st
                    if date_only:
                        exdates.append(date_only)

            if exdates:
                plan_ev["exdates"] = sorted(set(exdates))

            acc.events.append(plan_ev)

        return OutlookExportResult(
            events=acc.events,
            skipped=acc.skipped,
            out_path=payload.out_path,
            dry_run=payload.dry_run,
            verbose=payload.verbose,
        )


class OutlookExportProducer(BaseProducer):
    def _produce_success(self, payload: OutlookExportResult, diagnostics: dict[str, Any] | None) -> None:
        n = payload.event_count
        m = len(payload.skipped)
        print(f"Exported {n} events; skipped {m} (see --verbose for details)")

        if payload.verbose and payload.skipped:
            for s in payload.skipped:
                print(f"  skipped: {s}")

        if payload.dry_run:
            print("[dry-run] No file written.")
            return

        if payload.out_path:
            from core.yamlio import dump_config
            payload.out_path.parent.mkdir(parents=True, exist_ok=True)
            dump_config(str(payload.out_path), {"events": payload.events})
            print(f"Wrote plan to {payload.out_path}")


__all__ = [
    "OutlookExportRequest",
    "OutlookExportRequestConsumer",
    "OutlookExportResult",
    "OutlookExportProcessor",
    "OutlookExportProducer",
]
