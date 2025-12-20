from __future__ import annotations

"""Schedule assistant pipeline components."""

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.pipeline import Consumer, Processor, Producer, ResultEnvelope
from core.auth import build_outlook_service
from core.yamlio import dump_config as _dump_yaml, load_config as _load_yaml


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
        assert result.payload is not None
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
        return dt.strftime("%Y-%m-%dT%H:%M")
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
            return v.strftime("%Y-%m-%dT%H:%M:%S")
        if isinstance(v, _dt.date):
            return v.strftime("%Y-%m-%dT00:00:00")
    except Exception:
        pass
    return str(v)


def _weekday_code_to_py(d: str) -> Optional[int]:
    m = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
    return m.get(d.upper())


def _expand_recurring_occurrences(ev: Dict[str, Any], win_from: str, win_to: str) -> List[tuple[str, str]]:
    """Expand recurring event (weekly/daily) to list of (start_iso, end_iso) within window."""
    out: List[tuple[str, str]] = []
    rpt = (ev.get("repeat") or "").strip().lower()
    if rpt not in ("daily", "weekly"):
        return out
    start_time = ev.get("start_time")
    end_time = ev.get("end_time") or start_time
    rng = ev.get("range") or {}
    range_start = rng.get("start_date") or win_from
    range_until = rng.get("until") or win_to
    if not (start_time and end_time and range_start):
        return out
    def _to_date_str(d: Any) -> _dt.date:
        return _dt.date.fromisoformat(str(d))
    def to_dt(d: _dt.date, t: str) -> _dt.datetime:
        hh, mm = (t or "00:00").split(":", 1)
        return _dt.datetime(d.year, d.month, d.day, int(hh), int(mm))
    win_start = _to_date_str(win_from)
    win_end = _to_date_str(win_to)
    cur = max(_to_date_str(range_start), win_start)
    end = min(_to_date_str(range_until), win_end)
    if cur > end:
        return out
    exdates_raw = ev.get("exdates") or []
    ex_set = set()
    try:
        for x in exdates_raw:
            xs = str(x).strip()
            if not xs:
                continue
            ex_set.add(xs.split("T", 1)[0])
    except Exception:
        ex_set = set()
    if rpt == "daily":
        d = cur
        while d <= end:
            if d.isoformat() not in ex_set:
                sdt = to_dt(d, start_time)
                edt = to_dt(d, end_time)
                if edt <= sdt:
                    edt = edt + _dt.timedelta(days=1)
                if (edt - sdt).total_seconds() >= 4 * 3600:
                    edt = sdt + _dt.timedelta(hours=3, minutes=59)
                out.append((sdt.strftime("%Y-%m-%dT%H:%M"), edt.strftime("%Y-%m-%dT%H:%M")))
            d = d + _dt.timedelta(days=1)
        return out
    if rpt == "weekly":
        byday = ev.get("byday") or []
        days_idx = [x for x in (_weekday_code_to_py(d) for d in byday) if x is not None]
        if not days_idx:
            return out
        d = cur
        while d <= end:
            if d.weekday() in days_idx and d.isoformat() not in ex_set:
                sdt = to_dt(d, start_time)
                edt = to_dt(d, end_time)
                if edt <= sdt:
                    edt = edt + _dt.timedelta(days=1)
                if (edt - sdt).total_seconds() >= 4 * 3600:
                    edt = sdt + _dt.timedelta(hours=3, minutes=59)
                out.append((sdt.strftime("%Y-%m-%dT%H:%M"), edt.strftime("%Y-%m-%dT%H:%M")))
            d = d + _dt.timedelta(days=1)
        return out
    return out


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


class VerifyProcessor(Processor[VerifyRequest, ResultEnvelope[VerifyResult]]):
    def process(self, payload: VerifyRequest) -> ResultEnvelope[VerifyResult]:
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
            start_iso = _dt.datetime.fromisoformat(payload.from_date).strftime("%Y-%m-%dT00:00:00")
            end_iso = _dt.datetime.fromisoformat(payload.to_date).strftime("%Y-%m-%dT23:59:59")
        except Exception:
            return ResultEnvelope(
                status="error",
                diagnostics={"message": "Invalid --from/--to date format; expected YYYY-MM-DD", "code": 2},
            )

        svc, err = _build_outlook_service(payload.auth)
        if err:
            return ResultEnvelope(status="error", diagnostics={"message": err, "code": 2})
        try:
            occ = svc.list_events_in_range(
                calendar_name=payload.calendar,
                start_iso=start_iso,
                end_iso=end_iso,
                top=400,
            )
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to list events: {exc}", "code": 2})

        planned_subjects = [((e.get("subject") or "").strip()) for e in events or [] if (e.get("subject") or "").strip()]
        have_subjects = {((o.get("subject") or "").strip().lower()) for o in occ}

        def key_subject_time(subj: str, st: Optional[str], en: Optional[str]) -> str:
            ns = (subj or "").strip().lower()
            ks = _norm_dt_minute(st or "") or ""
            ke = _norm_dt_minute(en or "") or ""
            return f"{ns}|{ks}|{ke}"

        have_st_keys = set()
        for o in occ:
            sub = (o.get("subject") or "").strip()
            st = None
            en = None
            if isinstance(o.get("start"), dict):
                st = (o.get("start") or {}).get("dateTime")
            if isinstance(o.get("end"), dict):
                en = (o.get("end") or {}).get("dateTime")
            have_st_keys.add(key_subject_time(sub, st, en))

        plan_st_keys = set()
        for e in events or []:
            subj = (e.get("subject") or "").strip()
            if not subj:
                continue
            if e.get("start") and e.get("end"):
                plan_st_keys.add(key_subject_time(subj, e.get("start"), e.get("end")))
                continue
            for st, en in _expand_recurring_occurrences(e, payload.from_date, payload.to_date):
                plan_st_keys.add(key_subject_time(subj, st, en))

        lines: List[str] = []
        if payload.match == "subject-time":
            missing_keys = sorted(k for k in plan_st_keys if k not in have_st_keys)
            extra_keys = sorted(k for k in have_st_keys if k not in plan_st_keys)
            lines.append(f"Verified window {payload.from_date} → {payload.to_date} on '{payload.calendar}' (match=subject-time)")
            lines.append(f"Planned occurrences: {len(plan_st_keys)}; Found occurrences: {len(have_st_keys)}")
            if missing_keys:
                lines.append("Missing (subject@time):")
                for k in missing_keys[:20]:
                    lines.append(f"  - {k}")
            else:
                lines.append("Missing: none")
            if extra_keys:
                lines.append(f"Extras not in plan (sample {min(20, len(extra_keys))}/{len(extra_keys)}):")
                for k in extra_keys[:20]:
                    lines.append(f"  - {k}")
            else:
                lines.append("Extras not in plan: none")
            return ResultEnvelope(status="success", payload=VerifyResult(lines=lines))

        missing = [s for s in planned_subjects if s.strip().lower() not in have_subjects]
        extras = [
            ((o.get("subject") or "").strip())
            for o in occ
            if ((o.get("subject") or "").strip().lower()) not in {ps.lower() for ps in planned_subjects}
        ]

        lines.append(f"Verified window {payload.from_date} → {payload.to_date} on '{payload.calendar}'")
        lines.append(f"Planned subjects: {len(planned_subjects)}; Found subjects: {len(have_subjects)}")
        if missing:
            lines.append("Missing (by subject):")
            for s in sorted(set(missing)):
                lines.append(f"  - {s}")
        else:
            lines.append("Missing: none")
        if extras:
            sample = sorted(set(extras))[:10]
            lines.append(f"Extras not in plan (sample {len(sample)}/{len(set(extras))}):")
            for s in sample:
                lines.append(f"  - {s}")
        else:
            lines.append("Extras not in plan: none")
        return ResultEnvelope(status="success", payload=VerifyResult(lines=lines))


class VerifyProducer(Producer[ResultEnvelope[VerifyResult]]):
    def produce(self, result: ResultEnvelope[VerifyResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
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


class SyncProcessor(Processor[SyncRequest, ResultEnvelope[SyncResult]]):
    def process(self, payload: SyncRequest) -> ResultEnvelope[SyncResult]:
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

        match_mode = payload.match or "subject-time"
        plan_st_keys = set()
        series_by_subject: Dict[str, Dict[str, Any]] = {}
        planned_subjects_set = set()
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
                for st, en in _expand_recurring_occurrences(e, payload.from_date, payload.to_date):
                    plan_st_keys.add(f"{subj.strip().lower()}|{_norm_dt_minute(st)}|{_norm_dt_minute(en)}")

        svc, err = _build_outlook_service(payload.auth)
        if err:
            return ResultEnvelope(status="error", diagnostics={"message": err, "code": 2})
        try:
            cal_id = svc.ensure_calendar(payload.calendar)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to resolve calendar: {exc}", "code": 2})

        try:
            start_iso = _dt.datetime.fromisoformat(payload.from_date).strftime("%Y-%m-%dT00:00:00")
            end_iso = _dt.datetime.fromisoformat(payload.to_date).strftime("%Y-%m-%dT23:59:59")
        except Exception:
            return ResultEnvelope(
                status="error",
                diagnostics={"message": "Invalid --from/--to date format; expected YYYY-MM-DD", "code": 2},
            )

        try:
            occ = svc.list_events_in_range(calendar_id=cal_id, start_iso=start_iso, end_iso=end_iso, top=800)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to list events: {exc}", "code": 2})

        have_map: Dict[str, Dict[str, Any]] = {}
        have_keys = set()
        for o in occ:
            sub = (o.get("subject") or "").strip()
            st = (o.get("start") or {}).get("dateTime") if isinstance(o.get("start"), dict) else None
            en = (o.get("end") or {}).get("dateTime") if isinstance(o.get("end"), dict) else None
            k = f"{sub.strip().lower()}|{_norm_dt_minute(st)}|{_norm_dt_minute(en)}"
            have_map[k] = o
            have_keys.add(k)

        to_create_series: List[Dict[str, Any]] = []
        to_create_oneoffs: List[Dict[str, Any]] = []
        missing_occ = [k for k in plan_st_keys if k not in have_keys]
        present_subjects = {(o.get("subject") or "").strip().lower() for o in occ}
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

        extra_keys = [k for k in have_keys if k not in plan_st_keys]
        to_delete_occurrence_ids: List[str] = []
        to_delete_series_master_ids: List[str] = []
        if payload.delete_missing:
            if match_mode == "subject-time":
                for k in extra_keys:
                    o = have_map.get(k) or {}
                    typ = (o.get("type") or "").strip().lower()
                    has_recur = bool(o.get("recurrence"))
                    oid = o.get("id")
                    if oid and (typ in ("singleinstance",) or not has_recur) and not o.get("seriesMasterId"):
                        to_delete_occurrence_ids.append(oid)
                        continue
                    if oid and (typ in ("occurrence", "exception") or o.get("seriesMasterId")):
                        to_delete_occurrence_ids.append(oid)
            else:
                for k, o in have_map.items():
                    subj = (o.get("subject") or "").strip().lower()
                    if subj in planned_subjects_set:
                        continue
                    oid = o.get("id")
                    if oid:
                        to_delete_occurrence_ids.append(oid)

            if payload.delete_unplanned_series:
                series_keys: Dict[str, List[str]] = {}
                series_subject: Dict[str, str] = {}
                for k, o in have_map.items():
                    sid = o.get("seriesMasterId")
                    if sid:
                        series_keys.setdefault(sid, []).append(k)
                        subj = (o.get("subject") or "").strip()
                        if subj:
                            series_subject.setdefault(sid, subj)
                for sid, keys in series_keys.items():
                    subj = (series_subject.get(sid) or "").strip()
                    if subj.strip().lower() in planned_subjects_set:
                        continue
                    if match_mode == "subject-time":
                        if all((k not in plan_st_keys) for k in keys):
                            to_delete_series_master_ids.append(sid)
                    else:
                        to_delete_series_master_ids.append(sid)

        if not payload.apply:
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
            return ResultEnvelope(status="success", payload=SyncResult(lines=lines))

        lines: List[str] = []
        created = 0
        deleted = 0
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

        raw_client = getattr(svc, "client", None)
        if raw_client is None:
            return ResultEnvelope(status="error", diagnostics={"message": "Outlook client unavailable; cannot delete events.", "code": 2})
        if to_delete_occurrence_ids:
            for oid in to_delete_occurrence_ids:
                try:
                    raw_client.delete_event(oid, calendar_id=cal_id)
                    deleted += 1
                except Exception as exc:
                    return ResultEnvelope(status="error", diagnostics={"message": f"Failed deleting event id={oid}: {exc}", "code": 2})
        if payload.delete_unplanned_series and to_delete_series_master_ids:
            for sid in to_delete_series_master_ids:
                try:
                    raw_client.delete_event(sid, calendar_id=cal_id)
                    deleted += 1
                except Exception as exc:
                    return ResultEnvelope(
                        status="error",
                        diagnostics={"message": f"Failed deleting series master id={sid}: {exc}", "code": 2},
                    )
        lines.append(f"Sync complete. Created: {created}; Deleted: {deleted}")
        return ResultEnvelope(status="success", payload=SyncResult(lines=lines))


class SyncProducer(Producer[ResultEnvelope[SyncResult]]):
    def produce(self, result: ResultEnvelope[SyncResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
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

