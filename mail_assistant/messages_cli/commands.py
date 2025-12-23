from __future__ import annotations

"""Messages command orchestration helpers."""

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


def run_messages_reply(args) -> int:
    """Compose and send/draft a reply to a message."""
    from ..utils.cli_helpers import gmail_provider_from_args
    from ..messages import _compose_reply, encode_email_message
    from ..llm_adapter import summarize_text
    from ..yamlio import load_config
    from email.utils import formatdate

    client = gmail_provider_from_args(args)
    client.authenticate()
    mid, thread_id = select_message_id(args, client)
    if not mid:
        print("No message found. Provide --id or a --query with --latest.")
        return 1

    # Fetch headers for reply context
    msg_full = client.get_message(mid, fmt="full")
    headers = {h.get("name", "").lower(): h.get("value", "") for h in ((msg_full.get("payload") or {}).get("headers") or [])}
    orig_subj = headers.get("subject", "")
    msg_id = headers.get("message-id")
    refs = headers.get("references")
    reply_to = headers.get("reply-to") or headers.get("from") or ""
    _, to_email = __import__("email.utils").utils.parseaddr(reply_to)
    if not to_email:
        print("Could not determine recipient from original message headers")
        return 1

    profile = None
    try:
        profile = client.get_profile()
    except Exception:
        profile = {"emailAddress": ""}
    from_email = profile.get("emailAddress") or "me"

    # Build reply body
    points_text = getattr(args, "points", None) or ""
    plan_path = getattr(args, "points_file", None)
    if plan_path:
        doc = load_config(plan_path)
        goals = doc.get("goals") or doc.get("points") or []
        if isinstance(goals, list):
            points_text = points_text or "\n".join(f"- {g}" for g in goals if g)
        if not getattr(args, "signoff", None) and doc.get("signoff"):
            args.signoff = str(doc.get("signoff"))

    body_lines = []
    if points_text:
        pts = [ln.strip() for ln in str(points_text).splitlines() if ln.strip()]
        if len(pts) == 1 and not pts[0].startswith("-"):
            body_lines.append(pts[0])
        else:
            body_lines.append("Here are the points:")
            body_lines.extend([f"- {p.lstrip('-').strip()}" for p in pts])

    if getattr(args, "include_summary", False):
        orig_text = client.get_message_text(mid)
        summ = summarize_text(orig_text, max_words=80)
        body_lines.insert(0, f"Summary: {summ}")

    signoff = getattr(args, "signoff", None) or "Thanks,"
    body_lines.append("")
    body_lines.append(signoff)

    # Compose message
    subject = getattr(args, "subject", None) or orig_subj
    include_quote = bool(getattr(args, "include_quote", False))
    original_text = client.get_message_text(mid) if include_quote else None
    msg = _compose_reply(
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        body_text="\n".join(body_lines).strip(),
        in_reply_to=msg_id,
        references=(f"{refs} {msg_id}".strip() if msg_id else refs),
        cc=[str(x) for x in getattr(args, "cc", []) if x],
        bcc=[str(x) for x in getattr(args, "bcc", []) if x],
        include_quote=include_quote,
        original_text=original_text,
    )
    # Date for better previews
    msg["Date"] = formatdate(localtime=True)

    raw = encode_email_message(msg)
    # Planning path
    if getattr(args, "plan", False):
        when = None
        if getattr(args, "send_at", None):
            when = str(getattr(args, "send_at"))
        elif getattr(args, "send_in", None):
            when = str(getattr(args, "send_in"))
        print("Plan: reply")
        print(f"  to: {to_email}")
        if args.cc:
            print(f"  cc: {', '.join(args.cc)}")
        if args.bcc:
            print(f"  bcc: {', '.join(args.bcc)}")
        print(f"  subject: {'Re: ' + orig_subj if not getattr(args, 'subject', None) else args.subject}")
        if when:
            print(f"  when: {when}")
        print("  action: send (with --apply) or create draft (--create-draft)")
        return 0
    # Scheduling support
    send_at = getattr(args, "send_at", None)
    send_in = getattr(args, "send_in", None)
    if send_at or send_in:
        from ..scheduler import parse_send_at, parse_send_in, enqueue, ScheduledItem
        import base64
        due = None
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
        # Also write preview if requested
        draft_out = getattr(args, "draft_out", None)
        if draft_out:
            p = Path(draft_out)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(raw)
            print(f"Draft written to {p}")
        return 0

    if getattr(args, "apply", False):
        client.send_message_raw(raw, thread_id=thread_id)
        print(f"Sent reply to {to_email} (thread {thread_id or 'new'})")
        return 0

    if getattr(args, "create_draft", False):
        d = client.create_draft_raw(raw, thread_id=thread_id)
        did = (d or {}).get('id') or '(draft id unavailable)'
        print(f"Created Gmail draft id={did}")
        return 0

    draft_out = getattr(args, "draft_out", None)
    if draft_out:
        p = Path(draft_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        print(f"Draft written to {p}")
    else:
        # Preview to stdout
        text = raw.decode("utf-8", errors="replace")
        head = "\n".join(text.splitlines()[:20])
        print(head)
        print("... (preview; use --draft-out to write .eml or --apply to send)")
    return 0


def run_messages_apply_scheduled(args) -> int:
    """Apply scheduled messages that are due."""
    from ..scheduler import pop_due
    from ..utils.cli_helpers import gmail_provider_from_args
    import base64

    sent = 0
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
            raw = base64.b64decode(it.get("raw_b64") or b"")
            thread_id = it.get("thread_id")
            client.send_message_raw(raw, thread_id=thread_id)
            sent += 1
            to = it.get("to") or "recipient"
            subj = it.get("subject") or ""
            print(f"Sent scheduled message to {to} subject='{subj}' profile={prof}")
    print(f"Scheduled send complete. Sent: {sent}")
    return 0
