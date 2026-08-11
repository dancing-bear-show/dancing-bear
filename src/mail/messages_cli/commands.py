"""Messages command orchestration helpers."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

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


def _reply_show_plan(args, to_email: str, orig_subj: str) -> int:
    """Show plan preview for reply."""
    when = getattr(args, "send_at", None) or getattr(args, "send_in", None)
    print("Plan: reply")
    print(f"  to: {to_email}")
    if getattr(args, "cc", None):
        print(f"  cc: {', '.join(args.cc)}")
    if getattr(args, "bcc", None):
        print(f"  bcc: {', '.join(args.bcc)}")
    print(f"  subject: {'Re: ' + orig_subj if not getattr(args, 'subject', None) else args.subject}")
    if when:
        print(f"  when: {when}")
    print("  action: send (with --apply) or create draft (--create-draft)")
    return 0


def _reply_schedule(args, raw: bytes, thread_id: str | None, to_email: str, subject: str) -> int:
    """Schedule reply for later sending."""
    from ..scheduler import parse_send_at, parse_send_in, enqueue, ScheduledItem
    import base64

    due = None
    send_at = getattr(args, "send_at", None)
    send_in = getattr(args, "send_in", None)
    if send_at:
        due = parse_send_at(str(send_at))
    if due is None and send_in:
        delta = parse_send_in(str(send_in))
        if delta:
            due = int(__import__("time").time()) + int(delta)
    if due is None:
        print("Invalid --send-at/--send-in; expected 'YYYY-MM-DD HH:MM' or like '2h30m'")
        return 1

    prof = getattr(args, "profile", None) or "default"
    item = ScheduledItem(
        provider="gmail",
        profile=str(prof),
        due_at=int(due),
        raw_b64=base64.b64encode(raw).decode("utf-8"),
        thread_id=thread_id,
        to=to_email,
        subject=subject or "",
    )
    enqueue(item)
    from datetime import datetime
    print(f"Queued reply to {to_email} at {datetime.fromtimestamp(due).strftime('%Y-%m-%d %H:%M')}")

    draft_out = getattr(args, "draft_out", None)
    if draft_out:
        p = Path(draft_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        print(f"Draft written to {p}")
    return 0


def _load_points_from_file(plan_path: str, args) -> str:
    """Load points text from a plan file."""
    from ..yamlio import load_config
    doc = load_config(plan_path)
    goals = doc.get("goals") or doc.get("points") or []
    points = "\n".join(f"- {g}" for g in goals if g) if isinstance(goals, list) else ""
    if not getattr(args, "signoff", None) and doc.get("signoff"):
        args.signoff = str(doc.get("signoff"))
    return points


def _format_points(points_text: str) -> list[str]:
    """Format points text into body lines."""
    if not points_text:
        return []
    pts = [ln.strip() for ln in str(points_text).splitlines() if ln.strip()]
    if len(pts) == 1 and not pts[0].startswith("-"):
        return [pts[0]]
    return ["Here are the points:"] + [f"- {p.lstrip('-').strip()}" for p in pts]


def _build_reply_body(args, client, mid: str) -> list[str]:
    """Build reply body lines from args and message context."""
    from ..llm_adapter import summarize_text

    points_text = getattr(args, "points", None) or ""
    plan_path = getattr(args, "points_file", None)
    if plan_path:
        points_text = points_text or _load_points_from_file(plan_path, args)

    body_lines = _format_points(points_text)

    if getattr(args, "include_summary", False):
        summ = summarize_text(client.get_message_text(mid), max_words=80)
        body_lines.insert(0, f"Summary: {summ}")

    signoff = getattr(args, "signoff", None) or "Thanks,"
    body_lines.extend(["", signoff])
    return body_lines


def _reply_execute(args, client, raw: bytes, thread_id: str | None, to_email: str) -> None:
    """Execute reply action (send, draft, or preview)."""
    if getattr(args, "apply", False):
        client.send_message_raw(raw, thread_id=thread_id)
        print(f"Sent reply to {to_email} (thread {thread_id or 'new'})")
        return

    if getattr(args, "create_draft", False):
        d = client.create_draft_raw(raw, thread_id=thread_id)
        did = (d or {}).get('id') or '(draft id unavailable)'
        print(f"Created Gmail draft id={did}")
        return

    draft_out = getattr(args, "draft_out", None)
    if draft_out:
        p = Path(draft_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        print(f"Draft written to {p}")
    else:
        text = raw.decode("utf-8", errors="replace")
        head = "\n".join(text.splitlines()[:20])
        print(head)
        print("... (preview; use --draft-out to write .eml or --apply to send)")


def _extract_reply_headers(msg_full: dict) -> dict:
    """Extract relevant headers from message for reply."""
    headers = {h.get("name", "").lower(): h.get("value", "") for h in ((msg_full.get("payload") or {}).get("headers") or [])}
    return {
        "subject": headers.get("subject", ""),
        "message_id": headers.get("message-id"),
        "references": headers.get("references"),
        "reply_to": headers.get("reply-to") or headers.get("from") or "",
    }


def run_messages_reply(args) -> int:
    """Compose and send/draft a reply to a message."""
    from ..utils.cli_helpers import gmail_provider_from_args
    from ..messages import _compose_reply, encode_email_message, ReplyEnvelope, ReplyOptions
    from email.utils import formatdate

    client = gmail_provider_from_args(args)
    client.authenticate()
    mid, thread_id = select_message_id(args, client)
    if not mid:
        print("No message found. Provide --id or a --query with --latest.")
        return 1

    # Fetch headers for reply context
    hdr = _extract_reply_headers(client.get_message(mid, fmt="full"))
    _, to_email = __import__("email.utils").utils.parseaddr(hdr["reply_to"])
    if not to_email:
        print("Could not determine recipient from original message headers")
        return 1

    profile = client.get_profile() if hasattr(client, 'get_profile') else {}
    from_email = (profile or {}).get("emailAddress") or "me"

    # Build reply body and compose message
    body_lines = _build_reply_body(args, client, mid)
    subject = getattr(args, "subject", None) or hdr["subject"]
    include_quote = bool(getattr(args, "include_quote", False))
    msg = _compose_reply(
        envelope=ReplyEnvelope(
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            cc=[str(x) for x in getattr(args, "cc", []) if x],
            bcc=[str(x) for x in getattr(args, "bcc", []) if x],
        ),
        body_text="\n".join(body_lines).strip(),
        options=ReplyOptions(
            in_reply_to=hdr["message_id"],
            references=(f"{hdr['references']} {hdr['message_id']}".strip() if hdr["message_id"] else hdr["references"]),
            include_quote=include_quote,
            original_text=client.get_message_text(mid) if include_quote else None,
        ),
    )
    msg["Date"] = formatdate(localtime=True)
    raw = encode_email_message(msg)

    # Dispatch to appropriate action handler
    if getattr(args, "plan", False):
        return _reply_show_plan(args, to_email, hdr["subject"])
    if getattr(args, "send_at", None) or getattr(args, "send_in", None):
        return _reply_schedule(args, raw, thread_id, to_email, subject)
    _reply_execute(args, client, raw, thread_id, to_email)
    return 0


def _send_one_scheduled(client, item: dict, profile: str) -> bool:
    """Send a single scheduled item. Returns True on success."""
    import base64

    to = item.get("to") or "recipient"
    subj = item.get("subject") or ""
    try:
        raw = base64.b64decode(item.get("raw_b64") or b"")
        thread_id = item.get("thread_id")
        client.send_message_raw(raw, thread_id=thread_id)
        print(f"Sent scheduled message to {to} subject='{subj}' profile={profile}")
        return True
    except Exception as e:  # nosec B110 - log and continue on send failure
        print(f"Failed to send to {to}: {e}")
        return False


def _send_scheduled_for_profile(profile: str, items: list) -> tuple[int, int]:
    """Authenticate once for a profile and send all its due items. Returns (sent, errors)."""
    from ..utils.cli_helpers import gmail_provider_from_args

    ns = argparse.Namespace(profile=profile, credentials=None, token=None, cache=None)
    client = gmail_provider_from_args(ns)
    client.authenticate()
    results = [_send_one_scheduled(client, it, profile) for it in items]
    sent = sum(1 for ok in results if ok)
    return sent, len(results) - sent


def run_messages_apply_scheduled(args) -> int:
    """Apply scheduled messages that are due."""
    from ..scheduler import pop_due

    due = pop_due(profile=getattr(args, "profile", None), limit=int(getattr(args, "max", 10) or 10))
    if not due:
        print("No scheduled messages due.")
        return 0
    # Group by profile for provider reuse
    by_profile: dict = {}
    for it in due:
        by_profile.setdefault(it.get("profile") or "default", []).append(it)

    sent = 0
    errors = 0
    for prof, items in by_profile.items():
        prof_sent, prof_errors = _send_scheduled_for_profile(prof, items)
        sent += prof_sent
        errors += prof_errors
    print(f"Scheduled send complete. Sent: {sent}, Errors: {errors}")
    return 1 if errors else 0


@dataclass(frozen=True)
class AttachmentInfo:
    """Metadata for a single message attachment."""
    filename: str
    mime_type: str
    attachment_id: str
    size: int


def list_message_attachments(message: dict) -> list[AttachmentInfo]:
    """Return attachment metadata from a full Gmail message dict.

    Recursively walks payload.parts and returns one AttachmentInfo per
    part that has a non-empty filename and a body.attachmentId.
    """
    payload = message.get("payload") or {}
    return _collect_attachment_parts(payload)


def _collect_attachment_parts(part: dict) -> list[AttachmentInfo]:
    """Recursively collect attachment parts from a message part."""
    results: list[AttachmentInfo] = []
    filename = (part.get("filename") or "").strip()
    body = part.get("body") or {}
    attachment_id = body.get("attachmentId") or ""
    if filename and attachment_id:
        results.append(AttachmentInfo(
            filename=filename,
            mime_type=part.get("mimeType") or "",
            attachment_id=attachment_id,
            size=int(body.get("size") or 0),
        ))
    for sub in (part.get("parts") or []):
        results.extend(_collect_attachment_parts(sub))
    return results


_FALLBACK_ATTACHMENT_NAME = "attachment"


def _sanitize_filename(filename: str) -> str:
    """Return a safe basename, stripping path separators to prevent path traversal.

    Degenerate results ("", ".", "..") resolve to a directory rather than a file,
    so they fall back to a fixed placeholder name.
    """
    import os
    base = os.path.basename(filename.replace("\\", "/")).strip()
    if base in ("", ".", ".."):
        return _FALLBACK_ATTACHMENT_NAME
    return base


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


def run_messages_list_attachments(args) -> int:
    """List attachments in a Gmail message."""
    import json
    import sys
    from ..utils.cli_helpers import gmail_provider_from_args

    msg_id = getattr(args, "id", None)
    if not msg_id:
        print(_MSG_ID_REQUIRED, file=sys.stderr)
        return 1

    client = gmail_provider_from_args(args)
    client.authenticate()
    try:
        msg = client.get_message(msg_id, fmt="metadata")
    except Exception as exc:
        print(f"Failed to fetch message '{msg_id}': {exc}", file=sys.stderr)
        return 1
    attachments = list_message_attachments(msg)

    if not attachments:
        print("No attachments found.")
        return 0

    if getattr(args, "json", False):
        rows = [
            {
                "filename": a.filename,
                "mimeType": a.mime_type,
                "attachmentId": a.attachment_id,
                "size": a.size,
            }
            for a in attachments
        ]
        print(json.dumps(rows, indent=2))
    else:
        for a in attachments:
            print(f"{a.filename}  ({a.mime_type}, {a.size} bytes)  id={a.attachment_id}")
    return 0


def _print_attachment_choices(attachments: list[AttachmentInfo]) -> None:
    """Print attachment filename/id pairs to stderr as disambiguation help."""
    import sys
    for a in attachments:
        print(f"  {a.filename}  id={a.attachment_id}", file=sys.stderr)


def _resolve_by_filename(
    attachments: list[AttachmentInfo], filename_filter: str
) -> tuple[AttachmentInfo | None, int]:
    """Select the single attachment matching a filename."""
    import sys

    matched = [a for a in attachments if a.filename == filename_filter]
    if not matched:
        print(f"No attachment with filename '{filename_filter}' found.", file=sys.stderr)
        print("Available attachments:", file=sys.stderr)
        _print_attachment_choices(attachments)
        return None, 1
    if len(matched) > 1:
        print(
            f"Multiple attachments named '{filename_filter}'; "
            "specify --attachment-id instead:",
            file=sys.stderr,
        )
        _print_attachment_choices(matched)
        return None, 1
    return matched[0], 0


def _resolve_by_attachment_id(
    attachments: list[AttachmentInfo], attachment_id: str
) -> tuple[AttachmentInfo | None, int]:
    """Select the attachment with a given attachment id."""
    import sys

    matched = [a for a in attachments if a.attachment_id == attachment_id]
    if not matched:
        print(f"No attachment with id '{attachment_id}' found.", file=sys.stderr)
        return None, 1
    return matched[0], 0


def _resolve_attachment(
    attachments: list[AttachmentInfo],
    attachment_id: str | None,
    filename_filter: str | None,
) -> tuple[AttachmentInfo | None, int]:
    """Select one attachment from a list.

    Returns (chosen, 0) on success or (None, 1) on failure (error already printed).
    """
    import sys

    if filename_filter and attachment_id:
        print(
            "Specify only one of --attachment-id or --filename, not both.",
            file=sys.stderr,
        )
        return None, 1
    if filename_filter:
        return _resolve_by_filename(attachments, filename_filter)
    if attachment_id:
        return _resolve_by_attachment_id(attachments, attachment_id)
    if len(attachments) == 1:
        return attachments[0], 0
    print("Multiple attachments found; specify --attachment-id or --filename:", file=sys.stderr)
    _print_attachment_choices(attachments)
    return None, 1


def _resolve_output_path(chosen: AttachmentInfo, out_arg: str | None, out_dir_arg: str) -> Path:
    """Determine the output file path for a downloaded attachment."""
    safe_name = _sanitize_filename(chosen.filename)
    if out_arg:
        out_path = Path(out_arg)
        if out_path.is_dir():
            return out_path / safe_name
        return out_path
    return Path(out_dir_arg) / safe_name


def run_messages_download_attachment(args) -> int:
    """Download an attachment from a Gmail message to disk."""
    import sys
    from ..utils.cli_helpers import gmail_provider_from_args

    msg_id = getattr(args, "id", None)
    if not msg_id:
        print(_MSG_ID_REQUIRED, file=sys.stderr)
        return 1

    client = gmail_provider_from_args(args)
    client.authenticate()
    try:
        msg = client.get_message(msg_id, fmt="metadata")
    except Exception as exc:
        print(f"Failed to fetch message '{msg_id}': {exc}", file=sys.stderr)
        return 1
    attachments = list_message_attachments(msg)

    if not attachments:
        print("No attachments found in this message.", file=sys.stderr)
        return 1

    chosen, rc = _resolve_attachment(
        attachments,
        attachment_id=getattr(args, "attachment_id", None),
        filename_filter=getattr(args, "filename", None),
    )
    if chosen is None:
        return rc

    out_path = _resolve_output_path(
        chosen,
        out_arg=getattr(args, "out", None),
        out_dir_arg=getattr(args, "out_dir", None) or ".",
    )

    try:
        data = client.get_attachment(msg_id, chosen.attachment_id)
    except Exception as exc:
        print(f"Failed to fetch attachment '{chosen.filename}': {exc}", file=sys.stderr)
        return 1

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
    except OSError as exc:
        print(f"Failed to write {out_path}: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {out_path} ({len(data)} bytes)")
    return 0
