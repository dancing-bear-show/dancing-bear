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
    SafeProcessor,
    check_service_required,
)
from ._context import DedupSelectionContext

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


class OutlookDedupProcessor(SafeProcessor[OutlookDedupRequest, OutlookDedupResult]):
    def __init__(self, today_factory=None) -> None:
        self._window = DateWindowResolver(today_factory)

    def _process_safe(self, payload: OutlookDedupRequest) -> OutlookDedupResult:
        check_service_required(payload.service)
        svc = payload.service

        start_iso, end_iso = self._window.resolve(payload.from_date, payload.to_date)
        cal_id = None
        if payload.calendar:
            cal_id = svc.find_calendar_id(payload.calendar)
        from calendars.outlook_service import ListCalendarViewRequest
        occ = svc.list_calendar_view(ListCalendarViewRequest(
            start_iso=start_iso,
            end_iso=end_iso,
            calendar_id=cal_id,
        ))

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
        return result

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
        sorted_sids = sorted(series_ids, key=lambda sid: self._created_at(sid, masters) or "Z")
        if not sorted_sids:
            return None

        newest, oldest = sorted_sids[-1], sorted_sids[0]
        std = [sid for sid in sorted_sids if self._is_standardized(sid, masters)]
        non = [sid for sid in sorted_sids if sid not in std]

        ctx = DedupSelectionContext(
            sorted_sids=sorted_sids, std=std, non=non, newest=newest, oldest=oldest
        )
        keep, delete = self._pick_keep_delete(ctx, payload)
        return keep, delete

    def _created_at(self, sid: str, masters: Dict[str, List[Dict[str, Any]]]) -> str:
        vals = [o.get("createdDateTime") or "" for o in masters.get(sid, []) if o.get("createdDateTime")]
        return min(vals) if vals else ""

    def _is_standardized(self, sid: str, masters: Dict[str, List[Dict[str, Any]]]) -> bool:
        addr_keys = ("street", "city", "state", "postalCode", "countryOrRegion")
        for occ in masters.get(sid) or []:
            loc = occ.get("location") or {}
            disp = loc.get("displayName") or ""
            addr = loc.get("address") or {}
            if addr and any(addr.get(k) for k in addr_keys):
                return True
            if "(" in disp and ")" in disp:
                return True
        return False

    def _pick_keep_delete(
        self,
        ctx: DedupSelectionContext,
        payload: OutlookDedupRequest,
    ) -> Tuple[str, List[str]]:
        base_keep = ctx.newest if payload.keep_newest else ctx.oldest

        if payload.prefer_delete_nonstandard and ctx.non and ctx.std:
            return base_keep, list(ctx.non)

        if payload.delete_standardized and ctx.std and ctx.non:
            keep = ctx.non[-1] if (payload.keep_newest and len(ctx.non) > 1) else ctx.non[0]
            return keep, list(ctx.std)

        return base_keep, [sid for sid in ctx.sorted_sids if sid != base_keep]


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
