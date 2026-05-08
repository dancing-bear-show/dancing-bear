from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ReplyEnvelope:
    """Envelope addresses and subject for a reply message."""

    from_email: str
    to_email: str
    subject: str
    cc: List[str] = field(default_factory=list)
    bcc: List[str] = field(default_factory=list)


@dataclass
class ReplyOptions:
    """Threading and quoting options for a reply message."""

    in_reply_to: Optional[str] = None
    references: Optional[str] = None
    include_quote: bool = False
    original_text: Optional[str] = None


def _parse_addr(addr: str) -> Tuple[str, str]:
    """Return (name, email) from a header value like 'Name <email@example.com>'."""
    from email.utils import parseaddr

    name, email = parseaddr(addr or "")
    return name, email


def _compose_reply(
    *,
    envelope: ReplyEnvelope,
    body_text: str,
    options: Optional[ReplyOptions] = None,
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
    thread_id: Optional[str]
    from_header: str
    subject: str
    snippet: str


def candidates_from_metadata(msgs: List[Dict[str, Any]]) -> List[Candidate]:
    out: List[Candidate] = []
    for m in msgs:
        payload = m.get("payload") or {}
        headers = {h.get("name", "").lower(): h.get("value", "") for h in (payload.get("headers") or [])}
        out.append(
            Candidate(
                id=m.get("id", ""),
                thread_id=m.get("threadId"),
                from_header=headers.get("from", ""),
                subject=headers.get("subject", ""),
                snippet=(m.get("snippet") or "").strip(),
            )
        )
    return out


def encode_email_message(msg: EmailMessage) -> bytes:
    return msg.as_bytes()

