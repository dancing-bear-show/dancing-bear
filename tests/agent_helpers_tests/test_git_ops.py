"""git-ops against throwaway local repositories (no network)."""

from __future__ import annotations

import os
import unittest.mock

from agent_helpers import git_ops
from core.process import CompletedRun, run_binary
from tests.agent_helpers_tests.helpers import run_json, write
from tests.fixtures import TempDirMixin

_IDENT = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


def _git(cwd: str, *args: str) -> None:
    run = run_binary(["git", *_IDENT, *args], cwd=cwd, timeout=30)
    if not run.ok:
        raise AssertionError(f"git {args} failed: {run.stdout}{run.stderr}")


class GitRepoCase(TempDirMixin, unittest.TestCase):
    """A repo on branch ``main`` with one commit and a second branch ``topic``."""

    repo: str

    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.tmpdir, "repo")
        os.mkdir(self.repo)
        _git(self.repo, "init", "-q", "-b", "main")
        write(self.repo, "a.txt", "a\n")
        _git(self.repo, "add", "a.txt")
        _git(self.repo, "commit", "-q", "-m", "init")
        _git(self.repo, "branch", "topic")

    def _head(self) -> str:
        return run_binary(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=self.repo, timeout=30).stdout.strip()


class TestCheckout(GitRepoCase):
    def test_switches_branch(self):
        result = git_ops.op_checkout(self.repo, "topic", fetch=False)
        self.assertEqual((result["status"], result["branch"]), ("ok", "topic"))
        self.assertEqual(self._head(), "topic")

    def test_unknown_branch_is_error_with_git_output(self):
        result = git_ops.op_checkout(self.repo, "nope", fetch=False)
        self.assertEqual(result["status"], "error")
        self.assertIn("nope", result["output"])
        self.assertEqual(self._head(), "main")

    def test_dirty_tree_refuses(self):
        write(self.repo, "a.txt", "changed\n")
        result = git_ops.op_checkout(self.repo, "topic", fetch=False)
        self.assertEqual(result["status"], "error")
        self.assertIn("uncommitted", result["output"])
        self.assertEqual(self._head(), "main")

    def test_branch_required_and_option_like_rejected(self):
        self.assertIn("required", git_ops.op_checkout(self.repo, None, False)["output"])
        self.assertIn("must not start", git_ops.op_checkout(self.repo, "--force", False)["output"])

    def test_fetch_failure_stops_before_checkout(self):
        # No remote named origin: fetch fails locally, without touching the network.
        result = git_ops.op_checkout(self.repo, "topic", fetch=True)
        self.assertEqual(result["status"], "error")
        self.assertEqual(self._head(), "main")


class TestWorktrees(GitRepoCase):
    def test_add_list_remove_roundtrip(self):
        wt = os.path.join(self.tmpdir, "wt")
        added = git_ops.op_worktree_add(self.repo, wt, "topic")
        self.assertEqual(added["status"], "ok", added["output"])
        self.assertIn("wt", git_ops.op_worktree_list(self.repo)["output"])
        removed = git_ops.op_worktree_remove(self.repo, wt, None)
        self.assertEqual(removed["status"], "ok", removed["output"])
        self.assertNotIn("wt", git_ops.op_worktree_list(self.repo)["output"])

    def test_remove_then_checkout(self):
        wt = os.path.join(self.tmpdir, "wt")
        git_ops.op_worktree_add(self.repo, wt, "topic")
        result = git_ops.op_worktree_remove(self.repo, wt, "topic")
        # topic was only checked out in the removed worktree, so the main repo can take it.
        self.assertEqual((result["status"], result["branch"]), ("ok", "topic"), result["output"])
        self.assertEqual(self._head(), "topic")

    def test_remove_failure_skips_checkout(self):
        result = git_ops.op_worktree_remove(self.repo, os.path.join(self.tmpdir, "missing"), "topic")
        self.assertEqual(result["status"], "error")
        self.assertEqual(self._head(), "main")

    def test_remove_then_checkout_refuses_dirty_tree(self):
        wt = os.path.join(self.tmpdir, "wt")
        git_ops.op_worktree_add(self.repo, wt, "topic")
        write(self.repo, "a.txt", "changed\n")
        result = git_ops.op_worktree_remove(self.repo, wt, "topic")
        self.assertEqual(result["status"], "error")
        self.assertIn("uncommitted", result["output"])

    def test_add_requires_path_and_branch(self):
        for path, branch in ((None, "topic"), ("x", None)):
            with self.subTest(path=path, branch=branch):
                self.assertEqual(git_ops.op_worktree_add(self.repo, path, branch)["status"], "error")

    def test_remove_requires_path_and_rejects_option_like(self):
        self.assertEqual(git_ops.op_worktree_remove(self.repo, None, None)["status"], "error")
        self.assertIn("must not start", git_ops.op_worktree_remove(self.repo, "--force", None)["output"])

    def test_list_reports_main_worktree(self):
        result = git_ops.op_worktree_list(self.repo)
        self.assertEqual(result["status"], "ok")
        self.assertIn("main", result["output"])


class TestTimeoutAndCli(GitRepoCase):
    def test_timeout_is_reported_in_output(self):
        timed_out = CompletedRun(stdout="", stderr="partial", returncode=124, timed_out=True)
        with unittest.mock.patch.object(git_ops, "run_binary", return_value=timed_out):
            result = git_ops.op_worktree_list(self.repo)
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["output"].startswith("timed out"))

    def test_cli_worktree_list_from_repo_cwd(self):
        with self.in_tmpdir():
            os.chdir(self.repo)
            result = run_json(["git-ops", "--op", "worktree-list"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["op"], "worktree-list")

    def test_cli_outside_repo_reports_error_in_body(self):
        with unittest.mock.patch("agent_helpers.cli.resolve_repo_root", return_value=("", "not inside a git repository")):
            result = run_json(["git-ops", "--op", "worktree-list"])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output"], "not inside a git repository")


if __name__ == "__main__":
    unittest.main()
