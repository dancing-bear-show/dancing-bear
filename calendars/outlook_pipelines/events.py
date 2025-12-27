"""Outlook List One-Offs Pipeline - list single calendar events."""

from ._base import (
    dataclass,
    Path,
    Any,
    Dict,
    List,
    Optional,
    Processor,
    ResultEnvelope,
    BaseProducer,
    DateWindowResolver,
    RequestConsumer,
    check_service_required,
)


@dataclass
class OutlookListOneOffsRequest:
    service: Any
    calendar: Optional[str]
    from_date: Optional[str]
    to_date: Optional[str]
    limit: int
    out_path: Optional[Path]


OutlookListOneOffsRequestConsumer = RequestConsumer[OutlookListOneOffsRequest]


@dataclass
class OutlookListOneOffsResult:
    rows: List[Dict[str, str]]
    start: str
    end: str
    limit: int
    out_path: Optional[Path]


class OutlookListOneOffsProcessor(Processor[OutlookListOneOffsRequest, ResultEnvelope[OutlookListOneOffsResult]]):
    def __init__(self, today_factory=None) -> None:
        self._window = DateWindowResolver(today_factory)

    def process(self, payload: OutlookListOneOffsRequest) -> ResultEnvelope[OutlookListOneOffsResult]:
        if err := check_service_required(payload.service):
            return err
        svc = payload.service
        start_iso, end_iso = self._window.resolve(payload.from_date, payload.to_date)
        start_date = payload.from_date or start_iso[:10]
        end_date = payload.to_date or end_iso[:10]
        try:
            evs = svc.list_events_in_range(
                calendar_name=payload.calendar,
                start_iso=start_iso,
                end_iso=end_iso,
            )
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to list events: {exc}", "code": 3})
        one_offs = []
        for ev in evs or []:
            etype = (ev.get("type") or "").lower()
            if (etype == "singleinstance") or not ev.get("seriesMasterId"):
                one_offs.append(ev)
        rows: List[Dict[str, str]] = []
        for ev in one_offs[: max(0, payload.limit)]:
            subj = ev.get("subject") or ""
            st = ((ev.get("start") or {}).get("dateTime") or "") or ""
            en = ((ev.get("end") or {}).get("dateTime") or "") or ""
            loc = ((ev.get("location") or {}).get("displayName") or "") or ""
            rows.append({"subject": subj, "start": st, "end": en, "location": loc})
        result = OutlookListOneOffsResult(
            rows=rows,
            start=start_date,
            end=end_date,
            limit=payload.limit,
            out_path=payload.out_path,
        )
        return ResultEnvelope(status="success", payload=result)


class OutlookListOneOffsProducer(BaseProducer):
    def _produce_success(self, payload: OutlookListOneOffsResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        rows = payload.rows
        print(f"Found {len(rows)} single events from {payload.start} to {payload.end}.")
        for ev in rows[: payload.limit]:
            st = (ev.get("start") or "")[:16]
            en = (ev.get("end") or "")[:16]
            subj = ev.get("subject") or ""
            loc = ev.get("location") or ""
            print(f"- {st} → {en} | {subj} | {loc}")
        if payload.out_path:
            from calendars.yamlio import dump_config

            dump_config(str(payload.out_path), {"events": rows})
            print(f"Wrote one-offs to {payload.out_path}")


__all__ = [
    "OutlookListOneOffsRequest",
    "OutlookListOneOffsRequestConsumer",
    "OutlookListOneOffsResult",
    "OutlookListOneOffsProcessor",
    "OutlookListOneOffsProducer",
]
