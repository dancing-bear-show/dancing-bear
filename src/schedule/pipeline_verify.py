"""Verify and sync logic for the schedule pipeline."""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.pipeline import RequestConsumer, BaseProducer, SafeProcessor
from core.auth import build_outlook_service
from core.yamlio import load_config as _load_yaml
from core.constants import FMT_DAY_START, FMT_DAY_END

from schedule.pipeline_expand import _norm_dt_minute, _expand_recurring_occurrences

_ERR_NO_PLAN_EVENTS = "Invalid plan: no events found"


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
    except (ImportError, OSError, ValueError) as exc:  # nosec B110 - surface provider init failures as error tuple
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
        if err or events is None:
            raise ValueError(err or _ERR_NO_PLAN_EVENTS)
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
        from calendars.outlook_service import ListEventsRequest
        occ = svc.list_events_in_range(ListEventsRequest(
            start_iso=start_iso,
            end_iso=end_iso,
            calendar_name=payload.calendar,
            top=400,
        ))

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
