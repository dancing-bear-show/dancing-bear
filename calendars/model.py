"""Event plan normalization utilities.

Helpers to coerce loose, human-authored YAML/dicts into a canonical event
shape used by Outlook operations. Keep dependency-light and focused.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _coerce_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _tok_to_day_code(t: str, day_map: dict) -> str:
    """Convert a day token (full name or 2-letter code) to a 2-letter code."""
    if len(t) <= 2:
        return t.upper()
    code = day_map.get(t.lower())
    return code or t[:2].upper()


def _normalize_byday(v: Any) -> Optional[List[str]]:
    if not v:
        return None
    # Accept ["MO","TU"], or comma/space separated variants, or full names
    from .constants import DAY_MAP

    if isinstance(v, str):
        toks = [t.strip() for t in v.replace(";", ",").replace(" ", ",").split(",") if t.strip()]
    elif isinstance(v, (list, tuple)):
        toks = [str(t).strip() for t in v if str(t).strip()]
    else:
        return None
    out: List[str] = []
    seen = set()
    for t in toks:
        code = _tok_to_day_code(t, DAY_MAP)
        if code not in seen:
            out.append(code)
            seen.add(code)
    return out or None


def _normalize_range(ev: Dict[str, Any]) -> Optional[Dict[str, str]]:
    r = ev.get("range") or {}
    start_date = _coerce_str(r.get("start_date") or r.get("startDate")) or _coerce_str(
        ev.get("start_date") or ev.get("startDate")
    )
    until = (
        _coerce_str(r.get("until") or r.get("end_date") or r.get("endDate"))
        or _coerce_str(ev.get("until") or ev.get("end_date") or ev.get("endDate"))
    )
    if not (start_date or until):
        return None
    out: Dict[str, str] = {}
    if start_date:
        out["start_date"] = start_date
    if until:
        out["until"] = until
    return out or None


def _coerce_int(v: Any) -> Optional[int]:
    """Coerce a value to int, returning None on failure."""
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


def _normalize_exdates(raw: Any) -> Optional[List[str]]:
    """Normalize exdates from list/tuple or comma-separated string."""
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()] or None
    if isinstance(raw, str) and raw.strip():
        return [s.strip() for s in raw.split(",") if s.strip()] or None
    return None


def _normalize_reminder_on(v: Any) -> Optional[bool]:
    """Coerce reminder on/off value to bool or None."""
    if isinstance(v, bool):
        return v
    if not isinstance(v, str):
        return None
    s = v.strip().lower()
    if s in ("off", "none", "no", "false", "0"):
        return False
    if s in ("on", "yes", "true", "1"):
        return True
    return None


def normalize_event(ev: Dict[str, Any]) -> Dict[str, Any]:
    """Return a canonical event dict for plan/application.

    Canonical keys:
      - subject: str (required by most flows)
      - calendar: Optional[str]
      - tz: Optional[str]
      - location: Optional[str]
      - body_html: Optional[str]
      - repeat: Optional[str] ('daily'|'weekly'|'monthly')
      - interval: Optional[int]
      - byday: Optional[List[str]]  # e.g., ['MO','WE']
      - range: Optional[{'start_date': 'YYYY-MM-DD', 'until': 'YYYY-MM-DD'}]
      - start_time: Optional[str]   # 'HH:MM' for recurring
      - end_time: Optional[str]     # 'HH:MM' for recurring
      - exdates: Optional[List[str]]
      - start: Optional[str]        # ISO for single events
      - end: Optional[str]
      - count: Optional[int]
    Accepts legacy aliases and returns canonical names.
    """
    subject = _coerce_str(ev.get("subject"))
    calendar = _coerce_str(ev.get("calendar"))
    tz = _coerce_str(ev.get("tz"))
    location = _coerce_str(ev.get("location"))
    body_html = _coerce_str(ev.get("body_html") or ev.get("bodyHtml"))

    repeat = _coerce_str(ev.get("repeat"))
    interval = _coerce_int(ev.get("interval"))
    byday = _normalize_byday(ev.get("byday") or ev.get("byDay"))

    start_time = _coerce_str(ev.get("start_time") or ev.get("startTime") or ev.get("start-time"))
    end_time = _coerce_str(ev.get("end_time") or ev.get("endTime") or ev.get("end-time"))
    exdates = _normalize_exdates(ev.get("exdates") or ev.get("exceptions"))
    single_start = _coerce_str(ev.get("start"))
    single_end = _coerce_str(ev.get("end"))
    count = _coerce_int(ev.get("count"))
    rng = _normalize_range(ev)

    rem_on_val = ev.get("is_reminder_on") or ev.get("isReminderOn") or ev.get("reminder")
    is_reminder_on = _normalize_reminder_on(rem_on_val)
    reminder_minutes = _coerce_int(ev.get("reminder_minutes") or ev.get("reminderMinutes") or ev.get("reminder-minutes"))

    out: Dict[str, Any] = {
        "subject": subject,
        "calendar": calendar,
        "tz": tz,
        "location": location,
        "body_html": body_html,
        "repeat": repeat,
        "interval": interval,
        "byday": byday,
        "range": rng,
        "start_time": start_time,
        "end_time": end_time,
        "exdates": exdates,
        "start": single_start,
        "end": single_end,
        "count": count,
        "is_reminder_on": is_reminder_on,
        "reminder_minutes": reminder_minutes,
    }

    # Drop Nones to keep YAML clean when re-serializing
    return {k: v for k, v in out.items() if v is not None}
