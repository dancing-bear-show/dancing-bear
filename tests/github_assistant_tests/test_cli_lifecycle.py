"""CLI wiring for ``pr summary``, ``activity``, and the ``copilot`` group.

Behaviour lives in ``core.github`` and is tested in
``tests/core_tests/test_core_github_review_cycle.py`` and
``test_core_github_summary_activity.py``; these pin argv routing, output
shape, and exit codes.
"""

from __future__ import annotations

import json
import os
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from core.gh_cli import GhCLI
from core.github.copilot import COPILOT_REVIEW_ENV
from tests.github_assistant_tests.test_cli import FakeGhRunner, _install_client, _run_cli

REPO = ["--repo", "octo-org/demo-repo"]


def _pr_detail(number: int, paths: list[str]) -> str:
    return json.dumps({"data": {"repository": {"pullRequest": {
        "number": number, "title": f"PR {number}", "state": "MERGED", "url": f"https://example.invalid/{number}",
        "mergedAt": None, "closedAt": None, "baseRefName": "main", "headRefName": f"feat/{number}",
        "additions": 1, "deletions": 0, "changedFiles": len(paths), "author": {"login": "alice"},
        "files": {"totalCount": len(paths), "pageInfo": {"hasNextPage": False, "endCursor": None},
                  "nodes": [{"path": p, "additions": 1, "deletions": 0} for p in paths]},
    }}}})


class TestPrSummary(unittest.TestCase):
    def test_single_pr_json_omits_files_by_default(self):
        fake = FakeGhRunner()
        fake.add(["graphql", "files(first"], stdout=_pr_detail(476, ["src/a.py"]))
        with _install_client(fake):
            rc, out, _ = _run_cli(["pr", "summary", *REPO, "--pr", "476"])
        self.assertEqual(rc, 0)
        rows = json.loads(out)
        self.assertEqual([r["number"] for r in rows], [476])
        self.assertNotIn("files", rows[0])
        self.assertFalse(any(c.argv[1:3] == ["pr", "list"] for c in fake.calls))

    def test_files_flag_includes_files(self):
        fake = FakeGhRunner()
        fake.add(["graphql", "files(first"], stdout=_pr_detail(476, ["src/a.py"]))
        with _install_client(fake):
            _, out, _ = _run_cli(["pr", "summary", *REPO, "--pr", "476", "--files"])
        self.assertEqual(json.loads(out)[0]["files"][0]["path"], "src/a.py")

    def test_list_mode_uses_pr_list_and_path_filter(self):
        fake = FakeGhRunner()
        fake.add(["pr", "list"], stdout=json.dumps([{"number": 1}, {"number": 2}]))
        details = {1: _pr_detail(1, ["docs/x.md"]), 2: _pr_detail(2, ["src/core/y.py"])}

        def routed(cmd: list[str], **kwargs: Any) -> Any:
            # Each detail query carries its PR number in the stdin variables.
            if cmd[:3] == ["gh", "api", "graphql"]:
                pr = json.loads(kwargs["input"])["variables"]["pr"]
                return SimpleNamespace(returncode=0, stdout=details[pr], stderr="")
            return fake(cmd, **kwargs)

        with patch("github_assistant.cli.client", return_value=GhCLI(run_func=routed)):
            rc, out, _ = _run_cli(["pr", "summary", *REPO, "--author", "@me", "--limit", "2",
                                   "--include-path", "src/"])
        self.assertEqual(rc, 0)
        self.assertEqual([r["number"] for r in json.loads(out)], [2])
        listing = next(c.argv for c in fake.calls if c.argv[1:3] == ["pr", "list"])
        self.assertEqual(listing[listing.index("--state") + 1], "merged")
        self.assertEqual(listing[listing.index("--author") + 1], "@me")

    def test_text_with_no_match(self):
        fake = FakeGhRunner()
        fake.add(["graphql", "files(first"], stdout=_pr_detail(5, ["docs/x.md"]))
        with _install_client(fake):
            rc, out, _ = _run_cli(["pr", "summary", *REPO, "--pr", "5", "--exclude-path", "docs/",
                                   "--format", "text"])
        self.assertEqual(rc, 0)
        self.assertIn("No matching pull requests.", out)


class TestActivity(unittest.TestCase):
    def _fake(self) -> FakeGhRunner:
        fake = FakeGhRunner()
        fake.add(["graphql", "viewer"], stdout=json.dumps({"data": {"viewer": {"login": "alice"}}}))
        fake.add(["search", "prs"], stdout="[]")
        fake.add(["search", "issues"], stdout="[]")
        return fake

    def test_json_default(self):
        fake = self._fake()
        with _install_client(fake):
            rc, out, _ = _run_cli(["activity", "--owner", "octo-org"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual((data["login"], data["owner"], data["issues"]), ("alice", "octo-org", []))

    def test_text(self):
        with _install_client(self._fake()):
            rc, out, _ = _run_cli(["activity", "--format", "text"])
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("User: alice\n"))

    def test_search_failure_exits_nonzero(self):
        fake = FakeGhRunner()
        fake.add(["graphql", "viewer"], stdout=json.dumps({"data": {"viewer": {"login": "alice"}}}))
        fake.add(["search"], returncode=1, stderr="HTTP 403")
        with _install_client(fake):
            rc, _, _ = _run_cli(["activity"])
        self.assertNotEqual(rc, 0)


def _threads_doc_responses(fake: FakeGhRunner, nodes: list[dict[str, Any]]) -> None:
    fake.add(["graphql", "reviewThreads"], stdout=json.dumps({"data": {"repository": {"pullRequest": {
        "reviewThreads": {"totalCount": len(nodes), "pageInfo": {"hasNextPage": False, "endCursor": None},
                          "nodes": nodes}}}}}))
    fake.add(["--paginate"], stdout="[[]]")


def _copilot_node(tid: str) -> dict[str, Any]:
    return {"id": tid, "isResolved": False, "isOutdated": False, "path": "a.py", "line": 1,
            "comments": {"totalCount": 1, "pageInfo": {"hasNextPage": False, "endCursor": None},
                         "nodes": [{"databaseId": 1, "author": {"login": "copilot-pull-request-reviewer",
                                                                 "__typename": "Bot"},
                                    "body": "nit", "createdAt": "t", "url": "u"}]}}


@patch.dict(os.environ, {COPILOT_REVIEW_ENV: ""})
class TestCopilotGroup(unittest.TestCase):
    def test_request_posts_and_reports(self):
        fake = FakeGhRunner()
        fake.add(["requested_reviewers"], stdout=json.dumps({"number": 7, "requested_reviewers": []}))
        with _install_client(fake):
            rc, out, _ = _run_cli(["copilot", "request", *REPO, "--pr", "7"])
        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(out)["requested"])
        self.assertEqual(len(fake.calls), 1)

    def test_request_dry_run_and_kill_switch_post_nothing(self):
        for argv, env, reason in ((["--dry-run"], "", None), ([], "off", "copilot review disabled")):
            fake = FakeGhRunner()
            with _install_client(fake), patch.dict(os.environ, {COPILOT_REVIEW_ENV: env}):
                rc, out, _ = _run_cli(["copilot", "request", *REPO, "--pr", "7", *argv])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(out)["skip_reason"], reason)
            self.assertEqual(fake.calls, [])

    def test_cycle_dry_run_reads_only(self):
        fake = FakeGhRunner()
        _threads_doc_responses(fake, [_copilot_node("CP1")])
        with TemporaryDirectory() as tmp, _install_client(fake):
            body = os.path.join(tmp, "reply.md")
            with open(body, "w", encoding="utf-8") as fh:
                fh.write("Fixed.\n")
            rc, out, _ = _run_cli(["copilot", "cycle", *REPO, "--pr", "7", "--body-file", body, "--dry-run"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual([t["status"] for t in data["threads"]], ["would_reply"])
        self.assertFalse(any("mutation" in c.query_text or "requested_reviewers" in c.all_text()
                             for c in fake.calls))

    def test_cycle_reply_failure_exits_1(self):
        fake = FakeGhRunner()
        _threads_doc_responses(fake, [_copilot_node("CP1")])
        fake.add(["addPullRequestReviewThreadReply"],
                 stdout=json.dumps({"data": None, "errors": [{"message": "nope"}]}))
        with TemporaryDirectory() as tmp, _install_client(fake):
            body = os.path.join(tmp, "reply.md")
            with open(body, "w", encoding="utf-8") as fh:
                fh.write("Fixed.\n")
            rc, out, _ = _run_cli(["copilot", "cycle", *REPO, "--pr", "7", "--body-file", body])
        self.assertEqual(rc, 1)
        data = json.loads(out)
        self.assertEqual(data["re_review_skip_reason"], "errors present")
        self.assertFalse(any("resolveReviewThread" in c.query_text for c in fake.calls))


if __name__ == "__main__":
    unittest.main()
