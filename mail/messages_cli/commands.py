"""Messages command orchestration helpers."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from ..utils.filters import build_gmail_query


def select_message_id(args: argparse.Namespace, client) -> tuple[Optional[str], Optional[str]]:
    """Return (message_id, thread_id) resolved from --id or --query/--latest."""
    mid = getattr(args, "id", None)
    if mid:
        try:
            meta = client.get_message(mid, fmt="metadata")
            return meta.get("id"), meta.get("threadId")
        except Exception:
            return mid, None
    q = (getattr(args, "query", None) or "").strip()
    if q:
        crit = {"query": q}
        q_built = build_gmail_query(crit, days=getattr(args, "days", None), only_inbox=getattr(args, "only_inbox", False))
        ids = client.list_message_ids(query=q_built, max_pages=1, page_size=1)
        if ids:
            try:
                meta = client.get_message(ids[0], fmt="metadata")
                return meta.get("id"), meta.get("threadId")
            except Exception:
                return ids[0], None
    return None, None


def run_messages_search(args) -> int:
    """Search for messages and list candidates."""
    from ..utils.cli_helpers import gmail_provider_from_args
    from .pipeline import (
        MessagesSearchRequest,
        MessagesSearchRequestConsumer,
        MessagesSearchProcessor,
        MessagesSearchProducer,
    )

    client = gmail_provider_from_args(args)
    client.authenticate()

    request = MessagesSearchRequest(
        query=getattr(args, "query", "") or "",
        days=getattr(args, "days", None),
        only_inbox=getattr(args, "only_inbox", False),
        max_results=int(getattr(args, "max_results", 5) or 5),
        output_json=getattr(args, "json", False),
    )
    envelope = MessagesSearchProcessor(client).process(
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


def _reply_schedule(args, raw: bytes, thread_id: Optional[str], to_email: str, subject: str) -> int:
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


def _reply_execute(args, client, raw: bytes, thread_id: Optional[str], to_email: str) -> None:
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
    from ..messages import _compose_reply, encode_email_message
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
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        body_text="\n".join(body_lines).strip(),
        in_reply_to=hdr["message_id"],
        references=(f"{hdr['references']} {hdr['message_id']}".strip() if hdr["message_id"] else hdr["references"]),
        cc=[str(x) for x in getattr(args, "cc", []) if x],
        bcc=[str(x) for x in getattr(args, "bcc", []) if x],
        include_quote=include_quote,
        original_text=client.get_message_text(mid) if include_quote else None,
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


def run_messages_apply_scheduled(args) -> int:
    """Apply scheduled messages that are due."""
    from ..scheduler import pop_due
    from ..utils.cli_helpers import gmail_provider_from_args
    import base64

    sent = 0
    errors = 0
    due = pop_due(profile=getattr(args, "profile", None), limit=int(getattr(args, "max", 10) or 10))
    if not due:
        print("No scheduled messages due.")
        return 0
    # Group by profile for provider reuse
    by_profile = {}
    for it in due:
        by_profile.setdefault(it.get("profile") or "default", []).append(it)
    for prof, items in by_profile.items():
        ns = argparse.Namespace(profile=prof, credentials=None, token=None, cache=None)
        client = gmail_provider_from_args(ns)
        client.authenticate()
        for it in items:
            to = it.get("to") or "recipient"
            subj = it.get("subject") or ""
            try:
                raw = base64.b64decode(it.get("raw_b64") or b"")
                thread_id = it.get("thread_id")
                client.send_message_raw(raw, thread_id=thread_id)
                sent += 1
                print(f"Sent scheduled message to {to} subject='{subj}' profile={prof}")
            except Exception as e:  # nosec B110 - log and continue on send failure
                errors += 1
                print(f"Failed to send to {to}: {e}")
    print(f"Scheduled send complete. Sent: {sent}, Errors: {errors}")
    return 1 if errors else 0
