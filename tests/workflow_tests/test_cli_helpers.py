"""Tests for workflow.cli_helpers — friendly path-not-found messages."""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow.cli_helpers import (
    format_workflow_not_found,
    is_stale_worktree_path,
    list_available_workflows,
)


# ---------------------------------------------------------------------------
# is_stale_worktree_path
# ---------------------------------------------------------------------------


class TestIsStaleWorktreePath(unittest.TestCase):
    def test_returns_true_for_missing_worktree_path(self) -> None:
        path = "/tmp/no-such-dir/.claude/worktrees/deleted/workflows/foo.yaml"  # nosec B108 - test string only
        self.assertIs(is_stale_worktree_path(path), True)

    def test_returns_false_for_path_without_marker(self) -> None:
        self.assertIs(is_stale_worktree_path("/tmp/does-not-exist.yaml"), False)  # nosec B108 - test string only

    def test_returns_false_for_existing_worktree_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            worktree_dir = tmp_path / ".claude" / "worktrees" / "live" / "workflows"
            worktree_dir.mkdir(parents=True)
            existing = worktree_dir / "foo.yaml"
            self.assertIs(is_stale_worktree_path(str(existing)), False)


# ---------------------------------------------------------------------------
# list_available_workflows
# ---------------------------------------------------------------------------


class TestListAvailableWorkflows(unittest.TestCase):
    def test_returns_yaml_files_in_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            workflows_dir = tmp_path / "workflows"
            (workflows_dir / "code").mkdir(parents=True)
            (workflows_dir / "code" / "a.yaml").write_text("name: a\n")
            (workflows_dir / "code" / "b.yaml").write_text("name: b\n")

            result = list_available_workflows(repo_root=tmp_path)

            self.assertEqual(result, ["workflows/code/a.yaml", "workflows/code/b.yaml"])

    def test_returns_empty_when_no_workflows_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = list_available_workflows(repo_root=Path(tmp_dir))
            self.assertEqual(result, [])

    def test_excludes_non_yaml_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            workflows_dir = tmp_path / "workflows"
            (workflows_dir / "code").mkdir(parents=True)
            (workflows_dir / "code" / "real.yaml").write_text("name: real\n")
            (workflows_dir / "code" / "readme.txt").write_text("ignored")

            result = list_available_workflows(repo_root=tmp_path)
            self.assertEqual(result, ["workflows/code/real.yaml"])

    def test_excludes_shared_and_hints_subdirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            workflows_dir = tmp_path / "workflows"
            (workflows_dir / "code").mkdir(parents=True)
            (workflows_dir / "shared").mkdir(parents=True)
            (workflows_dir / "hints").mkdir(parents=True)
            (workflows_dir / "code" / "runnable.yaml").write_text("name: runnable\n")
            (workflows_dir / "shared" / "fragment.yaml").write_text("name: frag\n")
            (workflows_dir / "hints" / "hints.yaml").write_text("name: hints\n")

            result = list_available_workflows(repo_root=tmp_path)

            self.assertEqual(result, ["workflows/code/runnable.yaml"])
            self.assertNotIn("workflows/shared/fragment.yaml", result)
            self.assertNotIn("workflows/hints/hints.yaml", result)


# ---------------------------------------------------------------------------
# format_workflow_not_found
# ---------------------------------------------------------------------------


class TestFormatWorkflowNotFound(unittest.TestCase):
    def test_stale_worktree_path_mentions_deleted_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "workflows" / "code").mkdir(parents=True)
            (tmp_path / "workflows" / "code" / "real.yaml").write_text("name: x\n")

            message = format_workflow_not_found(
                "/old/.claude/worktrees/dead/workflows/foo.yaml",
                repo_root=tmp_path,
            )

            self.assertIn("deleted worktree", message)
            self.assertIn(".claude/worktrees/", message)
            self.assertIn("Available workflows:", message)
            self.assertIn("workflows/code/real.yaml", message)

    def test_plain_missing_path_lists_available_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "workflows" / "code").mkdir(parents=True)
            (tmp_path / "workflows" / "code" / "real.yaml").write_text("name: x\n")

            message = format_workflow_not_found(
                "/tmp/does-not-exist.yaml",  # nosec B108 - test string only
                repo_root=tmp_path,
            )

            self.assertNotIn("deleted worktree", message)
            self.assertIn("file not found", message)
            self.assertIn("Available workflows:", message)
            self.assertIn("workflows/code/real.yaml", message)

    def test_no_workflows_dir_falls_back_to_helpful_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            message = format_workflow_not_found("/tmp/does-not-exist.yaml", repo_root=Path(tmp_dir))  # nosec B108 - test string only
            self.assertIn("No workflows/ directory", message)

    def test_label_override_changes_leading_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            message = format_workflow_not_found(
                "/tmp/missing-workspace",  # nosec B108 - test string only, not actual file creation
                label="workspace",
                repo_root=Path(tmp_dir),
            )
            self.assertIn("workspace", message.splitlines()[0])


# ---------------------------------------------------------------------------
# End-to-end: workflow CLI subcommands with friendly errors
# ---------------------------------------------------------------------------


class TestWorkflowStatusFriendlyErrors(unittest.TestCase):
    """workflow main() surfaces the friendly message on stderr."""

    def test_status_stale_worktree_path_mentions_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "workflows" / "code").mkdir(parents=True)
            (tmp_path / "workflows" / "code" / "real.yaml").write_text("name: x\n")

            from workflow.cli import main

            stderr_buf = io.StringIO()
            stdout_buf = io.StringIO()
            with patch.object(sys, "argv", ["workflow", "status", "/old/.claude/worktrees/dead/workspace"]), \
                 patch("os.getcwd", return_value=str(tmp_path)), \
                 patch("sys.stderr", stderr_buf), \
                 patch("sys.stdout", stdout_buf), \
                 contextlib.suppress(SystemExit):
                main()

            combined = stderr_buf.getvalue() + stdout_buf.getvalue()
            self.assertIn("deleted worktree", combined)

    def test_status_plain_missing_path_lists_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "workflows" / "code").mkdir(parents=True)
            (tmp_path / "workflows" / "code" / "real.yaml").write_text("name: x\n")

            from workflow.cli import main

            stderr_buf = io.StringIO()
            stdout_buf = io.StringIO()
            missing_path = "/tmp/does-not-exist-status"  # nosec B108 - test string only, not actual temp file creation
            with patch.object(sys, "argv", ["workflow", "status", missing_path]), \
                 patch("os.getcwd", return_value=str(tmp_path)), \
                 patch("sys.stderr", stderr_buf), \
                 patch("sys.stdout", stdout_buf), \
                 contextlib.suppress(SystemExit):
                main()

            combined = stderr_buf.getvalue() + stdout_buf.getvalue()
            self.assertIn("Available workflows:", combined)
            self.assertNotIn("deleted worktree", combined)


class TestWorkflowMainSeparatorNormalization(unittest.TestCase):
    """workflow main() applies CLIApp's optional '--' separator normalization
    exactly once — regression coverage for the argv double-normalization bug
    (a second, legitimate '--' guarding a flag-like positional must survive)."""

    def test_no_subcommand_shows_usage_and_exits_usage_code(self) -> None:
        from core.cli_errors import ExitCode
        from workflow.cli import main

        stderr_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf):
            rc = main([])

        self.assertEqual(rc, ExitCode.USAGE)
        self.assertIn("Usage: workflow", stderr_buf.getvalue())

    def test_leading_separator_is_optional(self) -> None:
        """A post-subcommand '--' — the shape workflow.compiler._build_cli_command
        actually emits (subcommand, then '--', then flags) — and its absence
        must dispatch identically."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "workflows" / "code").mkdir(parents=True)
            (tmp_path / "workflows" / "code" / "real.yaml").write_text("name: x\n")

            from workflow.cli import main

            with patch("os.getcwd", return_value=str(tmp_path)):
                buf_with_sep = io.StringIO()
                with patch("sys.stdout", buf_with_sep), contextlib.suppress(SystemExit):
                    rc_with_sep = main(["list", "--", "--format", "json"])

                buf_without_sep = io.StringIO()
                with patch("sys.stdout", buf_without_sep), contextlib.suppress(SystemExit):
                    rc_without_sep = main(["list", "--format", "json"])

            self.assertEqual(rc_with_sep, rc_without_sep)
            self.assertEqual(buf_with_sep.getvalue(), buf_without_sep.getvalue())

    def test_second_separator_protects_flag_like_positional(self) -> None:
        """'workflow status -- -- -weird-dir' has two '--' tokens: the first
        is the optional CLIApp separator (stripped, matching the shape
        _build_cli_command emits right after the subcommand), the second is
        a genuine POSIX end-of-options marker protecting '-weird-dir' as the
        literal workspace_dir positional. Double-normalizing (main()'s
        pre-check plus app.run()'s internal call) would strip both, causing
        argparse to misparse '-weird-dir' as an unrecognized flag instead."""
        from workflow.cli import main

        stderr_buf = io.StringIO()
        stdout_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf), patch("sys.stdout", stdout_buf), \
             contextlib.suppress(SystemExit):
            main(["status", "--", "--", "-weird-dir"])

        combined = stderr_buf.getvalue() + stdout_buf.getvalue()
        # Reaching workspace-not-found handling (rather than argparse's
        # "unrecognized arguments" error) proves "-weird-dir" was parsed as
        # the workspace_dir positional, not stripped/misparsed as a flag.
        self.assertNotIn("unrecognized arguments", combined)


class TestBuildCliCommandWorkflowRoundTrip(unittest.TestCase):
    """workflow.compiler._build_cli_command's emitted '--' must round-trip
    through workflow.cli.main — this is the actual producer/consumer pair
    the separator-optional migration exists for, and neither side was
    covered end to end before this test."""

    def test_build_cli_command_emits_separator_for_workflow_skill(self) -> None:
        """'workflow' was removed from _NO_SEPARATOR_CLIS, so the compiler
        must now insert '--' before flags for it, same as any other
        CLIApp-based skill."""
        from workflow.compiler import _build_cli_command

        cmd = _build_cli_command("workflow", {"subcommand": "lint", "flags": "--strict"})

        self.assertEqual(cmd, "./bin/workflow lint -- --strict")

    def test_build_cli_command_still_omits_separator_for_exempt_clis(self) -> None:
        """llm/docs remain in _NO_SEPARATOR_CLIS and must not get '--'."""
        from workflow.compiler import _build_cli_command

        self.assertEqual(
            _build_cli_command("llm", {"subcommand": "agentic", "flags": "--stdout"}),
            "./bin/llm agentic --stdout",
        )
        self.assertEqual(
            _build_cli_command("docs", {"subcommand": "render", "flags": "--stdout"}),
            "./bin/docs render --stdout",
        )

    def test_compiler_emitted_workflow_command_parses_via_main(self) -> None:
        """Feed _build_cli_command's actual output for the 'workflow' skill
        back into workflow.cli.main — the full producer/consumer round trip."""
        import shlex

        from workflow.compiler import _build_cli_command
        from workflow.cli import main

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "workflows" / "code").mkdir(parents=True)
            (tmp_path / "workflows" / "code" / "real.yaml").write_text("name: x\n")

            cmd = _build_cli_command("workflow", {"subcommand": "list", "flags": "--format json"})
            # cmd == "./bin/workflow list -- --format json"; main() receives
            # everything after the "./bin/workflow" program name.
            argv = shlex.split(cmd)[1:]

            with patch("os.getcwd", return_value=str(tmp_path)):
                stdout_buf = io.StringIO()
                with patch("sys.stdout", stdout_buf), contextlib.suppress(SystemExit):
                    rc = main(argv)

        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
