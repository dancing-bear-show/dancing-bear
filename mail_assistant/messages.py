from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Tuple


def _parse_addr(addr: str) -> Tuple[str, str]:
    """Return (name, email) from a header value like 'Name <email@example.com>'."""
    from email.utils import parseaddr

    name, email = parseaddr(addr or "")
    return name, email


def _compose_reply(
    *,
    from_email: str,
    to_email: str,
    subject: str,
    body_text: str,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
    include_quote: bool = False,
    original_text: Optional[str] = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    if cc:
        msg["Cc"] = ", ".join(cc)
    if subject.lower().startswith("re:"):
        msg["Subject"] = subject
    else:
        msg["Subject"] = f"Re: {subject}"
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    content = body_text or ""
    if include_quote and (original_text or "").strip():
        content = f"{content}\n\nOn previous message:\n> " + "\n> ".join((original_text or "").splitlines())
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

