from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any


@dataclass
class ReplyEnvelope:
    """Envelope addresses and subject for a reply message."""

    from_email: str
    to_email: str
    subject: str
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)


@dataclass
class ReplyOptions:
    """Threading and quoting options for a reply message."""

    in_reply_to: str | None = None
    references: str | None = None
    include_quote: bool = False
    original_text: str | None = None


def _parse_addr(addr: str) -> tuple[str, str]:
    """Return (name, email) from a header value like 'Name <email@example.com>'."""
    from email.utils import parseaddr

    name, email = parseaddr(addr or "")
    return name, email


def _compose_reply(
    *,
    envelope: ReplyEnvelope,
    body_text: str,
    options: ReplyOptions | None = None,
) -> EmailMessage:
    opts = options or ReplyOptions()
    msg = EmailMessage()
    msg["From"] = envelope.from_email
    msg["To"] = envelope.to_email
    if envelope.cc:
        msg["Cc"] = ", ".join(envelope.cc)
    if envelope.bcc:
        msg["Bcc"] = ", ".join(envelope.bcc)
    if envelope.subject.lower().startswith("re:"):
        msg["Subject"] = envelope.subject
    else:
        msg["Subject"] = f"Re: {envelope.subject}"
    if opts.in_reply_to:
        msg["In-Reply-To"] = opts.in_reply_to
    if opts.references:
        msg["References"] = opts.references

    content = body_text or ""
    if opts.include_quote and (opts.original_text or "").strip():
        content = f"{content}\n\nOn previous message:\n> " + "\n> ".join((opts.original_text or "").splitlines())
    msg.set_content(content)
    return msg


@dataclass
class Candidate:
    id: str
    thread_id: str | None
    from_header: str
    subject: str
    snippet: str
    to_header: str = ""
    date: str = ""
    labels: list[str] = field(default_factory=list)
    unread: bool = False


def _internal_date_to_iso(ms: Any) -> str:
    """Return an ISO-8601 UTC timestamp for Gmail's epoch-millisecond internalDate.

    Returns "" when the value is missing or not coercible to an integer.
    """
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def candidates_from_metadata(msgs: list[dict[str, Any]]) -> list[Candidate]:
    out: list[Candidate] = []
    for m in msgs:
        payload = m.get("payload") or {}
        headers = {h.get("name", "").lower(): h.get("value", "") for h in (payload.get("headers") or [])}
        labels = [str(x) for x in (m.get("labelIds") or [])]
        out.append(
            Candidate(
                id=m.get("id", ""),
                thread_id=m.get("threadId"),
                from_header=headers.get("from", ""),
                subject=headers.get("subject", ""),
                snippet=(m.get("snippet") or "").strip(),
                to_header=headers.get("to", ""),
                date=_internal_date_to_iso(m.get("internalDate")),
                labels=labels,
                unread="UNREAD" in labels,
            )
        )
    return out


def encode_email_message(msg: EmailMessage) -> bytes:
    return msg.as_bytes()

