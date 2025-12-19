from __future__ import annotations

"""Schedule Assistant CLI

Follows the LLM patterns used in cars-sre-utils:
- plan then apply (apply requires --apply; default is dry-run)
- small, dependency-light modules with lazy imports
- YAML IO helpers kept minimal and human-friendly

Initial scope: generate a canonical schedule plan from simple sources
(CSV/XLSX/PDF/website via calendar_assistant.importer) and simulate
application (dry-run by default). This provides a stable CLI surface
to extend later with real calendar integrations.
"""

import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional

from personal_core.assistant import BaseAssistant
from personal_core.auth import build_outlook_service
from personal_core.yamlio import dump_config as _dump_yaml, load_config as _load_yaml

from .pipeline import PlanProducer, PlanProcessor, PlanRequest, PlanRequestConsumer


def _read_yaml(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"YAML file not found: {p}")
    data = _load_yaml(str(p)) or {}
    if not isinstance(data, dict):
        raise ValueError("Top-level YAML must be a mapping (dict)")
    return data


def _write_yaml(path: str | Path, data: Dict[str, Any]) -> None:
    p = Path(path)
    _dump_yaml(str(p), data)


assistant = BaseAssistant(
    "schedule_assistant",
    "agentic: schedule_assistant\npurpose: Generate/verify/apply calendar plans (dry-run first)",
)


def _emit_agentic(fmt: str, compact: bool) -> int:
    from .agentic import emit_agentic_context

    return emit_agentic_context(fmt, compact)


def _norm_dt_minute(s: str) -> Optional[str]:
    """Normalize an ISO-like datetime to minute precision without timezone.

    Returns 'YYYY-MM-DDTHH:MM' or None if not parseable.
    """
    if not s:
        return None
    try:
        import datetime as _dt
        # Allow values like '2025-10-01T10:00:00' or with 'Z'
        ss = s.replace("Z", "").replace("z", "").strip()
        # If no 'T' but date only, treat as start of day
        if "T" not in ss:
            ss = ss + "T00:00:00"
        # Try exact seconds; fallback to minutes
        try:
            dt = _dt.datetime.fromisoformat(ss)
        except Exception:
            # Attempt without seconds
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
    """Best-effort convert date/datetime-like values to ISO string.

    - datetime -> 'YYYY-MM-DDTHH:MM:SS'
    - date -> 'YYYY-MM-DDT00:00:00'
    - str -> returned as-is
    - None/empty -> None
    """
    if v is None:
        return None
    if isinstance(v, str):
        return v
    try:
        import datetime as _dt
        if isinstance(v, _dt.datetime):
            return v.strftime("%Y-%m-%dT%H:%M:%S")
        if isinstance(v, _dt.date):
            return v.strftime("%Y-%m-%dT00:00:00")
    except Exception:
        pass
    # Fallback string cast
    return str(v)


def _weekday_code_to_py(d: str) -> Optional[int]:
    m = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
    return m.get(d.upper())


def _expand_recurring_occurrences(ev: Dict[str, Any], win_from: str, win_to: str) -> List[tuple[str, str]]:
    """Expand recurring event (weekly/daily) to list of (start_iso, end_iso) within window.

    Only supports repeat: daily|weekly with start_time/end_time and range.start_date/until.
    """
    out: List[tuple[str, str]] = []
    rpt = (ev.get("repeat") or "").strip().lower()
    if rpt not in ("daily", "weekly"):
        return out
    start_time = ev.get("start_time"); end_time = ev.get("end_time") or start_time
    rng = ev.get("range") or {}
    # Fallback to provided verification window when range is missing
    range_start = rng.get("start_date") or win_from
    range_until = rng.get("until") or win_to
    if not (start_time and end_time and range_start):
        return out
    import datetime as _dt
    def _to_date_str(d: Any) -> _dt.date:
        return _dt.date.fromisoformat(str(d))
    def to_dt(d: _dt.date, t: str) -> _dt.datetime:
        # t is 'HH:MM'
        hh, mm = (t or '00:00').split(':', 1)
        return _dt.datetime(d.year, d.month, d.day, int(hh), int(mm))
    win_start = _to_date_str(win_from)
    win_end = _to_date_str(win_to)
    cur = max(_to_date_str(range_start), win_start)
    end = min(_to_date_str(range_until), win_end)
    if cur > end:
        return out
    # Normalize exdates to set of YYYY-MM-DD strings to exclude
    exdates_raw = ev.get("exdates") or []
    ex_set = set()
    try:
        for x in exdates_raw:
            xs = str(x).strip()
            if not xs:
                continue
            ex_set.add(xs.split('T', 1)[0])
    except Exception:
        ex_set = set()
    if rpt == "daily":
        d = cur
        while d <= end:
            if d.isoformat() not in ex_set:
                sdt = to_dt(d, start_time)
                edt = to_dt(d, end_time)
                # Handle cross-midnight (end earlier than or equal to start)
                if edt <= sdt:
                    edt = edt + _dt.timedelta(days=1)
                # Enforce max duration < 4 hours
                if (edt - sdt).total_seconds() >= 4 * 3600:
                    edt = sdt + _dt.timedelta(hours=3, minutes=59)
                out.append((sdt.strftime('%Y-%m-%dT%H:%M'), edt.strftime('%Y-%m-%dT%H:%M')))
            d = d + _dt.timedelta(days=1)
        return out
    if rpt == "weekly":
        byday = ev.get("byday") or []
        days_idx = [x for x in (_weekday_code_to_py(d) for d in byday) if x is not None]
        if not days_idx:
            return out
        # Start from the first occurrence on/after cur
        d = cur
        while d <= end:
            if d.weekday() in days_idx and d.isoformat() not in ex_set:
                sdt = to_dt(d, start_time)
                edt = to_dt(d, end_time)
                if edt <= sdt:
                    edt = edt + _dt.timedelta(days=1)
                if (edt - sdt).total_seconds() >= 4 * 3600:
                    edt = sdt + _dt.timedelta(hours=3, minutes=59)
                out.append((sdt.strftime('%Y-%m-%dT%H:%M'), edt.strftime('%Y-%m-%dT%H:%M')))
            d = d + _dt.timedelta(days=1)
        return out
    return out


def _cmd_plan(args: argparse.Namespace) -> int:
    out_path = Path(getattr(args, "out", "out/schedule.plan.yaml"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sources = getattr(args, "source", []) or []
    request = PlanRequest(sources=sources, kind=getattr(args, "kind", None), out_path=out_path)
    envelope = PlanProcessor().process(PlanRequestConsumer(request).consume())
    PlanProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def _build_outlook_service_from_args(args: argparse.Namespace):
    """Construct an OutlookService instance via shared auth helpers."""
    try:
        return build_outlook_service(
            profile=getattr(args, "profile", None),
            client_id=getattr(args, "client_id", None),
            tenant=getattr(args, "tenant", None),
            token_path=getattr(args, "token", None),
        )
    except RuntimeError as exc:
        print(str(exc))
        return None
    except Exception as exc:
        print(f"Outlook provider unavailable: {exc}")
        return None


def _apply_outlook(events: List[Dict[str, Any]], *, calendar_name: Optional[str], args: argparse.Namespace) -> int:
    svc = _build_outlook_service_from_args(args)
    if not svc:
        return 2
    cal_id = None
    if calendar_name:
        try:
            cal_id = svc.ensure_calendar(calendar_name)
        except Exception:
            # Best effort: if ensure fails, try resolve by name
            cal_id = svc.get_calendar_id_by_name(calendar_name)

    created = 0
    for ev in events:
        subject = (ev.get("subject") or "").strip()
        if not subject:
            print("Skipping event without subject")
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
                r = svc.create_recurring_event(
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
                r = svc.create_event(
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
                print(f"Skipping event (insufficient fields): {subject}")
                continue
            created += 1
            eid = r.get("id") if isinstance(r, dict) else None
            if eid:
                print(f"Created: {subject} (id={eid})")
            else:
                print(f"Created: {subject}")
        except Exception as e:
            print(f"Failed to create event '{subject}': {e}")
            return 2
    print(f"Applied {created} events.")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    # Subject-only verification over a date range
    plan_path = Path(getattr(args, "plan"))
    try:
        plan = _read_yaml(plan_path)
    except Exception as e:
        print(f"Failed to read plan: {e}")
        return 2
    events = plan.get("events") or []
    if not isinstance(events, list):
        print("Invalid plan: 'events' must be a list")
        return 2
    cal_name = getattr(args, "calendar", None)
    if not cal_name:
        print("--calendar is required")
        return 2
    from_date = getattr(args, "from_date", None)
    to_date = getattr(args, "to_date", None)
    if not (from_date and to_date):
        print("--from and --to are required (YYYY-MM-DD)")
        return 2
    try:
        import datetime as _dt
        start_iso = _dt.datetime.fromisoformat(from_date).strftime("%Y-%m-%dT00:00:00")
        end_iso = _dt.datetime.fromisoformat(to_date).strftime("%Y-%m-%dT23:59:59")
    except Exception:
        print("Invalid --from/--to date format; expected YYYY-MM-DD")
        return 2

    svc = _build_outlook_service_from_args(args)
    if not svc:
        return 2

    # Fetch events in window
    occ = svc.list_events_in_range(calendar_name=cal_name, start_iso=start_iso, end_iso=end_iso, top=400)
    match_mode = getattr(args, "match", "subject")
    planned_subjects = [((e.get("subject") or "").strip()) for e in events if (e.get("subject") or "").strip()]
    have_subjects = {((o.get("subject") or "").strip().lower()) for o in occ}
    # Build time-based maps
    def key_subject_time(subj: str, st: Optional[str], en: Optional[str]) -> str:
        ns = (subj or "").strip().lower()
        ks = _norm_dt_minute(st or "") or ""
        ke = _norm_dt_minute(en or "") or ""
        return f"{ns}|{ks}|{ke}"
    have_st_keys = set()
    for o in occ:
        sub = (o.get("subject") or "").strip()
        st = None; en = None
        if isinstance(o.get("start"), dict):
            st = (o.get("start") or {}).get("dateTime")
        if isinstance(o.get("end"), dict):
            en = (o.get("end") or {}).get("dateTime")
        have_st_keys.add(key_subject_time(sub, st, en))
    plan_st_keys = set()
    for e in events:
        subj = (e.get("subject") or "").strip()
        if not subj:
            continue
        # One-off
        if e.get("start") and e.get("end"):
            plan_st_keys.add(key_subject_time(subj, e.get("start"), e.get("end")))
            continue
        # Recurring: expand occurrences in window
        for st, en in _expand_recurring_occurrences(e, from_date, to_date):
            plan_st_keys.add(key_subject_time(subj, st, en))

    if match_mode == "subject-time":
        missing_keys = sorted(k for k in plan_st_keys if k not in have_st_keys)
        extra_keys = sorted(k for k in have_st_keys if k not in plan_st_keys)
        print(f"Verified window {from_date} → {to_date} on '{cal_name}' (match=subject-time)")
        print(f"Planned occurrences: {len(plan_st_keys)}; Found occurrences: {len(have_st_keys)}")
        if missing_keys:
            print("Missing (subject@time):")
            for k in missing_keys[:20]:
                print(f"  - {k}")
        else:
            print("Missing: none")
        if extra_keys:
            print(f"Extras not in plan (sample {min(20,len(extra_keys))}/{len(extra_keys)}):")
            for k in extra_keys[:20]:
                print(f"  - {k}")
        else:
            print("Extras not in plan: none")
        return 0

    # Default: subject-only
    missing = [s for s in planned_subjects if s.strip().lower() not in have_subjects]
    extras = [((o.get("subject") or "").strip()) for o in occ if ((o.get("subject") or "").strip().lower()) not in {ps.lower() for ps in planned_subjects}]

    print(f"Verified window {from_date} → {to_date} on '{cal_name}'")
    print(f"Planned subjects: {len(planned_subjects)}; Found subjects: {len(have_subjects)}")
    if missing:
        print("Missing (by subject):")
        for s in sorted(set(missing)):
            print(f"  - {s}")
    else:
        print("Missing: none")
    # Show a small sample of extras to spot-check
    if extras:
        sample = sorted(set(extras))[:10]
        print(f"Extras not in plan (sample {len(sample)}/{len(set(extras))}):")
        for s in sample:
            print(f"  - {s}")
    else:
        print("Extras not in plan: none")
    return 0

def _cmd_sync(args: argparse.Namespace) -> int:
    # Load plan
    plan_path = Path(getattr(args, "plan"))
    try:
        plan = _read_yaml(plan_path)
    except Exception as e:
        print(f"Failed to read plan: {e}")
        return 2
    events = plan.get("events") or []
    if not isinstance(events, list):
        print("Invalid plan: 'events' must be a list")
        return 2
    cal_name = getattr(args, "calendar", None)
    if not cal_name:
        print("--calendar is required")
        return 2
    from_date = getattr(args, "from_date", None)
    to_date = getattr(args, "to_date", None)
    if not (from_date and to_date):
        print("--from and --to are required (YYYY-MM-DD)")
        return 2

    # Build planned subject@time keys and representative series map
    match_mode = getattr(args, "match", "subject-time")
    plan_st_keys = set()
    series_by_subject: Dict[str, Dict[str, Any]] = {}
    planned_subjects_set = set()
    for e in events:
        subj = (e.get("subject") or "").strip()
        if not subj:
            continue
        planned_subjects_set.add(subj.strip().lower())
        if e.get("start") and e.get("end"):
            plan_st_keys.add(f"{subj.strip().lower()}|{_norm_dt_minute(e.get('start'))}|{_norm_dt_minute(e.get('end'))}")
        elif e.get("repeat") and e.get("start_time") and (e.get("range") or {}).get("start_date"):
            # keep a representative series for creation, but expand occurrences for matching
            series_by_subject.setdefault(subj.strip().lower(), e)
            for st, en in _expand_recurring_occurrences(e, from_date, to_date):
                plan_st_keys.add(f"{subj.strip().lower()}|{_norm_dt_minute(st)}|{_norm_dt_minute(en)}")

    # Connect to Outlook via shared factory
    svc = _build_outlook_service_from_args(args)
    if not svc:
        return 2
    cal_id = svc.ensure_calendar(cal_name)

    # Fetch occurrences in window
    import datetime as _dt
    start_iso = _dt.datetime.fromisoformat(from_date).strftime("%Y-%m-%dT00:00:00")
    end_iso = _dt.datetime.fromisoformat(to_date).strftime("%Y-%m-%dT23:59:59")
    occ = svc.list_events_in_range(calendar_id=cal_id, start_iso=start_iso, end_iso=end_iso, top=800)
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
    # Missing keys: planned occurrences not present
    missing_occ = [k for k in plan_st_keys if k not in have_keys]
    # Heuristic: if a recurring series subject exists anywhere in window, consider present
    present_subjects = { (o.get("subject") or "").strip().lower() for o in occ }
    for subj, e in series_by_subject.items():
        if subj not in present_subjects:
            to_create_series.append(e)
    # For one-offs specifically missing
    for e in events:
        subj = (e.get("subject") or "").strip().lower()
        if e.get("start") and e.get("end"):
            if match_mode == "subject-time":
                k = f"{subj}|{_norm_dt_minute(e.get('start'))}|{_norm_dt_minute(e.get('end'))}"
                if k in missing_occ:
                    to_create_oneoffs.append(e)
            else:  # subject-only
                if subj not in present_subjects:
                    to_create_oneoffs.append(e)

    # Extras: keys present but not planned
    extra_keys = [k for k in have_keys if k not in plan_st_keys]
    # Delete policy
    to_delete_occurrence_ids: List[str] = []
    to_delete_series_master_ids: List[str] = []
    if bool(getattr(args, "delete_missing", False)):
        if match_mode == "subject-time":
            # Classify extras: one-offs vs occurrences by exact key
            for k in extra_keys:
                o = have_map.get(k) or {}
                typ = (o.get("type") or "").strip().lower()
                has_recur = bool(o.get("recurrence"))
                oid = o.get("id")
                # Delete single-instance one-offs immediately
                if oid and (typ in ("singleinstance",) or not has_recur) and not o.get("seriesMasterId"):
                    to_delete_occurrence_ids.append(oid)
                    continue
                # Delete recurring occurrences within window
                if oid and (typ in ("occurrence", "exception") or o.get("seriesMasterId")):
                    to_delete_occurrence_ids.append(oid)
        else:
            # Delete by subject-only: remove items whose subject is not in plan
            for k, o in have_map.items():
                subj = (o.get("subject") or "").strip().lower()
                if subj in planned_subjects_set:
                    continue
                oid = o.get("id")
                if oid:
                    to_delete_occurrence_ids.append(oid)

        # Optionally delete entire series if fully out of plan in this window
        if bool(getattr(args, "delete_unplanned_series", False)):
            # Build map seriesMasterId -> list of its occurrence keys in window
            series_keys: Dict[str, List[str]] = {}
            series_subject: Dict[str, str] = {}
            for k, o in have_map.items():
                sid = o.get("seriesMasterId")
                if sid:
                    series_keys.setdefault(sid, []).append(k)
                    subj = (o.get("subject") or "").strip()
                    if subj:
                        series_subject.setdefault(sid, subj)
            # Planned subjects set available
            for sid, keys in series_keys.items():
                subj = (series_subject.get(sid) or "").strip()
                # Only consider deleting when the subject has no planned entries (avoid accidental series deletion)
                if subj.strip().lower() in planned_subjects_set:
                    continue
                if match_mode == "subject-time":
                    # Fully out of plan in this window: none of its occurrence keys are planned
                    if all((k not in plan_st_keys) for k in keys):
                        to_delete_series_master_ids.append(sid)
                else:
                    # Subject-only: if subject not in plan, delete series
                    to_delete_series_master_ids.append(sid)

    dry_run = not bool(getattr(args, "apply", False))
    if dry_run:
        print(f"[DRY-RUN] Sync window {from_date} → {to_date} on '{cal_name}'")
        print(f"Would create series: {len(to_create_series)}")
        for e in to_create_series[:10]:
            print(f"  - {e.get('subject')} (repeat={e.get('repeat')}, byday={e.get('byday')}, start_time={e.get('start_time')})")
        print(f"Would create one-offs: {len(to_create_oneoffs)}")
        for e in to_create_oneoffs[:10]:
            print(f"  - {e.get('subject')} @ {e.get('start')}→{e.get('end')}")
        if bool(getattr(args, "delete_missing", False)):
            print(f"Would delete extraneous occurrences: {len(to_delete_occurrence_ids)} (match={match_mode})")
            if bool(getattr(args, "delete_unplanned_series", False)):
                print(f"Would delete entire unplanned series: {len(to_delete_series_master_ids)}")
        else:
            print("Delete extraneous: disabled (pass --delete-missing)")
        return 0

    # Apply changes
    created = 0; deleted = 0
    # Create series
    for e in to_create_series:
        try:
            r = _apply_outlook([e], calendar_name=cal_name, args=args)
            if r == 0:
                created += 1
        except Exception as ex:
            print(f"Failed creating series {e.get('subject')}: {ex}")
            return 2
    # Create one-offs
    for e in to_create_oneoffs:
        try:
            r = _apply_outlook([e], calendar_name=cal_name, args=args)
            if r == 0:
                created += 1
        except Exception as ex:
            print(f"Failed creating event {e.get('subject')}: {ex}")
            return 2
    # Delete extras
    # Delete extra occurrences
    raw_client = getattr(svc, "client", None)
    if raw_client is None:
        print("Outlook client unavailable; cannot delete events.")
        return 2
    if to_delete_occurrence_ids:
        for oid in to_delete_occurrence_ids:
            try:
                raw_client.delete_event(oid, calendar_id=cal_id)
                deleted += 1
            except Exception as ex:
                print(f"Failed deleting event id={oid}: {ex}")
                return 2
    # Delete unplanned series masters
    if bool(getattr(args, "delete_unplanned_series", False)) and to_delete_series_master_ids:
        for sid in to_delete_series_master_ids:
            try:
                raw_client.delete_event(sid, calendar_id=cal_id)
                deleted += 1
            except Exception as ex:
                print(f"Failed deleting series master id={sid}: {ex}")
                return 2
    print(f"Sync complete. Created: {created}; Deleted: {deleted}")
    return 0

def _cmd_export(args: argparse.Namespace) -> int:
    import datetime as _dt
    svc = _build_outlook_service_from_args(args)
    if not svc:
        return 2
    cal_name = getattr(args, 'calendar', None)
    if not cal_name:
        print("--calendar is required")
        return 2
    try:
        start_iso = _dt.datetime.fromisoformat(args.from_date).strftime("%Y-%m-%dT00:00:00")
        end_iso = _dt.datetime.fromisoformat(args.to_date).strftime("%Y-%m-%dT23:59:59")
    except Exception:
        print("Invalid --from/--to date format; expected YYYY-MM-DD")
        return 2
    try:
        evs = svc.list_events_in_range(calendar_name=cal_name, start_iso=start_iso, end_iso=end_iso, top=800)
    except Exception as e:
        print(f"Failed to list events: {e}")
        return 3
    rows: List[Dict[str, Any]] = []
    for ev in evs:
        sub = (ev.get('subject') or '').strip()
        st = ((ev.get('start') or {}).get('dateTime') or '').strip()
        en = ((ev.get('end') or {}).get('dateTime') or '').strip()
        loc = (ev.get('location') or {}).get('displayName') or ''
        if not sub or not st or not en:
            continue
        rows.append({'calendar': cal_name, 'subject': sub, 'start': st, 'end': en, 'location': loc})
    # Sort by start ascending for readability
    def _key(ev: Dict[str, Any]) -> str:
        return ev.get('start', '')
    rows.sort(key=_key)
    out_path = Path(getattr(args, 'out'))
    _write_yaml(out_path, {'events': rows})
    print(f"Exported {len(rows)} events from '{cal_name}' to {out_path}")
    print("Note: export writes occurrences as one-offs for backup. Use verify/sync to manage plan application.")
    return 0

def _cmd_compress(args: argparse.Namespace) -> int:
    inp = Path(getattr(args, 'in_path'))
    if not inp.exists():
        print(f"Input not found: {inp}")
        return 2
    data = _read_yaml(inp)
    items = data.get('events') or []
    if not isinstance(items, list):
        print("Invalid input: events must be a list")
        return 2
    # Separate one-offs and ignore existing series entries
    one_offs: List[Dict[str, Any]] = []
    for ev in items:
        if ev.get('start') and ev.get('end'):
            one_offs.append(ev)
    if not one_offs:
        print("No one-off events found to compress.")
        return 0
    # Group by (subject, start_time, end_time, weekday-code, location)
    import datetime as _dt
    def iso_to_date(iso: Any) -> _dt.date:
        s = str(iso).replace('Z','').strip()
        if 'T' in s:
            s = s.split('T', 1)[0]
        elif ' ' in s:
            s = s.split(' ', 1)[0]
        return _dt.date.fromisoformat(s)
    def iso_to_time(iso: Any) -> str:
        s = str(iso).replace('Z','').strip()
        t = s
        if 'T' in s:
            t = s.split('T',1)[1]
        elif ' ' in s:
            t = s.split(' ',1)[1]
        # Extract HH:MM prefix
        return t[:5]
    def weekday_code(d: _dt.date) -> str:
        return ['MO','TU','WE','TH','FR','SA','SU'][d.weekday()]

    groups: Dict[tuple, List[_dt.date]] = {}
    meta: Dict[tuple, Dict[str, Any]] = {}
    for ev in one_offs:
        subj = (ev.get('subject') or '').strip()
        st = str(ev.get('start') or '')
        en = str(ev.get('end') or '')
        if not subj or not st or not en:
            continue
        d = iso_to_date(st)
        st_time = iso_to_time(st)
        en_time = iso_to_time(en)
        dow = weekday_code(d)
        loc = (ev.get('location') or '').strip()
        cal = ev.get('calendar')
        key = (subj, st_time, en_time, dow, loc)
        groups.setdefault(key, []).append(d)
        if key not in meta:
            meta[key] = {'calendar': cal, 'subject': subj, 'location': loc}

    min_occur = max(1, int(getattr(args, 'min_occur', 2)))
    out_events: List[Dict[str, Any]] = []
    # Build series for groups with >= min_occur, else keep as one-offs
    for key, dates in groups.items():
        subj, st_time, en_time, dow, loc = key
        dates_sorted = sorted(set(dates))
        if len(dates_sorted) < min_occur:
            # Re-emit as one-offs
            for d in dates_sorted:
                start_iso = f"{d.isoformat()}T{st_time}"
                end_iso = f"{d.isoformat()}T{en_time}"
                ev = {'subject': subj, 'start': start_iso, 'end': end_iso}
                if loc:
                    ev['location'] = loc
                cal = getattr(args, 'calendar', None) or meta[key].get('calendar')
                if cal:
                    ev['calendar'] = cal
                out_events.append(ev)
            continue
        # Compute range and exdates (weekly cadence for this weekday)
        start_date = dates_sorted[0]
        end_date = dates_sorted[-1]
        exdates: List[str] = []
        cur = start_date
        while cur <= end_date:
            if cur not in dates_sorted:
                exdates.append(cur.isoformat())
            cur = cur + _dt.timedelta(days=7)
        ev: Dict[str, Any] = {
            'subject': subj,
            'repeat': 'weekly',
            'byday': [dow],
            'start_time': st_time,
            'end_time': en_time,
            'range': {'start_date': start_date.isoformat(), 'until': end_date.isoformat()},
        }
        if loc:
            ev['location'] = loc
        if exdates:
            ev['exdates'] = exdates
        cal = getattr(args, 'calendar', None) or meta[key].get('calendar')
        if cal:
            ev['calendar'] = cal
        out_events.append(ev)

    # Sort by subject, weekday, start_date
    def sort_key(e: Dict[str, Any]) -> tuple:
        subj = (e.get('subject') or '')
        if e.get('repeat'):
            dow = (e.get('byday') or [''])[0]
            sd = ((e.get('range') or {}).get('start_date') or '')
            tm = e.get('start_time') or ''
            return (subj, dow, sd, tm)
        # one-off
        st = e.get('start') or ''
        return (subj, '', st, '')
    out_events.sort(key=sort_key)

    _write_yaml(Path(getattr(args, 'out')), {'events': out_events})
    print(f"Compressed {sum(len(v) for v in groups.values())} one-offs into {len(out_events)} entries → {getattr(args, 'out')}")
    return 0

def _cmd_apply(args: argparse.Namespace) -> int:
    plan_path = Path(getattr(args, "plan", getattr(args, "config", "")))
    if not plan_path:
        print("Missing --plan PATH")
        return 2
    try:
        plan = _read_yaml(plan_path)
    except Exception as e:
        print(f"Failed to read plan: {e}")
        return 2
    events = plan.get("events") or []
    if not isinstance(events, list):
        print("Invalid plan: 'events' must be a list")
        return 2
    do_apply = bool(getattr(args, "apply", False))
    dry_run = not do_apply
    provider = getattr(args, "provider", None) or "outlook"
    calendar_name = getattr(args, "calendar", None)

    # Dry-run summary
    if dry_run:
        print(f"[DRY-RUN] Would apply {len(events)} events" + (f" to calendar '{calendar_name}'" if calendar_name else ""))
        for i, ev in enumerate(events, start=1):
            subj = ev.get("subject")
            rep = ev.get("repeat") or "one-off"
            print(f"  - {i}. {subj} ({rep})")
        print("Pass --apply to perform changes.")
        return 0

    # Apply path: for now, print a clear placeholder and exit 0.
    # Future: integrate with calendar_assistant or mail_assistant OutlookClient.
    print(f"Applying {len(events)} events" + (f" to calendar '{calendar_name}'" if calendar_name else ""))
    if provider:
        print(f"Provider: {provider}")
    if provider == "outlook":
        return _apply_outlook(events, calendar_name=calendar_name, args=args)
    print("Unsupported provider for apply. Use --provider outlook.")
    return 2


def build_parser() -> argparse.ArgumentParser:
    epilog = (
        "Examples:\n"
        "  schedule-assistant plan --source schedules/classes.csv --out out/schedule.plan.yaml\n"
        "  schedule-assistant apply --plan out/schedule.plan.yaml --dry-run\n"
        "  schedule-assistant apply --plan out/schedule.plan.yaml --apply --calendar 'Your Family'\n"
    )
    p = argparse.ArgumentParser(
        description="Schedule Assistant CLI",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    assistant.add_agentic_flags(p)
    sub = p.add_subparsers(dest="cmd", required=False)

    sp = sub.add_parser("plan", help="Generate a canonical schedule plan from sources")
    sp.add_argument("--source", action="append", default=[], help="Source path/URL (repeatable); supports CSV/XLSX/PDF/website")
    sp.add_argument("--kind", choices=["auto", "csv", "xlsx", "pdf", "website"], default="auto", help="Force parser kind (default auto)")
    sp.add_argument("--out", default="out/schedule.plan.yaml", help="Output YAML path (default out/schedule.plan.yaml)")
    sp.set_defaults(func=_cmd_plan)

    sa = sub.add_parser("apply", help="Apply a schedule plan (dry-run by default)")
    sa.add_argument("--plan", "--config", dest="plan", help="Plan YAML path")
    sa.add_argument("--calendar", help="Target calendar name (optional)")
    sa.add_argument("--provider", choices=["outlook", "gmail"], help="Provider (default outlook)")
    sa.add_argument("--apply", action="store_true", help="Perform changes (omit for dry-run)")
    # Outlook auth/profile (file-first)
    sa.add_argument("--profile", help="Credentials profile (e.g., outlook_personal)")
    sa.add_argument("--client-id", help="Azure app (client) ID; defaults from profile or env")
    sa.add_argument("--tenant", help="Azure tenant (default consumers if not set)")
    sa.add_argument("--token", help="Path to Outlook token cache (defaults from profile)")
    sa.set_defaults(func=_cmd_apply)

    sv = sub.add_parser("verify", help="Verify a schedule plan against Outlook calendar within a window")
    sv.add_argument("--plan", required=True, help="Plan YAML path")
    sv.add_argument("--calendar", required=True, help="Target calendar name")
    sv.add_argument("--from", dest="from_date", required=True, help="Start date (YYYY-MM-DD)")
    sv.add_argument("--to", dest="to_date", required=True, help="End date (YYYY-MM-DD)")
    sv.add_argument("--match", choices=["subject", "subject-time"], default="subject", help="Verification mode (default subject)")
    sv.add_argument("--profile", help="Credentials profile (e.g., outlook_personal)")
    sv.add_argument("--client-id", help="Azure app (client) ID; defaults from profile or env")
    sv.add_argument("--tenant", help="Azure tenant (default consumers if not set)")
    sv.add_argument("--token", help="Path to Outlook token cache (defaults from profile)")
    sv.set_defaults(func=_cmd_verify)

    sy = sub.add_parser("sync", help="Create missing items from plan; optionally delete extraneous one-offs (dry-run by default)")
    sy.add_argument("--plan", required=True, help="Plan YAML path")
    sy.add_argument("--calendar", required=True, help="Target calendar name")
    sy.add_argument("--from", dest="from_date", required=True, help="Start date (YYYY-MM-DD)")
    sy.add_argument("--to", dest="to_date", required=True, help="End date (YYYY-MM-DD)")
    sy.add_argument("--match", choices=["subject", "subject-time"], default="subject-time", help="Matching mode for sync (default subject-time)")
    sy.add_argument("--delete-missing", action="store_true", help="Delete calendar items not present in plan (respects --match)")
    sy.add_argument("--delete-unplanned-series", action="store_true", help="Also delete entire recurring series with no matching occurrences in window")
    sy.add_argument("--apply", action="store_true", help="Perform changes (omit for dry-run)")
    sy.add_argument("--profile", help="Credentials profile (e.g., outlook_personal)")
    sy.add_argument("--client-id", help="Azure app (client) ID; defaults from profile or env")
    sy.add_argument("--tenant", help="Azure tenant (default consumers if not set)")
    sy.add_argument("--token", help="Path to Outlook token cache (defaults from profile)")
    sy.set_defaults(func=_cmd_sync)

    ex = sub.add_parser("export", help="Export Outlook calendar events to a plan YAML (one-offs for backup)")
    ex.add_argument("--calendar", required=True, help="Outlook calendar name (e.g., 'Activities')")
    ex.add_argument("--from", dest="from_date", required=True, help="Start date YYYY-MM-DD")
    ex.add_argument("--to", dest="to_date", required=True, help="End date YYYY-MM-DD")
    ex.add_argument("--out", required=True, help="Output YAML path (e.g., config/calendar/activities.yaml)")
    ex.add_argument("--profile", help="Credentials profile (e.g., outlook_personal)")
    ex.add_argument("--client-id", help="Azure app (client) ID; defaults from profile or env")
    ex.add_argument("--tenant", help="Azure tenant (default consumers if not set)")
    ex.add_argument("--token", help="Path to Outlook token cache (defaults from profile)")
    ex.set_defaults(func=_cmd_export)

    cp = sub.add_parser("compress", help="Infer recurring weekly series from one-off plan events")
    cp.add_argument("--in", dest="in_path", required=True, help="Input plan YAML with one-offs (events: [])")
    cp.add_argument("--out", required=True, help="Output compressed plan YAML")
    cp.add_argument("--calendar", help="Calendar name to set on series (optional)")
    cp.add_argument("--min-occur", type=int, default=2, help="Minimum occurrences to form a series (default 2)")
    cp.set_defaults(func=_cmd_compress)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    agentic_result = assistant.maybe_emit_agentic(args, emit_func=_emit_agentic)
    if agentic_result is not None:
        return int(agentic_result)
    func = getattr(args, "func", None)
    if not func:
        parser.print_help()
        return 0
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
