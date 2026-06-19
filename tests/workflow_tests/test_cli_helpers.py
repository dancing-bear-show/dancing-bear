"""Tests for workflow.cli_helpers — friendly path-not-found messages."""

from __future__ import annotations

from pathlib import Path

import pytest

from workflow.cli_helpers import (
    format_workflow_not_found,
    is_stale_worktree_path,
    list_available_workflows,
)


# ---------------------------------------------------------------------------
# is_stale_worktree_path
# ---------------------------------------------------------------------------


class TestIsStaleWorktreePath:
    def test_returns_true_for_missing_worktree_path(self) -> None:
        path = "/tmp/no-such-dir/.claude/worktrees/deleted/workflows/foo.yaml"
        assert is_stale_worktree_path(path) is True

    def test_returns_false_for_path_without_marker(self) -> None:
        assert is_stale_worktree_path("/tmp/does-not-exist.yaml") is False

    def test_returns_false_for_existing_worktree_path(self, tmp_path: Path) -> None:
        worktree_dir = tmp_path / ".claude" / "worktrees" / "live" / "workflows"
        worktree_dir.mkdir(parents=True)
        existing = worktree_dir / "foo.yaml"
        assert is_stale_worktree_path(str(existing)) is False


# ---------------------------------------------------------------------------
# list_available_workflows
# ---------------------------------------------------------------------------


class TestListAvailableWorkflows:
    def test_returns_yaml_files_in_subdirectory(self, tmp_path: Path) -> None:
        workflows_dir = tmp_path / "workflows"
        (workflows_dir / "code").mkdir(parents=True)
        (workflows_dir / "code" / "a.yaml").write_text("name: a\n")
        (workflows_dir / "code" / "b.yaml").write_text("name: b\n")

        result = list_available_workflows(repo_root=tmp_path)

        assert result == ["workflows/code/a.yaml", "workflows/code/b.yaml"]

    def test_returns_empty_when_no_workflows_dir(self, tmp_path: Path) -> None:
        result = list_available_workflows(repo_root=tmp_path)
        assert result == []

    def test_excludes_non_yaml_files(self, tmp_path: Path) -> None:
        workflows_dir = tmp_path / "workflows"
        (workflows_dir / "code").mkdir(parents=True)
        (workflows_dir / "code" / "real.yaml").write_text("name: real\n")
        (workflows_dir / "code" / "readme.txt").write_text("ignored")

        result = list_available_workflows(repo_root=tmp_path)
        assert result == ["workflows/code/real.yaml"]

    def test_excludes_shared_and_hints_subdirs(self, tmp_path: Path) -> None:
        workflows_dir = tmp_path / "workflows"
        (workflows_dir / "code").mkdir(parents=True)
        (workflows_dir / "shared").mkdir(parents=True)
        (workflows_dir / "hints").mkdir(parents=True)
        (workflows_dir / "code" / "runnable.yaml").write_text("name: runnable\n")
        (workflows_dir / "shared" / "fragment.yaml").write_text("name: frag\n")
        (workflows_dir / "hints" / "hints.yaml").write_text("name: hints\n")

        result = list_available_workflows(repo_root=tmp_path)

        assert result == ["workflows/code/runnable.yaml"]
        assert "workflows/shared/fragment.yaml" not in result
        assert "workflows/hints/hints.yaml" not in result


# ---------------------------------------------------------------------------
# format_workflow_not_found
# ---------------------------------------------------------------------------


class TestFormatWorkflowNotFound:
    def test_stale_worktree_path_mentions_deleted_worktree(self, tmp_path: Path) -> None:
        (tmp_path / "workflows" / "code").mkdir(parents=True)
        (tmp_path / "workflows" / "code" / "real.yaml").write_text("name: x\n")

        message = format_workflow_not_found(
            "/old/.claude/worktrees/dead/workflows/foo.yaml",
            repo_root=tmp_path,
        )

        assert "deleted worktree" in message
        assert ".claude/worktrees/" in message
        assert "Available workflows:" in message
        assert "workflows/code/real.yaml" in message

    def test_plain_missing_path_lists_available_workflows(self, tmp_path: Path) -> None:
        (tmp_path / "workflows" / "code").mkdir(parents=True)
        (tmp_path / "workflows" / "code" / "real.yaml").write_text("name: x\n")

        message = format_workflow_not_found(
            "/tmp/does-not-exist.yaml",
            repo_root=tmp_path,
        )

        assert "deleted worktree" not in message
        assert "file not found" in message
        assert "Available workflows:" in message
        assert "workflows/code/real.yaml" in message

    def test_no_workflows_dir_falls_back_to_helpful_text(self, tmp_path: Path) -> None:
        message = format_workflow_not_found("/tmp/does-not-exist.yaml", repo_root=tmp_path)
        assert "No workflows/ directory" in message

    def test_label_override_changes_leading_line(self, tmp_path: Path) -> None:
        message = format_workflow_not_found(
            "/tmp/missing-workspace",
            label="workspace",
            repo_root=tmp_path,
        )
        assert "workspace" in message.splitlines()[0]


# ---------------------------------------------------------------------------
# End-to-end: workflow CLI subcommands with friendly errors
# ---------------------------------------------------------------------------


class TestWorkflowStatusFriendlyErrors:
    """workflow main() surfaces the friendly message on stderr."""

    def test_status_stale_worktree_path_mentions_deleted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        (tmp_path / "workflows" / "code").mkdir(parents=True)
        (tmp_path / "workflows" / "code" / "real.yaml").write_text("name: x\n")
        monkeypatch.chdir(tmp_path)

        from workflow.cli import main
        import sys

        monkeypatch.setattr(sys, "argv", ["workflow", "status", "/old/.claude/worktrees/dead/workspace"])
        try:
            main()
        except SystemExit:
            pass

        captured = capsys.readouterr()
        assert "deleted worktree" in captured.err or "deleted worktree" in captured.out

    def test_status_plain_missing_path_lists_available(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        (tmp_path / "workflows" / "code").mkdir(parents=True)
        (tmp_path / "workflows" / "code" / "real.yaml").write_text("name: x\n")
        monkeypatch.chdir(tmp_path)

        from workflow.cli import main
        import sys

        monkeypatch.setattr(sys, "argv", ["workflow", "status", "/tmp/does-not-exist-status"])
        try:
            main()
        except SystemExit:
            pass

        captured = capsys.readouterr()
        combined = captured.err + captured.out
        assert "Available workflows:" in combined
        assert "deleted worktree" not in combined
