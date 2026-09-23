"""Tested GitHub access: review threads, replies, resolution, repo identity.

The single implementation behind ``./bin/github``, ``bin/pr-assistant``, and the
workflow stages that used to re-specify these calls as prose. Everything goes
through ``core.gh_cli.GhCLI``; construct it with ``client()`` so a stale
``GITHUB_TOKEN`` cannot silently override gh's own credentials.
"""

from __future__ import annotations

from core.gh_cli import GhCLI, GhError

from .authors import classify_author, normalize_login
from .mutations import (
    forged_run_marker,
    has_run_marker,
    mark_body,
    reply_and_resolve,
    reply_to_thread,
    resolve_thread,
    run_marker,
    strip_run_markers,
    viewer_login,
)
from .repo import resolve_owner_repo
from .threads import (
    build_threads_doc,
    fetch_review_threads,
    fetch_thread_comments,
    render_summary,
)

__all__ = [
    "GhCLI",
    "GhError",
    "build_threads_doc",
    "classify_author",
    "client",
    "fetch_review_threads",
    "fetch_thread_comments",
    "forged_run_marker",
    "has_run_marker",
    "mark_body",
    "normalize_login",
    "render_summary",
    "reply_and_resolve",
    "reply_to_thread",
    "resolve_owner_repo",
    "resolve_thread",
    "run_marker",
    "strip_run_markers",
    "viewer_login",
]


def client() -> GhCLI:
    """A GhCLI that ignores an exported ``GITHUB_TOKEN``."""
    return GhCLI(scrub_github_token=True)
