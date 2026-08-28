"""Reply composition and scheduled-send commands for messages.

Split out of commands.py to keep that module focused on search/summarize.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .commands import select_message_id


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
    from core.yamlio import load_config
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
    from ..gmail_api import GmailClient
    headers = GmailClient.headers_to_dict(msg_full)
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
    except Exception as e:  # log and continue on send failure
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
