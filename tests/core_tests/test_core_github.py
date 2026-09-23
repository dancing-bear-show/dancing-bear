"""Tests for core.github: review-thread fetch, author classification, mutations.

Each correctness test pins a defect a hand-written implementation in this repo
actually had — bin/pr-assistant or a workflow's prose — and fails if the fix is
reverted. The fixtures page like GitHub does, so "complete" means every page
was followed, not that the fixture happened to fit in one response.
"""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest import mock

from core.gh_cli import GhCLI, GhError, field_args
from core.github import (
    build_threads_doc,
    classify_author,
    fetch_review_threads,
    fetch_thread_comments,
    forged_run_marker,
    has_run_marker,
    mark_body,
    render_summary,
    reply_and_resolve,
    reply_to_thread,
    resolve_owner_repo,
    resolve_thread,
    run_marker,
    viewer_login,
)
from core.github.threads import COMMENT_PAGE, THREAD_PAGE
from tests.core_tests.github_fakes import FakeGh, GhCall, comment_node, ok, paged

# ---------------------------------------------------------------------------
# A paging GitHub
# ---------------------------------------------------------------------------


def _thread(i: int, comments: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    node = {
        "id": f"PRRT_{i}", "isResolved": False, "isOutdated": False, "isCollapsed": False,
        "path": f"src/f{i}.py", "line": i, "startLine": None, "diffSide": "RIGHT",
        "_all_comments": comments,
    }
    node.update(extra)
    return node


class PagingGitHub:
    """Answers GraphQL thread queries and REST list endpoints with real paging."""

    def __init__(self, threads: list[dict[str, Any]], reviews: list[dict[str, Any]] | None = None,
                 issue_comments: list[dict[str, Any]] | None = None, rest_page: int = 30) -> None:
        self.threads = threads
        self.reviews = reviews or []
        self.issue_comments = issue_comments or []
        self.rest_page = rest_page

    def _comments_conn(self, thread: dict[str, Any], after: str | None) -> dict[str, Any]:
        nodes, info = paged(thread["_all_comments"], COMMENT_PAGE, after, "c")
        return {"totalCount": len(thread["_all_comments"]), "pageInfo": info, "nodes": nodes}

    def _rest(self, items: list[dict[str, Any]], argv: list[str]):
        pages = [items[i:i + self.rest_page] for i in range(0, len(items), self.rest_page)] or [[]]
        if "--paginate" not in argv:
            # What gh does without --paginate: the first page only.
            pages = pages[:1]
        if "--slurp" in argv:
            return ok(pages)
        return ok([x for p in pages for x in p])

    def __call__(self, call: GhCall):
        argv = call.argv
        if "graphql" in argv and "reviewThreads" in call.query:
            nodes, info = paged(self.threads, THREAD_PAGE, call.value("after"), "t")
            out = []
            for t in nodes:
                node = {k: v for k, v in t.items() if k != "_all_comments"}
                node["comments"] = self._comments_conn(t, None)
                out.append(node)
            conn = {"totalCount": len(self.threads), "pageInfo": info, "nodes": out}
            return ok({"data": {"repository": {"pullRequest": {"reviewThreads": conn}}}})
        if "graphql" in argv and "node(id:" in call.query:
            thread = next(t for t in self.threads if t["id"] == call.value("id"))
            return ok({"data": {"node": {"comments": self._comments_conn(thread, call.value("after"))}}})
        if argv[:2] == ["gh", "api"] and any(a.endswith("/reviews") for a in argv):
            return self._rest(self.reviews, argv)
        if argv[:2] == ["gh", "api"] and any(a.endswith("/comments") for a in argv):
            return self._rest(self.issue_comments, argv)
        raise AssertionError(f"unexpected gh call: {argv}")


def _fetch(github: PagingGitHub):
    fake = FakeGh(github)
    doc, raw = fetch_review_threads(GhCLI(run_func=fake), "o", "r", 7)
    return doc, raw, fake


def _review(i: int, login: str = "someone", user_type: str = "User", body: str | None = None) -> dict[str, Any]:
    return {
        "id": 5000 + i, "user": {"login": login, "type": user_type},
        "body": body if body is not None else f"review {i}", "state": "COMMENTED",
        "submitted_at": f"2026-09-{1 + i // 24:02d}T{i % 24:02d}:00:00Z", "html_url": f"https://x/r{i}",
    }


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestThreadPagination(unittest.TestCase):
    def test_more_than_one_page_of_threads_comes_back_complete(self):
        threads = [_thread(i, [comment_node(i)]) for i in range(THREAD_PAGE + 37)]
        doc, _, fake = _fetch(PagingGitHub(threads))
        ids = [t["thread_id"] for t in doc["threads"]]
        self.assertEqual(ids, [f"PRRT_{i}" for i in range(THREAD_PAGE + 37)])
        self.assertFalse(doc["truncated"])
        self.assertEqual(len(fake.graphql_calls("reviewThreads")), 2)
        self.assertEqual(fake.graphql_calls("reviewThreads")[1].value("after"), f"t{THREAD_PAGE}")

    def test_more_than_one_page_of_comments_in_one_thread_comes_back_complete(self):
        n = COMMENT_PAGE * 2 + 13
        comments = [comment_node(i) for i in range(n)]
        comments[-1] = comment_node(n - 1, login="human-late", typename="User")
        doc, _, fake = _fetch(PagingGitHub([_thread(0, comments)]))
        entry = doc["threads"][0]
        self.assertEqual(len(entry["comments"]), n)
        self.assertEqual(entry["comments"][-1]["body"], f"comment {n - 1}")
        self.assertEqual([c["database_id"] for c in entry["comments"]], [1000 + i for i in range(n)])
        # The follow-up pages start where the inline page ended.
        follow = fake.graphql_calls("node(id:")
        self.assertEqual([c.value("after") for c in follow], [f"c{COMMENT_PAGE}", f"c{COMMENT_PAGE * 2}"])
        self.assertFalse(doc["truncated"])

    def test_more_than_thirty_reviews_returns_the_newest(self):
        reviews = [_review(i) for i in range(47)]
        doc, raw, fake = _fetch(PagingGitHub([], reviews=reviews))
        self.assertEqual(len(raw["reviews"]), 47)
        ids = [b["review_id"] for b in doc["review_bodies"]]
        self.assertIn(5046, ids, "the newest review (on the last page) was dropped")
        rest = [c for c in fake.calls if any(a.endswith("/reviews") for a in c.argv)]
        self.assertIn("--paginate", rest[0].argv)

    def test_issue_comments_are_paginated_too(self):
        comments = [
            {"id": i, "user": {"login": "h", "type": "User"}, "body": f"ic {i}",
             "created_at": "2026-09-23T00:00:00Z", "html_url": "u"}
            for i in range(65)
        ]
        doc, _, _ = _fetch(PagingGitHub([], issue_comments=comments))
        issue = [t for t in doc["threads"] if t["source"] == "issue-comment"]
        self.assertEqual(len(issue), 65)

    def test_stalled_cursor_raises_rather_than_looping_or_stopping_short(self):
        def handler(call: GhCall):
            conn = {"totalCount": 200, "pageInfo": {"hasNextPage": True, "endCursor": "same"},
                    "nodes": [{"id": "PRRT_x", "comments": {"totalCount": 0, "nodes": [], "pageInfo": {}}}]}
            return ok({"data": {"repository": {"pullRequest": {"reviewThreads": conn}}}})
        with self.assertRaisesRegex(GhError, "did not advance"):
            fetch_review_threads(GhCLI(run_func=FakeGh(handler)), "o", "r", 1)

    def test_missing_cursor_with_has_next_page_raises(self):
        def handler(call: GhCall):
            conn = {"totalCount": 5, "pageInfo": {"hasNextPage": True, "endCursor": None}, "nodes": []}
            return ok({"data": {"repository": {"pullRequest": {"reviewThreads": conn}}}})
        with self.assertRaises(GhError):
            fetch_review_threads(GhCLI(run_func=FakeGh(handler)), "o", "r", 1)

    def test_count_mismatch_is_flagged_truncated_not_reported_clean(self):
        def handler(call: GhCall):
            if "reviewThreads" in call.query:
                conn = {"totalCount": 3, "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [{"id": "PRRT_1", "comments": {
                            "totalCount": 1, "pageInfo": {"hasNextPage": False}, "nodes": [comment_node(1)]}}]}
                return ok({"data": {"repository": {"pullRequest": {"reviewThreads": conn}}}})
            return ok([[]])
        doc, _ = fetch_review_threads(GhCLI(run_func=FakeGh(handler)), "o", "r", 1)
        self.assertTrue(doc["truncated"])

    def test_pr_not_found_is_an_error_not_an_empty_result(self):
        # Structurally valid, semantically empty: a wrong PR number must not
        # read as "this PR has no threads".
        def handler(call: GhCall):
            return ok({"data": {"repository": {"pullRequest": None}}})
        with self.assertRaisesRegex(GhError, "no repository.pullRequest"):
            fetch_review_threads(GhCLI(run_func=FakeGh(handler)), "o", "r", 999)

    def test_zero_threads_is_a_valid_empty_result(self):
        doc, _, _ = _fetch(PagingGitHub([]))
        self.assertEqual(doc["threads"], [])
        self.assertEqual(doc["counts"]["total"], 0)
        self.assertFalse(doc["truncated"])

    def test_fetch_thread_comments_follows_every_page(self):
        n = COMMENT_PAGE + 5
        gh = GhCLI(run_func=FakeGh(PagingGitHub([_thread(0, [comment_node(i) for i in range(n)])])))
        self.assertEqual(len(fetch_thread_comments(gh, "PRRT_0")), n)


# ---------------------------------------------------------------------------
# Author classification
# ---------------------------------------------------------------------------


class TestClassifyAuthor(unittest.TestCase):
    def test_typename_bot_with_bare_unlisted_login_is_bot(self):
        # github-code-quality: no [bot] suffix, on no allowlist. Login-only
        # classification called it human on 10 of 14 threads of a real PR.
        self.assertEqual(classify_author("github-code-quality", typename="Bot"), "bot")

    def test_rest_user_type_bot_is_bot(self):
        self.assertEqual(classify_author("github-code-quality", user_type="Bot"), "bot")

    def test_both_copilot_spellings_are_bot_by_login_fallback(self):
        self.assertEqual(classify_author("copilot-pull-request-reviewer"), "bot")
        self.assertEqual(classify_author("copilot-pull-request-reviewer[bot]"), "bot")

    def test_typed_field_decides_over_login(self):
        self.assertEqual(classify_author("github-actions", typename="User"), "human")

    def test_plain_user_and_missing_author_are_human(self):
        self.assertEqual(classify_author("alice", typename="User"), "human")
        self.assertEqual(classify_author(None), "human")
        self.assertEqual(classify_author("some-app[bot]"), "bot")

    def test_fetch_classifies_github_code_quality_threads_as_bot(self):
        comments = [comment_node(0, login="github-code-quality", typename="Bot"),
                    comment_node(1, login="alice", typename="User")]
        doc, _, _ = _fetch(PagingGitHub([_thread(0, comments)]))
        entry = doc["threads"][0]
        self.assertEqual(entry["author_kind"], "bot")
        self.assertEqual(entry["latest_author_kind"], "human")
        self.assertEqual(doc["counts"]["bot"], 1)


# ---------------------------------------------------------------------------
# Document shape
# ---------------------------------------------------------------------------


class TestThreadsDoc(unittest.TestCase):
    def test_rest_entries_carry_no_thread_id_and_do_not_count_as_unresolved(self):
        doc = build_threads_doc(
            owner="o", repo="r", pr=3,
            raw_threads=[{"id": "PRRT_a", "isResolved": True, "isOutdated": True, "line": None,
                          "path": "p", "comments": {"nodes": [comment_node(0)]}}],
            reviews=[_review(0, "copilot-pull-request-reviewer[bot]", "Bot"), _review(1, body="  ")],
            issue_comments=[{"id": 9, "user": {"login": "h", "type": "User"}, "body": "hi"}],
        )
        by_source = {t["source"]: t for t in doc["threads"]}
        self.assertIsNone(by_source["review-body"]["thread_id"])
        self.assertIsNone(by_source["issue-comment"]["thread_id"])
        self.assertEqual(doc["counts"]["unresolved"], 0)
        self.assertEqual(doc["counts"]["resolved"], 1)
        self.assertEqual(doc["counts"]["total"], 3)
        # Empty-bodied reviews are not review bodies.
        self.assertEqual([b["review_id"] for b in doc["review_bodies"]], [5000])
        self.assertEqual(doc["repo"], "o/r")
        self.assertEqual(doc["pr_number"], "3")

    def test_outdated_thread_keeps_null_line(self):
        doc = build_threads_doc(owner="o", repo="r", pr=1, reviews=[], issue_comments=[],
                                raw_threads=[{"id": "T", "isOutdated": True, "line": None,
                                              "comments": {"nodes": [comment_node(0)]}}])
        self.assertIsNone(doc["threads"][0]["line"])
        self.assertTrue(doc["threads"][0]["is_outdated"])

    def test_review_body_kept_verbatim(self):
        body = "<!-- ccr-overview-v2 -->\n  <details>​ x  </details>\n"
        doc = build_threads_doc(owner="o", repo="r", pr=1, raw_threads=[], issue_comments=[],
                                reviews=[_review(0, body=body)])
        self.assertEqual(doc["review_bodies"][0]["body"], body)

    def test_summary_lists_every_entry(self):
        doc = build_threads_doc(owner="o", repo="r", pr=1, reviews=[_review(0)], issue_comments=[],
                                raw_threads=[{"id": "PRRT_abcdefgh1234", "line": 4, "path": "a.py",
                                              "comments": {"nodes": [comment_node(0)]}}])
        text = render_summary(doc)
        self.assertIn("`efgh1234`", text)
        self.assertIn("a.py:4", text)
        self.assertIn("review-body", text)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def _mutation_gh(reply_payload: Any, resolve_payload: Any | None = None, reply_rc: int = 0):
    def handler(call: GhCall):
        if "addPullRequestReviewThreadReply" in call.query:
            return ok(reply_payload, returncode=reply_rc)
        if "resolveReviewThread" in call.query:
            return ok(resolve_payload)
        raise AssertionError(call.argv)
    fake = FakeGh(handler)
    return GhCLI(run_func=fake), fake


_GOOD_REPLY = {"data": {"addPullRequestReviewThreadReply": {"comment": {"id": "PRRC_1", "url": "u"}}}}
_GOOD_RESOLVE = {"data": {"resolveReviewThread": {"thread": {"id": "T", "isResolved": True}}}}


class TestReplyAndResolve(unittest.TestCase):
    def test_http_200_with_errors_and_null_comment_is_failed_and_not_resolved(self):
        gh, fake = _mutation_gh(
            {"data": {"addPullRequestReviewThreadReply": {"comment": None}},
             "errors": [{"message": "Could not resolve to a node"}]},
            _GOOD_RESOLVE,
        )
        with self.assertRaisesRegex(GhError, "Could not resolve"):
            reply_and_resolve(gh, "T", "fixed in abc")
        self.assertEqual(fake.graphql_calls("resolveReviewThread"), [])

    def test_errors_alone_fail_even_with_a_comment_id(self):
        gh, _ = _mutation_gh({"data": {"addPullRequestReviewThreadReply": {"comment": {"id": "X"}}},
                              "errors": [{"message": "partial"}]})
        with self.assertRaises(GhError):
            reply_to_thread(gh, "T", "b")

    def test_null_comment_alone_fails_even_without_errors(self):
        gh, fake = _mutation_gh({"data": {"addPullRequestReviewThreadReply": {"comment": None}}},
                                _GOOD_RESOLVE)
        with self.assertRaisesRegex(GhError, "no comment id"):
            reply_and_resolve(gh, "T", "b")
        self.assertEqual(fake.graphql_calls("resolveReviewThread"), [])

    def test_body_starting_with_at_path_is_sent_as_literal_string(self):
        gh, fake = _mutation_gh(_GOOD_REPLY)
        reply_to_thread(gh, "T", "@/etc/passwd")
        call = fake.graphql_calls("addPullRequestReviewThreadReply")[0]
        self.assertEqual(call.fields["body"], ("-f", "@/etc/passwd"))
        self.assertNotIn("-F", [a for a, b in zip(call.argv, call.argv[1:]) if b.startswith("body=")])

    def test_good_reply_then_verified_resolve(self):
        gh, fake = _mutation_gh(_GOOD_REPLY, _GOOD_RESOLVE)
        out = reply_and_resolve(gh, "T", "done")
        self.assertEqual(out, {"reply": {"comment_id": "PRRC_1", "url": "u"}, "resolved": True, "error": None})
        order = [("reply" if "addPull" in c.query else "resolve") for c in fake.calls]
        self.assertEqual(order, ["reply", "resolve"])

    def test_resolve_that_does_not_report_resolved_is_failed(self):
        gh, _ = _mutation_gh(_GOOD_REPLY, {"data": {"resolveReviewThread": {"thread": {"isResolved": False}}}})
        out = reply_and_resolve(gh, "T", "done")
        self.assertFalse(out["resolved"])
        self.assertIn("isResolved", out["error"])

    def test_resolve_with_errors_and_exit_zero_raises(self):
        gh, _ = _mutation_gh(_GOOD_REPLY, {"data": {"resolveReviewThread": None}, "errors": [{"message": "no"}]})
        with self.assertRaises(GhError):
            resolve_thread(gh, "T")

    def test_empty_reply_is_refused_before_any_call(self):
        gh, fake = _mutation_gh(_GOOD_REPLY)
        with self.assertRaises(GhError):
            reply_to_thread(gh, "T", "   ")
        self.assertEqual(fake.calls, [])

    def test_run_marker_found_anywhere_in_the_chain(self):
        chain = [{"author": "rev", "body": "fix"},
                 {"author": "me[bot]", "body": "ok\n" + run_marker("run-1")},
                 {"author": "rev", "body": "reviewer again"}]
        self.assertTrue(has_run_marker(chain, "run-1", actor="me"))
        self.assertFalse(has_run_marker(chain, "run-2", actor="me"))

    def test_marker_by_anyone_else_is_forged_not_prior_work(self):
        chain = [{"author": "mallory", "body": "pasted " + run_marker("run-1")}]
        self.assertFalse(has_run_marker(chain, "run-1", actor="me"))
        self.assertTrue(forged_run_marker(chain, "run-1", actor="me"))
        self.assertFalse(forged_run_marker([{"author": "me", "body": run_marker("run-1")}],
                                           "run-1", actor="me"))

    def test_mark_body_strips_every_quoted_marker_then_appends_ours(self):
        body = "> <!-- dancing-bear-run: A -->\n<!--\ndancing-bear-run: B\n-->\nfixed\n"
        out = mark_body(body, "R")
        self.assertEqual(out.count("dancing-bear-run"), 1)
        self.assertTrue(out.endswith("\n\n" + run_marker("R")))
        self.assertEqual(mark_body("x " + run_marker("A"), None), "x")

    def test_viewer_login_fails_closed(self):
        for payload in ({"data": {"viewer": {"login": ""}}}, {"data": {"viewer": None}}):
            gh = GhCLI(run_func=FakeGh(lambda c, p=payload: ok(p)))
            with self.subTest(payload=payload), self.assertRaises(GhError):
                viewer_login(gh)
        gh = GhCLI(run_func=FakeGh(lambda c: ok({"data": {"viewer": {"login": "me"}}})))
        self.assertEqual(viewer_login(gh), "me")


# ---------------------------------------------------------------------------
# GhCLI plumbing the helper relies on
# ---------------------------------------------------------------------------


class TestGhPlumbing(unittest.TestCase):
    def test_field_args_types(self):
        self.assertEqual(
            field_args({"s": "@/x", "i": 3, "b": True, "n": None, "t": "true"}),
            ["-f", "s=@/x", "-F", "i=3", "-F", "b=true", "-f", "t=true"],
        )

    def test_graphql_checked_raises_on_nonzero_exit_non_json_and_missing_data(self):
        for payload, rc in (("boom", 1), ("not json", 0), ({"data": None}, 0)):
            gh = GhCLI(run_func=FakeGh(lambda c, p=payload, r=rc: ok(p, returncode=r)))
            with self.subTest(payload=payload), self.assertRaises(GhError):
                gh.graphql_checked("query { x }")

    def test_api_paginated_rejects_non_list_pages(self):
        gh = GhCLI(run_func=FakeGh(lambda c: ok([{"message": "Not Found"}])))
        with self.assertRaisesRegex(GhError, "not a list endpoint"):
            gh.api_paginated("repos/o/r/pulls/1/reviews")

    def test_scrub_removes_github_token_only(self):
        fake = FakeGh(lambda c: ok("o/r\n"))
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "stale", "GH_TOKEN": "keep"}):
            GhCLI(run_func=fake, scrub_github_token=True).run(["repo", "view"])
            GhCLI(run_func=fake).run(["repo", "view"])
        self.assertNotIn("GITHUB_TOKEN", fake.calls[0].env)
        self.assertEqual(fake.calls[0].env["GH_TOKEN"], "keep")
        self.assertIsNone(fake.calls[1].env)

    def test_resolve_owner_repo(self):
        gh = GhCLI(run_func=FakeGh(lambda c: ok("octo/cat\n")))
        self.assertEqual(resolve_owner_repo(gh), ("octo", "cat"))
        self.assertEqual(resolve_owner_repo(gh, "a/b"), ("a", "b"))
        for bad in ("nope", "a/b/c", "/b", "a/"):
            with self.subTest(bad=bad), self.assertRaises(GhError):
                resolve_owner_repo(gh, bad)

    def test_resolve_owner_repo_failure_raises(self):
        gh = GhCLI(run_func=FakeGh(lambda c: ok("", returncode=1, stderr="not a git repo")))
        with self.assertRaisesRegex(GhError, "not a git repo"):
            resolve_owner_repo(gh)


if __name__ == "__main__":
    unittest.main()
