"""Messages command orchestration helpers."""
from __future__ import annotations

import argparse

from ..utils.filters import build_gmail_query

_MSG_ID_REQUIRED = "--id is required"


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
    )

    processor = (
        _outlook_search_processor(args, query)
        if is_outlook_profile(profile)
        else _gmail_search_processor(args)
    )
    if processor is None:
        return 1

    envelope = processor.process(
        MessagesSearchRequestConsumer(request).consume()
    )
    MessagesSearchProducer(output_json=request.output_json).produce(envelope)
    return 0 if envelope.ok() else 1


def run_messages_summarize(args) -> int:
    """Summarize a message's content."""
    from ..utils.cli_helpers import gmail_provider_from_args
    from .pipeline import (
        MessagesSummarizeRequest,
        MessagesSummarizeRequestConsumer,
        MessagesSummarizeProcessor,
        MessagesSummarizeProducer,
    )

    client = gmail_provider_from_args(args)
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


def run_messages_get(args) -> int:
    """Fetch and print the full body of a Gmail message."""
    import json
    import sys
    from ..utils.cli_helpers import gmail_provider_from_args

    msg_id = getattr(args, "id", None)
    if not msg_id:
        print(_MSG_ID_REQUIRED, file=sys.stderr)
        return 1

    fmt = getattr(args, "format", "text") or "text"
    client = gmail_provider_from_args(args)
    client.authenticate()

    # Headers only: the body comes from get_message_text(), which performs its
    # own full fetch. Requesting "metadata" avoids pulling the payload twice.
    try:
        msg = client.get_message(msg_id, fmt="metadata")
    except Exception as exc:
        print(f"Failed to fetch message '{msg_id}': {exc}", file=sys.stderr)
        return 1

    headers = {
        h.get("name", "").lower(): h.get("value", "")
        for h in ((msg.get("payload") or {}).get("headers") or [])
    }
    try:
        body = client.get_message_text(msg_id)
    except Exception as exc:
        print(f"Failed to extract message body '{msg_id}': {exc}", file=sys.stderr)
        return 1

    if fmt == "json":
        print(json.dumps({
            "id": msg_id,
            "subject": headers.get("subject", ""),
            "from_header": headers.get("from", ""),
            "to_header": headers.get("to", ""),
            "date": headers.get("date", ""),
            "body": body,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"Date: {headers.get('date', '')}")
        print(f"From: {headers.get('from', '')}")
        print(f"To: {headers.get('to', '')}")
        print(f"Subject: {headers.get('subject', '')}")
        print()
        print(body)
    return 0
