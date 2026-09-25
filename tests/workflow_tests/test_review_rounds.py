"""Tests for workflow.review_rounds and the ./bin/workflow review-rounds subcommand.

Covers:
- Round assignment from Copilot review commit OIDs (other bots never open a round)
- line and original_line kept separate
- Stale summary.json / pr<N>.json removed before a run
- CLI: --prs parsing/dedupe, --recent bounds and count check, --min-threads defaults
- Null round for threads whose commit is not in any bot review
- Bot vs human classification by __typename (not login)
- Thread pagination (truncated -> exit 1)
- Reviews pagination and count-check (truncated -> exit 1)
- Comment count-check per thread (truncated -> exit 1)
- Commit pagination via REST
- --min-threads filter in summary.json
- Body truncation at 1500 chars
- unplaced_threads count in summary (not in round0 or later)
- review_bodies count in summary (bot reviews with non-empty body)
- Sad paths: API failure, truncated pagination
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from typing import Any

from tests.fixtures import TempDirMixin
from workflow.review_rounds import (
    _author_kind,
    _fetch_commit_headlines,
    _is_bot,
    _truncate,
    build_pr_rounds,
    fetch_recent_prs,
    run_review_rounds,
)


# ---------------------------------------------------------------------------
# Fake GhCLI transport
# ---------------------------------------------------------------------------


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class FakeGhTransport:
    """Queue-based fake for GhCLI.  Tests push scripted responses per verb."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.responses: dict[str, list[SimpleNamespace]] = {}

    def __call__(self, cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        self.calls.append(list(cmd))
        if not cmd or cmd[0] != "gh":
            raise AssertionError(f"non-gh command: {cmd!r}")
        return self._dispatch(cmd)

    def _dispatch(self, cmd: list[str]) -> SimpleNamespace:
        if cmd[:3] == ["gh", "api", "graphql"]:
            return self._pop("graphql", default=_proc(stdout='{"data":{}}'))
        if cmd[:2] == ["gh", "api"]:
            # REST paginated — default: one empty page
            return self._pop("api", default=_proc(stdout="[[]]"))
        if cmd[:3] == ["gh", "repo", "view"]:
            return self._pop("repo_view", default=_proc(stdout="owner/testrepo\n"))
        if cmd[:3] == ["gh", "pr", "list"]:
            return self._pop("pr_list", default=_proc(stdout="[]"))
        raise AssertionError(f"unhandled gh call: {cmd!r}")

    def _pop(self, key: str, *, default: SimpleNamespace | None = None) -> SimpleNamespace:
        queue = self.responses.get(key)
        if queue:
            return queue.pop(0)
        if default is None:
            raise AssertionError(f"no scripted response for {key!r}")
        return default

    def push_graphql(self, data: dict[str, Any]) -> None:
        self.responses.setdefault("graphql", []).append(_proc(stdout=json.dumps({"data": data})))

    def push_api(self, pages: list[list[Any]]) -> None:
        """Push a paginated REST response as a list of pages (each a list)."""
        self.responses.setdefault("api", []).append(_proc(stdout=json.dumps(pages)))

    def push_graphql_error(self, message: str) -> None:
        body = json.dumps({"errors": [{"message": message}]})
        self.responses.setdefault("graphql", []).append(_proc(stdout=body))

    def push_api_error(self, message: str) -> None:
        self.responses.setdefault("api", []).append(_proc(returncode=1, stderr=message))

    def push_pr_list(self, numbers: list[int]) -> None:
        rows = [{"number": n} for n in numbers]
        self.responses.setdefault("pr_list", []).append(_proc(stdout=json.dumps(rows)))


def _new_gh(fake: FakeGhTransport) -> Any:
    """Build a real GhCLI backed by fake."""
    from core.gh_cli import GhCLI
    return GhCLI(run_func=fake)


def _run_captured(**kwargs: Any) -> tuple[int, str, str]:
    """Call run_review_rounds with stdout/stderr captured; return (rc, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = run_review_rounds(**kwargs)
    return rc, out.getvalue(), err.getvalue()


def _quiet_run(**kwargs: Any) -> int:
    return _run_captured(**kwargs)[0]


# ---------------------------------------------------------------------------
# GraphQL fixture helpers for the new separate queries
# ---------------------------------------------------------------------------


def _reviews_response(
    nodes: list[dict[str, Any]],
    *,
    total: int | None = None,
    has_next: bool = False,
    cursor: str | None = None,
    title: str = "Test PR",
    commit_count: int | None = None,
) -> dict[str, Any]:
    """``commit_count`` None omits commits.totalCount, which reads as truncated."""
    if total is None:
        total = len(nodes)
    pull: dict[str, Any] = {"title": title}
    if commit_count is not None:
        pull["commits"] = {"totalCount": commit_count}
    return {
        "repository": {
            "pullRequest": {
                **pull,
                "reviews": {
                    "totalCount": total,
                    "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                    "nodes": nodes,
                },
            }
        }
    }


def _threads_response(
    nodes: list[dict[str, Any]],
    *,
    total: int | None = None,
    has_next: bool = False,
    cursor: str | None = None,
) -> dict[str, Any]:
    if total is None:
        total = len(nodes)
    return {
        "repository": {
            "pullRequest": {
                "reviewThreads": {
                    "totalCount": total,
                    "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                    "nodes": nodes,
                },
            }
        }
    }


def _bot_review(oid: str, *, submitted_at: str = "2024-01-01T00:00:00Z", body: str = "") -> dict[str, Any]:
    return {
        "author": {"login": "copilot-pull-request-reviewer[bot]", "__typename": "Bot"},
        "state": "COMMENTED",
        "submittedAt": submitted_at,
        "commit": {"oid": oid},
        "body": body,
    }


def _other_bot_review(
    oid: str,
    *,
    login: str = "github-code-quality",
    submitted_at: str = "2024-01-01T00:30:00Z",
    body: str = "",
) -> dict[str, Any]:
    return {
        "author": {"login": login, "__typename": "Bot"},
        "state": "COMMENTED",
        "submittedAt": submitted_at,
        "commit": {"oid": oid},
        "body": body,
    }


def _human_review(oid: str, *, submitted_at: str = "2024-01-01T01:00:00Z") -> dict[str, Any]:
    return {
        "author": {"login": "alice", "__typename": "User"},
        "state": "APPROVED",
        "submittedAt": submitted_at,
        "commit": {"oid": oid},
        "body": "",
    }


def _thread_node(
    thread_id: str,
    *,
    oid: str = "",
    path: str = "src/foo.py",
    line: int | None = 10,
    original_line: int | None = None,
    resolved: bool = False,
    outdated: bool = False,
    author_typename: str = "Bot",
    body: str = "Test comment",
    comment_total: int | None = None,
) -> dict[str, Any]:
    """Build a thread node for THREADS_QUERY (includes originalCommit)."""
    comment = {
        "author": {"login": "bot", "__typename": author_typename},
        "body": body,
        "databaseId": 1,
        "createdAt": "2024-01-01T00:00:00Z",
        "url": "https://example.com",
        "originalCommit": {"oid": oid} if oid else None,
    }
    nodes = [comment]
    return {
        "id": thread_id,
        "isResolved": resolved,
        "isOutdated": outdated,
        "path": path,
        "line": line,
        "originalLine": line if original_line is None else original_line,
        "comments": {
            "totalCount": comment_total if comment_total is not None else len(nodes),
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": nodes,
        },
    }


def _commit_page(items: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Build a REST commit page from [(sha, headline), ...]."""
    return [
        {"sha": sha, "commit": {"message": headline}}
        for sha, headline in items
    ]


def _setup_pr(
    fake: FakeGhTransport,
    *,
    reviews: list[dict[str, Any]],
    threads: list[dict[str, Any]],
    commits: list[tuple[str, str]],
    review_total: int | None = None,
    thread_total: int | None = None,
    title: str = "Test PR",
) -> None:
    """Push the three calls needed for one PR: reviews graphql, threads graphql, commits REST."""
    fake.push_graphql(_reviews_response(
        reviews, total=review_total, title=title, commit_count=len(commits)
    ))
    fake.push_graphql(_threads_response(threads, total=thread_total))
    fake.push_api([_commit_page(commits)])


# ---------------------------------------------------------------------------
# Unit tests: helper functions
# ---------------------------------------------------------------------------


class TestHelpers(unittest.TestCase):

    def test_is_bot_true(self) -> None:
        self.assertTrue(_is_bot({"__typename": "Bot", "login": "github-code-quality"}))

    def test_is_bot_false_for_user(self) -> None:
        self.assertFalse(_is_bot({"__typename": "User", "login": "alice"}))

    def test_is_bot_false_for_none(self) -> None:
        self.assertFalse(_is_bot(None))

    def test_is_bot_false_for_bot_in_login_but_user_typename(self) -> None:
        # Classification MUST use __typename, not login suffix.
        self.assertFalse(_is_bot({"__typename": "User", "login": "notabot[bot]"}))

    def test_author_kind_bot(self) -> None:
        comments = [{"author": {"__typename": "Bot", "login": "copilot[bot]"}}]
        self.assertEqual(_author_kind(comments), "bot")

    def test_author_kind_human(self) -> None:
        comments = [{"author": {"__typename": "User", "login": "alice"}}]
        self.assertEqual(_author_kind(comments), "human")

    def test_author_kind_empty(self) -> None:
        self.assertEqual(_author_kind([]), "human")

    def test_truncate_short(self) -> None:
        self.assertEqual(_truncate("hello", 10), "hello")

    def test_truncate_long(self) -> None:
        result = _truncate("a" * 1600, 1500)
        self.assertEqual(len(result), 1501)  # 1500 + ellipsis char
        self.assertTrue(result.endswith("…"))


# ---------------------------------------------------------------------------
# Integration tests: build_pr_rounds
# ---------------------------------------------------------------------------


class TestBuildPRRounds(TempDirMixin, unittest.TestCase):

    def test_basic_round_assignment(self) -> None:
        """Threads are assigned round by their first comment's originalCommit.oid."""
        oid0 = "aaaa0000" * 5
        oid1 = "bbbb1111" * 5
        fake = FakeGhTransport()
        _setup_pr(
            fake,
            reviews=[
                _bot_review(oid0, submitted_at="2024-01-01T00:00:00Z"),
                _bot_review(oid1, submitted_at="2024-01-02T00:00:00Z"),
            ],
            threads=[
                _thread_node("T1", oid=oid0),
                _thread_node("T2", oid=oid1),
                _thread_node("T3", oid="unknown"),
            ],
            commits=[(oid0, "fix: r0"), (oid1, "fix: r1")],
            title="My PR",
        )

        gh = _new_gh(fake)
        result = build_pr_rounds(gh, "owner", "repo", 42)

        self.assertEqual(result.pr, 42)
        self.assertEqual(result.title, "My PR")
        self.assertFalse(result.truncated)
        self.assertEqual(len(result.rounds), 2)
        self.assertEqual(result.rounds[0].round, 0)
        self.assertEqual(result.rounds[0].commit, oid0)
        self.assertEqual(result.rounds[1].round, 1)
        self.assertEqual(result.rounds[1].commit, oid1)

        by_id = {t.thread_id: t for t in result.threads}
        self.assertEqual(by_id["T1"].round, 0)
        self.assertEqual(by_id["T2"].round, 1)
        self.assertIsNone(by_id["T3"].round)

    def test_null_round_for_unreviewed_commit(self) -> None:
        """A thread whose oid isn't in any bot review round gets round=None."""
        oid_known = "cccc2222" * 5
        fake = FakeGhTransport()
        _setup_pr(
            fake,
            reviews=[_bot_review(oid_known)],
            threads=[_thread_node("T_unmatched", oid="dddd3333" * 5)],
            commits=[(oid_known, "fix")],
        )
        gh = _new_gh(fake)
        result = build_pr_rounds(gh, "owner", "repo", 1)
        self.assertIsNone(result.threads[0].round)

    def test_no_bot_reviews(self) -> None:
        """A PR with only human reviews has no rounds; threads get round=None."""
        oid = "eeee4444" * 5
        fake = FakeGhTransport()
        _setup_pr(
            fake,
            reviews=[_human_review(oid)],
            threads=[_thread_node("T_human", oid=oid)],
            commits=[(oid, "feat: stuff")],
        )
        gh = _new_gh(fake)
        result = build_pr_rounds(gh, "owner", "repo", 1)
        self.assertEqual(len(result.rounds), 0)
        self.assertIsNone(result.threads[0].round)

    def test_code_quality_only_push_opens_no_round(self) -> None:
        """A non-Copilot bot is a bot by __typename, but its review opens no round."""
        oid = "ffff5555" * 5
        fake = FakeGhTransport()
        _setup_pr(
            fake,
            reviews=[_other_bot_review(oid)],
            threads=[_thread_node("T_gcp", oid=oid, author_typename="Bot")],
            commits=[(oid, "fix: something")],
        )
        gh = _new_gh(fake)
        result = build_pr_rounds(gh, "owner", "repo", 7)
        self.assertEqual(result.rounds, [])
        self.assertIsNone(result.threads[0].round)
        self.assertEqual(result.threads[0].author_kind, "bot")
        self.assertEqual(result.other_bot_reviews, 1)

    def test_copilot_and_code_quality_on_one_commit_make_one_round(self) -> None:
        """Only Copilot opens the round; the other bot is counted, not a second round."""
        oid0 = "abab0000" * 5
        oid1 = "cdcd1111" * 5
        fake = FakeGhTransport()
        _setup_pr(
            fake,
            reviews=[
                _other_bot_review(oid0, submitted_at="2024-01-01T00:00:00Z"),
                _bot_review(oid0, submitted_at="2024-01-01T00:05:00Z"),
                # A later code-quality-only push: still no round.
                _other_bot_review(oid1, login="github-actions", submitted_at="2024-01-02T00:00:00Z"),
            ],
            threads=[_thread_node("T1", oid=oid0), _thread_node("T2", oid=oid1)],
            commits=[(oid0, "feat"), (oid1, "fix")],
        )
        gh = _new_gh(fake)
        result = build_pr_rounds(gh, "owner", "repo", 8)
        self.assertEqual([r.commit for r in result.rounds], [oid0])
        self.assertEqual(result.threads[0].round, 0)
        self.assertIsNone(result.threads[1].round)
        self.assertEqual(result.other_bot_reviews, 2)

    def test_user_with_copilot_login_opens_no_round(self) -> None:
        """Copilot is identified by __typename AND login, never by login alone."""
        oid = "efef2222" * 5
        impostor = {
            "author": {"login": "copilot-pull-request-reviewer", "__typename": "User"},
            "state": "COMMENTED",
            "submittedAt": "2024-01-01T00:00:00Z",
            "commit": {"oid": oid},
            "body": "",
        }
        fake = FakeGhTransport()
        _setup_pr(fake, reviews=[impostor], threads=[], commits=[(oid, "x")])
        result = build_pr_rounds(_new_gh(fake), "owner", "repo", 9)
        self.assertEqual(result.rounds, [])
        self.assertEqual(result.other_bot_reviews, 0)

    def test_outdated_thread_keeps_line_and_original_line_separate(self) -> None:
        """A null current line is never back-filled from originalLine."""
        oid = "1a1a3333" * 5
        fake = FakeGhTransport()
        _setup_pr(
            fake,
            reviews=[_bot_review(oid)],
            threads=[
                _thread_node("T_old", oid=oid, line=None, original_line=7, outdated=True),
                _thread_node("T_cur", oid=oid, line=12, original_line=10),
            ],
            commits=[(oid, "fix")],
        )
        result = build_pr_rounds(_new_gh(fake), "owner", "repo", 10)
        old, cur = result.threads
        self.assertIsNone(old.line)
        self.assertEqual(old.original_line, 7)
        self.assertTrue(old.outdated)
        self.assertEqual((cur.line, cur.original_line), (12, 10))

    def test_commit_count_mismatch_sets_truncated(self) -> None:
        """REST commits disagreeing with GraphQL's commit count -> truncated (commits)."""
        oid = "2b2b4444" * 5
        fake = FakeGhTransport()
        fake.push_graphql(_reviews_response([_bot_review(oid)], commit_count=300))
        fake.push_graphql(_threads_response([]))
        fake.push_api([_commit_page([(oid, "fix")])])
        result = build_pr_rounds(_new_gh(fake), "owner", "repo", 11)
        self.assertEqual(len(result.truncated_parts), 1)
        self.assertIn("commits", result.truncated_parts[0])
        self.assertIn("250", result.truncated_parts[0])

    def test_user_with_bot_in_login_is_human(self) -> None:
        """A reviewer with __typename=='User' is NOT a bot even if login has [bot]."""
        oid = "aaaa1234" * 5
        user_review = {
            "author": {"login": "notabot[bot]", "__typename": "User"},
            "state": "APPROVED",
            "submittedAt": "2024-01-01T00:00:00Z",
            "commit": {"oid": oid},
            "body": "",
        }
        fake = FakeGhTransport()
        _setup_pr(fake, reviews=[user_review], threads=[], commits=[])
        gh = _new_gh(fake)
        result = build_pr_rounds(gh, "owner", "repo", 2)
        self.assertEqual(len(result.rounds), 0)

    def test_body_truncation(self) -> None:
        """Thread body is truncated to 1500 chars."""
        oid = "bbbb6666" * 5
        long_body = "x" * 2000
        fake = FakeGhTransport()
        _setup_pr(
            fake,
            reviews=[_bot_review(oid)],
            threads=[_thread_node("T_long", oid=oid, body=long_body)],
            commits=[(oid, "fix")],
        )
        gh = _new_gh(fake)
        result = build_pr_rounds(gh, "owner", "repo", 3)
        self.assertLessEqual(len(result.threads[0].body), 1501)
        self.assertTrue(result.threads[0].body.endswith("…"))

    def test_replies_limited_to_three(self) -> None:
        """Only the first 3 replies (comments[1:4]) are captured."""
        oid = "cccc7777" * 5
        fake = FakeGhTransport()
        # Build a thread with 6 comments (1 body + 5 replies)
        thread = {
            "id": "T_replies",
            "isResolved": False,
            "isOutdated": False,
            "path": "src/a.py",
            "line": 1,
            "originalLine": 1,
            "comments": {
                "totalCount": 6,
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [
                    {
                        "author": {"login": "bot", "__typename": "Bot"},
                        "body": f"comment {i}",
                        "databaseId": i + 1,
                        "createdAt": "2024-01-01T00:00:00Z",
                        "url": "https://example.com",
                        "originalCommit": {"oid": oid},
                    }
                    for i in range(6)
                ],
            },
        }
        fake.push_graphql(_reviews_response([_bot_review(oid)], commit_count=1))
        fake.push_graphql(_threads_response([thread]))
        fake.push_api([_commit_page([(oid, "fix")])])

        gh = _new_gh(fake)
        result = build_pr_rounds(gh, "owner", "repo", 4)
        self.assertEqual(len(result.threads[0].replies), 3)

    def test_thread_pagination(self) -> None:
        """Two pages of threads are merged correctly."""
        oid = "dddd8888" * 5
        fake = FakeGhTransport()
        fake.push_graphql(_reviews_response([_bot_review(oid)], commit_count=1))
        # Page 1 of threads: has_next=True
        fake.push_graphql(_threads_response(
            [_thread_node("T_p1", oid=oid)],
            total=2,
            has_next=True,
            cursor="cursor1",
        ))
        # Page 2 of threads: no more pages
        fake.push_graphql(_threads_response(
            [_thread_node("T_p2", oid=oid)],
            total=2,
            has_next=False,
        ))
        fake.push_api([_commit_page([(oid, "fix")])])

        gh = _new_gh(fake)
        result = build_pr_rounds(gh, "owner", "repo", 5)
        thread_ids = [t.thread_id for t in result.threads]
        self.assertIn("T_p1", thread_ids)
        self.assertIn("T_p2", thread_ids)
        self.assertFalse(result.truncated)

    def test_reviews_count_mismatch_sets_truncated(self) -> None:
        """reviews totalCount mismatch -> truncated=True."""
        oid = "eeee9999" * 5
        fake = FakeGhTransport()
        # Claims 200 but only returns 1 node with no next page -> count mismatch
        fake.push_graphql(_reviews_response(
            [_bot_review(oid)],
            total=200,
            has_next=False,
            commit_count=0,
        ))
        fake.push_graphql(_threads_response([]))
        fake.push_api([_commit_page([])])

        gh = _new_gh(fake)
        result = build_pr_rounds(gh, "owner", "repo", 6)
        self.assertEqual(result.truncated_parts, ["reviews"])

    def test_threads_count_mismatch_sets_truncated(self) -> None:
        """reviewThreads totalCount mismatch -> truncated=True."""
        oid = "ffff0000" * 5
        fake = FakeGhTransport()
        fake.push_graphql(_reviews_response([_bot_review(oid)], commit_count=1))
        # Threads: claims 10 but only returns 1 with no next page
        fake.push_graphql(_threads_response(
            [_thread_node("T1", oid=oid)],
            total=10,
            has_next=False,
        ))
        fake.push_api([_commit_page([(oid, "fix")])])

        gh = _new_gh(fake)
        result = build_pr_rounds(gh, "owner", "repo", 7)
        self.assertEqual(result.truncated_parts, ["threads"])

    def test_thread_comments_count_mismatch_sets_truncated(self) -> None:
        """Per-thread comments totalCount mismatch -> truncated=True."""
        oid = "aaaa1111" * 5
        fake = FakeGhTransport()
        fake.push_graphql(_reviews_response([_bot_review(oid)], commit_count=1))
        # Thread claims 5 comments but only has 1 in nodes, no next page
        thread = _thread_node("T_short_comments", oid=oid, comment_total=5)
        fake.push_graphql(_threads_response([thread]))
        fake.push_api([_commit_page([(oid, "fix")])])

        gh = _new_gh(fake)
        result = build_pr_rounds(gh, "owner", "repo", 8)
        self.assertEqual(result.truncated_parts, ["threads"])

    def test_api_failure_raises(self) -> None:
        """A graphql error from the API raises GhError."""
        from core.gh_cli import GhError
        fake = FakeGhTransport()
        fake.push_graphql_error("API rate limit exceeded")

        gh = _new_gh(fake)
        with self.assertRaises(GhError):
            build_pr_rounds(gh, "owner", "repo", 99)

    def test_review_bodies_counted(self) -> None:
        """Bot reviews with non-empty body are counted as review_bodies."""
        oid = "bbbb2222" * 5
        fake = FakeGhTransport()
        _setup_pr(
            fake,
            reviews=[
                _bot_review(oid, body="This is a summary"),  # has body
                _bot_review(oid, body=""),                    # no body
                _human_review(oid),                           # human, ignored
            ],
            threads=[],
            commits=[],
        )
        gh = _new_gh(fake)
        result = build_pr_rounds(gh, "owner", "repo", 9)
        self.assertEqual(result.review_bodies_count, 1)


# ---------------------------------------------------------------------------
# Integration tests: run_review_rounds
# ---------------------------------------------------------------------------


class TestRunReviewRounds(TempDirMixin, unittest.TestCase):

    def _make_successful_fake(self, pr: int, oid: str, headline: str = "fix") -> FakeGhTransport:
        """Build a fake that returns one bot round and one thread."""
        fake = FakeGhTransport()
        fake.responses["repo_view"] = [_proc(stdout="owner/repo\n")]
        _setup_pr(
            fake,
            reviews=[_bot_review(oid)],
            threads=[_thread_node("T1", oid=oid)],
            commits=[(oid, headline)],
            title=f"PR #{pr}",
        )
        return fake

    def test_writes_pr_json(self) -> None:
        """run_review_rounds writes pr<N>.json to out_dir."""
        out = Path(self.tmpdir) / "out"
        oid = "1234abcd" * 5
        fake = self._make_successful_fake(42, oid)
        gh = _new_gh(fake)

        rc = _quiet_run(
            pr_numbers=[42],
            out_dir=out,
            min_threads=0,
            gh=gh,
        )
        self.assertEqual(rc, 0)
        pr_file = out / "pr42.json"
        self.assertTrue(pr_file.exists())
        data = json.loads(pr_file.read_text())
        self.assertEqual(data["pr"], 42)
        self.assertIn("rounds", data)
        self.assertIn("threads", data)
        self.assertEqual(data["rounds"][0]["round"], 0)
        self.assertEqual(data["rounds"][0]["commit"], oid)

    def test_writes_summary_json(self) -> None:
        """summary.json has one entry with correct stats."""
        out = Path(self.tmpdir) / "out"
        oid = "2345bcde" * 5
        fake = self._make_successful_fake(10, oid)
        gh = _new_gh(fake)

        rc = _quiet_run(
            pr_numbers=[10],
            out_dir=out,
            min_threads=0,
            gh=gh,
        )
        self.assertEqual(rc, 0)
        summary = json.loads((out / "summary.json").read_text())
        self.assertEqual(len(summary), 1)
        row = summary[0]
        self.assertEqual(row["pr"], 10)
        self.assertEqual(row["bot_rounds"], 1)
        self.assertEqual(row["threads"], 1)
        self.assertIn("unplaced_threads", row)
        self.assertIn("review_bodies", row)

    def test_min_threads_filter(self) -> None:
        """PRs below --min-threads threshold are excluded from summary.json."""
        out = Path(self.tmpdir) / "out"
        oid = "3456cdef" * 5
        fake = self._make_successful_fake(77, oid)
        gh = _new_gh(fake)

        rc = _quiet_run(
            pr_numbers=[77],
            out_dir=out,
            min_threads=5,  # PR only has 1 thread -> filtered out
            gh=gh,
        )
        self.assertEqual(rc, 0)
        summary = json.loads((out / "summary.json").read_text())
        self.assertEqual(summary, [])

    def test_exit_1_on_api_failure(self) -> None:
        """Returns exit code 1 when any PR's fetch fails."""
        out = Path(self.tmpdir) / "out"
        fake = FakeGhTransport()
        fake.push_graphql_error("not found")
        fake.responses["repo_view"] = [_proc(stdout="owner/repo\n")]
        gh = _new_gh(fake)

        rc = _quiet_run(
            pr_numbers=[99],
            out_dir=out,
            min_threads=0,
            gh=gh,
        )
        self.assertEqual(rc, 1)

    def test_exit_1_on_truncated_reviews(self) -> None:
        """Returns exit code 1 when reviews pagination is truncated."""
        out = Path(self.tmpdir) / "out"
        oid = "4567deef" * 5
        fake = FakeGhTransport()
        fake.responses["repo_view"] = [_proc(stdout="owner/repo\n")]
        # reviews: claims 200 but returns 1 with no next page -> truncated
        fake.push_graphql(_reviews_response(
            [_bot_review(oid)], total=200, has_next=False, commit_count=0
        ))
        fake.push_graphql(_threads_response([]))
        fake.push_api([_commit_page([])])

        gh = _new_gh(fake)

        rc = _quiet_run(
            pr_numbers=[200],
            out_dir=out,
            min_threads=0,
            gh=gh,
        )
        self.assertEqual(rc, 1)
        # pr200.json must NOT be written (partial data)
        self.assertFalse((out / "pr200.json").exists())

    def test_exit_1_on_truncated_threads(self) -> None:
        """Returns exit code 1 when threads pagination is truncated."""
        out = Path(self.tmpdir) / "out"
        oid = "5678efgh" * 5
        fake = FakeGhTransport()
        fake.responses["repo_view"] = [_proc(stdout="owner/repo\n")]
        fake.push_graphql(_reviews_response([_bot_review(oid)], commit_count=1))
        # threads: claims 10 but returns 1 with no next page -> truncated
        fake.push_graphql(_threads_response(
            [_thread_node("T1", oid=oid)], total=10, has_next=False
        ))
        fake.push_api([_commit_page([(oid, "fix")])])

        gh = _new_gh(fake)
        rc = _quiet_run(pr_numbers=[10], out_dir=out, min_threads=0, gh=gh)
        self.assertEqual(rc, 1)
        self.assertFalse((out / "pr10.json").exists())

    def test_exit_1_on_truncated_comments(self) -> None:
        """Returns exit code 1 when per-thread comment count is truncated."""
        out = Path(self.tmpdir) / "out"
        oid = "6789fghi" * 5
        fake = FakeGhTransport()
        fake.responses["repo_view"] = [_proc(stdout="owner/repo\n")]
        fake.push_graphql(_reviews_response([_bot_review(oid)], commit_count=1))
        # Thread claims 5 comments but only has 1
        thread = _thread_node("T_short", oid=oid, comment_total=5)
        fake.push_graphql(_threads_response([thread]))
        fake.push_api([_commit_page([(oid, "fix")])])

        gh = _new_gh(fake)
        rc = _quiet_run(pr_numbers=[11], out_dir=out, min_threads=0, gh=gh)
        self.assertEqual(rc, 1)

    def test_summary_sorted_by_threads_desc(self) -> None:
        """summary.json rows are sorted by thread count descending."""
        out = Path(self.tmpdir) / "out"
        oid_a = "aaaaaaaa" * 5
        oid_b = "bbbbbbbb" * 5

        fake = FakeGhTransport()
        fake.responses["repo_view"] = [_proc(stdout="owner/repo\n")]

        # PR 1: 2 threads
        _setup_pr(
            fake,
            reviews=[_bot_review(oid_a)],
            threads=[_thread_node("T1", oid=oid_a), _thread_node("T2", oid=oid_a)],
            commits=[(oid_a, "fix a")],
        )

        # PR 2: 1 thread
        _setup_pr(
            fake,
            reviews=[_bot_review(oid_b)],
            threads=[_thread_node("T3", oid=oid_b)],
            commits=[(oid_b, "fix b")],
        )

        gh = _new_gh(fake)
        rc = _quiet_run(pr_numbers=[1, 2], out_dir=out, min_threads=0, gh=gh)
        self.assertEqual(rc, 0)
        summary = json.loads((out / "summary.json").read_text())
        self.assertEqual(len(summary), 2)
        self.assertGreaterEqual(summary[0]["threads"], summary[1]["threads"])

    def test_later_share_calculation(self) -> None:
        """later_share = later_threads / total_threads."""
        out = Path(self.tmpdir) / "out"
        oid0 = "cccccccc" * 5
        oid1 = "dddddddd" * 5

        fake = FakeGhTransport()
        fake.responses["repo_view"] = [_proc(stdout="owner/repo\n")]
        _setup_pr(
            fake,
            reviews=[
                _bot_review(oid0, submitted_at="2024-01-01T00:00:00Z"),
                _bot_review(oid1, submitted_at="2024-01-02T00:00:00Z"),
            ],
            threads=[
                _thread_node("T_r0", oid=oid0),   # round 0
                _thread_node("T_r1a", oid=oid1),  # round 1 (later)
                _thread_node("T_r1b", oid=oid1),  # round 1 (later)
            ],
            commits=[(oid0, "r0"), (oid1, "r1")],
        )

        gh = _new_gh(fake)
        rc = _quiet_run(pr_numbers=[5], out_dir=out, min_threads=0, gh=gh)
        self.assertEqual(rc, 0)
        summary = json.loads((out / "summary.json").read_text())
        row = summary[0]
        self.assertEqual(row["round0_threads"], 1)
        self.assertEqual(row["later_threads"], 2)
        self.assertAlmostEqual(row["later_share"], 2 / 3, places=2)

    def test_unplaced_threads_not_in_round0_or_later(self) -> None:
        """Threads with round=None are unplaced, not counted in round0 or later."""
        out = Path(self.tmpdir) / "out"
        oid0 = "eeeeeeee" * 5
        oid_unplaced = "12345678" * 5

        fake = FakeGhTransport()
        fake.responses["repo_view"] = [_proc(stdout="owner/repo\n")]
        _setup_pr(
            fake,
            reviews=[_bot_review(oid0)],
            threads=[
                _thread_node("T_r0", oid=oid0),         # round 0
                _thread_node("T_unplaced", oid=oid_unplaced),  # unplaced
            ],
            commits=[(oid0, "fix")],
        )

        gh = _new_gh(fake)
        rc = _quiet_run(pr_numbers=[6], out_dir=out, min_threads=0, gh=gh)
        self.assertEqual(rc, 0)
        summary = json.loads((out / "summary.json").read_text())
        row = summary[0]
        self.assertEqual(row["threads"], 2)
        self.assertEqual(row["round0_threads"], 1)
        self.assertEqual(row["later_threads"], 0)
        self.assertEqual(row["unplaced_threads"], 1)
        # later_share is computed from total_threads, not (round0+later)
        self.assertEqual(row["later_share"], 0.0)

    def test_review_bodies_in_summary(self) -> None:
        """review_bodies counts bot reviews with non-empty body."""
        out = Path(self.tmpdir) / "out"
        oid = "ffffffff" * 5
        fake = FakeGhTransport()
        fake.responses["repo_view"] = [_proc(stdout="owner/repo\n")]
        _setup_pr(
            fake,
            reviews=[
                _bot_review(oid, body="Summary here"),
                _bot_review(oid, body="Another summary"),
                _bot_review(oid, body=""),  # empty body, not counted
            ],
            threads=[_thread_node("T1", oid=oid)],
            commits=[(oid, "fix")],
        )

        gh = _new_gh(fake)
        rc = _quiet_run(pr_numbers=[7], out_dir=out, min_threads=0, gh=gh)
        self.assertEqual(rc, 0)
        summary = json.loads((out / "summary.json").read_text())
        self.assertEqual(summary[0]["review_bodies"], 2)

    def test_commit_headlines_from_rest(self) -> None:
        """Round entries use commit headlines fetched via REST."""
        out = Path(self.tmpdir) / "out"
        oid = "eeeeeeee" * 5
        fake = FakeGhTransport()
        fake.responses["repo_view"] = [_proc(stdout="owner/repo\n")]
        _setup_pr(
            fake,
            reviews=[_bot_review(oid)],
            threads=[_thread_node("T1", oid=oid)],
            commits=[(oid, "feat: the real headline")],
        )

        gh = _new_gh(fake)
        self.assertEqual(_quiet_run(pr_numbers=[1], out_dir=out, min_threads=0, gh=gh), 0)

        pr_data = json.loads((out / "pr1.json").read_text())
        self.assertEqual(pr_data["rounds"][0]["headline"], "feat: the real headline")


# ---------------------------------------------------------------------------
# Housekeeping, commits, reviews pagination
# ---------------------------------------------------------------------------


class TestRunHousekeeping(TempDirMixin, unittest.TestCase):

    def _out(self) -> Path:
        out = Path(self.tmpdir) / "out"
        out.mkdir()
        return out

    def test_stale_summary_deleted_when_run_fails(self) -> None:
        """A failed run in a reused --out-dir must not leave the last good summary."""
        out = self._out()
        (out / "summary.json").write_text('[{"pr": 1, "threads": 99}]')
        fake = FakeGhTransport()
        fake.push_graphql_error("not found")
        rc, _, err = _run_captured(pr_numbers=[99], out_dir=out, min_threads=0, gh=_new_gh(fake))
        self.assertEqual(rc, 1)
        self.assertIn("PR #99 failed", err)
        self.assertFalse((out / "summary.json").exists())

    def test_stale_pr_file_removed_when_pr_is_truncated(self) -> None:
        out = self._out()
        (out / "pr200.json").write_text('{"pr": 200, "threads": []}')
        fake = FakeGhTransport()
        fake.push_graphql(_reviews_response([_bot_review("a" * 40)], total=5, commit_count=0))
        fake.push_graphql(_threads_response([]))
        fake.push_api([_commit_page([])])
        rc, _, err = _run_captured(pr_numbers=[200], out_dir=out, min_threads=0, gh=_new_gh(fake))
        self.assertEqual(rc, 1)
        self.assertIn("PR #200 pagination was truncated (reviews)", err)
        self.assertFalse((out / "pr200.json").exists())

    def test_commit_api_failure_reports_as_api_failure(self) -> None:
        """A GhError from the REST commits call is an API failure, not truncation."""
        out = self._out()
        fake = FakeGhTransport()
        fake.push_graphql(_reviews_response([_bot_review("b" * 40)], commit_count=1))
        fake.push_api_error("HTTP 502: Bad Gateway")
        rc, _, err = _run_captured(pr_numbers=[5], out_dir=out, min_threads=0, gh=_new_gh(fake))
        self.assertEqual(rc, 1)
        self.assertIn("PR #5 failed: HTTP 502: Bad Gateway", err)
        self.assertNotIn("truncated", err)

    def test_summary_reports_other_bot_reviews(self) -> None:
        out = self._out()
        oid = "c" * 40
        fake = FakeGhTransport()
        _setup_pr(
            fake,
            reviews=[_bot_review(oid), _other_bot_review(oid), _other_bot_review(oid, login="github-actions")],
            threads=[_thread_node("T1", oid=oid)],
            commits=[(oid, "fix")],
        )
        rc, stdout, _ = _run_captured(pr_numbers=[3], out_dir=out, min_threads=0, gh=_new_gh(fake))
        self.assertEqual(rc, 0)
        summary = json.loads((out / "summary.json").read_text())
        self.assertEqual(summary[0]["other_bot_reviews"], 2)
        self.assertEqual(summary[0]["bot_rounds"], 1)
        self.assertEqual(json.loads(stdout), summary)
        pr = json.loads((out / "pr3.json").read_text())
        self.assertIn("original_line", pr["threads"][0])


class TestFetchCommitHeadlines(unittest.TestCase):

    def test_gh_error_propagates(self) -> None:
        from core.gh_cli import GhError
        fake = FakeGhTransport()
        fake.push_api_error("HTTP 404")
        with self.assertRaises(GhError) as ctx:
            _fetch_commit_headlines(_new_gh(fake), "o", "r", 1, expected=1)
        self.assertIn("HTTP 404", str(ctx.exception))

    def test_unknown_expected_count_is_truncated(self) -> None:
        fake = FakeGhTransport()
        fake.push_api([_commit_page([("a" * 40, "x")])])
        headlines, truncated = _fetch_commit_headlines(_new_gh(fake), "o", "r", 1, expected=None)
        self.assertEqual(headlines, {"a" * 40: "x"})
        self.assertTrue(truncated)

    def test_matching_count_is_complete(self) -> None:
        fake = FakeGhTransport()
        fake.push_api([_commit_page([("a" * 40, "x\nbody")]), _commit_page([("b" * 40, "y")])])
        headlines, truncated = _fetch_commit_headlines(_new_gh(fake), "o", "r", 1, expected=2)
        self.assertEqual(headlines, {"a" * 40: "x", "b" * 40: "y"})
        self.assertFalse(truncated)


class TestFetchPrReviews(unittest.TestCase):

    def test_pages_past_100_reviews(self) -> None:
        from core.github.threads import fetch_pr_reviews
        page1 = [_bot_review(f"{i:040d}") for i in range(100)]
        page2 = [_bot_review(f"{i:040d}") for i in range(100, 105)]
        fake = FakeGhTransport()
        fake.push_graphql(_reviews_response(page1, total=105, has_next=True, cursor="c1", commit_count=7))
        fake.push_graphql(_reviews_response(page2, total=105, has_next=False, commit_count=7))
        got = fetch_pr_reviews(_new_gh(fake), "o", "r", 1)
        self.assertEqual(len(got.nodes), 105)
        self.assertFalse(got.truncated)
        self.assertEqual(got.commit_count, 7)
        graphql_calls = [c for c in fake.calls if c[:3] == ["gh", "api", "graphql"]]
        self.assertEqual(len(graphql_calls), 2)

    def test_short_second_page_is_truncated(self) -> None:
        from core.github.threads import fetch_pr_reviews
        fake = FakeGhTransport()
        fake.push_graphql(_reviews_response([_bot_review("a" * 40)] * 100, total=150, has_next=True, cursor="c1"))
        fake.push_graphql(_reviews_response([_bot_review("b" * 40)] * 10, total=150, has_next=False))
        got = fetch_pr_reviews(_new_gh(fake), "o", "r", 1)
        self.assertEqual(len(got.nodes), 110)
        self.assertTrue(got.truncated)


def _pr_total(total: int) -> dict[str, Any]:
    return {"repository": {"pullRequests": {"totalCount": total}}}


class TestFetchRecentPrs(unittest.TestCase):

    def test_returns_most_recent_any_state_descending(self) -> None:
        fake = FakeGhTransport()
        fake.push_graphql(_pr_total(400))
        fake.push_pr_list([431, 433, 432, 430, 429])
        got = fetch_recent_prs(_new_gh(fake), "o", "r", 5)
        self.assertEqual(got, [433, 432, 431, 430, 429])
        (call,) = [c for c in fake.calls if c[:3] == ["gh", "pr", "list"]]
        self.assertEqual(call[call.index("--state") + 1], "all")
        self.assertEqual(call[call.index("--limit") + 1], "5")

    def test_short_listing_fails(self) -> None:
        from core.gh_cli import GhError
        fake = FakeGhTransport()
        fake.push_graphql(_pr_total(400))
        fake.push_pr_list([3, 2, 1])
        with self.assertRaises(GhError) as ctx:
            fetch_recent_prs(_new_gh(fake), "o", "r", 5)
        self.assertIn("listing returned 3 PRs, expected 5 (400 in the repository)", str(ctx.exception))

    def test_small_repo_returns_all_it_has(self) -> None:
        fake = FakeGhTransport()
        fake.push_graphql(_pr_total(3))
        fake.push_pr_list([1, 2, 3])
        self.assertEqual(fetch_recent_prs(_new_gh(fake), "o", "r", 5), [3, 2, 1])

    def test_count_bounds(self) -> None:
        for bad in (0, 201):
            with self.subTest(count=bad), self.assertRaises(ValueError) as ctx:
                fetch_recent_prs(_new_gh(FakeGhTransport()), "o", "r", bad)
            self.assertIn("1..200", str(ctx.exception))


# ---------------------------------------------------------------------------
# CLI: ./bin/workflow review-rounds
# ---------------------------------------------------------------------------


class TestReviewRoundsCLI(TempDirMixin, unittest.TestCase):

    def _main(self, argv: list[str], fake: FakeGhTransport | None = None) -> tuple[int, str, str]:
        from workflow.cli import main
        gh = _new_gh(fake or FakeGhTransport())
        out, err = io.StringIO(), io.StringIO()
        with patch("core.github.client", return_value=gh), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(["review-rounds", *argv, "--out-dir", str(Path(self.tmpdir) / "o")])
        return rc, out.getvalue(), err.getvalue()

    def _five_thread_pr(self, fake: FakeGhTransport, pr_oid: str = "d" * 40) -> None:
        _setup_pr(
            fake,
            reviews=[_bot_review(pr_oid)],
            threads=[_thread_node(f"T{i}", oid=pr_oid) for i in range(5)],
            commits=[(pr_oid, "fix")],
        )

    def test_invalid_prs_rejected(self) -> None:
        rc, _, err = self._main(["--prs", "12,abc"])
        self.assertEqual(rc, 1)
        self.assertIn("invalid --prs value 'abc'", err)

    def test_zero_pr_rejected(self) -> None:
        rc, _, err = self._main(["--prs", "0"])
        self.assertEqual(rc, 1)
        self.assertIn("invalid --prs value '0'", err)

    def test_prs_comma_only_rejected(self) -> None:
        rc, _, err = self._main(["--prs", ","])
        self.assertEqual(rc, 1)
        self.assertIn("--prs names no PR numbers", err)

    def test_recent_bounds_rejected(self) -> None:
        for bad in ("0", "201", "-3"):
            with self.subTest(recent=bad):
                rc, _, err = self._main(["--recent", bad])
                self.assertEqual(rc, 1)
                self.assertIn(f"--recent must be 1..200, got {bad}", err)

    def test_needs_exactly_one_selector(self) -> None:
        for argv in ([], ["--prs", "1", "--recent", "5"]):
            with self.subTest(argv=argv):
                rc, _, err = self._main(argv)
                self.assertEqual(rc, 1)
                self.assertIn("give exactly one of --prs or --recent", err)

    def test_negative_min_threads_rejected(self) -> None:
        rc, _, err = self._main(["--prs", "1", "--min-threads", "-1"])
        self.assertEqual(rc, 1)
        self.assertIn("--min-threads must be >= 0, got -1", err)

    def test_named_pr_under_default_floor_is_kept(self) -> None:
        """An explicit --prs list is never thread-filtered by the default floor."""
        fake = FakeGhTransport()
        self._five_thread_pr(fake)
        rc, _, _ = self._main(["--prs", "429"], fake)
        self.assertEqual(rc, 0)
        summary = json.loads((Path(self.tmpdir) / "o/summary.json").read_text())
        self.assertEqual([(r["pr"], r["threads"]) for r in summary], [(429, 5)])

    def test_explicit_min_threads_still_filters_prs(self) -> None:
        fake = FakeGhTransport()
        self._five_thread_pr(fake)
        rc, _, _ = self._main(["--prs", "429", "--min-threads", "15"], fake)
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads((Path(self.tmpdir) / "o/summary.json").read_text()), [])

    def test_prs_deduped_in_order(self) -> None:
        with patch("workflow.review_rounds.run_review_rounds", return_value=0) as run:
            rc, _, _ = self._main(["--prs", "9, 7,9,,8,7"])
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_args.kwargs["pr_numbers"], [9, 7, 8])
        self.assertEqual(run.call_args.kwargs["min_threads"], 0)

    def test_recent_branch_lists_then_applies_default_floor(self) -> None:
        fake = FakeGhTransport()
        fake.push_graphql(_pr_total(300))
        fake.push_pr_list([10, 12, 11])
        with patch("workflow.review_rounds.run_review_rounds", return_value=0) as run:
            rc, _, _ = self._main(["--recent", "3"], fake)
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_args.kwargs["pr_numbers"], [12, 11, 10])
        self.assertEqual(run.call_args.kwargs["min_threads"], 15)

    def test_recent_short_listing_exits_1(self) -> None:
        fake = FakeGhTransport()
        fake.push_graphql(_pr_total(300))
        fake.push_pr_list([10])
        with patch("workflow.review_rounds.run_review_rounds", return_value=0) as run:
            rc, _, err = self._main(["--recent", "3"], fake)
        self.assertEqual(rc, 1)
        self.assertIn("listing returned 1 PRs, expected 3", err)
        run.assert_not_called()


# ---------------------------------------------------------------------------
# CLI registration tests
# ---------------------------------------------------------------------------


class TestCLIRegistration(unittest.TestCase):

    def test_review_rounds_in_agentic_capsule(self) -> None:
        """review-rounds appears in the agentic capsule."""
        from workflow.agentic import build_agentic_capsule
        capsule = build_agentic_capsule()
        self.assertIn("review-rounds", capsule)

    def test_review_rounds_command_parseable(self) -> None:
        """workflow CLI registers and parses review-rounds arguments."""
        from workflow.cli import main
        # --help raises SystemExit(0) from argparse; that proves the command is registered.
        out = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stdout(out):
            main(["review-rounds", "--help"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("--recent N", out.getvalue())

    def test_workflow_cli_agentic_includes_review_rounds(self) -> None:
        """The agentic schema emitted by the CLI includes review-rounds."""
        import io
        import sys
        from workflow.cli import main
        captured = io.StringIO()
        old = sys.stdout
        sys.stdout = captured
        try:
            main(["--agentic"])
        finally:
            sys.stdout = old
        self.assertIn("review-rounds", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
