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
)
from ..outlook_service import EventCreationParams, RecurringEventCreationParams


# =============================================================================
# Outlook Add Event Pipeline
# =============================================================================

@dataclass
class OutlookAddEventRequest:
    """Request to create a one-time event. Composes EventCreationParams."""
    service: Any
    params: EventCreationParams


OutlookAddEventRequestConsumer = RequestConsumer[OutlookAddEventRequest]


@dataclass
class OutlookAddEventResult:
    event_id: str
    subject: str


class OutlookAddEventProcessor(SafeProcessor[OutlookAddEventRequest, OutlookAddEventResult]):
    def _process_safe(self, payload: OutlookAddEventRequest) -> OutlookAddEventResult:
        check_service_required(payload.service)
        svc = payload.service
        evt = svc.create_event(payload.params)
        evt_id = (evt or {}).get("id") or ""
        result = OutlookAddEventResult(event_id=evt_id, subject=(evt or {}).get("subject") or payload.params.subject)
        return result


class OutlookAddEventProducer(BaseProducer):
    def _produce_success(self, payload: OutlookAddEventResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        print(f"Created event: {payload.event_id} subject={payload.subject}")


# =============================================================================
# Outlook Add Recurring Pipeline
# =============================================================================

@dataclass
class OutlookAddRecurringRequest:
    """Request to create a recurring event. Composes RecurringEventCreationParams."""
    service: Any
    params: RecurringEventCreationParams


OutlookAddRecurringRequestConsumer = RequestConsumer[OutlookAddRecurringRequest]


@dataclass
class OutlookAddRecurringResult:
    event_id: str
    subject: str


class OutlookAddRecurringProcessor(SafeProcessor[OutlookAddRecurringRequest, OutlookAddRecurringResult]):
    def _process_safe(self, payload: OutlookAddRecurringRequest) -> OutlookAddRecurringResult:
        check_service_required(payload.service)
        svc = payload.service
        evt = svc.create_recurring_event(payload.params)
        evt_id = (evt or {}).get("id") or ""
        subject = (evt or {}).get("subject") or payload.params.subject
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
