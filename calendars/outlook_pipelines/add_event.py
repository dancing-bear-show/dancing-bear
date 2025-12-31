"""Outlook Add Event Pipelines - create single and recurring events."""

from ._base import (
    dataclass,
    Any,
    Dict,
    List,
    Optional,
    SafeProcessor,
    BaseProducer,
    RequestConsumer,
    check_service_required,
    ERR_CODE_CALENDAR,
)


# =============================================================================
# Outlook Add Event Pipeline
# =============================================================================

@dataclass
class OutlookAddEventRequest:
    service: Any
    calendar: Optional[str]
    subject: str
    start_iso: str
    end_iso: str
    tz: Optional[str]
    body_html: Optional[str]
    all_day: bool
    location: Optional[str]
    no_reminder: bool
    reminder_minutes: Optional[int]


OutlookAddEventRequestConsumer = RequestConsumer[OutlookAddEventRequest]


@dataclass
class OutlookAddEventResult:
    event_id: str
    subject: str


class OutlookAddEventProcessor(SafeProcessor[OutlookAddEventRequest, OutlookAddEventResult]):
    def _process_safe(self, payload: OutlookAddEventRequest) -> OutlookAddEventResult:
        check_service_required(payload.service)
        svc = payload.service
        try:
            evt = svc.create_event(
                calendar_id=None,
                calendar_name=payload.calendar,
                subject=payload.subject,
                start_iso=payload.start_iso,
                end_iso=payload.end_iso,
                tz=payload.tz,
                body_html=payload.body_html,
                all_day=payload.all_day,
                location=payload.location,
                no_reminder=payload.no_reminder,
                reminder_minutes=payload.reminder_minutes,
            )
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to create event: {exc}", "code": ERR_CODE_CALENDAR})
        evt_id = (evt or {}).get("id") or ""
        result = OutlookAddEventResult(event_id=evt_id, subject=(evt or {}).get("subject") or payload.subject)
        return result


class OutlookAddEventProducer(BaseProducer):
    def _produce_success(self, payload: OutlookAddEventResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        print(f"Created event: {payload.event_id} subject={payload.subject}")


# =============================================================================
# Outlook Add Recurring Pipeline
# =============================================================================

@dataclass
class OutlookAddRecurringRequest:
    service: Any
    calendar: Optional[str]
    subject: str
    start_time: str
    end_time: str
    tz: Optional[str]
    repeat: str
    interval: int
    byday: Optional[List[str]]
    range_start_date: str
    range_until: Optional[str]
    count: Optional[int]
    body_html: Optional[str]
    location: Optional[str]
    exdates: Optional[List[str]]
    no_reminder: bool
    reminder_minutes: Optional[int]


OutlookAddRecurringRequestConsumer = RequestConsumer[OutlookAddRecurringRequest]


@dataclass
class OutlookAddRecurringResult:
    event_id: str
    subject: str


class OutlookAddRecurringProcessor(SafeProcessor[OutlookAddRecurringRequest, OutlookAddRecurringResult]):
    def _process_safe(self, payload: OutlookAddRecurringRequest) -> OutlookAddRecurringResult:
        check_service_required(payload.service)
        svc = payload.service
        try:
            evt = svc.create_recurring_event(
                calendar_id=None,
                calendar_name=payload.calendar,
                subject=payload.subject,
                start_time=payload.start_time,
                end_time=payload.end_time,
                tz=payload.tz,
                repeat=payload.repeat,
                interval=payload.interval,
                byday=payload.byday,
                range_start_date=payload.range_start_date,
                range_until=payload.range_until,
                count=payload.count,
                body_html=payload.body_html,
                location=payload.location,
                exdates=payload.exdates or None,
                no_reminder=payload.no_reminder,
                reminder_minutes=payload.reminder_minutes,
            )
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to create recurring event: {exc}", "code": ERR_CODE_CALENDAR})
        evt_id = (evt or {}).get("id") or ""
        subject = (evt or {}).get("subject") or payload.subject
        result = OutlookAddRecurringResult(event_id=evt_id, subject=subject)
        return result


class OutlookAddRecurringProducer(BaseProducer):
    def _produce_success(self, payload: OutlookAddRecurringResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        print(f"Created recurring series: {payload.event_id} subject={payload.subject}")


__all__ = [
    "OutlookAddEventRequest",
    "OutlookAddEventRequestConsumer",
    "OutlookAddEventResult",
    "OutlookAddEventProcessor",
    "OutlookAddEventProducer",
    "OutlookAddRecurringRequest",
    "OutlookAddRecurringRequestConsumer",
    "OutlookAddRecurringResult",
    "OutlookAddRecurringProcessor",
    "OutlookAddRecurringProducer",
]
