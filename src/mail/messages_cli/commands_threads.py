"""Thread command orchestration helpers.

`threads-get` fetches every message in a conversation. It reuses the `Candidate`
dataclass from `..messages` rather than defining a parallel thread-message type:
`threads().get(format="metadata")` returns `messages[]` in exactly the shape
`candidates_from_metadata` already parses, so a separate dataclass would only add
another place for fields to get dropped.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any

from ..messages import Candidate

_THREAD_ID_REQUIRED = "--thread-id, --id or --query is required"
_OUTLOOK_UNSUPPORTED = "threads-get is Gmail-only; Outlook profiles are not supported"


@dataclass
class ThreadMessage:
    """A thread message: the shared `Candidate` plus an optional decoded body."""

    candidate: Candidate
    body: str = ""

    def to_dict(self, *, include_body: bool) -> dict[str, Any]:
        c = self.candidate
        out: dict[str, Any] = {
            "id": c.id,
            "thread_id": c.thread_id,
            "subject": c.subject,
            "from_header": c.from_header,
            "to_header": c.to_header,
            "date": c.date,
            "snippet": c.snippet,
            "labels": list(c.labels),
            "unread": c.unread,
        }
        if include_body:
            out["body"] = self.body
        return out


@dataclass
class ThreadResult:
    """A resolved thread and its messages."""

    thread_id: str
    messages: list[ThreadMessage] = field(default_factory=list)

    def to_dict(self, *, include_body: bool) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "message_count": len(self.messages),
            "messages": [m.to_dict(include_body=include_body) for m in self.messages],
        }


def resolve_thread_id(args: argparse.Namespace, client) -> str | None:
    """Resolve a thread id from --thread-id, or via --id / --query lookup."""
    from .commands import select_message_id

    thread_id = (getattr(args, "thread_id", None) or "").strip()
    if thread_id:
        return thread_id
    _msg_id, resolved = select_message_id(args, client)
    return resolved or None


def _thread_messages(client, thread: dict[str, Any], *, include_body: bool) -> list[ThreadMessage]:
    """Build ThreadMessage entries from a raw thread payload."""
    from ..messages import candidates_from_metadata

    raw = thread.get("messages") or []
    out: list[ThreadMessage] = []
    for cand in candidates_from_metadata(raw):
        body = ""
        if include_body and cand.id:
            try:
                body = client.get_message_text(cand.id)
            except Exception as exc:  # nosec B110 - a body failure must not drop the message
                print(f"Warning: could not read body for '{cand.id}': {exc}", file=sys.stderr)
        out.append(ThreadMessage(candidate=cand, body=body))
    return out


def _print_thread_text(result: ThreadResult, *, include_body: bool) -> None:
    """Print a thread in human/LLM-readable text form."""
    print(f"Thread: {result.thread_id}")
    print(f"Messages: {len(result.messages)}")
    for idx, msg in enumerate(result.messages, start=1):
        c = msg.candidate
        print()
        print(f"[{idx}/{len(result.messages)}] {c.id}")
        print(f"Date: {c.date}")
        print(f"From: {c.from_header}")
        print(f"To: {c.to_header}")
        print(f"Subject: {c.subject}")
        if include_body:
            print()
            print(msg.body)
        elif c.snippet:
            print(f"Snippet: {c.snippet}")


def run_messages_threads_get(args) -> int:
    """Fetch all messages in a conversation."""
    import json

    from ..utils.cli_helpers import gmail_provider_from_args, is_outlook_profile

    if is_outlook_profile(getattr(args, "profile", None)):
        print(_OUTLOOK_UNSUPPORTED, file=sys.stderr)
        return 1

    client = gmail_provider_from_args(args)
    client.authenticate()

    thread_id = resolve_thread_id(args, client)
    if not thread_id:
        print(_THREAD_ID_REQUIRED, file=sys.stderr)
        return 1

    try:
        thread = client.get_thread(thread_id, fmt="metadata")
    except Exception as exc:
        # This group collapses every failure to 1, including not-found, rather
        # than letting NotFoundError propagate its own exit code (6).
        print(f"Failed to fetch thread '{thread_id}': {exc}", file=sys.stderr)
        return 1

    include_body = bool(getattr(args, "include_body", False))
    result = ThreadResult(
        thread_id=thread.get("id") or thread_id,
        messages=_thread_messages(client, thread, include_body=include_body),
    )

    if getattr(args, "json", False):
        print(json.dumps(result.to_dict(include_body=include_body), ensure_ascii=False, indent=2))
    else:
        _print_thread_text(result, include_body=include_body)
    return 0
