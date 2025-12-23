"""Schedule assistant pipeline components."""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.pipeline import Consumer, Processor, Producer, ResultEnvelope
from core.auth import build_outlook_service
from core.yamlio import dump_config as _dump_yaml, load_config as _load_yaml

# Date/time format constants
_FMT_DATETIME = "%Y-%m-%dT%H:%M"
_FMT_DATETIME_SEC = "%Y-%m-%dT%H:%M:%S"
_FMT_DAY_START = "%Y-%m-%dT00:00:00"
_FMT_DAY_END = "%Y-%m-%dT23:59:59"


def _events_from_source(source: str, kind: Optional[str]) -> List[Dict[str, dict]]:
    from calendar_assistant.importer import load_schedule
    from calendar_assistant.model import normalize_event

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


class PlanRequestConsumer(Consumer[PlanRequest]):
    def __init__(self, request: PlanRequest) -> None:
        self._request = request

    def consume(self) -> PlanRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class PlanResult:
    document: Dict[str, dict]
    out_path: Path


class PlanProcessor(Processor[PlanRequest, ResultEnvelope[PlanResult]]):
    def __init__(self, loader: Callable[[str, Optional[str]], List[Dict[str, dict]]] = _events_from_source) -> None:
        self._loader = loader

    def process(self, payload: PlanRequest) -> ResultEnvelope[PlanResult]:
        all_events: List[Dict[str, dict]] = []
        for src in payload.sources:
            try:
                all_events.extend(self._loader(src, payload.kind))
            except Exception as exc:
                return ResultEnvelope(
                    status="error",
                    diagnostics={"message": f"Error loading source {src}: {exc}", "code": 2},
                )
        if not all_events:
            plan = {
                "#": "Add events under the 'events' key. Use subject, repeat/byday or start/end.",
                "events": [],
            }
        else:
            plan = {"events": all_events}
        return ResultEnvelope(status="success", payload=PlanResult(document=plan, out_path=payload.out_path))


class PlanProducer(Producer[ResultEnvelope[PlanResult]]):
    def produce(self, result: ResultEnvelope[PlanResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        if result.payload is None:
            return
        _dump_yaml(str(result.payload.out_path), result.payload.document)
        events = result.payload.document.get("events", [])
        print(f"Wrote plan with {len(events)} events to {result.payload.out_path}")


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
        return dt.strftime(_FMT_DATETIME)
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
            return v.strftime(_FMT_DATETIME_SEC)
        if isinstance(v, _dt.date):
            return v.strftime(_FMT_DAY_START)
    except Exception:
        pass  # nosec B110 - datetime format failure
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
    return (sdt.strftime(_FMT_DATETIME), edt.strftime(_FMT_DATETIME))


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


def _expand_weekly(
    cur: _dt.date, end: _dt.date, start_time: str, end_time: str, ex_set: set, days_idx: List[int]
) -> List[Tuple[str, str]]:
    """Expand weekly occurrences within a date range."""
    out: List[Tuple[str, str]] = []
    d = cur
    while d <= end:
        if d.weekday() in days_idx and d.isoformat() not in ex_set:
            out.append(_make_occurrence(d, start_time, end_time))
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
        return _expand_weekly(cur, end, start_time, end_time, ex_set, days_idx)

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


class VerifyRequestConsumer(Consumer[VerifyRequest]):
    def __init__(self, request: VerifyRequest) -> None:
        self._request = request

    def consume(self) -> VerifyRequest:  # pragma: no cover - trivial
        return self._request


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


class VerifyProcessor(Processor[VerifyRequest, ResultEnvelope[VerifyResult]]):
    def process(self, payload: VerifyRequest) -> ResultEnvelope[VerifyResult]:
        # Validate inputs
        events, err = _load_plan_events(payload.plan_path)
        if err:
            return ResultEnvelope(status="error", diagnostics={"message": err, "code": 2})
        if not payload.calendar:
            return ResultEnvelope(status="error", diagnostics={"message": "--calendar is required", "code": 2})
        if not (payload.from_date and payload.to_date):
            return ResultEnvelope(
                status="error",
                diagnostics={"message": "--from and --to are required (YYYY-MM-DD)", "code": 2},
            )
        try:
            start_iso = _dt.datetime.fromisoformat(payload.from_date).strftime(_FMT_DAY_START)
            end_iso = _dt.datetime.fromisoformat(payload.to_date).strftime(_FMT_DAY_END)
        except Exception:
            return ResultEnvelope(
                status="error",
                diagnostics={"message": "Invalid --from/--to date format; expected YYYY-MM-DD", "code": 2},
            )

        # Fetch calendar events
        svc, err = _build_outlook_service(payload.auth)
        if err:
            return ResultEnvelope(status="error", diagnostics={"message": err, "code": 2})
        try:
            occ = svc.list_events_in_range(
                calendar_name=payload.calendar, start_iso=start_iso, end_iso=end_iso, top=400
            )
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to list events: {exc}", "code": 2})

        # Build output based on match mode
        if payload.match == "subject-time":
            have_st_keys = _build_have_st_keys(occ)
            plan_st_keys = _build_plan_st_keys(events, payload.from_date, payload.to_date)
            lines = _build_verify_lines_subject_time(payload, plan_st_keys, have_st_keys)
        else:
            lines = _build_verify_lines_subject(payload, events, occ)

        return ResultEnvelope(status="success", payload=VerifyResult(lines=lines))


class VerifyProducer(Producer[ResultEnvelope[VerifyResult]]):
    def produce(self, result: ResultEnvelope[VerifyResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        if result.payload is None:
            return
        for line in result.payload.lines:
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


class SyncRequestConsumer(Consumer[SyncRequest]):
    def __init__(self, request: SyncRequest) -> None:
        self._request = request

    def consume(self) -> SyncRequest:  # pragma: no cover - trivial
        return self._request


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


def _determine_creates(
    events: List[Dict[str, Any]],
    series_by_subject: Dict[str, Dict[str, Any]],
    present_subjects: set,
    plan_st_keys: set,
    have_keys: set,
    match_mode: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Determine which series and one-offs need to be created."""
    to_create_series: List[Dict[str, Any]] = []
    to_create_oneoffs: List[Dict[str, Any]] = []
    missing_occ = [k for k in plan_st_keys if k not in have_keys]
    for subj, e in series_by_subject.items():
        if subj not in present_subjects:
            to_create_series.append(e)
    for e in events or []:
        subj = (e.get("subject") or "").strip().lower()
        if e.get("start") and e.get("end"):
            if match_mode == "subject-time":
                k = f"{subj}|{_norm_dt_minute(e.get('start'))}|{_norm_dt_minute(e.get('end'))}"
                if k in missing_occ:
                    to_create_oneoffs.append(e)
            else:
                if subj not in present_subjects:
                    to_create_oneoffs.append(e)
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
    sid: str, keys: List[str], series_subject: Dict[str, str],
    plan_st_keys: set, planned_subjects_set: set, match_mode: str
) -> bool:
    """Check if a series should be deleted."""
    subj = (series_subject.get(sid) or "").strip().lower()
    if subj in planned_subjects_set:
        return False
    if match_mode == "subject-time":
        return all(k not in plan_st_keys for k in keys)
    return True


def _find_series_to_delete(
    have_map: Dict[str, Dict[str, Any]],
    plan_st_keys: set,
    planned_subjects_set: set,
    match_mode: str,
) -> List[str]:
    """Find series master IDs to delete."""
    series_keys, series_subject = _build_series_maps(have_map)
    return [
        sid for sid, keys in series_keys.items()
        if _should_delete_series(sid, keys, series_subject, plan_st_keys, planned_subjects_set, match_mode)
    ]


def _determine_deletes(
    payload: "SyncRequest",
    have_map: Dict[str, Dict[str, Any]],
    have_keys: set,
    plan_st_keys: set,
    planned_subjects_set: set,
    match_mode: str,
) -> Tuple[List[str], List[str]]:
    """Determine which occurrences and series masters to delete."""
    if not payload.delete_missing:
        return [], []

    extra_keys = [k for k in have_keys if k not in plan_st_keys]
    if match_mode == "subject-time":
        to_delete_occurrence_ids = _find_occurrences_to_delete_by_time(extra_keys, have_map)
    else:
        to_delete_occurrence_ids = _find_occurrences_to_delete_by_subject(have_map, planned_subjects_set)

    to_delete_series_master_ids: List[str] = []
    if payload.delete_unplanned_series:
        to_delete_series_master_ids = _find_series_to_delete(
            have_map, plan_st_keys, planned_subjects_set, match_mode
        )

    return to_delete_occurrence_ids, to_delete_series_master_ids


def _build_dry_run_lines(
    payload: "SyncRequest",
    to_create_series: List[Dict[str, Any]],
    to_create_oneoffs: List[Dict[str, Any]],
    to_delete_occurrence_ids: List[str],
    to_delete_series_master_ids: List[str],
    match_mode: str,
) -> List[str]:
    """Build dry-run output lines."""
    lines = [
        f"[DRY-RUN] Sync window {payload.from_date} → {payload.to_date} on '{payload.calendar}'",
        f"Would create series: {len(to_create_series)}",
    ]
    for e in to_create_series[:10]:
        lines.append(
            f"  - {e.get('subject')} (repeat={e.get('repeat')}, byday={e.get('byday')}, start_time={e.get('start_time')})"
        )
    lines.append(f"Would create one-offs: {len(to_create_oneoffs)}")
    for e in to_create_oneoffs[:10]:
        lines.append(f"  - {e.get('subject')} @ {e.get('start')}→{e.get('end')}")
    if payload.delete_missing:
        lines.append(
            f"Would delete extraneous occurrences: {len(to_delete_occurrence_ids)} (match={match_mode})"
        )
        if payload.delete_unplanned_series:
            lines.append(f"Would delete entire unplanned series: {len(to_delete_series_master_ids)}")
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
) -> Tuple[int, Optional[ResultEnvelope[SyncResult]]]:
    """Execute deletion of occurrences and series, return count and optional error."""
    deleted = 0
    for oid in to_delete_occurrence_ids:
        try:
            raw_client.delete_event(oid, calendar_id=cal_id)
            deleted += 1
        except Exception as exc:
            return deleted, ResultEnvelope(
                status="error", diagnostics={"message": f"Failed deleting event id={oid}: {exc}", "code": 2}
            )
    if payload.delete_unplanned_series and to_delete_series_master_ids:
        for sid in to_delete_series_master_ids:
            try:
                raw_client.delete_event(sid, calendar_id=cal_id)
                deleted += 1
            except Exception as exc:
                return deleted, ResultEnvelope(
                    status="error",
                    diagnostics={"message": f"Failed deleting series master id={sid}: {exc}", "code": 2},
                )
    return deleted, None


class SyncProcessor(Processor[SyncRequest, ResultEnvelope[SyncResult]]):
    def process(self, payload: SyncRequest) -> ResultEnvelope[SyncResult]:
        # Validate inputs
        events, err = _load_plan_events(payload.plan_path)
        if err:
            return ResultEnvelope(status="error", diagnostics={"message": err, "code": 2})
        if not payload.calendar:
            return ResultEnvelope(status="error", diagnostics={"message": "--calendar is required", "code": 2})
        if not (payload.from_date and payload.to_date):
            return ResultEnvelope(
                status="error",
                diagnostics={"message": "--from and --to are required (YYYY-MM-DD)", "code": 2},
            )

        # Build plan keys
        match_mode = payload.match or "subject-time"
        plan_st_keys, series_by_subject, planned_subjects_set = _build_plan_keys(
            events, payload.from_date, payload.to_date
        )

        # Connect to Outlook
        svc, err = _build_outlook_service(payload.auth)
        if err:
            return ResultEnvelope(status="error", diagnostics={"message": err, "code": 2})
        try:
            cal_id = svc.ensure_calendar(payload.calendar)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to resolve calendar: {exc}", "code": 2})

        try:
            start_iso = _dt.datetime.fromisoformat(payload.from_date).strftime(_FMT_DAY_START)
            end_iso = _dt.datetime.fromisoformat(payload.to_date).strftime(_FMT_DAY_END)
        except Exception:
            return ResultEnvelope(
                status="error",
                diagnostics={"message": "Invalid --from/--to date format; expected YYYY-MM-DD", "code": 2},
            )

        try:
            occ = svc.list_events_in_range(calendar_id=cal_id, start_iso=start_iso, end_iso=end_iso, top=800)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to list events: {exc}", "code": 2})

        # Build existing calendar state
        have_map, have_keys = _build_have_map(occ)
        present_subjects = {(o.get("subject") or "").strip().lower() for o in occ}

        # Determine creates and deletes
        to_create_series, to_create_oneoffs = _determine_creates(
            events, series_by_subject, present_subjects, plan_st_keys, have_keys, match_mode
        )
        to_delete_occurrence_ids, to_delete_series_master_ids = _determine_deletes(
            payload, have_map, have_keys, plan_st_keys, planned_subjects_set, match_mode
        )

        # Dry-run mode
        if not payload.apply:
            lines = _build_dry_run_lines(
                payload, to_create_series, to_create_oneoffs,
                to_delete_occurrence_ids, to_delete_series_master_ids, match_mode
            )
            return ResultEnvelope(status="success", payload=SyncResult(lines=lines))

        # Execute creates
        lines, created = _execute_sync_creates(svc, payload, to_create_series, to_create_oneoffs)

        # Execute deletes
        raw_client = getattr(svc, "client", None)
        if raw_client is None:
            return ResultEnvelope(status="error", diagnostics={"message": "Outlook client unavailable; cannot delete events.", "code": 2})

        deleted, error_env = _execute_sync_deletes(
            raw_client, cal_id, payload, to_delete_occurrence_ids, to_delete_series_master_ids
        )
        if error_env:
            return error_env

        lines.append(f"Sync complete. Created: {created}; Deleted: {deleted}")
        return ResultEnvelope(status="success", payload=SyncResult(lines=lines))


class SyncProducer(Producer[ResultEnvelope[SyncResult]]):
    def produce(self, result: ResultEnvelope[SyncResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        if result.payload is None:
            return
        for line in result.payload.lines:
            print(line)


@dataclass
class ApplyRequest:
    plan_path: Path
    calendar: Optional[str]
    provider: str
    apply: bool
    auth: OutlookAuth


class ApplyRequestConsumer(Consumer[ApplyRequest]):
    def __init__(self, request: ApplyRequest) -> None:
        self._request = request

    def consume(self) -> ApplyRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class ApplyResult:
    lines: List[str]


class ApplyProcessor(Processor[ApplyRequest, ResultEnvelope[ApplyResult]]):
    def process(self, payload: ApplyRequest) -> ResultEnvelope[ApplyResult]:
        events, err = _load_plan_events(payload.plan_path)
        if err:
            return ResultEnvelope(status="error", diagnostics={"message": err, "code": 2})
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
            return ResultEnvelope(status="success", payload=ApplyResult(lines=lines))

        provider = payload.provider or "outlook"
        lines = [
            f"Applying {len(events)} events" + (f" to calendar '{calendar_name}'" if calendar_name else ""),
            f"Provider: {provider}",
        ]
        if provider != "outlook":
            lines.append("Unsupported provider for apply. Use --provider outlook.")
            return ResultEnvelope(status="error", payload=ApplyResult(lines=lines), diagnostics={"code": 2})

        svc, err = _build_outlook_service(payload.auth)
        if err:
            lines.append(err)
            return ResultEnvelope(status="error", payload=ApplyResult(lines=lines), diagnostics={"code": 2})

        rc, logs = _apply_outlook_events(events or [], calendar_name=calendar_name, service=svc)
        lines.extend(logs)
        if rc != 0:
            return ResultEnvelope(status="error", payload=ApplyResult(lines=lines), diagnostics={"code": 2})
        return ResultEnvelope(status="success", payload=ApplyResult(lines=lines))


class ApplyProducer(Producer[ResultEnvelope[ApplyResult]]):
    def produce(self, result: ResultEnvelope[ApplyResult]) -> None:
        payload = result.payload
        if payload is not None:
            for line in payload.lines:
                print(line)
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)

