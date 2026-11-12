"""Tests for core.github.copilot and core.github.review_cycle.

The fake answers at the subprocess boundary (``GhCLI(run_func=FakeGh)``), so
each test sees the exact gh calls a live run would make. The load-bearing
claims: only Copilot-opened unresolved threads with all-bot comments are
touched; threads with any human reply are skipped and listed in
``skipped_human_reply``; a thread is resolved only after its own reply
verified; any failure skips the re-review; ``--dry-run`` issues no mutation.
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import patch

from core.gh_cli import GhCLI, GhError
from core.github import copilot, review_cycle
from tests.core_tests.github_fakes import FakeGh, GhCall, comment_node, ok

COPILOT = "copilot-pull-request-reviewer"
ACTOR = "alice"


def _thread(tid: str, *comments: dict[str, Any], resolved: bool = False) -> dict[str, Any]:
    return {
        "id": tid, "isResolved": resolved, "isOutdated": False, "isCollapsed": False,
        "path": "src/a.py", "line": 3, "startLine": None, "diffSide": "RIGHT",
        "comments": {
            "totalCount": len(comments),
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": list(comments),
        },
    }


def _copilot_thread(tid: str, *extra: dict[str, Any], resolved: bool = False) -> dict[str, Any]:
    return _thread(tid, comment_node(1, COPILOT, "Bot"), *extra, resolved=resolved)


class Scripted:
    """Routes each gh call by kind; records mutation targets."""

    def __init__(self, nodes: list[dict[str, Any]], *, total: int | None = None) -> None:
        self.nodes = nodes
        self.total = len(nodes) if total is None else total
        self.reply_fail: set[str] = set()
        self.resolve_fail: set[str] = set()
        self.request_rc = 0

    def __call__(self, call: GhCall):
        if "reviewThreads" in call.query:
            return ok({"data": {"repository": {"pullRequest": {"reviewThreads": {
                "totalCount": self.total,
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": self.nodes,
            }}}}})
        if "addPullRequestReviewThreadReply" in call.query:
            tid = call.value("threadId") or ""
            if tid in self.reply_fail:
                return ok({"data": None, "errors": [{"message": "reply refused"}]})
            return ok({"data": {"addPullRequestReviewThreadReply": {"comment": {"id": f"C_{tid}", "url": "u"}}}})
        if "resolveReviewThread" in call.query:
            tid = call.value("threadId") or ""
            resolved = tid not in self.resolve_fail
            return ok({"data": {"resolveReviewThread": {"thread": {"id": tid, "isResolved": resolved}}}})
        if "viewer" in call.query:
            return ok({"data": {"viewer": {"login": ACTOR}}})
        if "--paginate" in call.argv:
            return ok([[]])
        if "requested_reviewers" in " ".join(call.argv):
            if self.request_rc:
                return ok("", returncode=self.request_rc, stderr="HTTP 422: Reviews may only be requested from collaborators")
            return ok({"number": 7, "requested_reviewers": [{"login": "Copilot"}]})
        raise AssertionError(f"unexpected gh call {call.argv}")


def _gh(script: Scripted) -> tuple[GhCLI, FakeGh]:
    fake = FakeGh(script)
    return GhCLI(run_func=fake), fake


def _mutations(fake: FakeGh, needle: str) -> list[str]:
    return [c.value("threadId") or "" for c in fake.graphql_calls(needle)]


def _requests(fake: FakeGh) -> list[GhCall]:
    return [c for c in fake.calls if "requested_reviewers" in " ".join(c.argv)]


class TestCopilotSwitch(unittest.TestCase):
    def test_unset_and_true_values_enable(self):
        for env in ({}, {copilot.COPILOT_REVIEW_ENV: "1"}, {copilot.COPILOT_REVIEW_ENV: " Yes "}):
            self.assertEqual(copilot.copilot_review_switch(env), copilot.CopilotSwitch(True))

    def test_false_values_disable(self):
        for raw in ("0", "false", "OFF", "no"):
            self.assertFalse(copilot.copilot_review_switch({copilot.COPILOT_REVIEW_ENV: raw}).enabled)

    def test_typo_stays_enabled_with_warning(self):
        got = copilot.copilot_review_switch({copilot.COPILOT_REVIEW_ENV: "flase"})
        self.assertTrue(got.enabled)
        self.assertIn("flase", got.warning or "")


class TestCopilotThreadSelection(unittest.TestCase):
    def _entry(self, login: str, kind: str, **over: Any) -> dict[str, Any]:
        entry = {"source": "graphql-thread", "thread_id": "T", "is_resolved": False,
                 "comments": [{"author": login, "author_kind": kind}]}
        entry.update(over)
        return entry

    def test_bot_with_copilot_login_matches_either_spelling(self):
        self.assertTrue(copilot.is_copilot_thread(self._entry(COPILOT, "bot")))
        self.assertTrue(copilot.is_copilot_thread(self._entry(f"{COPILOT}[bot]", "bot")))

    def test_human_with_copilot_login_does_not_match(self):
        self.assertFalse(copilot.is_copilot_thread(self._entry(COPILOT, "human")))

    def test_other_bot_does_not_match(self):
        self.assertFalse(copilot.is_copilot_thread(self._entry("github-code-quality", "bot")))

    def test_rest_entry_and_empty_thread_do_not_match(self):
        self.assertFalse(copilot.is_copilot_thread(self._entry(COPILOT, "bot", source="review-body", thread_id=None)))
        self.assertFalse(copilot.is_copilot_thread(self._entry(COPILOT, "bot", comments=[])))

    def test_resolved_filtered_unless_asked(self):
        doc = {"threads": [self._entry(COPILOT, "bot", is_resolved=True)]}
        selected, skipped = copilot.copilot_threads(doc)
        self.assertEqual(selected, [])
        self.assertEqual(skipped, [])
        selected2, _ = copilot.copilot_threads(doc, include_resolved=True)
        self.assertEqual(len(selected2), 1)

    def test_mixed_author_thread_is_in_skipped_not_selected(self):
        """A Copilot-opened thread with a human reply is skipped, not selected."""
        entry = {"source": "graphql-thread", "thread_id": "T", "is_resolved": False,
                 "comments": [{"author": COPILOT, "author_kind": "bot"},
                               {"author": "alice", "author_kind": "human"}]}
        doc = {"threads": [entry]}
        selected, skipped = copilot.copilot_threads(doc)
        self.assertEqual(selected, [])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["thread_id"], "T")

    def test_pure_bot_thread_is_selected(self):
        """A Copilot-opened thread where all comments are bots is selected."""
        entry = self._entry(COPILOT, "bot")
        doc = {"threads": [entry]}
        selected, skipped = copilot.copilot_threads(doc)
        self.assertEqual(len(selected), 1)
        self.assertEqual(skipped, [])

    def test_truncated_doc_raises(self):
        with self.assertRaisesRegex(GhError, "incomplete"):
            copilot.copilot_threads({"truncated": True, "threads": []})


class TestRequestCopilotReview(unittest.TestCase):
    def test_posts_rest_login_on_stdin_and_returns_reviewers(self):
        gh, fake = _gh(Scripted([]))
        got = copilot.request_copilot_review(gh, "octo-org", "demo-repo", 7)
        self.assertEqual(got, ["Copilot"])
        call = _requests(fake)[0]
        self.assertIn("repos/octo-org/demo-repo/pulls/7/requested_reviewers", call.argv)
        self.assertEqual(json.loads(call.input or "{}"), {"reviewers": [f"{COPILOT}[bot]"]})

    def test_422_is_an_error_not_success(self):
        script = Scripted([])
        script.request_rc = 1
        gh, _ = _gh(script)
        with self.assertRaisesRegex(GhError, "422"):
            copilot.request_copilot_review(gh, "octo-org", "demo-repo", 7)

    def test_response_without_pr_number_raises(self):
        gh = GhCLI(run_func=FakeGh(lambda c: ok({"message": "?"})))
        with self.assertRaisesRegex(GhError, "no pull request"):
            copilot.request_copilot_review(gh, "octo-org", "demo-repo", 7)


@patch.dict("os.environ", {copilot.COPILOT_REVIEW_ENV: ""})
class TestRunReviewCycle(unittest.TestCase):
    def _run(self, script: Scripted, **kw: Any) -> tuple[review_cycle.ReviewCycleResult, FakeGh]:
        gh, fake = _gh(script)
        kw.setdefault("body", "Fixed.")
        opts = review_cycle.CycleOptions(**kw)
        return review_cycle.run_review_cycle(gh, "octo-org", "demo-repo", 7, opts), fake

    def test_only_unresolved_copilot_threads_are_replied_and_resolved(self):
        script = Scripted([
            _copilot_thread("CP1"),
            _copilot_thread("CP_DONE", resolved=True),
            _thread("HUMAN", comment_node(2, "bob", "User")),
            _thread("IMPOSTOR", comment_node(3, COPILOT, "User")),
        ])
        result, fake = self._run(script)
        self.assertEqual(_mutations(fake, "addPullRequestReviewThreadReply"), ["CP1"])
        self.assertEqual(_mutations(fake, "resolveReviewThread"), ["CP1"])
        self.assertTrue(result.re_review_requested)
        self.assertIsNone(result.re_review_skip_reason)
        self.assertEqual(result.to_dict()["replied"], 1)
        self.assertEqual(len(_requests(fake)), 1)
        self.assertEqual(result.skipped_human_reply, [])

    def test_failed_reply_never_resolves_that_thread_and_skips_rereview(self):
        script = Scripted([_copilot_thread("BAD"), _copilot_thread("GOOD")])
        script.reply_fail.add("BAD")
        result, fake = self._run(script)
        self.assertEqual(_mutations(fake, "resolveReviewThread"), ["GOOD"])
        self.assertEqual([t.status for t in result.threads], ["failed", "replied"])
        self.assertEqual(result.re_review_skip_reason, review_cycle.SKIP_ERRORS)
        self.assertFalse(result.re_review_requested)
        self.assertEqual(_requests(fake), [])

    def test_failed_resolve_is_recorded_and_skips_rereview(self):
        script = Scripted([_copilot_thread("CP1")])
        script.resolve_fail.add("CP1")
        result, fake = self._run(script)
        self.assertFalse(result.threads[0].resolved)
        self.assertIn("isResolved", result.threads[0].error or "")
        self.assertEqual(_requests(fake), [])

    def test_dry_run_posts_nothing(self):
        result, fake = self._run(Scripted([_copilot_thread("CP1")]), dry_run=True)
        self.assertEqual(fake.graphql_calls("mutation"), [])
        self.assertEqual(_requests(fake), [])
        self.assertEqual(result.threads[0].status, "would_reply")
        self.assertFalse(result.re_review_requested)
        self.assertTrue(result.re_review_planned)

    def test_human_reply_in_copilot_thread_skips_it(self):
        """A Copilot thread containing any human comment is skipped, not replied or resolved."""
        human_reply = comment_node(9, ACTOR, "User", body="can you explain this?")
        result, fake = self._run(Scripted([_copilot_thread("CP1", human_reply)]))
        self.assertEqual(_mutations(fake, "addPullRequestReviewThreadReply"), [])
        self.assertEqual(_mutations(fake, "resolveReviewThread"), [])
        self.assertIn("CP1", result.skipped_human_reply)
        # no threads processed → no re-review
        self.assertEqual(result.re_review_skip_reason, review_cycle.SKIP_NO_THREADS)

    def test_mixed_copilot_thread_skipped_pure_still_processed(self):
        """Pure-bot thread is replied and resolved; mixed thread is listed in skipped_human_reply."""
        mixed_reply = comment_node(5, "bob", "User")
        script = Scripted([_copilot_thread("CP_PURE"), _copilot_thread("CP_MIXED", mixed_reply)])
        result, fake = self._run(script)
        self.assertEqual(_mutations(fake, "addPullRequestReviewThreadReply"), ["CP_PURE"])
        self.assertEqual(_mutations(fake, "resolveReviewThread"), ["CP_PURE"])
        self.assertIn("CP_MIXED", result.skipped_human_reply)
        self.assertNotIn("CP_PURE", result.skipped_human_reply)
        self.assertTrue(result.re_review_requested)

    def test_truncated_fetch_raises_before_any_mutation(self):
        script = Scripted([_copilot_thread("CP1")], total=5)
        gh, fake = _gh(script)
        with self.assertRaisesRegex(GhError, "incomplete"):
            review_cycle.run_review_cycle(gh, "octo-org", "demo-repo", 7, review_cycle.CycleOptions(body="x"))
        self.assertEqual(fake.graphql_calls("mutation"), [])

    def test_empty_body_raises_before_any_call(self):
        gh, fake = _gh(Scripted([]))
        with self.assertRaises(GhError):
            review_cycle.run_review_cycle(gh, "octo-org", "demo-repo", 7, review_cycle.CycleOptions(body="  \n"))
        self.assertEqual(fake.calls, [])

    def test_kill_switch_skips_request(self):
        with patch.dict("os.environ", {copilot.COPILOT_REVIEW_ENV: "off"}):
            result, fake = self._run(Scripted([_copilot_thread("CP1")]))
        self.assertEqual(result.re_review_skip_reason, review_cycle.SKIP_DISABLED)
        self.assertEqual(_requests(fake), [])

    def test_no_request_flag_skips_request(self):
        result, fake = self._run(Scripted([]), request=False)
        self.assertEqual(result.re_review_skip_reason, review_cycle.SKIP_NOT_ASKED)
        self.assertEqual(_requests(fake), [])

    def test_no_threads_skips_request(self):
        """When no Copilot threads are selected, the re-review is skipped, not requested."""
        result, fake = self._run(Scripted([]))
        self.assertEqual(result.re_review_skip_reason, review_cycle.SKIP_NO_THREADS)
        self.assertFalse(result.re_review_requested)
        self.assertEqual(_requests(fake), [])

    def test_request_failure_is_recorded_not_raised(self):
        script = Scripted([_copilot_thread("CP1")])
        script.request_rc = 1
        result, _ = self._run(script)
        self.assertFalse(result.re_review_requested)
        self.assertEqual(result.re_review_skip_reason, review_cycle.SKIP_REQUEST_FAILED)
        self.assertTrue(any("422" in e for e in result.errors))


if __name__ == "__main__":
    unittest.main()
