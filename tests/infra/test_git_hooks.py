"""Tests for the .githooks/ git hook scripts.

Each hook is verified by executing it as a subprocess with crafted inputs:
- commit-msg: accepts valid Conventional Commit messages (including merge
  commits and dependabot double-scope messages) and rejects invalid ones.
- pre-push: rejects push lines targeting refs/heads/main and accepts
  feature branch push lines.

Both scripts are bash and require no Python at all, so the -I -S rule does
not apply here. The hook directory must remain a plain bash-only tree.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - runs this repo's own hook scripts, no user input
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / ".githooks"

# A real SHA40 for use in pre-push push-line payloads.
_FAKE_SHA = "abc1234567890abcdef1234567890abcdef12345"
_ZERO_SHA = "0" * 40


def _run_commit_msg(message: str) -> subprocess.CompletedProcess[str]:
    """Write message to a temp file and pipe it to the commit-msg hook."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(message)
        tmp_path = f.name
    try:
        return subprocess.run(  # nosec B603 B607 - trusted in-repo hook script
            ["bash", str(HOOKS_DIR / "commit-msg"), tmp_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
    finally:
        os.unlink(tmp_path)


def _run_pre_push(push_lines: str) -> subprocess.CompletedProcess[str]:
    """Pipe push_lines to the pre-push hook's stdin."""
    return subprocess.run(  # nosec B603 B607 - trusted in-repo hook script
        ["bash", str(HOOKS_DIR / "pre-push")],
        input=push_lines,
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestCommitMsgHookAcceptsValid(unittest.TestCase):
    """commit-msg must exit 0 for valid and auto-generated messages."""

    def _assert_accepted(self, message: str) -> None:
        result = _run_commit_msg(message)
        self.assertEqual(
            result.returncode,
            0,
            msg=f"Expected exit 0 for {message!r}:\n{result.stderr}",
        )

    def test_conventional_no_scope(self) -> None:
        self._assert_accepted("docs: update AGENTS.md with pipeline patterns\n")

    def test_conventional_with_scope(self) -> None:
        self._assert_accepted("feat(mail): add auto-labeling pipeline\n")

    def test_conventional_fix_with_scope(self) -> None:
        self._assert_accepted("fix(core): handle missing token gracefully\n")

    def test_breaking_change_marker(self) -> None:
        self._assert_accepted("feat(mail)!: change filter config format\n")

    def test_breaking_change_no_scope(self) -> None:
        self._assert_accepted("feat!: drop Python 3.9 support\n")

    def test_dependabot_double_scope(self) -> None:
        """chore(deps)(deps): style is used by dependabot in this repo."""
        self._assert_accepted("chore(deps)(deps): bump pyyaml from 6.0 to 6.0.1\n")

    def test_dependabot_dev_double_scope(self) -> None:
        self._assert_accepted("chore(deps)(deps-dev): bump mypy from 2.4.0 to 2.4.1\n")

    def test_merge_commit(self) -> None:
        """Merge commits bypass validation."""
        self._assert_accepted("Merge branch 'main' into feature/my-feat\n")

    def test_revert_commit(self) -> None:
        """Revert commits bypass validation."""
        self._assert_accepted("Revert \"feat(mail): add auto-labeling pipeline\"\n")

    def test_fixup_commit(self) -> None:
        """fixup! commits bypass validation."""
        self._assert_accepted("fixup! feat(mail): add auto-labeling pipeline\n")

    def test_squash_commit(self) -> None:
        """squash! commits bypass validation."""
        self._assert_accepted("squash! fix(core): handle missing token\n")

    def test_empty_message(self) -> None:
        """Empty messages (template-only) bypass validation."""
        self._assert_accepted("")

    def test_comment_only_message(self) -> None:
        """Messages whose only non-blank lines are comments bypass validation."""
        self._assert_accepted("# This is a comment\n# Another comment\n")

    def test_comment_then_valid_line(self) -> None:
        """A comment on line 1 followed by a valid commit line must be accepted."""
        self._assert_accepted("# comment\nfeat(mail): ok\n")

    def test_comma_separated_scopes(self) -> None:
        """Comma-separated scopes like refactor(core,workflow): ... must be accepted."""
        self._assert_accepted("refactor(core,workflow): consolidate helpers\n")

    def test_all_types_accepted(self) -> None:
        """Every type from COMMIT_CONVENTION.md must be accepted."""
        types = ["feat", "fix", "docs", "refactor", "test", "chore", "perf", "ci", "style", "revert"]
        for t in types:
            with self.subTest(type=t):
                self._assert_accepted(f"{t}: some subject\n")


class TestCommitMsgHookRejectsInvalid(unittest.TestCase):
    """commit-msg must exit 1 for non-conventional messages."""

    def _assert_rejected(self, message: str) -> None:
        result = _run_commit_msg(message)
        self.assertEqual(
            result.returncode,
            1,
            msg=f"Expected exit 1 for {message!r}; got {result.returncode}",
        )
        self.assertIn("Conventional Commits", result.stderr)

    def test_no_type(self) -> None:
        self._assert_rejected("Added a feature without conventional format\n")

    def test_wrong_case_type(self) -> None:
        self._assert_rejected("Feat(mail): upper-case type is not accepted\n")

    def test_missing_colon_space(self) -> None:
        self._assert_rejected("feat(mail):missing space after colon\n")

    def test_unknown_type(self) -> None:
        self._assert_rejected("build(ci): unknown type not in convention\n")

    def test_empty_subject(self) -> None:
        self._assert_rejected("feat(mail): \n")

    def test_colon_only(self) -> None:
        self._assert_rejected("feat:\n")

    def test_blank_first_line_not_bypassed(self) -> None:
        """A blank first line must not cause the validator to skip the real message."""
        self._assert_rejected("\nbad message\n")

    def test_comment_first_line_not_bypassed(self) -> None:
        """A comment on line 1 must not cause the validator to skip the real message."""
        self._assert_rejected("# comment\nbad message\n")


class TestPrePushHookBlocksMain(unittest.TestCase):
    """pre-push must exit 1 when any push targets main or master."""

    def _assert_blocked(self, push_lines: str) -> None:
        result = _run_pre_push(push_lines)
        self.assertEqual(
            result.returncode,
            1,
            msg=f"Expected push to be blocked:\n{push_lines!r}\n{result.stderr}",
        )
        self.assertIn("blocked", result.stderr)

    def test_blocks_push_to_main(self) -> None:
        line = f"refs/heads/feature {_FAKE_SHA} refs/heads/main {_ZERO_SHA}\n"
        self._assert_blocked(line)

    def test_blocks_push_to_master(self) -> None:
        line = f"refs/heads/feature {_FAKE_SHA} refs/heads/master {_ZERO_SHA}\n"
        self._assert_blocked(line)

    def test_blocks_force_push_to_main(self) -> None:
        """Force-pushes use a real (non-zero) remote SHA — still blocked."""
        line = f"refs/heads/feature {_FAKE_SHA} refs/heads/main {_FAKE_SHA}\n"
        self._assert_blocked(line)


    def test_blocks_delete_push_to_main(self) -> None:
        """Deleting main (local SHA = all zeros) is blocked like any other push."""
        line = f"(delete) {_ZERO_SHA} refs/heads/main {_FAKE_SHA}\n"
        self._assert_blocked(line)


class TestPrePushHookAllowsOther(unittest.TestCase):
    """pre-push must exit 0 for pushes that do not target main or master."""

    def _assert_allowed(self, push_lines: str) -> None:
        result = _run_pre_push(push_lines)
        self.assertEqual(
            result.returncode,
            0,
            msg=f"Expected push to be allowed:\n{push_lines!r}\n{result.stderr}",
        )

    def test_allows_feature_branch(self) -> None:
        line = f"refs/heads/feature/my-feat {_FAKE_SHA} refs/heads/feature/my-feat {_ZERO_SHA}\n"
        self._assert_allowed(line)

    def test_allows_worktree_branch(self) -> None:
        line = f"refs/heads/worktree-agent-abc {_FAKE_SHA} refs/heads/worktree-agent-abc {_ZERO_SHA}\n"
        self._assert_allowed(line)

    def test_allows_delete_push_to_feature_branch(self) -> None:
        """Deleting a non-protected branch is allowed."""
        line = f"(delete) {_ZERO_SHA} refs/heads/feat/old {_FAKE_SHA}\n"
        self._assert_allowed(line)

    def test_empty_stdin(self) -> None:
        """Empty stdin (no push lines) must exit 0."""
        self._assert_allowed("")


class TestHooksAreExecutable(unittest.TestCase):
    """Both hook files must exist and be executable."""

    def test_commit_msg_is_executable(self) -> None:
        path = HOOKS_DIR / "commit-msg"
        self.assertTrue(path.is_file(), msg=f"missing: {path}")
        self.assertTrue(os.access(path, os.X_OK), msg=f"not executable: {path}")

    def test_pre_push_is_executable(self) -> None:
        path = HOOKS_DIR / "pre-push"
        self.assertTrue(path.is_file(), msg=f"missing: {path}")
        self.assertTrue(os.access(path, os.X_OK), msg=f"not executable: {path}")

    def test_hooks_do_not_invoke_python(self) -> None:
        """Hook scripts are pure bash — no Python interpreter calls."""
        for name in ("commit-msg", "pre-push"):
            path = HOOKS_DIR / name
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(
                "python",
                text,
                msg=f"{name} invokes Python; hooks should be pure bash",
            )


if __name__ == "__main__":
    unittest.main()
