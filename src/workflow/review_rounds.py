"""Fetch PR review-round data and write per-PR JSON + summary.

A "bot round" is one distinct commit OID against which a bot submitted a review.
Bot classification uses author.__typename == "Bot" — never login-string matching.

Threads are assigned to a round by their first comment's originalCommit.oid.
Threads whose first comment's commit is not in any bot round get round=null and
are counted separately as unplaced_threads (excluded from both round0 and later).

Writes ``<out-dir>/pr<N>.json`` and ``<out-dir>/summary.json``.
Exit 1 on any API failure or truncated pagination (partial data is never
reported as complete).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_BODY_MAX = 1500
_REPLY_MAX = 400
_REPLY_COUNT = 3
_COMMIT_PAGE_REST = 100  # REST commit list, per page


# ---------------------------------------------------------------------------
# Internal data shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RoundEntry:
    round: int
    commit: str
    headline: str


@dataclass
class ThreadEntry:
    thread_id: str
    round: int | None
    commit: str | None
    path: str
    line: int | None
    outdated: bool
    resolved: bool
    author_kind: str
    body: str
    replies: list[str] = field(default_factory=list)


@dataclass
class PRRounds:
    pr: int
    title: str
    rounds: list[RoundEntry]
    threads: list[ThreadEntry]
    review_bodies_count: int
    truncated: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_bot(author: Any) -> bool:
    """Classify by __typename, never by login."""
    if not isinstance(author, dict):
        return False
    return author.get("__typename") == "Bot"


def _author_kind(comments: list[Any]) -> str:
    """Return 'bot' if the first comment's author is a Bot, else 'human'."""
    if not comments:
        return "human"
    return "bot" if _is_bot(comments[0].get("author")) else "human"


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


# ---------------------------------------------------------------------------
# Fetch commit headlines (REST)
# ---------------------------------------------------------------------------

def _fetch_commit_headlines(
    gh: Any,
    owner: str,
    repo: str,
    pr: int,
) -> tuple[dict[str, str], bool]:
    """Fetch all commits on a PR; return (oid -> headline, truncated).

    Uses REST pagination via api_paginated. A PR can have 40+ commits.
    """
    from core.gh_cli import GhError
    path = f"repos/{owner}/{repo}/pulls/{pr}/commits?per_page={_COMMIT_PAGE_REST}"
    try:
        items = gh.api_paginated(path)
    except GhError:
        return {}, True
    headlines: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        sha = item.get("sha") or ""
        msg = ""
        commit_obj = item.get("commit")
        if isinstance(commit_obj, dict):
            full_msg = commit_obj.get("message") or ""
            msg = full_msg.splitlines()[0] if full_msg else ""
        if sha:
            headlines[sha] = msg
    return headlines, False


# ---------------------------------------------------------------------------
# Build PR rounds structure
# ---------------------------------------------------------------------------

def _extract_bot_rounds(
    review_nodes: list[Any],
) -> tuple[list[str], int]:
    """Return (ordered round OIDs, bot_review_bodies) from review nodes.

    Bot rounds are ordered by their earliest submittedAt.
    bot_review_bodies counts bot reviews that have a non-empty body.
    """
    seen_oids: dict[str, str] = {}  # oid -> earliest submittedAt
    bot_review_bodies = 0
    for node in review_nodes:
        author = node.get("author") or {}
        if not _is_bot(author):
            continue
        body = (node.get("body") or "").strip()
        if body:
            bot_review_bodies += 1
        commit = node.get("commit") or {}
        oid = commit.get("oid") or ""
        if not oid:
            continue
        submitted_at = node.get("submittedAt") or ""
        if oid not in seen_oids or submitted_at < seen_oids[oid]:
            seen_oids[oid] = submitted_at
    ordered = sorted(seen_oids, key=lambda o: seen_oids[o])
    return ordered, bot_review_bodies


def _first_comment_oid(node: Any) -> str:
    """Return the originalCommit.oid of the first comment in a thread node, or ''."""
    comments = (node.get("comments") or {}).get("nodes") or []
    if not comments:
        return ""
    orig_commit = comments[0].get("originalCommit")
    if isinstance(orig_commit, dict):
        return orig_commit.get("oid") or ""
    return ""


def _thread_entry(
    node: Any,
    oid_to_round: dict[str, int],
) -> ThreadEntry:
    """Convert one raw thread node into a ThreadEntry."""
    thread_id = node.get("id") or ""
    comments = (node.get("comments") or {}).get("nodes") or []
    first_comment = comments[0] if comments else {}
    first_oid = _first_comment_oid(node)

    round_num = oid_to_round.get(first_oid) if first_oid else None
    return ThreadEntry(
        thread_id=thread_id,
        round=round_num,
        commit=first_oid or None,
        path=node.get("path") or "",
        line=node.get("line") or node.get("originalLine"),
        outdated=bool(node.get("isOutdated")),
        resolved=bool(node.get("isResolved")),
        author_kind=_author_kind(comments),
        body=_truncate(first_comment.get("body") or "", _BODY_MAX),
        replies=[
            _truncate(c.get("body") or "", _REPLY_MAX)
            for c in comments[1 : 1 + _REPLY_COUNT]
        ],
    )


def build_pr_rounds(
    gh: Any,
    owner: str,
    repo: str,
    pr: int,
) -> PRRounds:
    """Fetch and process one PR into a PRRounds structure.

    Uses core.github.threads for paginated, count-checked thread and review
    fetching. Raises GhError on API failure. Sets truncated=True on any
    pagination count mismatch — never silently returns partial data.
    """
    from core.github.threads import fetch_pr_reviews, fetch_raw_threads

    review_nodes, pr_title, reviews_truncated = fetch_pr_reviews(gh, owner, repo, pr)
    ordered_oids, bot_review_bodies = _extract_bot_rounds(review_nodes)
    headlines, commits_truncated = _fetch_commit_headlines(gh, owner, repo, pr)

    rounds = [
        RoundEntry(round=i, commit=oid, headline=headlines.get(oid) or "")
        for i, oid in enumerate(ordered_oids)
    ]
    oid_to_round: dict[str, int] = {r.commit: r.round for r in rounds}

    thread_nodes, threads_truncated = fetch_raw_threads(gh, owner, repo, pr)
    entries = [_thread_entry(node, oid_to_round) for node in thread_nodes]

    return PRRounds(
        pr=pr,
        title=pr_title,
        rounds=rounds,
        threads=entries,
        review_bodies_count=bot_review_bodies,
        truncated=reviews_truncated or threads_truncated or commits_truncated,
    )


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _pr_to_json(result: PRRounds) -> dict[str, Any]:
    return {
        "pr": result.pr,
        "title": result.title,
        "truncated": result.truncated,
        "rounds": [
            {"round": r.round, "commit": r.commit, "headline": r.headline}
            for r in result.rounds
        ],
        "threads": [
            {
                "thread_id": t.thread_id,
                "round": t.round,
                "commit": t.commit,
                "path": t.path,
                "line": t.line,
                "outdated": t.outdated,
                "resolved": t.resolved,
                "author_kind": t.author_kind,
                "body": t.body,
                "replies": t.replies,
            }
            for t in result.threads
        ],
    }


def _pr_summary(result: PRRounds) -> dict[str, Any]:
    total_threads = len(result.threads)
    round0_threads = sum(1 for t in result.threads if t.round == 0)
    later_threads = sum(1 for t in result.threads if t.round is not None and t.round > 0)
    unplaced_threads = sum(1 for t in result.threads if t.round is None)
    later_share = (
        round(later_threads / total_threads, 3) if total_threads else 0.0
    )

    per_round: dict[str, int] = {}
    for t in result.threads:
        if t.round is not None:
            key = str(t.round)
            per_round[key] = per_round.get(key, 0) + 1

    return {
        "pr": result.pr,
        "bot_rounds": len(result.rounds),
        "threads": total_threads,
        "round0_threads": round0_threads,
        "later_threads": later_threads,
        "unplaced_threads": unplaced_threads,
        "later_share": later_share,
        "review_bodies": result.review_bodies_count,
        "per_round": per_round,
        "truncated": result.truncated,
    }


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def run_review_rounds(
    *,
    pr_numbers: list[int],
    out_dir: Path,
    min_threads: int,
    gh: Any,
) -> int:
    """Fetch review-round data for each PR and write JSON files.

    Returns 0 on success, 1 on any API failure or truncated pagination.
    """
    from core.fileutil import atomic_write_json
    from core.gh_cli import GhError
    from core.github.repo import resolve_owner_repo

    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        owner, repo = resolve_owner_repo(gh)
    except GhError as exc:
        print(f"review-rounds: {exc}", file=sys.stderr)
        return 1

    summaries: list[dict[str, Any]] = []
    failed = False

    for pr_num in pr_numbers:
        try:
            result = build_pr_rounds(gh, owner, repo, pr_num)
        except GhError as exc:
            print(f"review-rounds: PR #{pr_num} failed: {exc}", file=sys.stderr)
            failed = True
            continue

        if result.truncated:
            print(
                f"review-rounds: PR #{pr_num} pagination was truncated — "
                "refusing to write partial data",
                file=sys.stderr,
            )
            failed = True
            continue

        pr_path = out_dir / f"pr{pr_num}.json"
        atomic_write_json(pr_path, _pr_to_json(result))
        summaries.append(_pr_summary(result))

    if failed:
        return 1

    # Filter by min_threads and sort descending by threads.
    filtered = [s for s in summaries if s["threads"] >= min_threads]
    filtered.sort(key=lambda s: s["threads"], reverse=True)

    summary_path = out_dir / "summary.json"
    atomic_write_json(summary_path, filtered)
    print(json.dumps(filtered, indent=2))
    return 0


def fetch_recent_prs(
    gh: Any,
    owner: str,
    repo: str,
    days: int,
) -> list[int]:
    """Return PR numbers merged in the last ``days`` days, sorted descending."""
    import datetime

    from core.gh_cli import GhError
    from core.github.pulls import pr_list

    since = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    ).strftime("%Y-%m-%d")
    try:
        prs = pr_list(
            gh,
            fields=["number", "mergedAt"],
            state="merged",
            limit=200,
            search=f"merged:>={since}",
            repo=f"{owner}/{repo}",
        )
    except GhError as exc:
        raise GhError(f"fetching recent PRs: {exc}") from exc
    numbers = [p["number"] for p in prs if isinstance(p.get("number"), int)]
    numbers.sort(reverse=True)
    return numbers
