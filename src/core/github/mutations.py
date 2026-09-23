"""Reply to and resolve PR review threads, verifying that each one landed.

``gh`` exits 0 on an HTTP 200 whose body carries a GraphQL ``errors`` array, so
a failed mutation is indistinguishable from a successful one by exit status.
Every function here checks the response payload instead, and raises
``GhError`` when the effect it asked for is not visible in it.

Reply before resolve, always. A thread resolved without its reply is a silent
closure: the reviewer sees the concern dismissed with no explanation.
"""

from __future__ import annotations

import re
from typing import Any

from core.gh_cli import GhCLI, GhError

from .authors import normalize_login

REPLY_MUTATION = """
mutation($threadId: ID!, $body: String!) {
  addPullRequestReviewThreadReply(input: {pullRequestReviewThreadId: $threadId, body: $body}) {
    comment { id url }
  }
}
"""

RESOLVE_MUTATION = """
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { id isResolved }
  }
}
"""

RUN_MARKER = "<!-- dancing-bear-run: {run_id} -->"

#: Any run marker, whatever its run id or spacing. Used to strip markers out of
#: reply text before this run's own is appended.
_ANY_RUN_MARKER = re.compile(r"<!--\s*dancing-bear-run:.*?-->", re.S)

VIEWER_QUERY = "query { viewer { login } }"


def run_marker(run_id: str) -> str:
    """The invisible line a reply carries so a retry can recognise it."""
    return RUN_MARKER.format(run_id=run_id)


def viewer_login(gh: GhCLI) -> str:
    """Login of the account gh is authenticated as; raises when unknown.

    Fails closed: an empty actor matches no comment, so every retry would
    re-post its replies as duplicates.
    """
    data = gh.graphql_checked(VIEWER_QUERY)
    login = ((data.get("viewer") or {}).get("login") or "").strip()
    if not login:
        raise GhError("could not resolve the authenticated GitHub actor")
    return login


def _marked(comments: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    marker = run_marker(run_id)
    return [c for c in comments if marker in (c.get("body") or "")]


def has_run_marker(comments: list[dict[str, Any]], run_id: str, *, actor: str) -> bool:
    """True when a comment by ``actor`` in the chain carries this run's marker.

    Searches the whole chain: a reviewer may have commented after our reply, so
    "is the latest comment ours" misses exactly the retry this guards.

    Both conditions are required. The marker alone is forgeable — it is
    plaintext, and the run id is public once the first reply posts, so anyone
    can paste it into a thread to suppress the reply this run owes there.
    Authorship alone is not specific — the same account posts for other runs.
    """
    me = normalize_login(actor)
    return any(normalize_login(c.get("author")) == me for c in _marked(comments, run_id))


def forged_run_marker(comments: list[dict[str, Any]], run_id: str, *, actor: str) -> bool:
    """True when someone other than ``actor`` posted this run's marker."""
    me = normalize_login(actor)
    return any(normalize_login(c.get("author")) != me for c in _marked(comments, run_id))


def strip_run_markers(body: str) -> str:
    """Remove every run marker from ``body``.

    Reply text is composed from reviewer-influenced material and may quote a
    comment. A quoted marker posted by our own account would satisfy both
    halves of ``has_run_marker`` and suppress the reply on whatever thread and
    run it names.
    """
    return _ANY_RUN_MARKER.sub("", body)


def mark_body(body: str, run_id: str | None) -> str:
    """Strip any markers from ``body``, then append this run's (if any)."""
    clean = strip_run_markers(body).rstrip()
    return f"{clean}\n\n{run_marker(run_id)}" if run_id else clean


def reply_to_thread(gh: GhCLI, thread_id: str, body: str) -> dict[str, str]:
    """Post ``body`` as a reply inside the thread; return its id and url.

    ``body`` is review-derived text and is sent as a string field (``-f``):
    through ``-F`` a value starting ``@/path`` would be read as a local file
    and its contents posted. ``field_args`` chooses the flag by Python type.
    """
    if not isinstance(body, str) or not body.strip():
        raise GhError(f"refusing to post an empty reply to {thread_id}")
    data = gh.graphql_checked(REPLY_MUTATION, {"threadId": str(thread_id), "body": body})
    comment = ((data.get("addPullRequestReviewThreadReply") or {}).get("comment")) or {}
    if not comment.get("id"):
        raise GhError(f"reply to {thread_id} returned no comment id")
    return {"comment_id": str(comment["id"]), "url": str(comment.get("url") or "")}


def resolve_thread(gh: GhCLI, thread_id: str) -> None:
    """Resolve the thread, raising unless the response shows it resolved."""
    data = gh.graphql_checked(RESOLVE_MUTATION, {"threadId": str(thread_id)})
    thread = ((data.get("resolveReviewThread") or {}).get("thread")) or {}
    if thread.get("isResolved") is not True:
        raise GhError(f"resolve of {thread_id} did not report isResolved: true")


def reply_and_resolve(gh: GhCLI, thread_id: str, body: str) -> dict[str, Any]:
    """Reply, then resolve only if the reply verifiably landed.

    Returns ``{"reply": {...}, "resolved": bool, "error": str | None}``. A
    failed reply propagates as ``GhError`` and nothing is resolved; a failed
    resolve after a good reply is reported, not raised, because the reply is
    already public and the caller must record it.
    """
    reply = reply_to_thread(gh, thread_id, body)
    try:
        resolve_thread(gh, thread_id)
    except GhError as exc:
        return {"reply": reply, "resolved": False, "error": str(exc)}
    return {"reply": reply, "resolved": True, "error": None}
