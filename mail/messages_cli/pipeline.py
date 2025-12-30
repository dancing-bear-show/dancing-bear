"""Pipeline primitives for messages commands."""
from __future__ import annotations

import json as _json
from dataclasses import dataclass, field
from typing import Any, List, Optional

from core.pipeline import RequestConsumer, SafeProcessor, BaseProducer


# -----------------------------------------------------------------------------
# Search pipeline
# -----------------------------------------------------------------------------


@dataclass
class MessagesSearchRequest:
    """Request for messages search."""

    query: str
    days: Optional[int] = None
    only_inbox: bool = False
    max_results: int = 5
    output_json: bool = False


@dataclass
class MessageCandidate:
    """A message search result."""

    id: str
    subject: str
    from_header: str
    snippet: str


@dataclass
class MessagesSearchResult:
    """Result from messages search."""

    candidates: List[MessageCandidate] = field(default_factory=list)


# Type alias using generic RequestConsumer from core.pipeline
MessagesSearchRequestConsumer = RequestConsumer[MessagesSearchRequest]


class MessagesSearchProcessor(SafeProcessor[MessagesSearchRequest, MessagesSearchResult]):
    """Process message search requests with automatic error handling."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def _process_safe(self, payload: MessagesSearchRequest) -> MessagesSearchResult:
        from ..utils.filters import build_gmail_query
        from ..messages import candidates_from_metadata

        crit = {"query": payload.query}
        q = build_gmail_query(crit, days=payload.days, only_inbox=payload.only_inbox)
        ids = self._client.list_message_ids(query=q, max_pages=1, page_size=payload.max_results)
        msgs = self._client.get_messages_metadata(ids, use_cache=True)
        cands = candidates_from_metadata(msgs)
        return MessagesSearchResult(
            candidates=[
                MessageCandidate(
                    id=c.id,
                    subject=c.subject,
                    from_header=c.from_header,
                    snippet=c.snippet,
                )
                for c in cands
            ]
        )


class MessagesSearchProducer(BaseProducer):
    """Output search results with automatic error handling."""

    def __init__(self, output_json: bool = False) -> None:
        self._output_json = output_json

    def _produce_success(self, payload: MessagesSearchResult, diagnostics: Optional[Any]) -> None:
        candidates = payload.candidates

        if self._output_json:
            print(_json.dumps([c.__dict__ for c in candidates], ensure_ascii=False, indent=2))
        else:
            for c in candidates:
                print(f"{c.id}\t{c.subject}\t{c.from_header}\t{c.snippet}")


# -----------------------------------------------------------------------------
# Summarize pipeline
# -----------------------------------------------------------------------------


@dataclass
class MessagesSummarizeRequest:
    """Request for message summarization."""

    message_id: Optional[str] = None
    query: Optional[str] = None
    days: Optional[int] = None
    only_inbox: bool = False
    max_words: int = 120
    out_path: Optional[str] = None


@dataclass
class MessagesSummarizeResult:
    """Result from message summarization."""

    summary: str
    message_id: str


# Type alias using generic RequestConsumer from core.pipeline
MessagesSummarizeRequestConsumer = RequestConsumer[MessagesSummarizeRequest]


class MessagesSummarizeProcessor(SafeProcessor[MessagesSummarizeRequest, MessagesSummarizeResult]):
    """Process message summarize requests with automatic error handling."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def _process_safe(self, payload: MessagesSummarizeRequest) -> MessagesSummarizeResult:
        from ..llm_adapter import summarize_text
        from ..utils.filters import build_gmail_query

        # Resolve message ID
        mid = payload.message_id
        if not mid and payload.query:
            crit = {"query": payload.query}
            q = build_gmail_query(crit, days=payload.days, only_inbox=payload.only_inbox)
            ids = self._client.list_message_ids(query=q, max_pages=1, page_size=1)
            if ids:
                mid = ids[0]

        if not mid:
            raise ValueError("No message found. Provide --id or a --query.")

        text = self._client.get_message_text(mid)
        summary = summarize_text(text, max_words=payload.max_words)
        if summary and not summary.lower().startswith("summary:"):
            summary = f"Summary: {summary}"

        return MessagesSummarizeResult(summary=summary, message_id=mid)


class MessagesSummarizeProducer(BaseProducer):
    """Output summarization results with automatic error handling."""

    def __init__(self, out_path: Optional[str] = None) -> None:
        self._out_path = out_path

    def _produce_success(self, payload: MessagesSummarizeResult, diagnostics: Optional[Any]) -> None:
        from pathlib import Path

        summary = payload.summary

        if self._out_path:
            p = Path(self._out_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(summary, encoding="utf-8")
            print(f"Summary written to {p}")
        else:
            print(summary)
