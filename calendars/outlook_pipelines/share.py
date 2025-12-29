"""Outlook Calendar Share Pipeline - share calendars with recipients."""

from ._base import (
    dataclass,
    Any,
    Dict,
    Optional,
    Processor,
    ResultEnvelope,
    BaseProducer,
    RequestConsumer,
    check_service_required,
    ERR_CODE_CALENDAR,
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


class OutlookCalendarShareProcessor(Processor[OutlookCalendarShareRequest, ResultEnvelope[OutlookCalendarShareResult]]):
    def process(self, payload: OutlookCalendarShareRequest) -> ResultEnvelope[OutlookCalendarShareResult]:
        if err := check_service_required(payload.service):
            return err
        svc = payload.service
        cal_name = payload.calendar
        try:
            cal_id = svc.find_calendar_id(cal_name)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to resolve calendar '{cal_name}': {exc}", "code": ERR_CODE_CALENDAR})
        if not cal_id:
            try:
                cal_id = svc.ensure_calendar_exists(cal_name)
            except Exception as exc:
                return ResultEnvelope(
                    status="error",
                    diagnostics={"message": f"Failed to ensure calendar '{cal_name}': {exc}", "code": ERR_CODE_CALENDAR},
                )
        role = self._normalize_role(payload.role)
        try:
            svc.ensure_calendar_permission(cal_id, payload.recipient, role)
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                diagnostics={"message": f"Failed to share calendar '{cal_name}' with {payload.recipient}: {exc}", "code": ERR_CODE_CALENDAR},
            )
        result = OutlookCalendarShareResult(calendar=cal_name, recipient=payload.recipient, role=role)
        return ResultEnvelope(status="success", payload=result)

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
