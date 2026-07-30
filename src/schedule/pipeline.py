"""Schedule assistant pipeline components."""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.pipeline import RequestConsumer, SafeProcessor, BaseProducer
from core.yamlio import dump_config as _dump_yaml
from core.constants import FMT_DAY_START, FMT_DAY_END

from core.date_utils import to_iso_str as _to_iso_str  # noqa: F401

from schedule.pipeline_expand import (  # noqa: F401
    EventCreateParams,
    RecurrenceExpansionConfig,
    SyncMatchContext,
    _apply_outlook_events,
    _calculate_expansion_window,
    _create_recurring_or_single,
    _ensure_calendar_id,
    _expand_daily,
    _expand_recurring_occurrences,
    _expand_weekly,
    _expand_weekly_occurrences,
    _extract_event_times,
    _make_occurrence,
    _norm_dt_minute,
    _parse_exdates,
    _to_date,
    _to_datetime,
    _weekday_code_to_py,
)
from schedule.pipeline_verify import (  # noqa: F401
    OutlookAuth,
    SyncRequest,
    SyncRequestConsumer,
    SyncResult,
    VerifyRequest,
    VerifyRequestConsumer,
    VerifyResult,
    VerifyProducer,
    VerifyProcessor,
    _ERR_NO_PLAN_EVENTS,
    _build_have_map,
    _build_have_st_keys,
    _build_outlook_service,
    _build_plan_keys,
    _build_plan_st_keys,
    _build_verify_lines_subject,
    _build_verify_lines_subject_time,
    _find_missing_series,
    _key_subject_time,
    _load_plan_events,
)
from core.auth import build_outlook_service  # noqa: F401


def _events_from_source(source: str, kind: Optional[str]) -> List[Dict[str, Any]]:
    from calendars.importer import load_schedule
    from calendars.model import normalize_event

    items = load_schedule(source, kind)
    events: List[Dict[str, Any]] = []
    for it in items:
        ev: Dict[str, Any] = {
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
    document: Dict[str, Any]
    out_path: Path


class PlanProcessor(SafeProcessor[PlanRequest, PlanResult]):
    """Generate a plan from schedule sources with automatic error handling."""

    def __init__(self, loader: Callable[[str, Optional[str]], List[Dict[str, Any]]] = _events_from_source) -> None:
        self._loader = loader

    def _process_safe(self, payload: PlanRequest) -> PlanResult:
        all_events: List[Dict[str, Any]] = []
        for src in payload.sources:
            all_events.extend(self._loader(src, payload.kind))
        plan: Dict[str, Any]
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
        if err or events is None:
            raise ValueError(err or _ERR_NO_PLAN_EVENTS)
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

        from calendars.outlook_service import ListEventsRequest
        occ = svc.list_events_in_range(ListEventsRequest(
            start_iso=start_iso,
            end_iso=end_iso,
            calendar_id=cal_id,
            top=800,
        ))

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


def _build_apply_dry_run_lines(events: List[Dict[str, Any]], calendar_name: Optional[str]) -> List[str]:
    """Build preview lines for an apply dry-run."""
    suffix = f" to calendar '{calendar_name}'" if calendar_name else ""
    lines = [f"[DRY-RUN] Would apply {len(events)} events{suffix}"]
    for i, ev in enumerate(events, start=1):
        subj = ev.get("subject")
        rep = ev.get("repeat") or "one-off"
        lines.append(f"  - {i}. {subj} ({rep})")
    lines.append("Pass --apply to perform changes.")
    return lines


class ApplyProcessor(SafeProcessor[ApplyRequest, ApplyResult]):
    """Apply events from a plan to a calendar with automatic error handling."""

    def _process_safe(self, payload: ApplyRequest) -> ApplyResult:
        events, err = _load_plan_events(payload.plan_path)
        if err or events is None:
            raise ValueError(err or _ERR_NO_PLAN_EVENTS)
        calendar_name = payload.calendar
        if not payload.apply:
            return ApplyResult(lines=_build_apply_dry_run_lines(events, calendar_name))

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

        rc, logs = _apply_outlook_events(events, calendar_name=calendar_name, service=svc)
        lines.extend(logs)
        if rc != 0:
            raise RuntimeError("\n".join(logs))
        return ApplyResult(lines=lines)


class ApplyProducer(BaseProducer):
    """Produce output for apply operations with automatic error handling."""

    def _produce_success(self, payload: ApplyResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        for line in payload.lines:
            print(line)
