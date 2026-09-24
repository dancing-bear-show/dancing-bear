"""Fetch PR review-round data and write per-PR JSON + summary.

A "round" is one distinct commit OID against which the Copilot pull-request
reviewer submitted a review. Other bots (github-code-quality, github-actions)
do not open rounds; their reviews are counted per PR as ``other_bot_reviews``.
Copilot is identified with ``core.github.authors.is_copilot_reviewer`` (bot by
``__typename`` AND Copilot's login), never by a login match alone.

Threads are assigned to a round by their first comment's originalCommit.oid.
Threads whose first comment's commit is not in any round get round=null and
are counted separately as unplaced_threads (excluded from both round0 and later).

Writes ``<out-dir>/pr<N>.json`` and ``<out-dir>/summary.json``. A stale
``summary.json`` is deleted before anything is fetched, so a failed run never
leaves an earlier run's summary looking current.
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
#: GitHub's REST ``pulls/{n}/commits`` endpoint never returns more than this.
_REST_COMMIT_CAP = 250

#: Default --min-threads floor, applied only to a --recent scan.
DEFAULT_MIN_THREADS = 15
#: Upper bound for --recent: one ``gh pr list`` call, count-checked.
RECENT_MAX = 200


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
    original_line: int | None
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
    other_bot_reviews: int = 0
    truncated_parts: list[str] = field(default_factory=list)

    @property
    def truncated(self) -> bool:
        return bool(self.truncated_parts)


@dataclass(frozen=True)
class _ReviewScan:
    """What the review list says about rounds, once classified by author."""

    round_oids: list[str]
    review_bodies: int
    other_bot_reviews: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_bot(author: Any) -> bool:
    """Classify with the shared helper, typed field first, never login alone."""
    from core.github.authors import classify_author

    if not isinstance(author, dict):
        return False
    return classify_author(author.get("login"), typename=author.get("__typename")) == "bot"


def _is_copilot(author: Any) -> bool:
    from core.github.authors import is_copilot_reviewer

    if not isinstance(author, dict):
        return False
    return is_copilot_reviewer(author.get("login"), typename=author.get("__typename"))


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
    expected: int | None,
) -> tuple[dict[str, str], bool]:
    """Fetch all commits on a PR; return (oid -> headline, truncated).

    Raises GhError on API failure; that is an API failure, not a truncation.
    ``truncated`` is True when the listing disagrees with ``expected`` (the
    PR's GraphQL commit count) or ``expected`` is unknown. REST lists at most
    250 commits, so a longer PR always reports truncated.
    """
    path = f"repos/{owner}/{repo}/pulls/{pr}/commits?per_page={_COMMIT_PAGE_REST}"
    items = gh.api_paginated(path)
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
    truncated = expected is None or len(items) != expected or expected > _REST_COMMIT_CAP
    return headlines, truncated


# ---------------------------------------------------------------------------
# Build PR rounds structure
# ---------------------------------------------------------------------------

def _extract_bot_rounds(review_nodes: list[Any]) -> _ReviewScan:
    """Classify review nodes into Copilot rounds and other-bot counts.

    Only Copilot reviews open a round; rounds are ordered by their earliest
    submittedAt. ``review_bodies`` counts bot reviews (any bot) with a
    non-empty body. ``other_bot_reviews`` counts reviews by bots other than
    Copilot, which never open a round.
    """
    seen_oids: dict[str, str] = {}  # oid -> earliest submittedAt
    bot_review_bodies = 0
    other_bot_reviews = 0
    for node in review_nodes:
        author = node.get("author") or {}
        if not _is_bot(author):
            continue
        if (node.get("body") or "").strip():
            bot_review_bodies += 1
        if not _is_copilot(author):
            other_bot_reviews += 1
            continue
        oid = (node.get("commit") or {}).get("oid") or ""
        submitted_at = node.get("submittedAt") or ""
        if oid and (oid not in seen_oids or submitted_at < seen_oids[oid]):
            seen_oids[oid] = submitted_at
    ordered = sorted(seen_oids, key=lambda o: seen_oids[o])
    return _ReviewScan(ordered, bot_review_bodies, other_bot_reviews)


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
    """Convert one raw thread node into a ThreadEntry.

    ``line`` (current; null once the thread is outdated) and ``original_line``
    (the line in ``commit``) are kept separate: they refer to different
    revisions of the file and must never be merged.
    """
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
        line=node.get("line"),
        original_line=node.get("originalLine"),
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
    fetching. Raises GhError on API failure. Records each connection whose
    count disagrees in ``truncated_parts`` — never silently returns partial data.
    """
    from core.github.threads import fetch_pr_reviews, fetch_raw_threads

    reviews = fetch_pr_reviews(gh, owner, repo, pr)
    scan = _extract_bot_rounds(reviews.nodes)
    headlines, commits_truncated = _fetch_commit_headlines(
        gh, owner, repo, pr, reviews.commit_count
    )

    rounds = [
        RoundEntry(round=i, commit=oid, headline=headlines.get(oid) or "")
        for i, oid in enumerate(scan.round_oids)
    ]
    oid_to_round: dict[str, int] = {r.commit: r.round for r in rounds}

    thread_nodes, threads_truncated = fetch_raw_threads(gh, owner, repo, pr)
    entries = [_thread_entry(node, oid_to_round) for node in thread_nodes]

    parts = [
        name
        for name, short in (
            ("reviews", reviews.truncated),
            ("threads", threads_truncated),
            (f"commits (REST lists at most {_REST_COMMIT_CAP})", commits_truncated),
        )
        if short
    ]
    return PRRounds(
        pr=pr,
        title=reviews.title,
        rounds=rounds,
        threads=entries,
        review_bodies_count=scan.review_bodies,
        other_bot_reviews=scan.other_bot_reviews,
        truncated_parts=parts,
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
                "original_line": t.original_line,
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
        "other_bot_reviews": result.other_bot_reviews,
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
    summary_path = out_dir / "summary.json"
    summary_path.unlink(missing_ok=True)

    try:
        owner, repo = resolve_owner_repo(gh)
    except GhError as exc:
        print(f"review-rounds: {exc}", file=sys.stderr)
        return 1

    summaries: list[dict[str, Any]] = []
    failed = False

    for pr_num in pr_numbers:
        pr_path = out_dir / f"pr{pr_num}.json"
        pr_path.unlink(missing_ok=True)  # a failed fetch must not leave the last run's file
        try:
            result = build_pr_rounds(gh, owner, repo, pr_num)
        except GhError as exc:
            print(f"review-rounds: PR #{pr_num} failed: {exc}", file=sys.stderr)
            failed = True
            continue

        if result.truncated:
            print(
                f"review-rounds: PR #{pr_num} pagination was truncated "
                f"({', '.join(result.truncated_parts)}) — refusing to write partial data",
                file=sys.stderr,
            )
            failed = True
            continue

        atomic_write_json(pr_path, _pr_to_json(result))
        summaries.append(_pr_summary(result))

    if failed:
        return 1

    # Filter by min_threads and sort descending by threads.
    filtered = [s for s in summaries if s["threads"] >= min_threads]
    filtered.sort(key=lambda s: s["threads"], reverse=True)

    atomic_write_json(summary_path, filtered)
    print(json.dumps(filtered, indent=2))
    return 0


def fetch_recent_prs(
    gh: Any,
    owner: str,
    repo: str,
    count: int,
) -> list[int]:
    """Return the ``count`` most recent PR numbers, any state, sorted descending.

    Open, merged and closed PRs all count. The listing is count-checked
    against the repository's PR total: a result shorter than
    ``min(count, total)`` raises GhError rather than passing as complete.
    """
    from core.gh_cli import GhError
    from core.github.pulls import pr_list, pr_total_count

    if not 1 <= count <= RECENT_MAX:
        raise ValueError(f"count must be 1..{RECENT_MAX}, got {count}")
    try:
        total = pr_total_count(gh, owner, repo)
        prs = pr_list(
            gh,
            fields=["number"],
            state="all",
            limit=count,
            repo=f"{owner}/{repo}",
        )
    except GhError as exc:
        raise GhError(f"fetching recent PRs: {exc}") from exc
    numbers = sorted({p["number"] for p in prs if isinstance(p.get("number"), int)}, reverse=True)
    expected = min(count, total)
    if len(numbers) != expected:
        raise GhError(
            f"fetching recent PRs: listing returned {len(numbers)} PRs, "
            f"expected {expected} ({total} in the repository)"
        )
    return numbers
