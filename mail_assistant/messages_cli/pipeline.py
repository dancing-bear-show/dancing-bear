from __future__ import annotations

"""Pipeline primitives for messages commands."""

import json as _json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.pipeline import Consumer, Processor, Producer, ResultEnvelope


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


class MessagesSearchRequestConsumer(Consumer[MessagesSearchRequest]):
    """Consumer for search requests."""

    def __init__(self, request: MessagesSearchRequest) -> None:
        self._request = request

    def consume(self) -> MessagesSearchRequest:
        return self._request


class MessagesSearchProcessor(Processor[MessagesSearchRequest, ResultEnvelope[MessagesSearchResult]]):
    """Process message search requests."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def process(self, payload: MessagesSearchRequest) -> ResultEnvelope[MessagesSearchResult]:
        from ..utils.filters import build_gmail_query
        from ..messages import candidates_from_metadata

        try:
            crit = {"query": payload.query}
            q = build_gmail_query(crit, days=payload.days, only_inbox=payload.only_inbox)
            ids = self._client.list_message_ids(query=q, max_pages=1, page_size=payload.max_results)
            msgs = self._client.get_messages_metadata(ids, use_cache=True)
            cands = candidates_from_metadata(msgs)
            result = MessagesSearchResult(
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
            return ResultEnvelope(status="success", payload=result)
        except Exception as e:
            return ResultEnvelope(
                status="error",
                diagnostics={"message": str(e)},
            )


class MessagesSearchProducer(Producer[ResultEnvelope[MessagesSearchResult]]):
    """Output search results."""

    def __init__(self, output_json: bool = False) -> None:
        self._output_json = output_json

    def produce(self, result: ResultEnvelope[MessagesSearchResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message", "Search failed")
            print(f"Error: {msg}")
            return

        assert result.payload is not None
        candidates = result.payload.candidates

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


class MessagesSummarizeRequestConsumer(Consumer[MessagesSummarizeRequest]):
    """Consumer for summarize requests."""

    def __init__(self, request: MessagesSummarizeRequest) -> None:
        self._request = request

    def consume(self) -> MessagesSummarizeRequest:
        return self._request


class MessagesSummarizeProcessor(Processor[MessagesSummarizeRequest, ResultEnvelope[MessagesSummarizeResult]]):
    """Process message summarize requests."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def process(self, payload: MessagesSummarizeRequest) -> ResultEnvelope[MessagesSummarizeResult]:
        from ..llm_adapter import summarize_text
        from ..utils.filters import build_gmail_query

        try:
            # Resolve message ID
            mid = payload.message_id
            if not mid and payload.query:
                crit = {"query": payload.query}
                q = build_gmail_query(crit, days=payload.days, only_inbox=payload.only_inbox)
                ids = self._client.list_message_ids(query=q, max_pages=1, page_size=1)
                if ids:
                    mid = ids[0]

            if not mid:
                return ResultEnvelope(
                    status="error",
                    diagnostics={"message": "No message found. Provide --id or a --query."},
                )

            text = self._client.get_message_text(mid)
            summary = summarize_text(text, max_words=payload.max_words)
            if summary and not summary.lower().startswith("summary:"):
                summary = f"Summary: {summary}"

            return ResultEnvelope(
                status="success",
                payload=MessagesSummarizeResult(summary=summary, message_id=mid),
            )
        except Exception as e:
            return ResultEnvelope(
                status="error",
                diagnostics={"message": str(e)},
            )


class MessagesSummarizeProducer(Producer[ResultEnvelope[MessagesSummarizeResult]]):
    """Output summarization results."""

    def __init__(self, out_path: Optional[str] = None) -> None:
        self._out_path = out_path

    def produce(self, result: ResultEnvelope[MessagesSummarizeResult]) -> None:
        from pathlib import Path

        if not result.ok():
            msg = (result.diagnostics or {}).get("message", "Summarization failed")
            print(msg)
            return

        assert result.payload is not None
        summary = result.payload.summary

        if self._out_path:
            p = Path(self._out_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(summary, encoding="utf-8")
            print(f"Summary written to {p}")
        else:
            print(summary)
