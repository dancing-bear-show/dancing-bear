"""Selection helpers for recurring event matching.

Pure functions to compute calendar windows and filter Outlook events
by weekday/time. Dependency-light and easily unit testable.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple
import datetime as _dt

from core.constants import DAY_START_TIME, DAY_END_TIME


def _ymd(d: str) -> str:
    return str(d)[:10]


def compute_window(event: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Compute [start_iso, end_iso] for an event spec.

    Accepts canonical event dict (see model.normalize_event). Returns
    None if insufficient information.
    """
    start = (event.get("start") or "").strip()
    end = (event.get("end") or "").strip()
    if start and end:
        return start, end
    rng = event.get("range") or {}
    s = (rng.get("start_date") or "").strip()
    u = (rng.get("until") or "").strip()
    if s and u:
        return f"{_ymd(s)}{DAY_START_TIME}", f"{_ymd(u)}{DAY_END_TIME}"
    if s:
        return f"{_ymd(s)}{DAY_START_TIME}", f"{_ymd(s)}{DAY_END_TIME}"
    return None


def _weekday_code(dt: _dt.datetime) -> str:
    return ["MO", "TU", "WE", "TH", "FR", "SA", "SU"][dt.weekday()]


def _local_time_hhmm(iso: str) -> str:
    """Extract HH:MM from an ISO datetime, tolerant of Z/offsets.

    Falls back to naive string slicing if parsing fails.
    """
    try:
        dt = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return f"{dt.hour:02d}:{dt.minute:02d}"
    except Exception:
        if "T" not in iso:
            return ""
        return iso.split("T", 1)[1][:5]


def filter_events_by_day_time(
    events: Iterable[Dict[str, Any]],
    *,
    byday: Optional[List[str]] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter Outlook events by weekday and start/end time.

    - byday: list like ["MO", "WE"]. If None/empty, weekday is ignored.
    - start_time/end_time: HH:MM strings. If missing, time is ignored.
    """
    want_days = set([(d or "").lower() for d in (byday or [])])
    out: List[Dict[str, Any]] = []
    for ex in events:
        st = ((ex.get("start") or {}).get("dateTime") or "")
        en = ((ex.get("end") or {}).get("dateTime") or "")
        if not st:
            continue
        tstart = _local_time_hhmm(st)
        tend = _local_time_hhmm(en)
        try:
            dt = _dt.datetime.fromisoformat(st.replace("Z", "+00:00"))
            wcode = _weekday_code(dt)
        except Exception:
            wcode = None
        if want_days and (not wcode or wcode.lower() not in want_days):
            continue
        if start_time and tstart and start_time != tstart:
            continue
        if end_time and tend and end_time != tend:
            continue
        out.append(ex)
    return out
