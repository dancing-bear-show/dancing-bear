"""Tests for core.github.summary and core.github.activity.

Summary: files are paged and count-checked, so a PR summarised from a short
page fails instead of reporting the wrong top directories. Activity: searches
use filter flags (never a composed query string) and a failed search raises.
"""

from __future__ import annotations

import unittest
from typing import Any

from core.gh_cli import GhCLI, GhError
from core.github import activity, summary
from tests.core_tests.github_fakes import FakeGh, GhCall, ok, paged


def _files(n: int) -> list[dict[str, Any]]:
    paths = ["src/core/a.py", "src/mail/b.py", "tests/t.py", "README.md"]
    return [{"path": paths[i % len(paths)] if i < 4 else f"src/x{i}.py", "additions": i, "deletions": 1}
            for i in range(n)]


def _pr_handler(files: list[dict[str, Any]], *, total: int | None = None, page: int = 2):
    def handler(call: GhCall):
        chunk, info = paged(files, page, call.value("after"), "f")
        return ok({"data": {"repository": {"pullRequest": {
            "number": 476, "title": "Fix resume", "state": "MERGED", "url": "https://example.invalid/pr/476",
            "mergedAt": "2026-11-10T00:00:00Z", "closedAt": "2026-11-10T00:00:00Z",
            "baseRefName": "main", "headRefName": "fix/resume", "additions": 10, "deletions": 2,
            "changedFiles": len(files), "author": {"login": "alice"},
            "files": {"totalCount": len(files) if total is None else total, "pageInfo": info, "nodes": chunk},
        }}}})
    return handler


class TestFetchPrSummary(unittest.TestCase):
    def test_pages_every_file_and_counts_top_dirs(self):
        fake = FakeGh(_pr_handler(_files(5)))
        s = summary.fetch_pr_summary(GhCLI(run_func=fake), "octo-org", "demo-repo", 476)
        self.assertEqual(len(fake.calls), 3)  # 2 + 2 + 1
        self.assertEqual(len(s.files), 5)
        self.assertEqual(s.top_dirs()[0], ("src", 3))
        self.assertEqual(s.author, "alice")
        row = s.to_dict()
        self.assertEqual(row["top_dirs"][0], {"dir": "src", "files": 3})
        self.assertEqual(row["head"], "fix/resume")

    def test_short_file_list_raises(self):
        fake = FakeGh(_pr_handler(_files(3), total=9))
        with self.assertRaisesRegex(GhError, "fetched 3 of 9"):
            summary.fetch_pr_summary(GhCLI(run_func=fake), "octo-org", "demo-repo", 476)

    def test_missing_pull_request_raises(self):
        fake = FakeGh(lambda c: ok({"data": {"repository": {"pullRequest": None}}}))
        with self.assertRaisesRegex(GhError, "PR #9"):
            summary.fetch_pr_summary(GhCLI(run_func=fake), "octo-org", "demo-repo", 9)

    def test_text_render_truncates_file_list(self):
        fake = FakeGh(_pr_handler(_files(12), page=100))
        text = summary.render_summary_text(summary.fetch_pr_summary(GhCLI(run_func=fake), "o", "r", 476))
        self.assertIn("PR #476 - Fix resume", text)
        self.assertIn("... 2 more", text)


class TestMatchesPaths(unittest.TestCase):
    PATHS = ["src/core/a.py", "docs/x.md"]

    def test_no_filters_matches(self):
        self.assertTrue(summary.matches_paths(self.PATHS))

    def test_prefix_include_and_exclude(self):
        self.assertTrue(summary.matches_paths(self.PATHS, include=["src/core"]))
        self.assertFalse(summary.matches_paths(self.PATHS, include=["src/mail"]))
        self.assertFalse(summary.matches_paths(self.PATHS, include=["src/"], exclude=["docs/"]))

    def test_glob_and_regex(self):
        self.assertTrue(summary.matches_paths(self.PATHS, include=["*.md"], mode="glob"))
        self.assertFalse(summary.matches_paths(self.PATHS, include=["*.rs"], mode="glob"))
        self.assertTrue(summary.matches_paths(self.PATHS, include=[r"core/\w+\.py$"], mode="regex"))
        self.assertFalse(summary.matches_paths(self.PATHS, include=[r"^core/"], mode="regex"))

    def test_bad_regex_and_mode_raise(self):
        with self.assertRaisesRegex(GhError, "invalid path regex"):
            summary.matches_paths(self.PATHS, include=["("], mode="regex")
        with self.assertRaisesRegex(GhError, "unknown path mode"):
            summary.matches_paths(self.PATHS, include=["x"], mode="fuzzy")


def _pr_row(n: int, **over: Any) -> dict[str, Any]:
    row = {"number": n, "title": f"PR {n}", "repository": {"nameWithOwner": "octo-org/demo-repo"},
           "updatedAt": "2026-11-01T00:00:00Z", "url": f"https://example.invalid/{n}", "state": "open",
           "author": {"login": "bob"}, "isDraft": False}
    row.update(over)
    return row


class ActivityScript:
    def __init__(self, *, fail_kind: str | None = None, body: str | None = None) -> None:
        self.fail_kind = fail_kind
        self.body = body

    def __call__(self, call: GhCall):
        if "viewer" in call.query:
            return ok({"data": {"viewer": {"login": "alice"}}})
        kind = call.argv[2]
        if kind == self.fail_kind:
            return ok("", returncode=1, stderr="HTTP 403 rate limited")
        if self.body is not None:
            return ok(self.body)
        if kind == "issues":
            return ok([{"number": 3, "title": "Bug", "repository": {"nameWithOwner": "octo-org/demo-repo"},
                        "updatedAt": "u", "url": "x", "state": "open"}])
        if "--review-requested" in call.argv:
            return ok([_pr_row(2, isDraft=True)])
        return ok([_pr_row(1, author="alice")])


class TestFetchActivity(unittest.TestCase):
    def test_sections_and_flags(self):
        fake = FakeGh(ActivityScript())
        a = activity.fetch_activity(GhCLI(run_func=fake), owner="octo-org", limit=500)
        self.assertEqual(a.login, "alice")
        self.assertEqual([i.number for i in a.authored_prs], [1])
        self.assertEqual(a.authored_prs[0].author, "alice")  # string author form
        self.assertTrue(a.review_requests[0].is_draft)
        self.assertEqual(a.review_requests[0].author, "bob")
        self.assertEqual(a.issues[0].repo, "octo-org/demo-repo")
        searches = [c.argv for c in fake.calls if c.argv[1] == "search"]
        self.assertEqual(len(searches), 3)
        for argv in searches:
            self.assertEqual(argv[argv.index("--owner") + 1], "octo-org")
            self.assertEqual(argv[argv.index("--limit") + 1], "100")  # clamped
        review = next(a for a in searches if "--review-requested" in a)
        self.assertEqual(review[review.index("--state") + 1], "open")

    def test_no_owner_omits_flag(self):
        fake = FakeGh(ActivityScript())
        activity.fetch_activity(GhCLI(run_func=fake))
        self.assertFalse(any("--owner" in c.argv for c in fake.calls))

    def test_failed_search_raises_instead_of_empty_section(self):
        fake = FakeGh(ActivityScript(fail_kind="issues"))
        with self.assertRaisesRegex(GhError, "rate limited"):
            activity.fetch_activity(GhCLI(run_func=fake))

    def test_non_list_and_non_json_raise(self):
        with self.assertRaisesRegex(GhError, "expected a list"):
            activity.fetch_activity(GhCLI(run_func=FakeGh(ActivityScript(body='{"a": 1}'))))
        with self.assertRaisesRegex(GhError, "non-JSON"):
            activity.fetch_activity(GhCLI(run_func=FakeGh(ActivityScript(body="oops"))))

    def test_text_render(self):
        a = activity.fetch_activity(GhCLI(run_func=FakeGh(ActivityScript())), owner="octo-org")
        text = activity.render_activity_text(a)
        self.assertIn("User: alice (owner: octo-org)", text)
        self.assertIn("octo-org/demo-repo #2 | 2026-11-01T00:00:00Z | open draft | PR 2", text)
        empty = activity.Activity(login="alice", owner=None)
        self.assertEqual(activity.render_activity_text(empty).count("(none)"), 3)


if __name__ == "__main__":
    unittest.main()
