"""Pipeline primitives for messages commands."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.cli_output import OutputWriter, emit_one
from core.pipeline import RequestConsumer, SafeProcessor, BaseProducer


# -----------------------------------------------------------------------------
# Search pipeline
# -----------------------------------------------------------------------------


@dataclass
class MessagesSearchRequest:
    """Request for messages search."""

    query: str
    days: int | None = None
    only_inbox: bool = False
    max_results: int = 5
    output_json: bool = False
    from_: str | None = None
    to: str | None = None
    subject_contains: str | None = None
    not_query: str | None = None
    has_attachment: bool = False
    unread: bool = False


def search_request_to_criteria(request: MessagesSearchRequest) -> dict[str, Any]:
    """Map a search request onto the criteria keys ``build_gmail_query`` understands.

    Keys are dropped when empty so the built query stays free of no-op operators.
    ``unread`` is intentionally absent: ``build_gmail_query`` has no such key and is
    shared with the filters/sweep path, so callers append ``is:unread`` themselves.
    """
    criteria: dict[str, Any] = {
        "query": request.query,
        "from": request.from_,
        "to": request.to,
        "subject": request.subject_contains,
        "negatedQuery": request.not_query,
    }
    normalized = {k: v for k, v in criteria.items() if v not in (None, "")}
    if request.has_attachment:
        normalized["hasAttachment"] = True
    return normalized


@dataclass
class MessageCandidate:
    """A message search result."""

    id: str
    subject: str
    from_header: str
    snippet: str
    to_header: str = ""
    date: str = ""
    labels: list[str] = field(default_factory=list)
    unread: bool = False
    # Tri-state, and deliberately asymmetric between providers. Outlook's
    # $select returns hasAttachments, so True/False are both meaningful. Gmail's
    # format="metadata" response genuinely lacks payload.parts, so attachment
    # state is UNKNOWN there -- None keeps the key out of the output entirely
    # rather than emitting a False that would read as "no attachments".
    has_attachment: bool | None = None


@dataclass
class MessagesSearchResult:
    """Result from messages search."""

    candidates: list[MessageCandidate] = field(default_factory=list)


# Type alias using generic RequestConsumer from core.pipeline
MessagesSearchRequestConsumer = RequestConsumer[MessagesSearchRequest]


class MessagesSearchProcessor(SafeProcessor[MessagesSearchRequest, MessagesSearchResult]):
    """Process Gmail message search requests with automatic error handling."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def _process_safe(self, payload: MessagesSearchRequest) -> MessagesSearchResult:
        from ..utils.filters import build_gmail_query
        from ..messages import candidates_from_metadata

        crit = search_request_to_criteria(payload)
        q = build_gmail_query(crit, days=payload.days, only_inbox=payload.only_inbox)
        # build_gmail_query has no unread key and is shared with the filters/sweep
        # path, so the operator is appended here instead of widening that helper.
        if payload.unread:
            q = f"{q} is:unread".strip()
        # max_pages=0 exhausts the cursor (paging.gather_pages breaks only on a
        # truthy max_pages). Decoupling page_size from max_results is what lifts
        # the old one-page cap; the slice keeps the caller's requested ceiling.
        ids = self._client.list_message_ids(
            query=q,
            max_pages=0,
            page_size=min(500, max(payload.max_results, 100)),
        )[: payload.max_results]
        msgs = self._client.get_messages_metadata(ids, use_cache=True)
        cands = candidates_from_metadata(msgs)
        return MessagesSearchResult(
            candidates=[
                MessageCandidate(
                    id=c.id,
                    subject=c.subject,
                    from_header=c.from_header,
                    snippet=c.snippet,
                    to_header=c.to_header,
                    date=c.date,
                    labels=list(c.labels),
                    unread=c.unread,
                )
                for c in cands
            ]
        )


class OutlookMessagesSearchProcessor(SafeProcessor[MessagesSearchRequest, MessagesSearchResult]):
    """Process Outlook message search requests with automatic error handling."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def _process_safe(self, payload: MessagesSearchRequest) -> MessagesSearchResult:
        from core.outlook.models import SearchParams

        # search_query takes a RAW, unquoted term: _build_search_url owns the
        # KQL quoting and percent-encoding. Pre-encoding here would double-encode.
        params = SearchParams(
            search_query=payload.query,
            days=payload.days,
            top=payload.max_results,
            pages=1,
            use_cache=True,
        )
        # Single fetch: search_inbox_message_dicts $selects every field a
        # candidate needs, so there is no per-message get_message round trip.
        msgs = self._client.search_inbox_message_dicts(params)
        candidates = [
            _outlook_msg_to_candidate(msg.get("id", ""), msg)
            for msg in msgs[:payload.max_results]
        ]
        return MessagesSearchResult(candidates=candidates)


def _graph_address(entry: dict | None) -> str:
    """Format one Graph emailAddress entry as "Name <addr>" or a bare address."""
    addr_obj = (entry or {}).get("emailAddress") or {}
    name = (addr_obj.get("name") or "").strip()
    address = (addr_obj.get("address") or "").strip()
    if name and address:
        return f"{name} <{address}>"
    return address or name


def _graph_datetime_to_iso(value: Any) -> str:
    """Normalize Graph's receivedDateTime to ISO-8601 UTC ("%Y-%m-%dT%H:%M:%SZ").

    Graph already returns ISO-8601, but may include sub-second precision or a
    "+00:00" offset. This matches the Gmail-side format produced by
    ``mail.messages._internal_date_to_iso`` so both providers agree.
    """
    from datetime import datetime, timezone

    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _graph_recipients(entries: list[dict] | None) -> str:
    """Format a Graph recipient list as a comma-separated header string."""
    formatted = (_graph_address(entry) for entry in (entries or []))
    return ", ".join(addr for addr in formatted if addr)


def _outlook_msg_to_candidate(mid: str, msg: dict) -> MessageCandidate:
    """Convert an Outlook message dict to a MessageCandidate.

    ``has_attachment`` is populated from Graph's ``hasAttachments``; unlike the
    Gmail path it is never left unknown. See MessageCandidate.
    """
    return MessageCandidate(
        id=mid,
        subject=msg.get("subject", ""),
        from_header=_graph_address(msg.get("from")),
        snippet=(msg.get("bodyPreview") or "").strip(),
        to_header=_graph_recipients(msg.get("toRecipients")),
        date=_graph_datetime_to_iso(msg.get("receivedDateTime")),
        unread=not msg.get("isRead", True),
        has_attachment=bool(msg.get("hasAttachments", False)),
    )


class MessagesSearchProducer(BaseProducer):
    """Output search results with automatic error handling."""

    def __init__(self, output_json: bool = False, writer: OutputWriter | None = None) -> None:
        super().__init__(writer)
        self._output_json = output_json

    def _produce_success(self, payload: MessagesSearchResult, diagnostics: Any | None) -> None:
        candidates = payload.candidates

        if self._output_json:
            # Drop None-valued keys so an UNKNOWN has_attachment (Gmail) is
            # absent rather than rendered as null/false. See MessageCandidate.
            rows = [
                {k: v for k, v in c.__dict__.items() if v is not None}
                for c in candidates
            ]
            emit_one(rows)
        else:
            for c in candidates:
                print(f"{c.id}\t{c.subject}\t{c.from_header}\t{c.snippet}")


# -----------------------------------------------------------------------------
# Summarize pipeline
# -----------------------------------------------------------------------------


@dataclass
class MessagesSummarizeRequest:
    """Request for message summarization."""

    message_id: str | None = None
    query: str | None = None
    days: int | None = None
    only_inbox: bool = False
    max_words: int = 120
    out_path: str | None = None


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

    def __init__(self, out_path: str | None = None, writer: OutputWriter | None = None) -> None:
        super().__init__(writer)
        self._out_path = out_path

    def _produce_success(self, payload: MessagesSummarizeResult, diagnostics: Any | None) -> None:
        from pathlib import Path

        summary = payload.summary

        if self._out_path:
            p = Path(self._out_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(summary, encoding="utf-8")
            print(f"Summary written to {p}")
        else:
            print(summary)
