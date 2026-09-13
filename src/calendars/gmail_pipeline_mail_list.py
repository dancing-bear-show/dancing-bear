"""Gmail mail-list pipeline for calendar assistant."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.pipeline import SafeProcessor

from .gmail_service import GmailService, QueryParams
from .pipeline_base import (
    BaseProducer,
    GmailAuth,
    GmailServiceBuilder,
    RequestConsumer,
)


# =============================================================================
# Gmail Mail List Pipeline
# =============================================================================

@dataclass
class GmailMailListRequest:
    auth: GmailAuth
    query: str | None
    from_text: str | None
    days: int
    pages: int
    page_size: int
    inbox_only: bool


GmailMailListRequestConsumer = RequestConsumer[GmailMailListRequest]


@dataclass
class GmailMailListResult:
    messages: list[dict[str, str]]


class GmailMailListProcessor(SafeProcessor[GmailMailListRequest, GmailMailListResult]):
    def __init__(self, service_builder=None) -> None:
        self._service_builder = service_builder or self._default_service_builder

    def _default_service_builder(self, auth: GmailAuth):
        return GmailServiceBuilder.build(auth)

    def _process_safe(self, payload: GmailMailListRequest) -> GmailMailListResult:
        svc = self._service_builder(payload.auth)
        query = GmailService.build_query_from_params(QueryParams(
            explicit=payload.query,
            from_text=payload.from_text,
            days=payload.days,
            inbox_only=payload.inbox_only,
        ))
        ids = svc.list_message_ids(query=query, max_pages=payload.pages, page_size=payload.page_size)
        if not ids:
            return GmailMailListResult(messages=[])
        messages: list[dict[str, str]] = []
        for mid in ids:
            try:
                text = svc.get_message_text(mid)
            except Exception as exc:
                messages.append({"id": mid, "snippet": f"<failed to fetch: {exc}>"})
                continue
            first_line = (text or "").splitlines()[0] if text else ""
            messages.append({"id": mid, "snippet": first_line[:100]})
        return GmailMailListResult(messages=messages)


class GmailMailListProducer(BaseProducer):
    def _produce_success(self, payload: GmailMailListResult, diagnostics: dict[str, Any] | None) -> None:
        messages = payload.messages
        if not messages:
            self._writer.print("No messages matched.")
            return
        for msg in messages:
            self._writer.print(f"- {msg.get('id')} | {msg.get('snippet')}")
        self._writer.print(f"Listed {len(messages)} Gmail message(s).")
