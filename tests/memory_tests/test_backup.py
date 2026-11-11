"""Covers backup_stores and backup_status — explicit-path git staging and read-only status check."""

from __future__ import annotations

import os
import shutil
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from memory.backup import (
    BackupResult,
    BackupStatus,
    backup_status,
    backup_stores,
)
from memory.models import MemoryStore
from tests.memory_tests.fixtures import MemoryTestCase

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FEEDBACK_YAML = (
    "---\nmetadata:\n  type: feedback\n  node_type: memory\n---\n\n"
    "**Why:** Test.\n\n**How to apply:** Test.\n"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_proc(**kwargs) -> MagicMock:
    """Return a MagicMock subprocess result with returncode=0 and empty stdout/stderr."""
    return MagicMock(returncode=0, stdout="", stderr="", **kwargs)


def _make_store_with_file(
    tmp_path: Path, slug: str, filename: str, content: str
) -> MemoryStore:
    """Create a MemoryStore with one real file on disk."""
    from memory.parser import parse_memory_file

    mem_dir = tmp_path / slug / "memory"
    mem_dir.mkdir(parents=True)
    f = mem_dir / filename
    f.write_text(content, encoding="utf-8")
    memory = parse_memory_file(f, project_slug=slug)

    return MemoryStore(
        project_slug=slug,
        root=str(tmp_path / slug),
        memories=(memory,),
        non_memory_files=(),
        index_path=None,
        index_entries=(),
        inferred_repo=None,
        is_worktree_slug=False,
    )


def _empty_store(slug: str) -> MemoryStore:
    return MemoryStore(
        project_slug=slug,
        root="/nonexistent",
        memories=(),
        non_memory_files=(),
        index_path=None,
        index_entries=(),
        inferred_repo=None,
        is_worktree_slug=False,
    )


# ---------------------------------------------------------------------------
# backup_stores — subprocess mocked to avoid real git calls
# ---------------------------------------------------------------------------


class TestBackupStores(MemoryTestCase):
    def test_explicit_path_staging_never_add_all(self) -> None:
        """Every git add invocation must name an explicit path — never -A or ."""
        store = _make_store_with_file(
            self.tmp,
            "-Users-alice-code-repo",
            "feedback_thing.md",
            _FEEDBACK_YAML,
        )
        dest = self.tmp / "backup"

        with patch("memory.backup.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="[master abc1234] backup\n",
                stderr="",
            )

            result = backup_stores((store,), dest)

        self.assertIsInstance(result, BackupResult)

        git_add_calls = [c for c in mock_run.call_args_list if c.args[0][1] == "add"]
        for call_obj in git_add_calls:
            cmd = call_obj.args[0]
            self.assertIsInstance(cmd, list, "git add must use list args")
            self.assertIsNot(call_obj.kwargs.get("shell"), True)
            self.assertNotIn("-A", cmd, "git add -A is forbidden")
            # Verify "--" then an explicit path after 'add'
            add_idx = cmd.index("add")
            self.assertGreater(len(cmd), add_idx + 2, "git add must have an explicit path")
            self.assertEqual(cmd[add_idx + 1], "--", "git add must end option parsing")
            explicit_path = cmd[add_idx + 2]
            self.assertNotIn(
                explicit_path, ("-A", "."),
                f"git add path must be explicit, got {explicit_path!r}",
            )

    @unittest.skipIf(shutil.which("git") is None, "git not installed")
    def test_dash_leading_slug_stages_with_real_git(self) -> None:
        """Real slugs start with '-'; git must stage them as paths, not options."""
        empty_config = self.tmp / "gitconfig"
        empty_config.write_text("", encoding="utf-8")

        # Isolate git environment for this test
        env_to_set = {
            "GIT_CONFIG_GLOBAL": str(empty_config),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
        env_to_remove = [
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_COMMON_DIR",
            "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_NAMESPACE",
            "GIT_PREFIX",
        ]
        saved = {k: os.environ.get(k) for k in list(env_to_set) + env_to_remove}
        for k, v in env_to_set.items():
            os.environ[k] = v
        for k in env_to_remove:
            os.environ.pop(k, None)

        def restore_env():
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
                else:
                    os.environ.pop(k, None)

        self.addCleanup(restore_env)

        projects_tmp = self.tmp / "projects"
        store = _make_store_with_file(
            projects_tmp,
            "-Users-alice-code-real",
            "feedback_real.md",
            _FEEDBACK_YAML,
        )
        dest = self.tmp / "real_backup"

        result = backup_stores((store,), dest, message="backup")

        self.assertFalse(result.failed, result.message)
        self.assertIsNotNone(result.commit_sha)
        self.assertEqual(
            result.files_staged,
            (str(dest / "-Users-alice-code-real__feedback_real.md"),),
        )

    def test_no_git_push_called(self) -> None:
        store = _make_store_with_file(
            self.tmp,
            "-Users-alice-code-repo2",
            "ref.md",
            "---\ntype: reference\n---\n\nContent.\n",
        )
        dest = self.tmp / "bkp2"

        with patch("memory.backup.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="[master abc] msg\n", stderr=""
            )
            backup_stores((store,), dest)

        git_push_calls = [c for c in mock_run.call_args_list if c.args[0][1] == "push"]
        self.assertEqual(len(git_push_calls), 0, "git push must never be called")

    def test_no_git_remote_called(self) -> None:
        store = _make_store_with_file(
            self.tmp,
            "-Users-alice-code-repo3",
            "ref.md",
            "---\ntype: reference\n---\n\nContent.\n",
        )
        dest = self.tmp / "bkp3"

        with patch("memory.backup.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="[master abc] msg\n", stderr=""
            )
            backup_stores((store,), dest)

        git_remote_calls = [
            c for c in mock_run.call_args_list if c.args[0][1] == "remote"
        ]
        self.assertEqual(len(git_remote_calls), 0, "git remote must never be called")

    def test_returns_backup_result(self) -> None:
        store = _make_store_with_file(
            self.tmp,
            "-Users-alice-code-repo4",
            "feedback.md",
            "---\ntype: feedback\n---\n\nBody.\n",
        )
        dest = self.tmp / "backup4"

        with patch("memory.backup.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="[master abc1234] msg\n", stderr=""
            )
            result = backup_stores((store,), dest)

        self.assertIsInstance(result, BackupResult)
        self.assertEqual(result.dest, str(dest))
        self.assertIsInstance(result.files_staged, tuple)
        self.assertIsInstance(result.created_repo, bool)

    def test_empty_stores_tuple(self) -> None:
        dest = self.tmp / "empty_backup"

        with patch("memory.backup.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="nothing to commit\n", stderr=""
            )
            result = backup_stores((), dest)

        self.assertIsInstance(result, BackupResult)
        self.assertEqual(result.files_staged, ())

    def test_default_message_is_iso_timestamp(self) -> None:
        store = _empty_store("slug1")
        dest = self.tmp / "ts_backup"

        with patch("memory.backup.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="[master abc] msg\n", stderr=""
            )
            result = backup_stores((store,), dest)

        # message should be parseable as ISO datetime
        self.assertIsNotNone(result.message)
        datetime.fromisoformat(result.message)  # type: ignore[arg-type]

    def test_custom_message_preserved(self) -> None:
        store = _empty_store("slug2")
        dest = self.tmp / "msg_backup"

        with patch("memory.backup.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="[master abc] my msg\n", stderr=""
            )
            result = backup_stores((store,), dest, message="my custom message")

        self.assertEqual(result.message, "my custom message")


# ---------------------------------------------------------------------------
# backup_status — read-only, no subprocess calls when repo absent
# ---------------------------------------------------------------------------


class TestBackupStatus(MemoryTestCase):
    def test_nonexistent_dest_returns_not_initialized(self) -> None:
        result = backup_status(self.tmp / "nonexistent_backup")
        self.assertIsInstance(result, BackupStatus)
        self.assertFalse(result.initialized)
        self.assertIsNone(result.last_commit)

    def test_status_is_read_only_on_nonexistent_path(self) -> None:
        """backup_status on a path with no .git must not call subprocess.run."""
        with patch("memory.backup.subprocess.run") as mock_run:
            result = backup_status(self.tmp / "no_git")

        self.assertFalse(mock_run.called, "backup_status must not call subprocess.run when .git absent")
        self.assertIsInstance(result, BackupStatus)

    def test_status_contains_expected_keys(self) -> None:
        result = backup_status(self.tmp / "missing")
        self.assertTrue(hasattr(result, "initialized"))
        self.assertTrue(hasattr(result, "last_commit"))
        self.assertTrue(hasattr(result, "dirty"))
        self.assertTrue(hasattr(result, "message"))

    def test_initialized_repo_calls_subprocess(self) -> None:
        """When .git exists, backup_status reads status and log via subprocess."""
        fake_git_dir = self.tmp / "fake_backup"
        fake_git_dir.mkdir()
        (fake_git_dir / ".git").mkdir()

        with patch("memory.backup.subprocess.run") as mock_run:
            mock_run.return_value = _ok_proc()
            result = backup_status(fake_git_dir)

        self.assertTrue(result.initialized)
        self.assertTrue(mock_run.called)


# ---------------------------------------------------------------------------
# BackupResult dataclass completeness
# ---------------------------------------------------------------------------


class TestBackupResult(MemoryTestCase):
    def test_required_fields_present(self) -> None:
        r = BackupResult(
            dest="/some/path",
            files_staged=("file1.md", "file2.md"),
            commit_sha="abc1234",
            message="test commit",
            created_repo=True,
        )
        self.assertEqual(r.dest, "/some/path")
        self.assertEqual(r.files_staged, ("file1.md", "file2.md"))
        self.assertEqual(r.commit_sha, "abc1234")
        self.assertEqual(r.message, "test commit")
        self.assertTrue(r.created_repo)

    def test_commit_sha_can_be_none(self) -> None:
        """commit_sha is None when there was nothing to commit."""
        r = BackupResult(
            dest="/some/path",
            files_staged=(),
            commit_sha=None,
            message="nothing to commit",
            created_repo=False,
        )
        self.assertIsNone(r.commit_sha)

    def test_failed_flag_defaults_false(self) -> None:
        r = BackupResult(
            dest="/some/path",
            files_staged=(),
            commit_sha=None,
            message="ok",
            created_repo=False,
        )
        self.assertFalse(r.failed)

    def test_failed_flag_can_be_true(self) -> None:
        r = BackupResult(
            dest="/some/path",
            files_staged=(),
            commit_sha=None,
            message="git init failed: permission denied",
            created_repo=False,
            failed=True,
        )
        self.assertTrue(r.failed)


# ---------------------------------------------------------------------------
# git subprocess failure paths
# ---------------------------------------------------------------------------


class TestGitSubprocessFailures(MemoryTestCase):
    """Cover every non-zero-exit path that must surface as failed=True."""

    def test_git_init_failure_returns_failed_result(self) -> None:
        """_init_repo_if_absent: git init non-zero → BackupResult(failed=True)."""
        dest = self.tmp / "init_fail_backup"
        # dest does not have .git, so init will be attempted
        store = _empty_store("slug-init-fail")

        with patch("memory.backup.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="fatal: cannot create directory",
            )
            result = backup_stores((store,), dest)

        self.assertIsInstance(result, BackupResult)
        self.assertTrue(result.failed)
        self.assertIn("git init failed", result.message)  # type: ignore[operator]
        self.assertIsNone(result.commit_sha)

    def test_git_add_failure_returns_failed_result(self) -> None:
        """_stage_files: git add non-zero → BackupResult(failed=True)."""
        store = _make_store_with_file(
            self.tmp,
            "-Users-alice-code-add-fail",
            "feedback_add.md",
            _FEEDBACK_YAML,
        )
        dest = self.tmp / "add_fail_backup"
        # Pre-create .git so init is skipped
        dest.mkdir()
        (dest / ".git").mkdir()

        with patch("memory.backup.subprocess.run") as mock_run:
            # git add fails
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="fatal: pathspec does not match any files",
            )
            result = backup_stores((store,), dest)

        self.assertIsInstance(result, BackupResult)
        self.assertTrue(result.failed)
        self.assertIn("git add failed", result.message)  # type: ignore[operator]
        self.assertIsNone(result.commit_sha)

    def test_git_commit_failure_real_error_returns_failed_result(self) -> None:
        """_commit_and_resolve_sha: commit non-zero AND not 'nothing to commit' → failed=True."""
        store = _empty_store("slug-commit-fail")
        dest = self.tmp / "commit_fail_backup"
        dest.mkdir()
        (dest / ".git").mkdir()

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if args[0][1] == "commit":
                return MagicMock(
                    returncode=1,
                    stdout="error: pre-commit hook rejected",
                    stderr="pre-commit hook exited with code 1",
                )
            # git add succeeds (no files to add since store is empty)
            return _ok_proc()

        with patch("memory.backup.subprocess.run", side_effect=side_effect):
            result = backup_stores((store,), dest)

        self.assertIsInstance(result, BackupResult)
        self.assertTrue(result.failed)
        self.assertIn("git commit failed", result.message)  # type: ignore[operator]
        self.assertIsNone(result.commit_sha)

    def test_git_commit_nothing_to_commit_is_not_failure(self) -> None:
        """_commit_and_resolve_sha: non-zero with 'nothing to commit' in stdout → not failed, commit_sha=None."""
        store = _empty_store("slug-noop")
        dest = self.tmp / "noop_backup"
        dest.mkdir()
        (dest / ".git").mkdir()

        with patch("memory.backup.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="nothing to commit, working tree clean",
                stderr="",
            )
            result = backup_stores((store,), dest)

        self.assertIsInstance(result, BackupResult)
        self.assertFalse(result.failed)
        self.assertIsNone(result.commit_sha)

    def test_sha_resolution_failure_leaves_commit_sha_none(self) -> None:
        """When commit succeeds (rc=0) but rev-parse HEAD fails, commit_sha is None but failed stays False."""
        store = _empty_store("slug-sha-fail")
        dest = self.tmp / "sha_fail_backup"
        dest.mkdir()
        (dest / ".git").mkdir()

        def side_effect(*args, **kwargs):
            subcmd = args[0][1]
            if subcmd == "commit":
                return MagicMock(returncode=0, stdout="[master abc1234]", stderr="")
            if subcmd == "rev-parse":
                return MagicMock(
                    returncode=1, stdout="", stderr="fatal: not a git repo"
                )
            return _ok_proc()

        with patch("memory.backup.subprocess.run", side_effect=side_effect):
            result = backup_stores((store,), dest)

        self.assertIsInstance(result, BackupResult)
        # SHA resolution failed — commit_sha is None but the backup is not failed
        self.assertIsNone(result.commit_sha)
        self.assertFalse(result.failed)


class TestBackupStatusGitLogFailure(MemoryTestCase):
    """Cover the branch where git log -1 returns non-zero → last_commit = None."""

    def test_git_log_failure_sets_last_commit_none(self) -> None:
        """backup_status: git log -1 non-zero → last_commit is None, initialized is True."""
        fake_git_dir = self.tmp / "log_fail_backup"
        fake_git_dir.mkdir()
        (fake_git_dir / ".git").mkdir()

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            subcmd = args[0][1] if len(args[0]) > 1 else ""
            # First call is git status --porcelain
            if subcmd == "status":
                return _ok_proc()
            # Second call is git log -1
            if subcmd == "log":
                return MagicMock(
                    returncode=1, stdout="", stderr="fatal: bad default revision"
                )
            return _ok_proc()

        with patch("memory.backup.subprocess.run", side_effect=side_effect):
            result = backup_status(fake_git_dir)

        self.assertIsInstance(result, BackupStatus)
        self.assertTrue(result.initialized)
        self.assertIsNone(result.last_commit)


if __name__ == "__main__":
    unittest.main()
