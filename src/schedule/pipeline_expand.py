"""Recurrence expansion logic for the schedule pipeline."""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any

from core.constants import FMT_DATETIME
from core.date_utils import to_iso_str as _to_iso_str


@dataclass
class EventCreateParams:
    """Bundled parameters for creating a calendar event."""

    cal_id: Any
    calendar_name: str | None
    subject: str
    tz: Any
    body_html: Any
    location: Any
    no_reminder: bool
    reminder_minutes: Any


@dataclass
class RecurrenceExpansionConfig:
    """Configuration for expanding recurring event occurrences."""

    start_date: _dt.date
    end_date: _dt.date
    start_time: str
    end_time: str
    excluded_dates: set
    weekdays: list[int] | None = None  # For weekly recurrence


@dataclass
class SyncMatchContext:
    """Context for matching and synchronizing calendar events."""

    plan_st_keys: set  # Planned subject-time keys
    planned_subjects_set: set  # Set of planned subjects (lowercased)
    have_keys: set  # Existing event keys
    have_map: dict[str, dict[str, Any]]  # Map of existing events by key
    match_mode: str  # "subject-time" or "subject"


def _norm_dt_minute(s: str | None) -> str | None:
    """Normalize an ISO-like datetime to minute precision without timezone."""
    if not s:
        return None
    try:
        ss = str(s).replace("Z", "").replace("z", "").strip()
        if "T" not in ss:
            ss = ss + "T00:00:00"
        try:
            dt = _dt.datetime.fromisoformat(ss)
        except Exception:
            base, _, tail = ss.partition("T")
            hhmm = tail.split(":")
            if len(hhmm) >= 2:
                dt = _dt.datetime.fromisoformat(f"{base}T{hhmm[0]}:{hhmm[1]}:00")
            else:
                return None
        return dt.strftime(FMT_DATETIME)
    except Exception:
        return None


def _weekday_code_to_py(d: str) -> int | None:
    m = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
    return m.get(d.upper())


def _to_date(d: Any) -> _dt.date:
    """Parse a date string to a date object."""
    return _dt.date.fromisoformat(str(d))


def _to_datetime(d: _dt.date, t: str) -> _dt.datetime:
    """Combine a date and time string into a datetime."""
    hh, mm = (t or "00:00").split(":", 1)
    return _dt.datetime(d.year, d.month, d.day, int(hh), int(mm))


def _parse_exdates(exdates_raw: list[Any]) -> set:
    """Parse exclusion dates into a set of ISO date strings."""
    ex_set: set = set()
    for x in exdates_raw:
        try:
            xs = str(x).strip()
            if xs:
                ex_set.add(xs.split("T", 1)[0])
        except (TypeError, ValueError):
            continue  # Skip malformed entries
    return ex_set


def _make_occurrence(d: _dt.date, start_time: str, end_time: str) -> tuple[str, str]:
    """Create a start/end ISO string pair for a single occurrence."""
    sdt = _to_datetime(d, start_time)
    edt = _to_datetime(d, end_time)
    if edt <= sdt:
        edt = edt + _dt.timedelta(days=1)
    if (edt - sdt).total_seconds() >= 4 * 3600:
        edt = sdt + _dt.timedelta(hours=3, minutes=59)
    return (sdt.strftime(FMT_DATETIME), edt.strftime(FMT_DATETIME))


def _expand_daily(
    cur: _dt.date, end: _dt.date, start_time: str, end_time: str, ex_set: set
) -> list[tuple[str, str]]:
    """Expand daily occurrences within a date range."""
    out: list[tuple[str, str]] = []
    d = cur
    while d <= end:
        if d.isoformat() not in ex_set:
            out.append(_make_occurrence(d, start_time, end_time))
        d = d + _dt.timedelta(days=1)
    return out


def _expand_weekly(config: RecurrenceExpansionConfig) -> list[tuple[str, str]]:
    """Expand weekly occurrences within a date range."""
    out: list[tuple[str, str]] = []
    d = config.start_date
    while d <= config.end_date:
        if config.weekdays and d.weekday() in config.weekdays and d.isoformat() not in config.excluded_dates:
            out.append(_make_occurrence(d, config.start_time, config.end_time))
        d = d + _dt.timedelta(days=1)
    return out


def _extract_event_times(ev: dict[str, Any], win_from: str, win_to: str) -> tuple[str, str, str, str] | None:
    """Extract and validate time fields from event.

    Returns (start_time, end_time, range_start, range_until) or None if invalid.
    """
    start_time = ev.get("start_time")
    end_time = ev.get("end_time") or start_time
    rng = ev.get("range") or {}
    range_start = rng.get("start_date") or win_from
    range_until = rng.get("until") or win_to

    if not (start_time and end_time and range_start):
        return None

    return start_time, end_time, range_start, range_until


def _calculate_expansion_window(
    range_start: str, range_until: str, win_from: str, win_to: str
) -> tuple[_dt.date, _dt.date] | None:
    """Calculate effective date range for expansion.

    Returns (start_date, end_date) or None if range is invalid.
    """
    win_start = _to_date(win_from)
    win_end = _to_date(win_to)
    cur = max(_to_date(range_start), win_start)
    end = min(_to_date(range_until), win_end)

    if cur > end:
        return None

    return cur, end


def _expand_weekly_occurrences(
    ev: dict[str, Any], config: RecurrenceExpansionConfig
) -> list[tuple[str, str]]:
    """Expand weekly recurrence for event."""
    byday = ev.get("byday") or []
    days_idx = [x for x in (_weekday_code_to_py(d) for d in byday) if x is not None]
    if not days_idx:
        return []

    week_config = RecurrenceExpansionConfig(
        start_date=config.start_date,
        end_date=config.end_date,
        start_time=config.start_time,
        end_time=config.end_time,
        excluded_dates=config.excluded_dates,
        weekdays=days_idx,
    )
    return _expand_weekly(week_config)


def _expand_recurring_occurrences(ev: dict[str, Any], win_from: str, win_to: str) -> list[tuple[str, str]]:
    """Expand recurring event (weekly/daily) to list of (start_iso, end_iso) within window."""
    rpt = (ev.get("repeat") or "").strip().lower()
    if rpt not in ("daily", "weekly"):
        return []

    times = _extract_event_times(ev, win_from, win_to)
    if not times:
        return []

    start_time, end_time, range_start, range_until = times
    window = _calculate_expansion_window(range_start, range_until, win_from, win_to)
    if not window:
        return []

    start_date, end_date = window
    ex_set = _parse_exdates(ev.get("exdates") or [])

    if rpt == "daily":
        return _expand_daily(start_date, end_date, start_time, end_time, ex_set)

    return _expand_weekly_occurrences(ev, RecurrenceExpansionConfig(
        start_date=start_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
        excluded_dates=ex_set,
    ))


def _ensure_calendar_id(service: Any, calendar_name: str | None) -> Any:
    """Resolve calendar ID, falling back to name lookup on error."""
    if not calendar_name:
        return None
    try:
        return service.ensure_calendar(calendar_name)
    except Exception:  # nosec B110 - fallback across heterogeneous service implementations
        return service.get_calendar_id_by_name(calendar_name)


def _create_recurring_or_single(
    service: Any, ev: dict[str, Any], params: EventCreateParams,
) -> Any | None:
    """Create recurring or single event. Returns result dict or None if skipped."""
    ev_range = ev.get("range") or {}
    if ev.get("repeat") and ev.get("start_time") and ev_range.get("start_date"):
        return service.create_recurring_event(
            calendar_id=params.cal_id,
            calendar_name=params.calendar_name,
            subject=params.subject,
            start_time=ev.get("start_time"),
            end_time=ev.get("end_time") or ev.get("start_time"),
            tz=params.tz,
            repeat=str(ev.get("repeat") or "").lower(),
            interval=int(ev.get("interval") or 1),
            byday=ev.get("byday") or [],
            range_start_date=ev_range.get("start_date"),
            range_until=ev_range.get("until"),
            count=ev.get("count"),
            body_html=params.body_html,
            location=params.location,
            exdates=ev.get("exdates"),
            no_reminder=params.no_reminder,
            reminder_minutes=params.reminder_minutes,
        )
    if ev.get("start") and ev.get("end"):
        return service.create_event(
            calendar_id=params.cal_id,
            calendar_name=params.calendar_name,
            subject=params.subject,
            start_iso=_to_iso_str(ev.get("start")),
            end_iso=_to_iso_str(ev.get("end")),
            tz=params.tz,
            body_html=params.body_html,
            location=params.location,
            no_reminder=params.no_reminder,
            reminder_minutes=params.reminder_minutes,
        )
    return None


def _apply_outlook_events(
    events: list[dict[str, Any]],
    *,
    calendar_name: str | None,
    service: Any,
) -> tuple[int, list[str]]:
    logs: list[str] = []
    cal_id = _ensure_calendar_id(service, calendar_name)
    created = 0
    for ev in events:
        subject = (ev.get("subject") or "").strip()
        if not subject:
            logs.append("Skipping event without subject")
            continue
        no_reminder = ev.get("is_reminder_on") is False
        try:
            params = EventCreateParams(
                cal_id=cal_id,
                calendar_name=calendar_name,
                subject=subject,
                tz=ev.get("tz"),
                body_html=ev.get("body_html"),
                location=ev.get("location"),
                no_reminder=no_reminder,
                reminder_minutes=ev.get("reminder_minutes"),
            )
            r = _create_recurring_or_single(service, ev, params)
            if r is None:
                logs.append(f"Skipping event (insufficient fields): {subject}")
                continue
            created += 1
            eid = r.get("id") if isinstance(r, dict) else None
            logs.append(f"Created: {subject} (id={eid})" if eid else f"Created: {subject}")
        except Exception as exc:
            logs.append(f"Failed to create event '{subject}': {exc}")
            return 2, logs
    logs.append(f"Applied {created} events.")
    return 0, logs
