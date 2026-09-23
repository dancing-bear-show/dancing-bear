"""Reply to and resolve PR review threads, verifying that each one landed.

``gh`` exits 0 on an HTTP 200 whose body carries a GraphQL ``errors`` array, so
a failed mutation is indistinguishable from a successful one by exit status.
Every function here checks the response payload instead, and raises
``GhError`` when the effect it asked for is not visible in it.

Reply before resolve, always. A thread resolved without its reply is a silent
closure: the reviewer sees the concern dismissed with no explanation.
"""

from __future__ import annotations

from typing import Any

from core.gh_cli import GhCLI, GhError

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


def run_marker(run_id: str) -> str:
    """The invisible line a reply carries so a retry can recognise it."""
    return RUN_MARKER.format(run_id=run_id)


def has_run_marker(comments: list[dict[str, Any]], run_id: str) -> bool:
    """True when any comment in the chain already carries this run's marker.

    Searches the whole chain: a reviewer may have commented after our reply, so
    "is the latest comment ours" misses exactly the retry this guards.
    """
    marker = run_marker(run_id)
    return any(marker in (c.get("body") or "") for c in comments)


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
