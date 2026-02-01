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


def _parse_day_tokens(v: Any) -> Optional[List[str]]:
    """Parse day value into list of token strings."""
    if isinstance(v, str):
        return [t.strip() for t in v.replace(";", ",").replace(" ", ",").split(",") if t.strip()]
    if isinstance(v, (list, tuple)):
        return [str(t).strip() for t in v if str(t).strip()]
    return None


def _normalize_day_code(token: str) -> str:
    """Normalize a single day token to 2-char code."""
    from .constants import DAY_MAP
    if len(token) <= 2:
        return token.upper()
    code = DAY_MAP.get(token.lower(), None)
    return code or token[:2].upper()


def _normalize_byday(v: Any) -> Optional[List[str]]:
    if not v:
        return None
    toks = _parse_day_tokens(v)
    if not toks:
        return None
    out: List[str] = []
    seen = set()
    for t in toks:
        code = _normalize_day_code(t)
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
    """Safely convert value to int."""
    try:
        return int(v) if v is not None else None
    except Exception:
        return None


def _normalize_exdates(raw: Any) -> Optional[List[str]]:
    """Normalize exdates from various formats."""
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        return [s.strip() for s in raw.split(",") if s.strip()]
    return None


def _normalize_reminder_on(val: Any) -> Optional[bool]:
    """Normalize reminder on/off value."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("off", "none", "no", "false", "0"):
            return False
        if v in ("on", "yes", "true", "1"):
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
    out: Dict[str, Any] = {
        "subject": _coerce_str(ev.get("subject")),
        "calendar": _coerce_str(ev.get("calendar")),
        "tz": _coerce_str(ev.get("tz")),
        "location": _coerce_str(ev.get("location")),
        "body_html": _coerce_str(ev.get("body_html") or ev.get("bodyHtml")),
        "repeat": _coerce_str(ev.get("repeat")),
        "interval": _coerce_int(ev.get("interval")),
        "byday": _normalize_byday(ev.get("byday") or ev.get("byDay")),
        "start_time": _coerce_str(ev.get("start_time") or ev.get("startTime") or ev.get("start-time")),
        "end_time": _coerce_str(ev.get("end_time") or ev.get("endTime") or ev.get("end-time")),
        "exdates": _normalize_exdates(ev.get("exdates") or ev.get("exceptions")),
        "start": _coerce_str(ev.get("start")),
        "end": _coerce_str(ev.get("end")),
        "count": _coerce_int(ev.get("count")),
        "range": _normalize_range(ev),
        "is_reminder_on": _normalize_reminder_on(ev.get("is_reminder_on") or ev.get("isReminderOn") or ev.get("reminder")),
        "reminder_minutes": _coerce_int(ev.get("reminder_minutes") or ev.get("reminderMinutes") or ev.get("reminder-minutes")),
    }

    # Drop Nones to keep YAML clean when re-serializing
    return {k: v for k, v in out.items() if v is not None}
