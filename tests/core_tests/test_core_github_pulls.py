"""Tests for core.github.pulls: argv shape, stdin bodies, and failure paths.

The happy paths are exercised through ./bin/github's CLI tests; these pin what
each helper does when gh returns something other than what it asked for —
the branches where a thin wrapper would otherwise pass garbage on as data.
"""

from __future__ import annotations

import json
import unittest

from core.gh_cli import GhCLI, GhError
from core.github import pulls
from tests.core_tests.github_fakes import FakeGh, GhCall, ok


def _gh(handler):
    fake = FakeGh(handler)
    return GhCLI(run_func=fake), fake


class TestPrView(unittest.TestCase):
    def test_non_json_body_raises(self):
        gh, _ = _gh(lambda c: ok("not json"))
        with self.assertRaisesRegex(GhError, "non-JSON"):
            pulls.pr_view(gh, 1, ["title"])

    def test_non_object_body_raises(self):
        gh, _ = _gh(lambda c: ok([1, 2]))
        with self.assertRaisesRegex(GhError, "expected an object"):
            pulls.pr_view(gh, 1, ["title"])

    def test_no_fields_is_refused_before_calling_gh(self):
        gh, fake = _gh(lambda c: ok({}))
        with self.assertRaises(GhError):
            pulls.pr_view(gh, 1, [])
        self.assertEqual(fake.calls, [])

    def test_no_pr_means_current_branch_and_repo_is_forwarded(self):
        gh, fake = _gh(lambda c: ok({"number": 5}))
        pulls.pr_view(gh, None, ["number"], repo="o/r")
        self.assertEqual(fake.calls[0].argv, ["gh", "pr", "view", "--repo", "o/r", "--json", "number"])

    def test_gh_failure_raises_with_stderr(self):
        gh, _ = _gh(lambda c: ok("", returncode=1, stderr="no pull requests found"))
        with self.assertRaisesRegex(GhError, "no pull requests found"):
            pulls.pr_view(gh, None, ["number"])


class TestPrCreate(unittest.TestCase):
    def _handler(self, create_stdout="https://github.com/o/r/pull/9\n"):
        def handler(call: GhCall):
            if call.argv[:3] == ["gh", "pr", "create"]:
                return ok(create_stdout)
            return ok({"number": 9, "url": "https://github.com/o/r/pull/9"})
        return handler

    def test_body_goes_on_stdin_and_head_and_draft_are_passed(self):
        gh, fake = _gh(self._handler())
        out = pulls.pr_create(gh, base="main", title="t", body="`$(rm -rf /)`", head="feat/x", draft=True)
        create = fake.calls[0]
        self.assertEqual(create.input, "`$(rm -rf /)`")
        self.assertNotIn("`$(rm -rf /)`", create.argv)
        self.assertIn("--body-file", create.argv)
        self.assertEqual(create.argv[create.argv.index("--head") + 1], "feat/x")
        self.assertIn("--draft", create.argv)
        self.assertEqual(out, {"number": 9, "url": "https://github.com/o/r/pull/9"})
        # Read back by the URL gh printed, not guessed.
        self.assertEqual(fake.calls[1].argv[3], "https://github.com/o/r/pull/9")

    def test_no_url_printed_raises(self):
        gh, _ = _gh(self._handler(create_stdout="   \n"))
        with self.assertRaisesRegex(GhError, "no URL"):
            pulls.pr_create(gh, base="main", title="t", body="b")


class TestPrEdit(unittest.TestCase):
    def test_nothing_to_edit_is_refused(self):
        gh, fake = _gh(lambda c: ok({}))
        with self.assertRaises(GhError):
            pulls.pr_edit(gh, 3)
        self.assertEqual(fake.calls, [])

    def test_title_that_did_not_stick_raises(self):
        def handler(call: GhCall):
            if call.argv[:3] == ["gh", "pr", "edit"]:
                return ok("")
            return ok({"title": "old", "body": ""})
        gh, _ = _gh(handler)
        with self.assertRaisesRegex(GhError, "title did not update"):
            pulls.pr_edit(gh, 3, title="new")

    def test_trailing_whitespace_difference_is_accepted(self):
        def handler(call: GhCall):
            if call.argv[:3] == ["gh", "pr", "edit"]:
                return ok("")
            return ok({"title": "t", "body": "body text"})
        gh, fake = _gh(handler)
        pulls.pr_edit(gh, 3, body="body text\n\n")
        self.assertEqual(fake.calls[0].input, "body text\n\n")


class TestPrChecks(unittest.TestCase):
    def test_nonzero_exit_with_valid_json_is_still_the_result(self):
        # gh exits 8 while checks are pending and still prints the JSON.
        rows = [{"name": "ci", "bucket": "pending"}]
        gh, _ = _gh(lambda c: ok(rows, returncode=8))
        self.assertEqual(pulls.pr_checks(gh, 4), rows)

    def test_no_checks_reported_is_an_empty_list(self):
        gh, _ = _gh(lambda c: ok("", returncode=1, stderr="no checks reported on the 'x' branch"))
        self.assertEqual(pulls.pr_checks(gh, 4), [])

    def test_empty_output_for_any_other_reason_raises(self):
        gh, _ = _gh(lambda c: ok("", returncode=1, stderr="HTTP 404"))
        with self.assertRaisesRegex(GhError, "404"):
            pulls.pr_checks(gh, 4)

    def test_non_list_raises(self):
        gh, _ = _gh(lambda c: ok({"name": "ci"}))
        with self.assertRaisesRegex(GhError, "expected a list"):
            pulls.pr_checks(gh, 4)

    def test_watch_returns_gh_exit_code(self):
        gh, fake = _gh(lambda c: ok("", returncode=1))
        self.assertEqual(pulls.pr_checks_watch(gh, 4, interval=30), 1)
        self.assertEqual(fake.calls[0].argv[-3:], ["--watch", "--interval", "30"])


class TestPrList(unittest.TestCase):
    def test_filters_are_forwarded(self):
        gh, fake = _gh(lambda c: ok([]))
        pulls.pr_list(gh, fields=["number"], state="merged", limit=5, author="a", head="h", search="s")
        argv = fake.calls[0].argv
        for flag, value in (("--state", "merged"), ("--limit", "5"), ("--author", "a"),
                            ("--head", "h"), ("--search", "s"), ("--json", "number")):
            self.assertEqual(argv[argv.index(flag) + 1], value)

    def test_non_list_raises(self):
        gh, _ = _gh(lambda c: ok({"number": 1}))
        with self.assertRaises(GhError):
            pulls.pr_list(gh, fields=["number"])


class TestComments(unittest.TestCase):
    def test_empty_comment_is_refused_before_calling_gh(self):
        gh, fake = _gh(lambda c: ok(""))
        with self.assertRaises(GhError):
            pulls.pr_comment(gh, 2, "  \n")
        self.assertEqual(fake.calls, [])

    def test_comment_body_on_stdin(self):
        gh, fake = _gh(lambda c: ok("https://x/c\n"))
        self.assertEqual(pulls.pr_comment(gh, 2, "@/etc/passwd"), "https://x/c")
        self.assertEqual(fake.calls[0].input, "@/etc/passwd")

    def test_comment_kinds_hit_their_endpoints_paginated(self):
        gh, fake = _gh(lambda c: ok([[{"id": 1}], [{"id": 2}]]))
        self.assertEqual(pulls.pr_comments(gh, "o", "r", 6, kind="review"), [{"id": 1}, {"id": 2}])
        pulls.pr_comments(gh, "o", "r", 6, kind="issue")
        self.assertEqual(fake.calls[0].argv[-1], "repos/o/r/pulls/6/comments")
        self.assertEqual(fake.calls[1].argv[-1], "repos/o/r/issues/6/comments")
        self.assertTrue(all("--paginate" in c.argv for c in fake.calls))

    def test_unknown_kind_raises(self):
        gh, _ = _gh(lambda c: ok([]))
        with self.assertRaisesRegex(GhError, "unknown comment kind"):
            pulls.pr_comments(gh, "o", "r", 6, kind="thread")


class TestPrReviewComment(unittest.TestCase):
    def _handler(self, post_payload, post_rc=0):
        def handler(call: GhCall):
            if call.argv[:3] == ["gh", "pr", "view"]:
                return ok({"headRefOid": "headsha123"})
            if "--method" in call.argv:
                return ok(post_payload, returncode=post_rc)
            raise AssertionError(call.argv)
        return handler

    def test_posts_typed_fields_with_the_pr_head_sha(self):
        gh, fake = _gh(self._handler({"id": 99, "html_url": "https://x/r99"}))
        out = pulls.pr_review_comment(gh, "o", "r", 7, path="a.py", line=12, body="@/etc/passwd")
        self.assertEqual(out, {"id": "99", "url": "https://x/r99"})
        post = fake.calls[-1]
        self.assertEqual(post.argv[:5], ["gh", "api", "--method", "POST", "repos/o/r/pulls/7/comments"])
        self.assertEqual(post.fields["line"], ("-F", "12"))
        self.assertEqual(post.fields["body"], ("-f", "@/etc/passwd"))
        self.assertEqual(post.fields["commit_id"], ("-f", "headsha123"))
        self.assertEqual(post.fields["side"], ("-f", "RIGHT"))

    def test_explicit_commit_skips_the_head_lookup(self):
        gh, fake = _gh(self._handler({"id": 1}))
        pulls.pr_review_comment(gh, "o", "r", 7, path="a.py", line=1, body="b", commit_id="abc")
        self.assertEqual([c.argv[1] for c in fake.calls], ["api"])

    def test_response_without_id_is_an_error(self):
        gh, _ = _gh(self._handler({"message": "Validation Failed"}))
        with self.assertRaisesRegex(GhError, "returned no id"):
            pulls.pr_review_comment(gh, "o", "r", 7, path="a.py", line=1, body="b")

    def test_http_failure_is_an_error(self):
        gh, _ = _gh(self._handler("", post_rc=1))
        with self.assertRaises(GhError):
            pulls.pr_review_comment(gh, "o", "r", 7, path="a.py", line=1, body="b", commit_id="abc")

    def test_bad_inputs_refused_before_any_call(self):
        for kwargs in ({"body": "  "}, {"line": 0}, {"side": "UP"}):
            gh, fake = _gh(self._handler({"id": 1}))
            args = {"path": "a.py", "line": 1, "body": "b", **kwargs}
            with self.subTest(kwargs=kwargs), self.assertRaises(GhError):
                pulls.pr_review_comment(gh, "o", "r", 7, **args)
            self.assertEqual(fake.calls, [])


class TestRunLog(unittest.TestCase):
    def test_failed_only_by_default_and_full_log_on_request(self):
        gh, fake = _gh(lambda c: ok("log"))
        pulls.run_log(gh, 11)
        pulls.run_log(gh, 11, failed_only=False)
        self.assertEqual(fake.calls[0].argv[-1], "--log-failed")
        self.assertEqual(fake.calls[1].argv[-1], "--log")


class TestApiPaginatedFailures(unittest.TestCase):
    def test_nonzero_exit_raises(self):
        gh, _ = _gh(lambda c: ok("", returncode=1, stderr="HTTP 403"))
        with self.assertRaisesRegex(GhError, "403"):
            gh.api_paginated("repos/o/r/pulls/1/reviews")

    def test_non_json_raises(self):
        gh, _ = _gh(lambda c: ok("<html>"))
        with self.assertRaisesRegex(GhError, "non-JSON"):
            gh.api_paginated("repos/o/r/pulls/1/reviews")

    def test_object_instead_of_pages_raises(self):
        gh, _ = _gh(lambda c: ok(json.dumps({"message": "Not Found"})))
        with self.assertRaisesRegex(GhError, "expected a list of pages"):
            gh.api_paginated("repos/o/r/pulls/1/reviews")


if __name__ == "__main__":
    unittest.main()
