"""Outlook Calendar Share Pipeline - share calendars with recipients."""

from ._base import (
    dataclass,
    Any,
    Dict,
    Optional,
    SafeProcessor,
    BaseProducer,
    RequestConsumer,
    check_service_required,
)


@dataclass
class OutlookCalendarShareRequest:
    service: Any
    calendar: str
    recipient: str
    role: str


OutlookCalendarShareRequestConsumer = RequestConsumer[OutlookCalendarShareRequest]


@dataclass
class OutlookCalendarShareResult:
    calendar: str
    recipient: str
    role: str


class OutlookCalendarShareProcessor(SafeProcessor[OutlookCalendarShareRequest, OutlookCalendarShareResult]):
    def _process_safe(self, payload: OutlookCalendarShareRequest) -> OutlookCalendarShareResult:
        check_service_required(payload.service)
        svc = payload.service
        cal_name = payload.calendar
        cal_id = svc.find_calendar_id(cal_name)
        if not cal_id:
            cal_id = svc.ensure_calendar_exists(cal_name)
        role = self._normalize_role(payload.role)
        svc.ensure_calendar_permission(cal_id, payload.recipient, role)
        result = OutlookCalendarShareResult(calendar=cal_name, recipient=payload.recipient, role=role)
        return result

    def _normalize_role(self, role: str) -> str:
        cleaned = (role or "write").strip().lower()
        if cleaned in ("admin", "owner", "editor"):
            cleaned = "write"
        allowed = {
            "read",
            "write",
            "limitedread",
            "freebusyread",
            "delegatewithoutprivateeventaccess",
            "delegatewithprivateeventaccess",
            "custom",
        }
        camel_map = {
            "limitedread": "limitedRead",
            "freebusyread": "freeBusyRead",
            "delegatewithoutprivateeventaccess": "delegateWithoutPrivateEventAccess",
            "delegatewithprivateeventaccess": "delegateWithPrivateEventAccess",
        }
        if cleaned not in allowed:
            return "write"
        return camel_map.get(cleaned, cleaned)


class OutlookCalendarShareProducer(BaseProducer):
    def _produce_success(self, payload: OutlookCalendarShareResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        print(f"Shared '{payload.calendar}' with {payload.recipient} role={payload.role}")


__all__ = [
    "OutlookCalendarShareRequest",
    "OutlookCalendarShareRequestConsumer",
    "OutlookCalendarShareResult",
    "OutlookCalendarShareProcessor",
    "OutlookCalendarShareProducer",
]
