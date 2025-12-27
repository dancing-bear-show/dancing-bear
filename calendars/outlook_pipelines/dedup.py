"""Outlook Dedup Pipeline."""

from __future__ import annotations

from ._base import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    dataclass,
    defaultdict,
    _dt,
    BaseProducer,
    DateWindowResolver,
    RequestConsumer,
    Processor,
    ResultEnvelope,
    check_service_required,
)

__all__ = [
    "OutlookDedupRequest",
    "OutlookDedupRequestConsumer",
    "OutlookDedupDuplicate",
    "OutlookDedupResult",
    "OutlookDedupProcessor",
    "OutlookDedupProducer",
]


@dataclass
class OutlookDedupRequest:
    service: Any
    calendar: Optional[str] = None
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    apply: bool = False
    keep_newest: bool = False
    prefer_delete_nonstandard: bool = False
    delete_standardized: bool = False


OutlookDedupRequestConsumer = RequestConsumer[OutlookDedupRequest]


@dataclass
class OutlookDedupDuplicate:
    subject: str
    weekday: str
    start_time: str
    end_time: str
    keep: str
    delete: List[str]


@dataclass
class OutlookDedupResult:
    duplicates: List[OutlookDedupDuplicate]
    apply: bool
    deleted: int
    logs: List[str]


class OutlookDedupProcessor(Processor[OutlookDedupRequest, ResultEnvelope[OutlookDedupResult]]):
    def __init__(self, today_factory=None) -> None:
        self._window = DateWindowResolver(today_factory)

    def process(self, payload: OutlookDedupRequest) -> ResultEnvelope[OutlookDedupResult]:
        if err := check_service_required(payload.service):
            return err
        svc = payload.service

        start_iso, end_iso = self._window.resolve(payload.from_date, payload.to_date)
        cal_id = None
        if payload.calendar:
            cal_id = svc.find_calendar_id(payload.calendar)
        try:
            occ = svc.list_calendar_view(calendar_id=cal_id, start_iso=start_iso, end_iso=end_iso)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Graph error: {exc}", "code": 4})

        duplicates = self._find_duplicates(occ or [], payload)
        logs: List[str] = []
        deleted = 0
        if payload.apply and duplicates:
            for group in duplicates:
                for sid in group.delete:
                    ok = False
                    try:
                        ok = bool(svc.delete_event_by_id(sid))
                    except Exception as exc:
                        logs.append(f"Failed to delete {sid}: {exc}")
                        continue
                    if ok:
                        deleted += 1
                        logs.append(f"Deleted series master {sid}")

        result = OutlookDedupResult(duplicates=duplicates, apply=payload.apply, deleted=deleted, logs=logs)
        return ResultEnvelope(status="success", payload=result)

    def _find_duplicates(
        self,
        occ: List[Dict[str, Any]],
        payload: OutlookDedupRequest,
    ) -> List[OutlookDedupDuplicate]:
        groups: Dict[Tuple[str, str, str, str], Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        for event in occ:
            sid = event.get("seriesMasterId")
            if not sid:
                continue
            key = self._key_for_event(event)
            if not key:
                continue
            groups[key][sid].append(event)

        duplicates: List[OutlookDedupDuplicate] = []
        for key, masters in groups.items():
            if len(masters) <= 1:
                continue
            selection = self._select_series(list(masters.keys()), masters, payload)
            if not selection:
                continue
            keep, delete = selection
            subject, weekday, start_time, end_time = key
            duplicates.append(
                OutlookDedupDuplicate(
                    subject=subject,
                    weekday=weekday,
                    start_time=start_time,
                    end_time=end_time,
                    keep=keep,
                    delete=delete,
                )
            )
        return duplicates

    def _key_for_event(self, event: Dict[str, Any]) -> Optional[Tuple[str, str, str, str]]:
        subject = (event.get("subject") or "").strip().lower()
        start = ((event.get("start") or {}).get("dateTime") or "")
        end = ((event.get("end") or {}).get("dateTime") or "")
        t1 = start.split("T", 1)[1][:5] if "T" in start else ""
        t2 = end.split("T", 1)[1][:5] if "T" in end else ""
        weekday = ""
        try:
            dt = _dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
            weekday = ["mo", "tu", "we", "th", "fr", "sa", "su"][dt.weekday()]
        except Exception:
            weekday = ""
        return subject, weekday, t1, t2

    def _select_series(
        self,
        series_ids: List[str],
        masters: Dict[str, List[Dict[str, Any]]],
        payload: OutlookDedupRequest,
    ) -> Optional[Tuple[str, List[str]]]:
        def created_at(sid: str) -> str:
            vals = [o.get("createdDateTime") or "" for o in masters.get(sid, []) if o.get("createdDateTime")]
            if not vals:
                return ""
            return min(vals)

        def is_standardized(sid: str) -> bool:
            occs = masters.get(sid) or []
            for occ in occs:
                loc = occ.get("location") or {}
                disp = loc.get("displayName") or ""
                addr = loc.get("address") or {}
                if addr and any(addr.get(k) for k in ("street", "city", "state", "postalCode", "countryOrRegion")):
                    return True
                if "(" in disp and ")" in disp:
                    return True
            return False

        sorted_sids = sorted(series_ids, key=lambda sid: created_at(sid) or "Z")
        if not sorted_sids:
            return None
        newest = sorted_sids[-1]
        oldest = sorted_sids[0]
        std = [sid for sid in sorted_sids if is_standardized(sid)]
        non = [sid for sid in sorted_sids if sid not in std]

        keep = oldest

        if payload.prefer_delete_nonstandard:
            if non and std:
                keep = newest if payload.keep_newest else oldest
                delete = list(non)
            else:
                keep = newest if payload.keep_newest else oldest
                delete = [sid for sid in sorted_sids if sid != keep]
        elif payload.delete_standardized:
            if std and non:
                if payload.keep_newest:
                    keep = non[-1] if len(non) > 1 else non[0]
                else:
                    keep = non[0]
                delete = list(std)
            else:
                keep = newest if payload.keep_newest else oldest
                delete = [sid for sid in sorted_sids if sid != keep]
        else:
            keep = newest if payload.keep_newest else oldest
            delete = [sid for sid in sorted_sids if sid != keep]

        return keep, delete


class OutlookDedupProducer(BaseProducer):
    def _produce_success(self, payload: OutlookDedupResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        duplicates = payload.duplicates
        if not duplicates:
            print("No duplicate series detected in window.")
            return

        print(f"Found {len(duplicates)} duplicate groups. (subject,day,time)-> keep + delete list")
        for dup in duplicates:
            deletes = ", ".join(dup.delete)
            print(f"- {dup.subject} {dup.weekday} {dup.start_time}-{dup.end_time}: keep {dup.keep} delete {deletes}")

        if not payload.apply:
            print("Dry plan only. Re-run with --apply to delete duplicates (keep oldest).")
            return

        self.print_logs(payload.logs)
        print(f"Deleted {payload.deleted} duplicate series.")
