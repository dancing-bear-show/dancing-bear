"""Copilot reviewer helpers: select its open threads, request a re-review.

Selection works on the ``threads.json`` document from ``fetch_review_threads``
so every caller sees the same, fully paginated thread list. A thread counts as
Copilot's only when its opening comment is a bot *and* its login normalises to
``COPILOT_LOGIN`` — the typed bot marker decides, the login only narrows.

``COPILOT_REVIEW_ENV`` is a kill switch for re-review requests (e.g. during a
Copilot outage), so callers can skip the request without editing workflows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from core.gh_cli import GhCLI, GhError

from .authors import COPILOT_LOGIN, normalize_login

#: Env switch: 0/false/no/off disables re-review requests; unset means enabled.
COPILOT_REVIEW_ENV = "DANCING_BEAR_COPILOT_REVIEW"

#: REST spelling of the reviewer, which ``requested_reviewers`` requires.
COPILOT_REVIEWER_REST = f"{COPILOT_LOGIN}[bot]"

_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class CopilotSwitch:
    """Whether re-review requests are enabled, plus any config warning."""

    enabled: bool
    warning: str | None = None


def copilot_review_switch(environ: dict[str, str] | None = None) -> CopilotSwitch:
    """Read ``COPILOT_REVIEW_ENV``. Unrecognised values stay enabled, with a warning.

    Defaulting to ON keeps a typo from silently disabling reviews; the warning
    keeps a typo in an intended kill switch visible.
    """
    env = os.environ if environ is None else environ
    raw = (env.get(COPILOT_REVIEW_ENV) or "").strip()
    value = raw.lower()
    if not value or value in _TRUE_VALUES:
        return CopilotSwitch(True)
    if value in _FALSE_VALUES:
        return CopilotSwitch(False)
    return CopilotSwitch(
        True,
        f"unrecognised {COPILOT_REVIEW_ENV}={raw!r}; treating as enabled "
        "(0/false/no/off disables)",
    )


def is_copilot_thread(entry: dict[str, Any]) -> bool:
    """True for a resolvable GraphQL thread opened by the Copilot reviewer."""
    if entry.get("source") != "graphql-thread" or not entry.get("thread_id"):
        return False
    comments = entry.get("comments") or []
    if not comments:
        return False
    opening = comments[0]
    return opening.get("author_kind") == "bot" and normalize_login(opening.get("author")) == COPILOT_LOGIN


def copilot_threads(doc: dict[str, Any], *, include_resolved: bool = False) -> list[dict[str, Any]]:
    """Copilot-opened thread entries from a ``threads.json`` document.

    Raises on a truncated document: acting on a partial list would present an
    incomplete run as complete.
    """
    if doc.get("truncated"):
        raise GhError("review-thread fetch incomplete (reported counts did not match); rerun")
    return [
        e for e in doc.get("threads") or []
        if is_copilot_thread(e) and (include_resolved or not e.get("is_resolved"))
    ]


def request_copilot_review(gh: GhCLI, owner: str, repo: str, pr: int) -> list[str]:
    """Request a Copilot review on ``owner/repo#pr``; return the requested reviewer logins.

    Uses REST ``requested_reviewers``, which also re-requests after Copilot has
    already reviewed. A non-2xx response (including 422) raises: GitHub returns
    422 for several distinct refusals, so it is never read as success.
    """
    data = gh.api_post(
        f"repos/{owner}/{repo}/pulls/{int(pr)}/requested_reviewers",
        {"reviewers": [COPILOT_REVIEWER_REST]},
    )
    if data.get("number") is None:
        raise GhError(f"review request on PR #{pr} returned no pull request")
    return [
        str(r.get("login") or "") for r in data.get("requested_reviewers") or []
        if isinstance(r, dict)
    ]
