"""Outlook Remove Pipeline - delete calendar events based on config."""

from ._base import (
    _dt,
    dataclass,
    Path,
    Any,
    Sequence,
    EventIterationProcessor,
    BaseProducer,
    RequestConsumer,
    check_service_required,
    load_events_config,
)
from ._context import EventMatchingCriteria
from calendars.selection import weekday_code
from core.constants import DAY_START_TIME, DAY_END_TIME


@dataclass
class OutlookRemoveRequest:
    config_path: Path
    calendar: str | None
    subject_only: bool
    apply: bool
    service: Any


OutlookRemoveRequestConsumer = RequestConsumer[OutlookRemoveRequest]


@dataclass
class OutlookRemovePlanEntry:
    subject: str
    series_ids: list[str]
    event_ids: list[str]


@dataclass
class OutlookRemoveResult:
    plan: list[OutlookRemovePlanEntry]
    apply: bool
    deleted: int
    logs: list[str]


@dataclass
class DeleteOneRequest:
    """Shared context for deleting one event/series and logging the outcome.

    Deliberately not frozen: ``logs`` is the caller's accumulator list, which
    ``_delete_one`` appends to. ``frozen=True`` would block field rebinding but
    not that mutation, so it would advertise an immutability this type does not
    have.
    """

    subj: str
    svc: Any
    logs: list[str]
    deleted_label: str
    failed_label: str


@dataclass
class _RemoveAccumulator:
    """Per-run accumulator for OutlookRemoveProcessor's template method."""

    apply: bool
    plan: list[OutlookRemovePlanEntry]
    logs: list[str]
    deleted_total: int


class OutlookRemoveProcessor(EventIterationProcessor):
    def __init__(self, config_loader=None) -> None:
        self._config_loader = config_loader

    def _load_events(self, payload: OutlookRemoveRequest) -> list[dict[str, Any]]:
        return load_events_config(payload.config_path, self._config_loader)

    def _init_accumulator(self, payload: OutlookRemoveRequest) -> _RemoveAccumulator:
        check_service_required(payload.service)  # Raises ValueError if None
        return _RemoveAccumulator(apply=payload.apply, plan=[], logs=[], deleted_total=0)

    def _handle_event(
        self, payload: OutlookRemoveRequest, idx: int, nev: dict[str, Any], accumulator: _RemoveAccumulator
    ) -> None:
        subj = (nev.get("subject") or "").strip()
        window = self._resolve_window(nev)
        if not window:
            return
        start_iso, end_iso = window
        cal_name = payload.calendar or nev.get("calendar")
        svc = payload.service
        try:
            from calendars.outlook_service import ListEventsRequest
            occ = svc.list_events_in_range(ListEventsRequest(
                start_iso=start_iso,
                end_iso=end_iso,
                calendar_name=cal_name,
                subject_filter=subj,
            ))
        except Exception as exc:
            accumulator.logs.append(f"[{idx}] list error: {exc}")
            return
        matches = self._match_events(occ or [], nev, payload.subject_only)
        series_ids, event_ids = self._collect_ids(matches)
        if not series_ids and not event_ids:
            return
        entry = OutlookRemovePlanEntry(subject=subj, series_ids=series_ids, event_ids=event_ids)
        accumulator.plan.append(entry)
        if payload.apply:
            accumulator.deleted_total += self._apply_deletions(entry, svc, accumulator.logs)

    def _finalize(self, accumulator: _RemoveAccumulator) -> OutlookRemoveResult:
        return OutlookRemoveResult(
            plan=accumulator.plan,
            apply=accumulator.apply,
            deleted=accumulator.deleted_total,
            logs=accumulator.logs,
        )

    def _resolve_window(self, event: dict[str, Any]) -> tuple[str, str] | None:
        single_start = (event.get("start") or "").strip()
        single_end = (event.get("end") or "").strip()
        if single_start and single_end:
            return single_start, single_end
        rng = event.get("range") or {}
        start_date = (rng.get("start_date") or "").strip()
        until = (rng.get("until") or "").strip()
        if not start_date:
            return None
        start_iso = f"{start_date[:10]}{DAY_START_TIME}"
        end_iso = f"{(until or start_date)[:10]}{DAY_END_TIME}"
        return start_iso, end_iso

    def _extract_occurrence_times(self, ex: dict[str, Any]) -> tuple[str, str]:
        """Extract start and end datetime from occurrence."""
        st = ((ex.get("start") or {}).get("dateTime") or "")
        en = ((ex.get("end") or {}).get("dateTime") or "")
        return st, en

    def _extract_time_from_datetime(self, dt_str: str) -> str:
        """Extract HH:MM time from ISO datetime string."""
        return dt_str.split("T", 1)[1][:5] if "T" in dt_str else ""

    def _get_weekday_code(self, dt_str: str) -> str:
        """Get weekday code (mo/tu/we/th/fr/sa/su) from datetime string."""
        try:
            dt = _dt.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            return weekday_code(dt)
        except Exception:  # nosec B110 - invalid datetime format
            return ""

    def _matches_single_event(self, st: str, en: str, ctx: EventMatchingCriteria) -> bool:
        """Check if occurrence matches single event criteria (specific start/end datetime)."""
        return st.startswith(ctx.single_start[:16]) and en.startswith(ctx.single_end[:16])

    def _matches_recurring_criteria(self, st: str, en: str, ctx: EventMatchingCriteria) -> bool:
        """Check if occurrence matches recurring event criteria (day of week + times)."""
        # Check weekday match
        if ctx.want_days:
            wcode = self._get_weekday_code(st)
            if not wcode or wcode.lower() not in ctx.want_days:
                return False

        # Check start time match
        if ctx.start_time:
            t1 = self._extract_time_from_datetime(st)
            if t1 and ctx.start_time != t1:
                return False

        # Check end time match
        if ctx.end_time:
            t2 = self._extract_time_from_datetime(en)
            if t2 and ctx.end_time != t2:
                return False

        return True

    def _is_matching_occurrence(self, ex: dict[str, Any], ctx: EventMatchingCriteria) -> bool:
        """Check if a single occurrence matches the event criteria."""
        st, en = self._extract_occurrence_times(ex)

        # Single event matching (specific date/time)
        if ctx.single_start and ctx.single_end:
            return self._matches_single_event(st, en, ctx)

        # Recurring event matching (day of week + times)
        if not ctx.subject_only:
            return self._matches_recurring_criteria(st, en, ctx)

        return True

    def _match_events(self, occ: Sequence[dict[str, Any]], event: dict[str, Any], subject_only: bool):
        """Match occurrences against event criteria."""
        single_start = (event.get("start") or "").strip()
        single_end = (event.get("end") or "").strip()
        start_time = (event.get("start_time") or "").strip()
        end_time = (event.get("end_time") or "").strip()
        want_days = set(d.lower() for d in (event.get("byday") or []) if d)

        ctx = EventMatchingCriteria(
            single_start=single_start,
            single_end=single_end,
            subject_only=subject_only,
            want_days=want_days,
            start_time=start_time,
            end_time=end_time,
        )

        matches = []
        for ex in occ:
            if self._is_matching_occurrence(ex, ctx):
                matches.append(ex)
        return matches

    def _collect_ids(self, matches: Sequence[dict[str, Any]]) -> tuple[list[str], list[str]]:
        series_ids: list[str] = []
        event_ids: list[str] = []
        for match in matches:
            sid = match.get("seriesMasterId")
            if sid:
                if sid not in series_ids:
                    series_ids.append(sid)
                continue
            mid = match.get("id")
            if mid and mid not in event_ids:
                event_ids.append(mid)
        return series_ids, event_ids

    def _delete_one(self, item_id: str, request: DeleteOneRequest) -> bool:
        """Delete a single event or series by id, appending the matching log line."""
        logs = request.logs
        try:
            ok = bool(request.svc.delete_event_by_id(item_id))
        except Exception as exc:
            logs.append(f"Failed to delete {request.failed_label} {item_id}: {exc}")
            return False
        if ok:
            logs.append(f"Deleted {request.deleted_label}: {item_id} ({request.subj})")
        else:
            logs.append(f"Failed to delete {request.failed_label} {item_id}")
        return ok

    def _apply_deletions(self, entry: OutlookRemovePlanEntry, svc, logs: list[str]) -> int:
        deleted = 0
        subj = entry.subject
        series_req = DeleteOneRequest(
            subj=subj, svc=svc, logs=logs, deleted_label="series master", failed_label="series"
        )
        for sid in entry.series_ids:
            if self._delete_one(sid, series_req):
                deleted += 1
        event_req = DeleteOneRequest(
            subj=subj, svc=svc, logs=logs, deleted_label="event", failed_label="event"
        )
        for eid in entry.event_ids:
            if self._delete_one(eid, event_req):
                deleted += 1
        return deleted


class OutlookRemoveProducer(BaseProducer):
    def _produce_success(self, payload: OutlookRemoveResult, diagnostics: dict[str, Any] | None) -> None:
        if not payload.apply:
            self._writer.print("Planned deletions:")
            for entry in payload.plan:
                if entry.series_ids:
                    self._writer.print(f"- {entry.subject}: delete series {len(entry.series_ids)}")
                if entry.event_ids:
                    self._writer.print(f"- {entry.subject}: delete events {len(entry.event_ids)}")
            self._writer.print("Re-run with --apply to delete.")
            return
        self.print_logs(payload.logs)
        self._writer.print(f"Deleted {payload.deleted} items.")


__all__ = [
    "OutlookRemoveRequest",
    "OutlookRemoveRequestConsumer",
    "OutlookRemovePlanEntry",
    "OutlookRemoveResult",
    "DeleteOneRequest",
    "OutlookRemoveProcessor",
    "OutlookRemoveProducer",
]
