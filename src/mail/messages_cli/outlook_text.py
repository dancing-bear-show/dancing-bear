"""Body-text extraction for Outlook (Microsoft Graph) messages.

Used only by the Outlook ``messages get``/``messages summarize`` paths. The
Graph message shape differs from Gmail's MIME payload, so the Gmail-side
``get_message_text`` cannot be reused directly.
"""

from __future__ import annotations

from typing import Any


def outlook_message_text(msg: dict[str, Any] | None) -> str:
    """Return readable plain text for a Graph message.

    Prefers ``body.content``, converting HTML to text and stripping the CSS
    boilerplate transactional senders leave behind. Falls back to
    ``bodyPreview`` when the body is absent or empty.

    Any ``contentType`` other than ``text`` is treated as HTML: Graph documents
    only ``html`` and ``text``, and running the HTML path over plain text is
    harmless, whereas the reverse leaks markup.
    """
    from core.text_utils import html_to_text, strip_css_boilerplate

    if not msg:
        return ""

    body = msg.get("body") or {}
    content = (body.get("content") or "").strip()
    if content:
        content_type = str(body.get("contentType") or "html").lower()
        text = content if content_type == "text" else html_to_text(content)
        text = strip_css_boilerplate(text).strip()
        if text:
            return text

    return (msg.get("bodyPreview") or "").strip()
