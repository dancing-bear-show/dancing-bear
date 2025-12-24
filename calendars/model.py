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


def _normalize_byday(v: Any) -> Optional[List[str]]:
    if not v:
        return None
    # Accept ["MO","TU"], or comma/space separated variants, or full names
    days_map = {
        "monday": "MO",
        "mon": "MO",
        "tuesday": "TU",
        "tue": "TU",
        "tues": "TU",
        "wednesday": "WE",
        "wed": "WE",
        "thursday": "TH",
        "thu": "TH",
        "thur": "TH",
        "thurs": "TH",
        "friday": "FR",
        "fri": "FR",
        "saturday": "SA",
        "sat": "SA",
        "sunday": "SU",
        "sun": "SU",
    }
    if isinstance(v, str):
        toks = [t.strip() for t in v.replace(";", ",").replace(" ", ",").split(",") if t.strip()]
    elif isinstance(v, (list, tuple)):
        toks = [str(t).strip() for t in v if str(t).strip()]
    else:
        return None
    out: List[str] = []
    seen = set()
    for t in toks:
        tt = t.upper() if len(t) <= 2 else t.lower()
        code = None
        if len(t) <= 2:
            code = tt
        else:
            code = days_map.get(tt, None)
        code = code or (t[:2].upper() if len(t) > 2 else tt)
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
    interval = ev.get("interval")
    try:
        interval = int(interval) if interval is not None else None
    except Exception:
        interval = None
    byday = _normalize_byday(ev.get("byday") or ev.get("byDay"))

    start_time = _coerce_str(ev.get("start_time") or ev.get("startTime") or ev.get("start-time"))
    end_time = _coerce_str(ev.get("end_time") or ev.get("endTime") or ev.get("end-time"))
    exdates_raw = ev.get("exdates") or ev.get("exceptions")
    exdates: Optional[List[str]] = None
    if isinstance(exdates_raw, (list, tuple)):
        exdates = [str(x).strip() for x in exdates_raw if str(x).strip()]
    elif isinstance(exdates_raw, str) and exdates_raw.strip():
        exdates = [s.strip() for s in exdates_raw.split(",") if s.strip()]

    single_start = _coerce_str(ev.get("start"))
    single_end = _coerce_str(ev.get("end"))

    count = ev.get("count")
    try:
        count = int(count) if count is not None else None
    except Exception:
        count = None

    rng = _normalize_range(ev)

    # Reminder fields
    rem_on_val = ev.get("is_reminder_on") or ev.get("isReminderOn") or ev.get("reminder")
    is_reminder_on: Optional[bool] = None
    if isinstance(rem_on_val, bool):
        is_reminder_on = rem_on_val
    elif isinstance(rem_on_val, str):
        v = rem_on_val.strip().lower()
        if v in ("off", "none", "no", "false", "0"):
            is_reminder_on = False
        elif v in ("on", "yes", "true", "1"):
            is_reminder_on = True
    rem_min_raw = ev.get("reminder_minutes") or ev.get("reminderMinutes") or ev.get("reminder-minutes")
    reminder_minutes: Optional[int] = None
    try:
        reminder_minutes = int(rem_min_raw) if rem_min_raw is not None else None
    except Exception:
        reminder_minutes = None

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
