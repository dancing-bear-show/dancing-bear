"""Messages command orchestration helpers."""
from __future__ import annotations

import argparse

from ..utils.filters import build_gmail_query

_MSG_ID_REQUIRED = "--id is required"


def parse_id_list(raw: str | None) -> list[str]:
    """Split a comma-separated --ids value into clean message ids.

    `--id` must stay scalar: `select_message_id` treats any truthy value as an id
    and hands it straight to `client.get_message`, where a list would be swallowed
    by the fallback and returned as the id itself. Bulk ids therefore arrive via
    this separate flag and are normalized to a list before resolution runs.
    """
    if not raw:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _fetch_id_and_thread(client, message_id: str) -> tuple[str | None, str | None]:
    """Fetch (id, threadId) metadata for a message, falling back to (message_id, None)."""
    try:
        meta = client.get_message(message_id, fmt="metadata")
        return meta.get("id"), meta.get("threadId")
    except Exception:  # nosec B112 - fall back to bare id when metadata lookup fails
        return message_id, None


def select_message_id(args: argparse.Namespace, client) -> tuple[str | None, str | None]:
    """Return (message_id, thread_id) resolved from --id or --query/--latest."""
    mid = getattr(args, "id", None)
    if mid:
        return _fetch_id_and_thread(client, mid)
    q = (getattr(args, "query", None) or "").strip()
    if not q:
        return None, None
    crit = {"query": q}
    q_built = build_gmail_query(crit, days=getattr(args, "days", None), only_inbox=getattr(args, "only_inbox", False))
    ids = client.list_message_ids(query=q_built, max_pages=1, page_size=1)
    if not ids:
        return None, None
    return _fetch_id_and_thread(client, ids[0])


def _outlook_search_processor(args, query: str):
    """Build the Outlook search processor, or return None (error already printed)."""
    from ..utils.cli_helpers import outlook_client_from_args
    from .pipeline import OutlookMessagesSearchProcessor

    if not query.strip():
        print("Outlook search requires a non-empty --query")
        return None
    try:
        client = outlook_client_from_args(args)
    except RuntimeError as exc:
        message = str(exc).strip()
        if message:
            print(message)
        return None
    return OutlookMessagesSearchProcessor(client)


# CLI flag names for the Gmail-only structured search criteria, keyed by the
# MessagesSearchRequest field each one populates.
_STRUCTURED_SEARCH_FLAGS = {
    "from_": "--from",
    "to": "--to",
    "subject_contains": "--subject-contains",
    "not_query": "--not-query",
    "has_attachment": "--has-attachment",
    "unread": "--unread",
}


def _unsupported_outlook_flags(request) -> list[str]:
    """Return the structured search flags set on a request, which Outlook cannot honor."""
    return [
        flag
        for attr, flag in _STRUCTURED_SEARCH_FLAGS.items()
        if getattr(request, attr, None) not in (None, "", False)
    ]


def _gmail_search_processor(args):
    """Build the Gmail search processor."""
    from ..utils.cli_helpers import gmail_provider_from_args
    from .pipeline import MessagesSearchProcessor

    client = gmail_provider_from_args(args)
    client.authenticate()
    return MessagesSearchProcessor(client)


def run_messages_search(args) -> int:
    """Search for messages and list candidates."""
    from ..utils.cli_helpers import is_outlook_profile
    from .pipeline import (
        MessagesSearchRequest,
        MessagesSearchRequestConsumer,
        MessagesSearchProducer,
    )

    profile = getattr(args, "profile", None)
    query = getattr(args, "query", "") or ""
    request = MessagesSearchRequest(
        query=query,
        days=getattr(args, "days", None),
        only_inbox=getattr(args, "only_inbox", False),
        max_results=int(getattr(args, "max_results", 5) or 5),
        output_json=getattr(args, "json", False),
        from_=getattr(args, "from_", None),
        to=getattr(args, "to", None),
        subject_contains=getattr(args, "subject_contains", None),
        not_query=getattr(args, "not_query", None),
        has_attachment=getattr(args, "has_attachment", False),
        unread=getattr(args, "unread", False),
    )

    if is_outlook_profile(profile):
        unsupported = _unsupported_outlook_flags(request)
        if unsupported:
            print(
                "Structured search flags are Gmail-only; not supported for Outlook "
                f"profiles: {', '.join(unsupported)}"
            )
            return 1
        processor = _outlook_search_processor(args, query)
    else:
        processor = _gmail_search_processor(args)
    if processor is None:
        return 1

    envelope = processor.process(
        MessagesSearchRequestConsumer(request).consume()
    )
    MessagesSearchProducer(output_json=request.output_json).produce(envelope)
    return 0 if envelope.ok() else 1


def _run_outlook_summarize(args) -> int:
    """Summarize one Outlook message, resolving --id or --query."""
    import sys

    from ..utils import cli_helpers
    from .outlook_text import outlook_message_text
    from .pipeline import MessagesSummarizeResult, MessagesSummarizeProducer
    from core.pipeline import ResultEnvelope

    try:
        client = cli_helpers.outlook_client_from_args(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    msg_id = getattr(args, "id", None)
    if not msg_id:
        query = (getattr(args, "query", None) or "").strip()
        if not query:
            print("No message found. Provide --id or a --query.", file=sys.stderr)
            return 1
        from core.outlook.models import SearchParams

        # Raw, unquoted term: the Graph URL builder owns quoting/encoding.
        found = client.search_inbox_message_dicts(
            SearchParams(search_query=query, days=getattr(args, "days", None), top=1, pages=1)
        )
        if not found:
            print("No message found. Provide --id or a --query.", file=sys.stderr)
            return 1
        msg_id = found[0].get("id")

    try:
        msg = client.get_message(msg_id, select_body=True)
    except Exception as exc:
        print(f"Failed to fetch message '{msg_id}': {exc}", file=sys.stderr)
        return 1

    from ..llm_adapter import summarize_text

    summary = summarize_text(
        outlook_message_text(msg),
        max_words=int(getattr(args, "max_words", 120) or 120),
    )
    if summary and not summary.lower().startswith("summary:"):
        summary = f"Summary: {summary}"

    envelope = ResultEnvelope(
        status="success",
        payload=MessagesSummarizeResult(summary=summary, message_id=msg_id),
    )
    MessagesSummarizeProducer(out_path=getattr(args, "out", None)).produce(envelope)
    return 0


def run_messages_summarize(args) -> int:
    """Summarize a message's content (Gmail or Outlook)."""
    from ..utils import cli_helpers
    from .pipeline import (
        MessagesSummarizeRequest,
        MessagesSummarizeRequestConsumer,
        MessagesSummarizeProcessor,
        MessagesSummarizeProducer,
    )

    # Dispatch before client construction; see run_messages_get.
    if cli_helpers.is_outlook_profile(getattr(args, "profile", None)):
        return _run_outlook_summarize(args)

    client = cli_helpers.gmail_provider_from_args(args)
    client.authenticate()

    request = MessagesSummarizeRequest(
        message_id=getattr(args, "id", None),
        query=getattr(args, "query", None),
        days=getattr(args, "days", None),
        only_inbox=getattr(args, "only_inbox", False),
        max_words=int(getattr(args, "max_words", 120) or 120),
        out_path=getattr(args, "out", None),
    )
    envelope = MessagesSummarizeProcessor(client).process(
        MessagesSummarizeRequestConsumer(request).consume()
    )
    MessagesSummarizeProducer(out_path=request.out_path).produce(envelope)
    return 0 if envelope.ok() else 1


def _fetch_outlook_message_record(client, msg_id: str) -> dict[str, str] | None:
    """Fetch one Outlook message as a normalized record, or None on failure.

    Returns the same key set as the Gmail-side ``_fetch_message_record`` so
    ``_emit_get_records`` stays provider-agnostic. One fetch is enough: Graph's
    widened ``$select`` carries headers and body together.
    """
    import sys

    from .outlook_text import outlook_message_text
    from .pipeline import _graph_address, _graph_datetime_to_iso, _graph_recipients

    try:
        msg = client.get_message(msg_id, select_body=True)
    except Exception as exc:
        print(f"Failed to fetch message '{msg_id}': {exc}", file=sys.stderr)
        return None

    return {
        "id": msg.get("id") or msg_id,
        "subject": msg.get("subject", ""),
        "from_header": _graph_address(msg.get("from")),
        "to_header": _graph_recipients(msg.get("toRecipients")),
        "date": _graph_datetime_to_iso(msg.get("receivedDateTime")),
        "body": outlook_message_text(msg),
    }


def _fetch_message_record(client, msg_id: str) -> dict[str, str] | None:
    """Fetch headers + body for one message, or None after printing the failure."""
    import sys

    # Headers only: the body comes from get_message_text(), which performs its
    # own full fetch. Requesting "metadata" avoids pulling the payload twice.
    try:
        msg = client.get_message(msg_id, fmt="metadata")
    except Exception as exc:
        print(f"Failed to fetch message '{msg_id}': {exc}", file=sys.stderr)
        return None

    headers = {
        h.get("name", "").lower(): h.get("value", "")
        for h in ((msg.get("payload") or {}).get("headers") or [])
    }
    try:
        body = client.get_message_text(msg_id)
    except Exception as exc:
        print(f"Failed to extract message body '{msg_id}': {exc}", file=sys.stderr)
        return None

    return {
        "id": msg_id,
        "subject": headers.get("subject", ""),
        "from_header": headers.get("from", ""),
        "to_header": headers.get("to", ""),
        "date": headers.get("date", ""),
        "body": body,
    }


def _print_message_text(record: dict[str, str]) -> None:
    """Print one message record in text form."""
    print(f"Date: {record['date']}")
    print(f"From: {record['from_header']}")
    print(f"To: {record['to_header']}")
    print(f"Subject: {record['subject']}")
    print()
    print(record["body"])


def _has_get_selector(args) -> bool:
    """True when --id, --ids or --query supplied something to look up.

    --id/--ids/--query are all optional at the argparse layer, so this reproduces
    the exit-1 guard that dropping required=True from --id would otherwise remove.
    """
    return bool(
        getattr(args, "id", None)
        or parse_id_list(getattr(args, "ids", None))
        or (getattr(args, "query", None) or "").strip()
    )


def _resolve_get_ids(args, client) -> list[str]:
    """Resolve the message ids `get` should fetch, in precedence order.

    `--ids` wins, then scalar `--id`, then a `--query` lookup. The comma-separated
    value is split here so a list never reaches `select_message_id`.
    """
    ids = parse_id_list(getattr(args, "ids", None))
    if ids:
        return ids
    msg_id = getattr(args, "id", None)
    if msg_id:
        return [msg_id]
    resolved, _thread = select_message_id(args, client)
    return [resolved] if resolved else []


def _emit_get_records(records: list[dict[str, str]], *, fmt: str, single: bool) -> None:
    """Print fetched message records in the requested format."""
    import json

    if fmt == "json":
        # A single id keeps emitting a bare object for backwards compatibility;
        # only an explicit multi-id request produces a list.
        print(json.dumps(records[0] if single else records, ensure_ascii=False, indent=2))
        return
    for idx, record in enumerate(records):
        if idx:
            print("\n---\n")
        _print_message_text(record)


def run_messages_get(args) -> int:
    """Fetch and print the full body of one or more messages (Gmail or Outlook)."""
    import sys
    from ..utils import cli_helpers

    if not _has_get_selector(args):
        print(_MSG_ID_REQUIRED, file=sys.stderr)
        return 1

    # Dispatch BEFORE building any client: constructing the Gmail provider
    # triggers an interactive OAuth flow, so an Outlook profile must never
    # reach it.
    is_outlook = cli_helpers.is_outlook_profile(getattr(args, "profile", None))
    if is_outlook:
        try:
            client = cli_helpers.outlook_client_from_args(args)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    else:
        client = cli_helpers.gmail_provider_from_args(args)
        client.authenticate()

    msg_ids = _resolve_get_ids(args, client)
    if not msg_ids:
        print(_MSG_ID_REQUIRED, file=sys.stderr)
        return 1

    fetch = _fetch_outlook_message_record if is_outlook else _fetch_message_record
    records = [rec for mid in msg_ids if (rec := fetch(client, mid))]
    if not records:
        return 1

    _emit_get_records(
        records,
        fmt=getattr(args, "format", "text") or "text",
        single=len(msg_ids) == 1,
    )
    return 0 if len(records) == len(msg_ids) else 1
