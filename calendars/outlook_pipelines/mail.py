"""Outlook Mail List Pipeline - list mail messages.

NOTE: This pipeline is misplaced in the calendars module. It handles mail
operations, not calendar operations. It's kept here for backward compatibility
with existing CLI commands and tests. New mail-related pipelines should go
in mail/outlook_pipelines/.
"""

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
    ERR_CODE_CONFIG,
)


@dataclass
class OutlookMailListRequest:
    service: Any
    folder: str
    top: int
    pages: int


OutlookMailListRequestConsumer = RequestConsumer[OutlookMailListRequest]


@dataclass
class OutlookMailListResult:
    messages: List[Dict[str, Any]]
    folder: str


class OutlookMailListProcessor(SafeProcessor[OutlookMailListRequest, OutlookMailListResult]):
    def _process_safe(self, payload: OutlookMailListRequest) -> OutlookMailListResult:
        if err := check_service_required(payload.service):
            return err
        svc = payload.service
        try:
            msgs = svc.list_messages(folder=payload.folder, top=payload.top, pages=payload.pages)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to list messages: {exc}", "code": ERR_CODE_CONFIG})
        msgs = msgs or []
        result = OutlookMailListResult(messages=msgs, folder=payload.folder)
        return result


class OutlookMailListProducer(BaseProducer):
    def _produce_success(self, payload: OutlookMailListResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        msgs = payload.messages
        if not msgs:
            print("No messages.")
            return
        for msg in msgs:
            sub = (msg.get("subject") or "").strip()
            recv = (msg.get("receivedDateTime") or "")[:19]
            frm = (((msg.get("from") or {}).get("emailAddress") or {}).get("address") or "")
            print(f"- {recv} | {sub[:80]} | {frm}")
        print(f"Listed {len(msgs)} message(s).")


__all__ = [
    "OutlookMailListRequest",
    "OutlookMailListRequestConsumer",
    "OutlookMailListResult",
    "OutlookMailListProcessor",
    "OutlookMailListProducer",
]
