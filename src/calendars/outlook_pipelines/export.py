"""Outlook Export Plan Pipeline - export calendar events to a plan YAML."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._base import (
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

# Last-resort timezone when neither the event nor the mailbox supplies one.
# Every event resolved this way is recorded in OutlookExportResult.tz_inferred.
_TZ_FALLBACK = "America/Toronto"

# Private marker carrying how an event's tz was resolved from the reversal
# helpers up to the processor. Stripped before the event reaches the plan file —
# it is provenance for the run report, not part of the plan schema.
_TZ_SOURCE_KEY = "_tz_source"

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
    # Events whose timezone was not read from the event itself. Each entry is
    # {subject, tz, source} with source "mailbox" or "fallback". A guessed
    # timezone silently shifts every occurrence of an event on re-import, so
    # the run must say which events were guessed — not emit one process-wide
    # warning that says nothing about how many or which.
    tz_inferred: list[dict[str, Any]] = field(default_factory=list)

    @property
    def event_count(self) -> int:
        return len(self.events)


@dataclass
class _ExportAccumulator:
    events: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    seen_masters: set[str] = field(default_factory=set)
    tz_inferred: list[dict[str, Any]] = field(default_factory=list)


def _record_event(acc: _ExportAccumulator, plan_ev: dict[str, Any]) -> None:
    """Append a plan event, moving any tz-provenance marker into the report.

    The marker must not reach the plan file: the plan schema is a fixed key set
    and an extra private key would fail the round-trip equivalence check.
    """
    source = plan_ev.pop(_TZ_SOURCE_KEY, None)
    if source:
        acc.tz_inferred.append({
            "subject": plan_ev.get("subject", ""),
            "tz": plan_ev.get("tz", ""),
            "source": source,
        })
    acc.events.append(plan_ev)


def _extract_time(dt_str: str) -> str:
    """Extract HH:MM from a dateTime string like '2026-03-10T09:00:00'."""
    if "T" in dt_str:
        return dt_str.split("T", 1)[1][:5]
    return ""


def _date_part(dt_str: str | None) -> str:
    """Return the YYYY-MM-DD prefix of an ISO datetime, or "" when absent."""
    s = (dt_str or "").strip()
    return s.split("T", 1)[0] if "T" in s else s


def _is_all_day(ev: dict[str, Any]) -> bool:
    """Return True if the event is all-day.

    Graph signals this two ways, and both must be honoured:
      - a date-only start block ("date" with no "dateTime"), and
      - the isAllDay flag alongside a normal dateTime block, which is what
        /calendarView returns and what this repo's own write path emits
        (core/outlook/calendar.py:254 sets isAllDay while keeping dateTime).
    Checking only the date-only shape misclassifies every all-day event created
    by add-from-config as a timed event, silently losing its all-day nature on
    round-trip.
    """
    if ev.get("isAllDay"):
        return True
    start = ev.get("start") or {}
    return "date" in start and "dateTime" not in start


def _resolve_tz(start: dict[str, Any], svc: Any) -> tuple[str, str]:
    """Resolve timezone from the event start block, mailbox, or fallback.

    Returns (tz, source) where source is one of "event", "mailbox" or
    "fallback". Callers record anything other than "event" against the event
    itself: the exported plan must carry evidence of which timezones were
    inferred rather than read, and a warnings.warn fires only once per process
    (so a hundred guessed events would surface a single warning and leave no
    trace in the plan file).
    """
    tz = (start.get("timeZone") or "").strip()
    if tz:
        return tz, "event"
    mbx = None
    try:
        mbx = svc.get_mailbox_timezone()
    except Exception:  # nosec B110 - best-effort mailbox tz lookup, non-fatal
        pass
    if mbx:
        return mbx, "mailbox"
    return _TZ_FALLBACK, "fallback"


def _apply_recurrence_byday(
    ev: dict[str, Any],
    ptype: str,
    pattern: dict[str, Any],
) -> None:
    """Populate ev["byday"] for weekly patterns if day codes are present."""
    if ptype != "weekly":
        return
    raw_days = pattern.get("daysOfWeek") or []
    byday = [_GRAPH_DAY_MAP[d.lower()] for d in raw_days if d.lower() in _GRAPH_DAY_MAP]
    if byday:
        ev["byday"] = byday


def _apply_recurrence_range(
    ev: dict[str, Any],
    rng: dict[str, Any],
) -> None:
    """Populate ev["range"] and ev["count"] from a Graph recurrence range block."""
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


def _apply_recurrence_times(
    ev: dict[str, Any],
    master: dict[str, Any],
    svc: Any,
) -> None:
    """Populate ev start_time/end_time and timezone from the series master.

    Grouped with the tz lookup because both read the same master start block:
    splitting them would mean resolving that block twice.
    """
    master_start = master.get("start") or {}
    master_end = master.get("end") or {}
    start_dt = master_start.get("dateTime") or ""
    end_dt = master_end.get("dateTime") or ""
    if start_dt:
        ev["start_time"] = _extract_time(start_dt)
    if end_dt:
        ev["end_time"] = _extract_time(end_dt)

    tz, tz_source = _resolve_tz(master_start, svc)
    if tz:
        ev["tz"] = tz
    if tz_source != "event":
        ev[_TZ_SOURCE_KEY] = tz_source


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
    _apply_recurrence_byday(ev, ptype, pattern)

    # start_time / end_time / tz from master start/end
    _apply_recurrence_times(ev, master, svc)

    # range
    _apply_recurrence_range(ev, rng)

    # location
    loc = ((master.get("location") or {}).get("displayName") or "").strip()
    if loc:
        ev["location"] = loc

    return ev


def _convert_one_off_all_day(
    start: dict[str, Any],
    end_block: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """Populate result with all-day date fields (no time, no tz).

    An isAllDay event may carry either a date-only block or a full dateTime
    block (Graph does the latter); take the date part of whichever is present
    rather than emitting an empty start.
    """
    start_date = start.get("date") or _date_part(start.get("dateTime"))
    end_date = end_block.get("date") or _date_part(end_block.get("dateTime"))
    if start_date:
        result["start"] = start_date
    if end_date:
        result["end"] = end_date


def _convert_one_off_timed(
    start: dict[str, Any],
    end_block: dict[str, Any],
    svc: Any,
    result: dict[str, Any],
) -> None:
    """Populate result with timed event fields (start, end, tz)."""
    start_dt = start.get("dateTime") or ""
    end_dt = end_block.get("dateTime") or ""
    if start_dt:
        result["start"] = start_dt
    if end_dt:
        result["end"] = end_dt
    tz, tz_source = _resolve_tz(start, svc)
    if tz:
        result["tz"] = tz
    if tz_source != "event":
        result[_TZ_SOURCE_KEY] = tz_source


def _convert_one_off(ev: dict[str, Any], svc: Any) -> dict[str, Any]:
    """Convert a Graph single-instance event to a plan dict."""
    result: dict[str, Any] = {}
    subject = ev.get("subject") or ""
    if subject:
        result["subject"] = subject

    start = ev.get("start") or {}
    end_block = ev.get("end") or {}

    if _is_all_day(ev):
        # All-day: emit date strings, no start_time/end_time/tz.
        _convert_one_off_all_day(start, end_block, result)
    else:
        _convert_one_off_timed(start, end_block, svc, result)

    loc = ((ev.get("location") or {}).get("displayName") or "").strip()
    if loc:
        result["location"] = loc

    return result


def _partition_events(
    all_events: list[dict[str, Any]] | None,
    is_one_off: Any,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Split a raw event list into one-offs and occurrences grouped by master id.

    Classification is entirely the caller's ``is_one_off`` predicate; this
    function only routes. The ``mid`` guard drops a non-one-off that carries no
    seriesMasterId, since there is no series to attribute it to -- but with the
    production predicate (OutlookExportProcessor._is_one_off, which already
    returns True when seriesMasterId is falsy) that case cannot arise. The
    guard is kept for predicates that classify differently, not because the
    current call site can reach it.
    """
    one_offs: list[dict[str, Any]] = []
    by_master: dict[str, list[dict[str, Any]]] = {}
    for ev in (all_events or []):
        if is_one_off(ev):
            one_offs.append(ev)
            continue
        mid = ev.get("seriesMasterId") or ""
        if mid:
            by_master.setdefault(mid, []).append(ev)
    return one_offs, by_master


def _validate_recurring_master(
    master: dict[str, Any] | None,
    master_id: str,
    subject: str,
) -> dict[str, Any] | None:
    """Return a skip record if this master cannot be exported, else None.

    Collects the three independent reject reasons -- missing master,
    unsupported pattern type, absent interval -- so the caller reads as a
    single "is this exportable?" question instead of three nested guards.
    """
    if master is None:
        return {
            "seriesMasterId": master_id,
            "subject": subject,
            "reason": "orphaned_master",
        }

    pattern = (master.get("recurrence") or {}).get("pattern") or {}
    ptype_raw = pattern.get("type") or ""
    if ptype_raw.lower() not in _SUPPORTED_PATTERNS:
        return {
            "seriesMasterId": master_id,
            "subject": subject,
            "pattern_type": ptype_raw,  # preserve original casing from Graph
            "reason": "unsupported_pattern",
        }

    if "interval" not in pattern:
        return {
            "seriesMasterId": master_id,
            "subject": subject,
            "reason": "missing_interval",
        }
    return None


def _collect_exdates(occurrences: list[dict[str, Any]]) -> list[str]:
    """Return sorted unique exdates for cancelled/rescheduled occurrences.

    originalStart is the originally-scheduled date, set by Graph only when an
    occurrence was rescheduled; a plain cancellation carries just
    start.dateTime. The exdate must name the slot the series would have
    occupied, so prefer originalStart.
    """
    exdates = []
    for occ in occurrences:
        if not (occ.get("isCancelled") or (occ.get("type") or "").lower() == "exceptionoccurrence"):
            continue
        st = (occ.get("originalStart") or (occ.get("start") or {}).get("dateTime") or "")
        date_only = st.split("T", 1)[0] if "T" in st else st
        if date_only:
            exdates.append(date_only)
    return sorted(set(exdates))


def _process_recurring_series(
    master_id: str,
    occurrences: list[dict[str, Any]],
    svc: Any,
    acc: "_ExportAccumulator",
) -> None:
    """Reverse one recurring series into a plan event, or record why it was skipped."""
    rep = occurrences[0] if occurrences else {}
    subject = rep.get("subject") or ""

    master = svc.get_event(master_id)
    skip = _validate_recurring_master(master, master_id, subject)
    if skip is not None:
        acc.skipped.append(skip)
        return

    try:
        plan_ev = _reverse_recurrence(master, svc)
    except ValueError as exc:
        acc.skipped.append({
            "seriesMasterId": master_id,
            "subject": subject,
            "reason": str(exc),
        })
        return

    if plan_ev is None:
        # Unreachable today: _validate_recurring_master already rejects every
        # unsupported pattern, and that is the only case where
        # _reverse_recurrence returns None. Kept deliberately -- if the two
        # checks ever drift apart, the alternative to this branch is appending
        # None to acc.events and silently corrupting the plan. A skipped series
        # is recoverable; a malformed one is not.
        pattern_type = ((master or {}).get("recurrence") or {}).get("pattern", {}).get("type") or ""
        acc.skipped.append({
            "seriesMasterId": master_id,
            "subject": subject,
            "pattern_type": pattern_type,
            "reason": "unsupported_pattern",
        })
        return

    exdates = _collect_exdates(occurrences)
    if exdates:
        plan_ev["exdates"] = exdates

    _record_event(acc, plan_ev)


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
        one_offs, by_master = _partition_events(all_events, self._is_one_off)

        for ev in one_offs:
            _record_event(acc, _convert_one_off(ev, svc))

        for master_id, occurrences in by_master.items():
            if master_id in acc.seen_masters:
                continue
            acc.seen_masters.add(master_id)
            _process_recurring_series(master_id, occurrences, svc, acc)

        return OutlookExportResult(
            events=acc.events,
            skipped=acc.skipped,
            out_path=payload.out_path,
            dry_run=payload.dry_run,
            verbose=payload.verbose,
            tz_inferred=acc.tz_inferred,
        )


class OutlookExportProducer(BaseProducer):
    def _produce_success(self, payload: OutlookExportResult, diagnostics: dict[str, Any] | None) -> None:
        n = payload.event_count
        m = len(payload.skipped)
        print(f"Exported {n} events; skipped {m} (see --verbose for details)")

        inferred = getattr(payload, "tz_inferred", []) or []
        if inferred:
            # Not gated behind --verbose: a guessed timezone shifts every
            # occurrence of an event on re-import, so the count belongs in the
            # default summary. Subjects stay out of the console (see below).
            fell_back = sum(1 for i in inferred if i.get("source") == "fallback")
            print(
                f"Timezone inferred for {len(inferred)} event(s) "
                f"({fell_back} via {_TZ_FALLBACK} fallback); "
                "recorded in result.tz_inferred"
            )

        if payload.verbose and payload.skipped:
            # Print the reason and pattern type only. The skipped dicts also
            # carry the event subject and seriesMasterId; a Graph object id and
            # a calendar subject are not console material, so they stay in the
            # plan file (which lands outside the checkout) and out of logs.
            for s in payload.skipped:
                reason = s.get("reason", "unknown")
                ptype = s.get("pattern_type")
                suffix = f" (pattern_type={ptype})" if ptype else ""
                print(f"  skipped: {reason}{suffix}")

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
