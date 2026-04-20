"""Outlook List One-Offs Pipeline - list single calendar events."""

from ._base import (
    dataclass,
    Path,
    Any,
    Dict,
    List,
    Optional,
    SafeProcessor,
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


class OutlookListOneOffsProcessor(SafeProcessor[OutlookListOneOffsRequest, OutlookListOneOffsResult]):
    def __init__(self, today_factory=None) -> None:
        self._window = DateWindowResolver(today_factory)

    def _is_one_off(self, ev: Dict[str, Any]) -> bool:
        """Return True if the event is a single-instance (not part of a series)."""
        etype = (ev.get("type") or "").lower()
        return etype == "singleinstance" or not ev.get("seriesMasterId")

    def _event_to_row(self, ev: Dict[str, Any]) -> Dict[str, str]:
        """Convert an Outlook event dict to a flat row dict."""
        return {
            "subject": ev.get("subject") or "",
            "start": ((ev.get("start") or {}).get("dateTime") or ""),
            "end": ((ev.get("end") or {}).get("dateTime") or ""),
            "location": ((ev.get("location") or {}).get("displayName") or ""),
        }

    def _process_safe(self, payload: OutlookListOneOffsRequest) -> OutlookListOneOffsResult:
        check_service_required(payload.service)
        svc = payload.service
        start_iso, end_iso = self._window.resolve(payload.from_date, payload.to_date)
        start_date = payload.from_date or start_iso[:10]
        end_date = payload.to_date or end_iso[:10]
        from calendars.outlook_service import ListEventsRequest
        evs = svc.list_events_in_range(ListEventsRequest(
            start_iso=start_iso,
            end_iso=end_iso,
            calendar_name=payload.calendar,
        ))
        one_offs = [ev for ev in (evs or []) if self._is_one_off(ev)]
        rows = [self._event_to_row(ev) for ev in one_offs[:max(0, payload.limit)]]
        return OutlookListOneOffsResult(
            rows=rows,
            start=start_date,
            end=end_date,
            limit=payload.limit,
            out_path=payload.out_path,
        )


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
