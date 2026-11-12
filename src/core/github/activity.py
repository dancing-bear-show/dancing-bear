"""The authenticated user's recent GitHub activity: PRs, review requests, issues.

Every search goes through ``gh search`` with filter *flags*, never a composed
query string, so an owner value cannot smuggle in extra qualifiers. A failed
search raises: an empty section must mean "nothing found", not "the call broke".
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from core.gh_cli import GhCLI, GhError

from .mutations import viewer_login

PR_FIELDS = "number,title,repository,updatedAt,url,state,author,isDraft"
ISSUE_FIELDS = "number,title,repository,updatedAt,url,state"
MAX_LIMIT = 100


@dataclass(frozen=True)
class ActivityItem:
    """One PR or issue from a search result."""

    repo: str
    number: int
    title: str
    state: str
    updated_at: str
    url: str
    author: str | None = None
    is_draft: bool = False

    @classmethod
    def from_search(cls, data: dict[str, Any]) -> ActivityItem:
        repo = data.get("repository") or {}
        author = data.get("author")
        login = author.get("login") if isinstance(author, dict) else author
        return cls(
            repo=str(repo.get("nameWithOwner") or "?"),
            number=int(data.get("number") or 0),
            title=str(data.get("title") or ""),
            state=str(data.get("state") or ""),
            updated_at=str(data.get("updatedAt") or ""),
            url=str(data.get("url") or ""),
            author=str(login) if login else None,
            is_draft=bool(data.get("isDraft")),
        )


@dataclass(frozen=True)
class Activity:
    """Activity sections for one user; ``to_dict`` is the CLI's JSON."""

    login: str
    owner: str | None
    authored_prs: list[ActivityItem] = field(default_factory=list)
    review_requests: list[ActivityItem] = field(default_factory=list)
    issues: list[ActivityItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _search(gh: GhCLI, kind: str, flags: list[str], fields: str) -> list[ActivityItem]:
    res = gh.run(["search", kind, *flags, "--json", fields])
    if res.returncode != 0:
        raise GhError(res.stderr or res.stdout or f"gh search {kind} failed")
    try:
        rows = json.loads(res.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise GhError(f"gh search {kind} returned non-JSON output: {exc}") from exc
    if not isinstance(rows, list):
        raise GhError(f"gh search {kind} returned {type(rows).__name__}, expected a list")
    return [ActivityItem.from_search(r) for r in rows if isinstance(r, dict)]


def fetch_activity(gh: GhCLI, *, owner: str | None = None, limit: int = 10) -> Activity:
    """Recent authored PRs, open review requests, and authored issues for ``@me``."""
    n = max(1, min(int(limit), MAX_LIMIT))
    common = ["--sort", "updated", "--order", "desc", "--limit", str(n)]
    if owner:
        common += ["--owner", owner]
    return Activity(
        login=viewer_login(gh),
        owner=owner,
        authored_prs=_search(gh, "prs", ["--author", "@me", *common], PR_FIELDS),
        review_requests=_search(gh, "prs", ["--review-requested", "@me", "--state", "open", *common], PR_FIELDS),
        issues=_search(gh, "issues", ["--author", "@me", *common], ISSUE_FIELDS),
    )


def _section(label: str, items: list[ActivityItem]) -> list[str]:
    lines = [label]
    if not items:
        return [*lines, "  (none)"]
    for i in items:
        draft = " draft" if i.is_draft else ""
        lines.append(f"  - {i.repo} #{i.number} | {i.updated_at} | {i.state}{draft} | {i.title}")
    return lines


def render_activity_text(a: Activity) -> str:
    lines = [f"User: {a.login}" + (f" (owner: {a.owner})" if a.owner else "")]
    lines += _section("My recent PRs:", a.authored_prs)
    lines += _section("Review requests for me:", a.review_requests)
    lines += _section("My recent issues:", a.issues)
    return "\n".join(lines) + "\n"
