"""Schedule assistant pipeline components."""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.pipeline import RequestConsumer, SafeProcessor, BaseProducer
from core.auth import build_outlook_service
from core.yamlio import dump_config as _dump_yaml, load_config as _load_yaml
from core.constants import FMT_DAY_START, FMT_DAY_END, FMT_DATETIME, FMT_DATETIME_SEC


def _events_from_source(source: str, kind: Optional[str]) -> List[Dict[str, dict]]:
    from calendars.importer import load_schedule
    from calendars.model import normalize_event

    items = load_schedule(source, kind)
    events: List[Dict[str, dict]] = []
    for it in items:
        ev: Dict[str, dict] = {
            "subject": getattr(it, "subject", None),
            "start": getattr(it, "start_iso", None),
            "end": getattr(it, "end_iso", None),
            "repeat": getattr(it, "recurrence", None),
            "byday": getattr(it, "byday", None),
            "start_time": getattr(it, "start_time", None),
            "end_time": getattr(it, "end_time", None),
            "range": {
                "start_date": getattr(it, "range_start", None),
                "until": getattr(it, "range_until", None),
            },
            "count": getattr(it, "count", None),
            "location": getattr(it, "location", None),
            "body_html": getattr(it, "notes", None),
        }
        rng = ev.get("range") or {}
        if not rng.get("start_date") and not rng.get("until"):
            ev.pop("range", None)
        events.append(normalize_event(ev))
    return events


@dataclass
class PlanRequest:
    sources: List[str]
    kind: Optional[str]
    out_path: Path


# Type alias using generic RequestConsumer from core.pipeline
PlanRequestConsumer = RequestConsumer[PlanRequest]


@dataclass
class PlanResult:
    document: Dict[str, dict]
    out_path: Path


class PlanProcessor(SafeProcessor[PlanRequest, PlanResult]):
    """Generate a plan from schedule sources with automatic error handling."""

    def __init__(self, loader: Callable[[str, Optional[str]], List[Dict[str, dict]]] = _events_from_source) -> None:
        self._loader = loader

    def _process_safe(self, payload: PlanRequest) -> PlanResult:
        all_events: List[Dict[str, dict]] = []
        for src in payload.sources:
            all_events.extend(self._loader(src, payload.kind))
        if not all_events:
            plan = {
                "#": "Add events under the 'events' key. Use subject, repeat/byday or start/end.",
                "events": [],
            }
        else:
            plan = {"events": all_events}
        return PlanResult(document=plan, out_path=payload.out_path)


class PlanProducer(BaseProducer):
    """Produce output for plan generation with automatic error handling."""

    def _produce_success(self, payload: PlanResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        _dump_yaml(str(payload.out_path), payload.document)
        events = payload.document.get("events", [])
        print(f"Wrote plan with {len(events)} events to {payload.out_path}")


@dataclass
class OutlookAuth:
    profile: Optional[str]
    client_id: Optional[str]
    tenant: Optional[str]
    token_path: Optional[str]


def _build_outlook_service(auth: OutlookAuth):
    try:
        return build_outlook_service(
            profile=auth.profile,
            client_id=auth.client_id,
            tenant=auth.tenant,
            token_path=auth.token_path,
        ), None
    except RuntimeError as exc:
        return None, str(exc)
    except Exception as exc:
        return None, f"Outlook provider unavailable: {exc}"


def _load_plan_events(plan_path: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    try:
        data = _load_yaml(str(plan_path)) or {}
        if not isinstance(data, dict):
            raise ValueError("Top-level YAML must be a mapping (dict)")
    except Exception as exc:
        return None, f"Failed to read plan: {exc}"
    events = data.get("events") or []
    if not isinstance(events, list):
        return None, "Invalid plan: 'events' must be a list"
    return events, None


def _norm_dt_minute(s: Optional[str]) -> Optional[str]:
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


def _to_iso_str(v: Any) -> Optional[str]:
    """Best-effort convert date/datetime-like values to ISO string."""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    try:
        if isinstance(v, _dt.datetime):
            return v.strftime(FMT_DATETIME_SEC)
        if isinstance(v, _dt.date):
            return v.strftime(FMT_DAY_START)
    except Exception:  # noqa: S110 - datetime format failure
        pass
    return str(v)


def _weekday_code_to_py(d: str) -> Optional[int]:
    m = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
    return m.get(d.upper())


def _to_date(d: Any) -> _dt.date:
    """Parse a date string to a date object."""
    return _dt.date.fromisoformat(str(d))


def _to_datetime(d: _dt.date, t: str) -> _dt.datetime:
    """Combine a date and time string into a datetime."""
    hh, mm = (t or "00:00").split(":", 1)
    return _dt.datetime(d.year, d.month, d.day, int(hh), int(mm))


def _parse_exdates(exdates_raw: List[Any]) -> set:
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


def _make_occurrence(d: _dt.date, start_time: str, end_time: str) -> Tuple[str, str]:
    """Create a start/end ISO string pair for a single occurrence."""
    sdt = _to_datetime(d, start_time)
    edt = _to_datetime(d, end_time)
    if edt <= sdt:
        edt = edt + _dt.timedelta(days=1)
    if (edt - sdt).total_seconds() >= 4 * 3600:
        edt = sdt + _dt.timedelta(hours=3, minutes=59)
    return (sdt.strftime(FMT_DATETIME), edt.strftime(FMT_DATETIME))


@dataclass
class RecurrenceExpansionConfig:
    """Configuration for expanding recurring event occurrences."""

    start_date: _dt.date
    end_date: _dt.date
    start_time: str
    end_time: str
    excluded_dates: set
    weekdays: Optional[List[int]] = None  # For weekly recurrence


@dataclass
class SyncMatchContext:
    """Context for matching and synchronizing calendar events."""

    plan_st_keys: set  # Planned subject-time keys
    planned_subjects_set: set  # Set of planned subjects (lowercased)
    have_keys: set  # Existing event keys
    have_map: Dict[str, Dict[str, Any]]  # Map of existing events by key
    match_mode: str  # "subject-time" or "subject"


def _expand_daily(
    cur: _dt.date, end: _dt.date, start_time: str, end_time: str, ex_set: set
) -> List[Tuple[str, str]]:
    """Expand daily occurrences within a date range."""
    out: List[Tuple[str, str]] = []
    d = cur
    while d <= end:
        if d.isoformat() not in ex_set:
            out.append(_make_occurrence(d, start_time, end_time))
        d = d + _dt.timedelta(days=1)
    return out


def _expand_weekly(config: RecurrenceExpansionConfig) -> List[Tuple[str, str]]:
    """Expand weekly occurrences within a date range."""
    out: List[Tuple[str, str]] = []
    d = config.start_date
    while d <= config.end_date:
        if config.weekdays and d.weekday() in config.weekdays and d.isoformat() not in config.excluded_dates:
            out.append(_make_occurrence(d, config.start_time, config.end_time))
        d = d + _dt.timedelta(days=1)
    return out


def _expand_recurring_occurrences(ev: Dict[str, Any], win_from: str, win_to: str) -> List[Tuple[str, str]]:
    """Expand recurring event (weekly/daily) to list of (start_iso, end_iso) within window."""
    rpt = (ev.get("repeat") or "").strip().lower()
    if rpt not in ("daily", "weekly"):
        return []

    start_time = ev.get("start_time")
    end_time = ev.get("end_time") or start_time
    rng = ev.get("range") or {}
    range_start = rng.get("start_date") or win_from
    range_until = rng.get("until") or win_to

    if not (start_time and end_time and range_start):
        return []

    win_start = _to_date(win_from)
    win_end = _to_date(win_to)
    cur = max(_to_date(range_start), win_start)
    end = min(_to_date(range_until), win_end)

    if cur > end:
        return []

    ex_set = _parse_exdates(ev.get("exdates") or [])

    if rpt == "daily":
        return _expand_daily(cur, end, start_time, end_time, ex_set)

    if rpt == "weekly":
        byday = ev.get("byday") or []
        days_idx = [x for x in (_weekday_code_to_py(d) for d in byday) if x is not None]
        if not days_idx:
            return []
        config = RecurrenceExpansionConfig(
            start_date=cur,
            end_date=end,
            start_time=start_time,
            end_time=end_time,
            excluded_dates=ex_set,
            weekdays=days_idx,
        )
        return _expand_weekly(config)

    return []


def _apply_outlook_events(
    events: List[Dict[str, Any]],
    *,
    calendar_name: Optional[str],
    service: Any,
) -> Tuple[int, List[str]]:
    logs: List[str] = []
    cal_id = None
    if calendar_name:
        try:
            cal_id = service.ensure_calendar(calendar_name)
        except Exception:
            cal_id = service.get_calendar_id_by_name(calendar_name)

    created = 0
    for ev in events:
        subject = (ev.get("subject") or "").strip()
        if not subject:
            logs.append("Skipping event without subject")
            continue
        tz = ev.get("tz")
        body_html = ev.get("body_html")
        location = ev.get("location")
        no_reminder = False
        if ev.get("is_reminder_on") is False:
            no_reminder = True
        reminder_minutes = ev.get("reminder_minutes")

        try:
            if ev.get("repeat") and ev.get("start_time") and (ev.get("range") or {}).get("start_date"):
                rep = str(ev.get("repeat") or "").lower()
                byday = ev.get("byday") or []
                interval = int(ev.get("interval") or 1)
                r = service.create_recurring_event(
                    calendar_id=cal_id,
                    calendar_name=calendar_name,
                    subject=subject,
                    start_time=ev.get("start_time"),
                    end_time=ev.get("end_time") or ev.get("start_time"),
                    tz=tz,
                    repeat=rep,
                    interval=interval,
                    byday=byday,
                    range_start_date=(ev.get("range") or {}).get("start_date"),
                    range_until=(ev.get("range") or {}).get("until"),
                    count=ev.get("count"),
                    body_html=body_html,
                    location=location,
                    exdates=ev.get("exdates"),
                    no_reminder=no_reminder,
                    reminder_minutes=reminder_minutes,
                )
            elif ev.get("start") and ev.get("end"):
                r = service.create_event(
                    calendar_id=cal_id,
                    calendar_name=calendar_name,
                    subject=subject,
                    start_iso=_to_iso_str(ev.get("start")),
                    end_iso=_to_iso_str(ev.get("end")),
                    tz=tz,
                    body_html=body_html,
                    location=location,
                    no_reminder=no_reminder,
                    reminder_minutes=reminder_minutes,
                )
            else:
                logs.append(f"Skipping event (insufficient fields): {subject}")
                continue
            created += 1
            eid = r.get("id") if isinstance(r, dict) else None
            if eid:
                logs.append(f"Created: {subject} (id={eid})")
            else:
                logs.append(f"Created: {subject}")
        except Exception as exc:
            logs.append(f"Failed to create event '{subject}': {exc}")
            return 2, logs
    logs.append(f"Applied {created} events.")
    return 0, logs


@dataclass
class VerifyRequest:
    plan_path: Path
    calendar: Optional[str]
    from_date: Optional[str]
    to_date: Optional[str]
    match: str
    auth: OutlookAuth


# Type alias using generic RequestConsumer from core.pipeline
VerifyRequestConsumer = RequestConsumer[VerifyRequest]


@dataclass
class VerifyResult:
    lines: List[str]


def _key_subject_time(subj: str, st: Optional[str], en: Optional[str]) -> str:
    """Build a key from subject and start/end times."""
    ns = (subj or "").strip().lower()
    ks = _norm_dt_minute(st or "") or ""
    ke = _norm_dt_minute(en or "") or ""
    return f"{ns}|{ks}|{ke}"


def _build_have_st_keys(occ: List[Dict[str, Any]]) -> set:
    """Build subject-time keys from calendar occurrences."""
    have_st_keys: set = set()
    for o in occ:
        sub = (o.get("subject") or "").strip()
        st = (o.get("start") or {}).get("dateTime") if isinstance(o.get("start"), dict) else None
        en = (o.get("end") or {}).get("dateTime") if isinstance(o.get("end"), dict) else None
        have_st_keys.add(_key_subject_time(sub, st, en))
    return have_st_keys


def _build_plan_st_keys(events: List[Dict[str, Any]], from_date: str, to_date: str) -> set:
    """Build subject-time keys from plan events."""
    plan_st_keys: set = set()
    for e in events or []:
        subj = (e.get("subject") or "").strip()
        if not subj:
            continue
        if e.get("start") and e.get("end"):
            plan_st_keys.add(_key_subject_time(subj, e.get("start"), e.get("end")))
            continue
        for st, en in _expand_recurring_occurrences(e, from_date, to_date):
            plan_st_keys.add(_key_subject_time(subj, st, en))
    return plan_st_keys


def _build_verify_lines_subject_time(
    payload: "VerifyRequest", plan_st_keys: set, have_st_keys: set
) -> List[str]:
    """Build verification output lines for subject-time mode."""
    missing_keys = sorted(k for k in plan_st_keys if k not in have_st_keys)
    extra_keys = sorted(k for k in have_st_keys if k not in plan_st_keys)
    lines = [
        f"Verified window {payload.from_date} → {payload.to_date} on '{payload.calendar}' (match=subject-time)",
        f"Planned occurrences: {len(plan_st_keys)}; Found occurrences: {len(have_st_keys)}",
    ]
    if missing_keys:
        lines.append("Missing (subject@time):")
        lines.extend(f"  - {k}" for k in missing_keys[:20])
    else:
        lines.append("Missing: none")
    if extra_keys:
        lines.append(f"Extras not in plan (sample {min(20, len(extra_keys))}/{len(extra_keys)}):")
        lines.extend(f"  - {k}" for k in extra_keys[:20])
    else:
        lines.append("Extras not in plan: none")
    return lines


def _build_verify_lines_subject(
    payload: "VerifyRequest",
    events: List[Dict[str, Any]],
    occ: List[Dict[str, Any]],
) -> List[str]:
    """Build verification output lines for subject-only mode."""
    planned_subjects = [
        (e.get("subject") or "").strip() for e in events or []
        if (e.get("subject") or "").strip()
    ]
    have_subjects = {(o.get("subject") or "").strip().lower() for o in occ}

    missing = [s for s in planned_subjects if s.strip().lower() not in have_subjects]
    extras = [
        (o.get("subject") or "").strip() for o in occ
        if (o.get("subject") or "").strip().lower() not in {ps.lower() for ps in planned_subjects}
    ]

    lines = [
        f"Verified window {payload.from_date} → {payload.to_date} on '{payload.calendar}'",
        f"Planned subjects: {len(planned_subjects)}; Found subjects: {len(have_subjects)}",
    ]
    if missing:
        lines.append("Missing (by subject):")
        lines.extend(f"  - {s}" for s in sorted(set(missing)))
    else:
        lines.append("Missing: none")
    if extras:
        sample = sorted(set(extras))[:10]
        lines.append(f"Extras not in plan (sample {len(sample)}/{len(set(extras))}):")
        lines.extend(f"  - {s}" for s in sample)
    else:
        lines.append("Extras not in plan: none")
    return lines


class VerifyProcessor(SafeProcessor[VerifyRequest, VerifyResult]):
    """Verify calendar events against a plan with automatic error handling."""

    def _process_safe(self, payload: VerifyRequest) -> VerifyResult:
        # Validate inputs
        events, err = _load_plan_events(payload.plan_path)
        if err:
            raise ValueError(err)
        if not payload.calendar:
            raise ValueError("--calendar is required")
        if not (payload.from_date and payload.to_date):
            raise ValueError("--from and --to are required (YYYY-MM-DD)")
        try:
            start_iso = _dt.datetime.fromisoformat(payload.from_date).strftime(FMT_DAY_START)
            end_iso = _dt.datetime.fromisoformat(payload.to_date).strftime(FMT_DAY_END)
        except Exception:
            raise ValueError("Invalid --from/--to date format; expected YYYY-MM-DD")

        # Fetch calendar events
        svc, err = _build_outlook_service(payload.auth)
        if err:
            raise RuntimeError(err)
        occ = svc.list_events_in_range(
            calendar_name=payload.calendar, start_iso=start_iso, end_iso=end_iso, top=400
        )

        # Build output based on match mode
        if payload.match == "subject-time":
            have_st_keys = _build_have_st_keys(occ)
            plan_st_keys = _build_plan_st_keys(events, payload.from_date, payload.to_date)
            lines = _build_verify_lines_subject_time(payload, plan_st_keys, have_st_keys)
        else:
            lines = _build_verify_lines_subject(payload, events, occ)

        return VerifyResult(lines=lines)


class VerifyProducer(BaseProducer):
    """Produce output for verify operations with automatic error handling."""

    def _produce_success(self, payload: VerifyResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        for line in payload.lines:
            print(line)


@dataclass
class SyncRequest:
    plan_path: Path
    calendar: Optional[str]
    from_date: Optional[str]
    to_date: Optional[str]
    match: str
    delete_missing: bool
    delete_unplanned_series: bool
    apply: bool
    auth: OutlookAuth


# Type alias using generic RequestConsumer from core.pipeline
SyncRequestConsumer = RequestConsumer[SyncRequest]


@dataclass
class SyncResult:
    lines: List[str]


def _build_plan_keys(
    events: List[Dict[str, Any]], from_date: str, to_date: str
) -> Tuple[set, Dict[str, Dict[str, Any]], set]:
    """Build plan keys, series map, and planned subjects from events."""
    plan_st_keys: set = set()
    series_by_subject: Dict[str, Dict[str, Any]] = {}
    planned_subjects_set: set = set()
    for e in events or []:
        subj = (e.get("subject") or "").strip()
        if not subj:
            continue
        planned_subjects_set.add(subj.strip().lower())
        if e.get("start") and e.get("end"):
            plan_st_keys.add(
                f"{subj.strip().lower()}|{_norm_dt_minute(e.get('start'))}|{_norm_dt_minute(e.get('end'))}"
            )
        elif e.get("repeat") and e.get("start_time") and (e.get("range") or {}).get("start_date"):
            series_by_subject.setdefault(subj.strip().lower(), e)
            for st, en in _expand_recurring_occurrences(e, from_date, to_date):
                plan_st_keys.add(f"{subj.strip().lower()}|{_norm_dt_minute(st)}|{_norm_dt_minute(en)}")
    return plan_st_keys, series_by_subject, planned_subjects_set


def _build_have_map(occurrences: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], set]:
    """Build map and keys from existing calendar occurrences."""
    have_map: Dict[str, Dict[str, Any]] = {}
    have_keys: set = set()
    for o in occurrences:
        sub = (o.get("subject") or "").strip()
        st = (o.get("start") or {}).get("dateTime") if isinstance(o.get("start"), dict) else None
        en = (o.get("end") or {}).get("dateTime") if isinstance(o.get("end"), dict) else None
        k = f"{sub.strip().lower()}|{_norm_dt_minute(st)}|{_norm_dt_minute(en)}"
        have_map[k] = o
        have_keys.add(k)
    return have_map, have_keys


def _find_missing_series(
    series_by_subject: Dict[str, Dict[str, Any]], present_subjects: set
) -> List[Dict[str, Any]]:
    """Find series that need to be created (not present in calendar)."""
    return [e for subj, e in series_by_subject.items() if subj not in present_subjects]


def _should_create_oneoff(
    e: Dict[str, Any], match_mode: str, missing_occ: List[str], present_subjects: set
) -> bool:
    """Check if a one-off event should be created."""
    if not (e.get("start") and e.get("end")):
        return False
    subj = (e.get("subject") or "").strip().lower()
    if match_mode == "subject-time":
        k = f"{subj}|{_norm_dt_minute(e.get('start'))}|{_norm_dt_minute(e.get('end'))}"
        return k in missing_occ
    return subj not in present_subjects


def _determine_creates(
    events: List[Dict[str, Any]],
    series_by_subject: Dict[str, Dict[str, Any]],
    present_subjects: set,
    ctx: SyncMatchContext,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Determine which series and one-offs need to be created."""
    to_create_series = _find_missing_series(series_by_subject, present_subjects)
    missing_occ = [k for k in ctx.plan_st_keys if k not in ctx.have_keys]
    to_create_oneoffs = [
        e for e in (events or [])
        if _should_create_oneoff(e, ctx.match_mode, missing_occ, present_subjects)
    ]
    return to_create_series, to_create_oneoffs


def _find_occurrences_to_delete_by_time(
    extra_keys: List[str], have_map: Dict[str, Dict[str, Any]]
) -> List[str]:
    """Find occurrence IDs to delete using subject-time matching."""
    to_delete: List[str] = []
    for k in extra_keys:
        o = have_map.get(k) or {}
        typ = (o.get("type") or "").strip().lower()
        has_recur = bool(o.get("recurrence"))
        oid = o.get("id")
        if oid and (typ in ("singleinstance",) or not has_recur) and not o.get("seriesMasterId"):
            to_delete.append(oid)
            continue
        if oid and (typ in ("occurrence", "exception") or o.get("seriesMasterId")):
            to_delete.append(oid)
    return to_delete


def _find_occurrences_to_delete_by_subject(
    have_map: Dict[str, Dict[str, Any]], planned_subjects_set: set
) -> List[str]:
    """Find occurrence IDs to delete using subject-only matching."""
    to_delete: List[str] = []
    for _k, o in have_map.items():
        subj = (o.get("subject") or "").strip().lower()
        if subj in planned_subjects_set:
            continue
        oid = o.get("id")
        if oid:
            to_delete.append(oid)
    return to_delete


def _build_series_maps(
    have_map: Dict[str, Dict[str, Any]]
) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    """Build series keys and subject mappings from occurrences."""
    series_keys: Dict[str, List[str]] = {}
    series_subject: Dict[str, str] = {}
    for k, o in have_map.items():
        sid = o.get("seriesMasterId")
        if sid:
            series_keys.setdefault(sid, []).append(k)
            subj = (o.get("subject") or "").strip()
            if subj:
                series_subject.setdefault(sid, subj)
    return series_keys, series_subject


def _should_delete_series(
    sid: str,
    keys: List[str],
    series_subject: Dict[str, str],
    ctx: SyncMatchContext,
) -> bool:
    """Check if a series should be deleted."""
    subj = (series_subject.get(sid) or "").strip().lower()
    if subj in ctx.planned_subjects_set:
        return False
    if ctx.match_mode == "subject-time":
        return all(k not in ctx.plan_st_keys for k in keys)
    return True


def _find_series_to_delete(ctx: SyncMatchContext) -> List[str]:
    """Find series master IDs to delete."""
    series_keys, series_subject = _build_series_maps(ctx.have_map)
    return [
        sid for sid, keys in series_keys.items()
        if _should_delete_series(sid, keys, series_subject, ctx)
    ]


def _determine_deletes(
    payload: "SyncRequest",
    ctx: SyncMatchContext,
) -> Tuple[List[str], List[str]]:
    """Determine which occurrences and series masters to delete."""
    if not payload.delete_missing:
        return [], []

    extra_keys = [k for k in ctx.have_keys if k not in ctx.plan_st_keys]
    if ctx.match_mode == "subject-time":
        to_delete_occurrence_ids = _find_occurrences_to_delete_by_time(extra_keys, ctx.have_map)
    else:
        to_delete_occurrence_ids = _find_occurrences_to_delete_by_subject(ctx.have_map, ctx.planned_subjects_set)

    to_delete_series_master_ids: List[str] = []
    if payload.delete_unplanned_series:
        to_delete_series_master_ids = _find_series_to_delete(ctx)

    return to_delete_occurrence_ids, to_delete_series_master_ids


@dataclass
class DryRunConfig:
    """Configuration for building dry-run output."""

    to_create_series: List[Dict[str, Any]]
    to_create_oneoffs: List[Dict[str, Any]]
    to_delete_occurrence_ids: List[str]
    to_delete_series_master_ids: List[str]
    match_mode: str


def _build_dry_run_lines(payload: "SyncRequest", config: DryRunConfig) -> List[str]:
    """Build dry-run output lines."""
    lines = [
        f"[DRY-RUN] Sync window {payload.from_date} → {payload.to_date} on '{payload.calendar}'",
        f"Would create series: {len(config.to_create_series)}",
    ]
    for e in config.to_create_series[:10]:
        lines.append(
            f"  - {e.get('subject')} (repeat={e.get('repeat')}, byday={e.get('byday')}, start_time={e.get('start_time')})"
        )
    lines.append(f"Would create one-offs: {len(config.to_create_oneoffs)}")
    for e in config.to_create_oneoffs[:10]:
        lines.append(f"  - {e.get('subject')} @ {e.get('start')}→{e.get('end')}")
    if payload.delete_missing:
        lines.append(
            f"Would delete extraneous occurrences: {len(config.to_delete_occurrence_ids)} (match={config.match_mode})"
        )
        if payload.delete_unplanned_series:
            lines.append(f"Would delete entire unplanned series: {len(config.to_delete_series_master_ids)}")
    else:
        lines.append("Delete extraneous: disabled (pass --delete-missing)")
    return lines


def _execute_sync_creates(
    svc: Any,
    payload: "SyncRequest",
    to_create_series: List[Dict[str, Any]],
    to_create_oneoffs: List[Dict[str, Any]],
) -> Tuple[List[str], int]:
    """Execute creation of series and one-offs, return lines and count."""
    lines: List[str] = []
    created = 0
    for e in to_create_series:
        rc, logs = _apply_outlook_events([e], calendar_name=payload.calendar, service=svc)
        lines.extend(logs)
        if rc == 0:
            created += 1
    for e in to_create_oneoffs:
        rc, logs = _apply_outlook_events([e], calendar_name=payload.calendar, service=svc)
        lines.extend(logs)
        if rc == 0:
            created += 1
    return lines, created


def _execute_sync_deletes(
    raw_client: Any,
    cal_id: str,
    payload: "SyncRequest",
    to_delete_occurrence_ids: List[str],
    to_delete_series_master_ids: List[str],
) -> int:
    """Execute deletion of occurrences and series, return count."""
    deleted = 0
    for oid in to_delete_occurrence_ids:
        raw_client.delete_event(oid, calendar_id=cal_id)
        deleted += 1
    if payload.delete_unplanned_series and to_delete_series_master_ids:
        for sid in to_delete_series_master_ids:
            raw_client.delete_event(sid, calendar_id=cal_id)
            deleted += 1
    return deleted


class SyncProcessor(SafeProcessor[SyncRequest, SyncResult]):
    """Sync calendar events with a plan with automatic error handling."""

    def _process_safe(self, payload: SyncRequest) -> SyncResult:
        # Validate inputs
        events, err = _load_plan_events(payload.plan_path)
        if err:
            raise ValueError(err)
        if not payload.calendar:
            raise ValueError("--calendar is required")
        if not (payload.from_date and payload.to_date):
            raise ValueError("--from and --to are required (YYYY-MM-DD)")

        # Build plan keys
        match_mode = payload.match or "subject-time"
        plan_st_keys, series_by_subject, planned_subjects_set = _build_plan_keys(
            events, payload.from_date, payload.to_date
        )

        # Connect to Outlook
        svc, err = _build_outlook_service(payload.auth)
        if err:
            raise RuntimeError(err)
        cal_id = svc.ensure_calendar(payload.calendar)

        try:
            start_iso = _dt.datetime.fromisoformat(payload.from_date).strftime(FMT_DAY_START)
            end_iso = _dt.datetime.fromisoformat(payload.to_date).strftime(FMT_DAY_END)
        except Exception:
            raise ValueError("Invalid --from/--to date format; expected YYYY-MM-DD")

        occ = svc.list_events_in_range(calendar_id=cal_id, start_iso=start_iso, end_iso=end_iso, top=800)

        # Build existing calendar state
        have_map, have_keys = _build_have_map(occ)
        present_subjects = {(o.get("subject") or "").strip().lower() for o in occ}

        # Create sync context
        sync_ctx = SyncMatchContext(
            plan_st_keys=plan_st_keys,
            planned_subjects_set=planned_subjects_set,
            have_keys=have_keys,
            have_map=have_map,
            match_mode=match_mode,
        )

        # Determine creates and deletes
        to_create_series, to_create_oneoffs = _determine_creates(
            events, series_by_subject, present_subjects, sync_ctx
        )
        to_delete_occurrence_ids, to_delete_series_master_ids = _determine_deletes(payload, sync_ctx)

        # Dry-run mode
        if not payload.apply:
            dry_run_cfg = DryRunConfig(
                to_create_series=to_create_series,
                to_create_oneoffs=to_create_oneoffs,
                to_delete_occurrence_ids=to_delete_occurrence_ids,
                to_delete_series_master_ids=to_delete_series_master_ids,
                match_mode=match_mode,
            )
            lines = _build_dry_run_lines(payload, dry_run_cfg)
            return SyncResult(lines=lines)

        # Execute creates
        lines, created = _execute_sync_creates(svc, payload, to_create_series, to_create_oneoffs)

        # Execute deletes
        raw_client = getattr(svc, "client", None)
        if raw_client is None:
            raise RuntimeError("Outlook client unavailable; cannot delete events.")

        deleted = _execute_sync_deletes(
            raw_client, cal_id, payload, to_delete_occurrence_ids, to_delete_series_master_ids
        )

        lines.append(f"Sync complete. Created: {created}; Deleted: {deleted}")
        return SyncResult(lines=lines)


class SyncProducer(BaseProducer):
    """Produce output for sync operations with automatic error handling."""

    def _produce_success(self, payload: SyncResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        for line in payload.lines:
            print(line)


@dataclass
class ApplyRequest:
    plan_path: Path
    calendar: Optional[str]
    provider: str
    apply: bool
    auth: OutlookAuth


# Type alias using generic RequestConsumer from core.pipeline
ApplyRequestConsumer = RequestConsumer[ApplyRequest]


@dataclass
class ApplyResult:
    lines: List[str]


class ApplyProcessor(SafeProcessor[ApplyRequest, ApplyResult]):
    """Apply events from a plan to a calendar with automatic error handling."""

    def _process_safe(self, payload: ApplyRequest) -> ApplyResult:
        events, err = _load_plan_events(payload.plan_path)
        if err:
            raise ValueError(err)
        do_apply = bool(payload.apply)
        calendar_name = payload.calendar
        if not do_apply:
            lines = [
                f"[DRY-RUN] Would apply {len(events)} events" + (f" to calendar '{calendar_name}'" if calendar_name else ""),
            ]
            for i, ev in enumerate(events or [], start=1):
                subj = ev.get("subject")
                rep = ev.get("repeat") or "one-off"
                lines.append(f"  - {i}. {subj} ({rep})")
            lines.append("Pass --apply to perform changes.")
            return ApplyResult(lines=lines)

        provider = payload.provider or "outlook"
        lines = [
            f"Applying {len(events)} events" + (f" to calendar '{calendar_name}'" if calendar_name else ""),
            f"Provider: {provider}",
        ]
        if provider != "outlook":
            raise ValueError("Unsupported provider for apply. Use --provider outlook.")

        svc, err = _build_outlook_service(payload.auth)
        if err:
            raise RuntimeError(err)

        rc, logs = _apply_outlook_events(events or [], calendar_name=calendar_name, service=svc)
        lines.extend(logs)
        if rc != 0:
            raise RuntimeError("\n".join(logs))
        return ApplyResult(lines=lines)


class ApplyProducer(BaseProducer):
    """Produce output for apply operations with automatic error handling."""

    def _produce_success(self, payload: ApplyResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        for line in payload.lines:
            print(line)

