"""Outlook Remove Pipeline - delete calendar events based on config."""

from ._base import (
    _dt,
    dataclass,
    Path,
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    SafeProcessor,
    normalize_event,
    BaseProducer,
    RequestConsumer,
    check_service_required,
    load_events_config,
)
from core.constants import DAY_START_TIME, DAY_END_TIME


@dataclass
class OutlookRemoveRequest:
    config_path: Path
    calendar: Optional[str]
    subject_only: bool
    apply: bool
    service: Any


OutlookRemoveRequestConsumer = RequestConsumer[OutlookRemoveRequest]


@dataclass
class OutlookRemovePlanEntry:
    subject: str
    series_ids: List[str]
    event_ids: List[str]


@dataclass
class OutlookRemoveResult:
    plan: List[OutlookRemovePlanEntry]
    apply: bool
    deleted: int
    logs: List[str]


class OutlookRemoveProcessor(SafeProcessor[OutlookRemoveRequest, OutlookRemoveResult]):
    def __init__(self, config_loader=None) -> None:
        self._config_loader = config_loader

    def _process_safe(self, payload: OutlookRemoveRequest) -> OutlookRemoveResult:
        items = load_events_config(payload.config_path, self._config_loader)
        if err := check_service_required(payload.service):
            return err
        svc = payload.service

        plan: List[OutlookRemovePlanEntry] = []
        logs: List[str] = []
        deleted_total = 0

        for idx, raw in enumerate(items, start=1):
            if not isinstance(raw, dict):
                continue
            nev = normalize_event(raw)
            subj = (nev.get("subject") or "").strip()
            window = self._resolve_window(nev)
            if not window:
                continue
            start_iso, end_iso = window
            cal_name = payload.calendar or nev.get("calendar")
            try:
                occ = svc.list_events_in_range(
                    calendar_name=cal_name,
                    start_iso=start_iso,
                    end_iso=end_iso,
                    subject_filter=subj,
                )
            except Exception as exc:
                logs.append(f"[{idx}] list error: {exc}")
                continue
            matches = self._match_events(occ or [], nev, payload.subject_only)
            series_ids, event_ids = self._collect_ids(matches)
            if not series_ids and not event_ids:
                continue
            entry = OutlookRemovePlanEntry(subject=subj, series_ids=series_ids, event_ids=event_ids)
            plan.append(entry)
            if payload.apply:
                deleted_total += self._apply_deletions(entry, svc, logs)

        result = OutlookRemoveResult(plan=plan, apply=payload.apply, deleted=deleted_total, logs=logs)
        return result

    def _resolve_window(self, event: Dict[str, Any]) -> Optional[Tuple[str, str]]:
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

    def _match_events(self, occ: Sequence[Dict[str, Any]], event: Dict[str, Any], subject_only: bool):
        matches = []
        single_start = (event.get("start") or "").strip()
        single_end = (event.get("end") or "").strip()
        start_time = (event.get("start_time") or "").strip()
        end_time = (event.get("end_time") or "").strip()
        want_days = set(d.lower() for d in (event.get("byday") or []) if d)
        for ex in occ:
            st = ((ex.get("start") or {}).get("dateTime") or "")
            en = ((ex.get("end") or {}).get("dateTime") or "")
            if single_start and single_end:
                if not (st.startswith(single_start[:16]) and en.startswith(single_end[:16])):
                    continue
            elif not subject_only:
                t1 = st.split("T", 1)[1][:5] if "T" in st else ""
                t2 = en.split("T", 1)[1][:5] if "T" in en else ""
                try:
                    dt = _dt.datetime.fromisoformat(st.replace("Z", "+00:00"))
                    wcode = ["mo", "tu", "we", "th", "fr", "sa", "su"][dt.weekday()]
                except Exception:
                    wcode = ""
                if want_days and wcode and wcode.lower() not in want_days:
                    continue
                if start_time and t1 and start_time != t1:
                    continue
                if end_time and t2 and end_time != t2:
                    continue
            matches.append(ex)
        return matches

    def _collect_ids(self, matches: Sequence[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
        series_ids: List[str] = []
        event_ids: List[str] = []
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

    def _apply_deletions(self, entry: OutlookRemovePlanEntry, svc, logs: List[str]) -> int:
        deleted = 0
        subj = entry.subject
        for sid in entry.series_ids:
            try:
                ok = bool(svc.delete_event_by_id(sid))
            except Exception as exc:
                logs.append(f"Failed to delete series {sid}: {exc}")
                continue
            if ok:
                deleted += 1
                logs.append(f"Deleted series master: {sid} ({subj})")
            else:
                logs.append(f"Failed to delete series {sid}")
        for eid in entry.event_ids:
            try:
                ok2 = bool(svc.delete_event_by_id(eid))
            except Exception as exc:
                logs.append(f"Failed to delete event {eid}: {exc}")
                continue
            if ok2:
                deleted += 1
                logs.append(f"Deleted event: {eid} ({subj})")
            else:
                logs.append(f"Failed to delete event {eid}")
        return deleted


class OutlookRemoveProducer(BaseProducer):
    def _produce_success(self, payload: OutlookRemoveResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        if not payload.apply:
            print("Planned deletions:")
            for entry in payload.plan:
                if entry.series_ids:
                    print(f"- {entry.subject}: delete series {len(entry.series_ids)}")
                if entry.event_ids:
                    print(f"- {entry.subject}: delete events {len(entry.event_ids)}")
            print("Re-run with --apply to delete.")
            return
        self.print_logs(payload.logs)
        print(f"Deleted {payload.deleted} items.")


__all__ = [
    "OutlookRemoveRequest",
    "OutlookRemoveRequestConsumer",
    "OutlookRemovePlanEntry",
    "OutlookRemoveResult",
    "OutlookRemoveProcessor",
    "OutlookRemoveProducer",
]
