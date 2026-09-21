"""Selection helpers for recurring event matching.

Pure functions to compute calendar windows and filter Outlook events
by weekday/time. Dependency-light and easily unit testable.
"""
from __future__ import annotations

from typing import Any, Iterable
import datetime as _dt

from core.constants import DAY_START_TIME, DAY_END_TIME

#: Zone used to interpret plan wall-clock times when the caller names none.
#: Matches the export pipeline's ``_TZ_FALLBACK``.
DEFAULT_PLAN_TZ = "America/Toronto"

#: Minimum span, in days, for an open-ended recurring window. Four weeks yields
#: at least two occurrences of every weekday even for a bi-weekly series.
_OPEN_ENDED_MIN_DAYS = 28

#: Ceiling on an open-ended window so an implausible ``interval`` cannot ask
#: Graph for an unbounded range.
_OPEN_ENDED_MAX_DAYS = 120


def _ymd(d: str) -> str:
    return str(d)[:10]


def _open_ended_span_days(event: dict[str, Any]) -> int:
    """Days to search forward for an open-ended recurring series.

    Sized to contain at least two occurrences of every weekday in ``byday``:
    two ``interval`` cycles plus a week of slack, so a series whose first
    occurrence lands later than ``start_date`` is still found. Clamped to
    [_OPEN_ENDED_MIN_DAYS, _OPEN_ENDED_MAX_DAYS].
    """
    try:
        interval = int(event.get("interval") or 1)
    except (TypeError, ValueError):
        interval = 1
    interval = max(1, interval)
    span = interval * 14 + 7
    return max(_OPEN_ENDED_MIN_DAYS, min(span, _OPEN_ENDED_MAX_DAYS))


def compute_window(event: dict[str, Any]) -> tuple[str, str] | None:
    """Compute [start_iso, end_iso] for an event spec.

    Accepts canonical event dict (see model.normalize_event). Returns
    None if insufficient information.

    An open-ended recurring series (``range.start_date`` with no ``until``,
    and a non-empty ``byday``) gets a multi-week window rather than a single
    day. A one-day window can only ever contain the weekday of ``start_date``,
    so a series recurring on any other weekday -- the normal case for an
    ongoing enrollment -- would return no occurrences and be reported as
    missing even though it exists.

    A non-recurring event keeps the single-day window: it has exactly one
    occurrence, on ``start_date``, and widening would only cost API time.
    """
    start = (event.get("start") or "").strip()
    end = (event.get("end") or "").strip()
    if start and end:
        return start, end
    rng = event.get("range") or {}
    s = (rng.get("start_date") or "").strip()
    u = (rng.get("until") or "").strip()
    if s and u:
        # Explicit end date: already wide enough, and widening costs API time.
        return f"{_ymd(s)}{DAY_START_TIME}", f"{_ymd(u)}{DAY_END_TIME}"
    if not s:
        return None
    if not (event.get("byday") or []):
        # Non-recurring (or no weekday info): one occurrence, on start_date.
        return f"{_ymd(s)}{DAY_START_TIME}", f"{_ymd(s)}{DAY_END_TIME}"
    try:
        start_date = _dt.date.fromisoformat(_ymd(s))
    except ValueError:
        # Unparseable date: fall back to the original single-day behaviour
        # rather than raising on a malformed plan entry.
        return f"{_ymd(s)}{DAY_START_TIME}", f"{_ymd(s)}{DAY_END_TIME}"
    until = start_date + _dt.timedelta(days=_open_ended_span_days(event))
    return f"{_ymd(s)}{DAY_START_TIME}", f"{until.isoformat()}{DAY_END_TIME}"


def weekday_code(dt: _dt.datetime, *, upper: bool = False) -> str:
    """Return 2-letter weekday code (mo/tu/we/th/fr/sa/su) for a datetime.

    Args:
        dt: datetime object.
        upper: If True, return uppercase (MO/TU/...). Default is lowercase.
    """
    code = ["mo", "tu", "we", "th", "fr", "sa", "su"][dt.weekday()]
    return code.upper() if upper else code


def _load_zone(tz_name: str | None) -> _dt.tzinfo | None:
    """Resolve an IANA zone name to a tzinfo, or None if unusable.

    Graph may report a Windows zone name ("Eastern Standard Time"), which
    ``zoneinfo`` cannot load. Returning None lets callers fall back to the
    event's own UTC offset rather than raising.
    """
    if not tz_name or not tz_name.strip():
        return None
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz_name.strip())
    except Exception:  # nosec B110 - unknown/Windows zone name; caller falls back
        return None


def _parse_dt(iso: str) -> _dt.datetime | None:
    """Parse an ISO datetime, tolerating a trailing Z, or None if unparseable.

    Graph emits seven fractional digits ("...T14:30:00.0000000"). On the Python
    floor this project targets (3.11) ``fromisoformat`` accepts that form
    directly, with or without a trailing offset, so no fraction-trimming
    fallback is needed.

    Deliberately not shared with ``core.date_utils.parse_iso_utc``, which
    overlaps this closely but converts its result to UTC. Callers here need the
    instant in its *original* offset so ``_as_local`` can express it in a target
    zone; a value already collapsed to UTC has lost that distinction.
    """
    raw = (iso or "").strip()
    if not raw:
        return None
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        return _dt.datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _as_local(
    iso: str, graph_tz: str | None, target: _dt.tzinfo | None
) -> _dt.datetime | None:
    """Return the event instant expressed in ``target``, or None if unparseable.

    Resolution order for the source zone:
      1. an explicit offset already in ``iso`` (e.g. ``-05:00``),
      2. ``graph_tz`` when it is a loadable IANA name,
      3. treat the value as already-local wall clock (no conversion).

    A naive datetime that cannot be anchored is returned unconverted, so callers
    still compare wall clock to wall clock: mixing naive and aware values never
    raises here.
    """
    dt = _parse_dt(iso)
    if dt is None:
        return None
    if dt.tzinfo is None:
        source = _load_zone(graph_tz)
        if source is None:
            # No offset and no loadable zone: treat the string as wall clock.
            return dt
        dt = dt.replace(tzinfo=source)
    if target is None:
        return dt
    return dt.astimezone(target)


def _hhmm(dt: _dt.datetime | None) -> str:
    """Render HH:MM for a datetime, or "" when absent."""
    return "" if dt is None else f"{dt.hour:02d}:{dt.minute:02d}"


def _event_matches_filters(
    start_dt: _dt.datetime | None,
    end_dt: _dt.datetime | None,
    want_days: set,
    start_time: str | None,
    end_time: str | None,
) -> bool:
    """Return True if an event's times/weekday match the given filters.

    Both datetimes must already be normalised to the comparison zone by the
    caller; this function performs no conversion of its own.
    """
    wcode = weekday_code(start_dt, upper=True) if start_dt is not None else None
    if want_days and (not wcode or wcode.lower() not in want_days):
        return False
    tstart = _hhmm(start_dt)
    tend = _hhmm(end_dt)
    if start_time and tstart and start_time != tstart:
        return False
    if end_time and tend and end_time != tend:
        return False
    return True


def filter_events_by_day_time(
    events: Iterable[dict[str, Any]],
    *,
    byday: list[str] | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    tz: str | None = None,
) -> list[dict[str, Any]]:
    """Filter Outlook events by weekday and start/end time.

    - byday: list like ["MO", "WE"]. If None/empty, weekday is ignored.
    - start_time/end_time: HH:MM strings interpreted in ``tz``. If missing,
      the corresponding time is ignored.
    - tz: IANA zone the filter times are expressed in; defaults to
      ``DEFAULT_PLAN_TZ``.

    Graph's ``calendarView`` returns times in UTC unless a ``Prefer:
    outlook.timezone`` header asks otherwise, while plan files carry local wall
    clock. Each occurrence is therefore converted to ``tz`` before comparison,
    which is DST-correct because the conversion runs per occurrence rather than
    against a single fixed offset.
    """
    want_days = {(d or "").lower() for d in (byday or [])}
    target = _load_zone(tz or DEFAULT_PLAN_TZ)
    out: list[dict[str, Any]] = []
    for ex in events:
        start_block = ex.get("start") or {}
        end_block = ex.get("end") or {}
        st = start_block.get("dateTime") or ""
        if not st:
            continue
        start_dt = _as_local(st, start_block.get("timeZone"), target)
        end_dt = _as_local(
            end_block.get("dateTime") or "", end_block.get("timeZone"), target
        )
        if _event_matches_filters(start_dt, end_dt, want_days, start_time, end_time):
            out.append(ex)
    return out
