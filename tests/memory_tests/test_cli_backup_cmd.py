"""Coverage for memory.commands.backup (via memory.cli.main): --status read-only path,
missing-target validation error, --store/--all-stores dispatch, load_store failure
handling, and backup_stores failure handling.

Patches backup_status/backup_stores/discover_stores/load_store where they are
USED (memory.commands.backup.*), not where they are defined.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import patch

import memory.cli as memory_cli
from memory.backup import BackupResult, BackupStatus
from memory.commands.backup import default_backup_dest
from memory.discovery import load_store
from tests.memory_tests.fixtures import MemoryTestCase, SLUG_MAIN, make_projects_root


def _run_backup(*argv: str) -> tuple[int, str, str]:
    """Call memory.cli.main(["backup", *argv]) and return (rc, stdout, stderr)."""
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = memory_cli.main(["backup", *argv])
    return rc, out_buf.getvalue(), err_buf.getvalue()


class TestBackupStatus(MemoryTestCase):
    """--status is strictly read-only and must never call backup_stores."""

    def test_status_reports_uninitialized_repo(self) -> None:
        dest = self.tmp / "backup-repo"

        with patch("memory.commands.backup.backup_stores") as mock_backup_stores:
            rc, out, _ = _run_backup("--status", "--dest", str(dest), "--format", "json")
            mock_backup_stores.assert_not_called()

        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertFalse(payload["initialized"])

    def test_status_uses_default_dest_when_not_given(self) -> None:
        with patch("memory.commands.backup.backup_status") as mock_status:
            mock_status.return_value = BackupStatus(
                initialized=False,
                last_commit=None,
                dirty=False,
                message="not initialized",
            )
            rc, out, _ = _run_backup("--status", "--format", "json")

        self.assertEqual(rc, 0)
        mock_status.assert_called_once_with(default_backup_dest())
        payload = json.loads(out)
        self.assertFalse(payload["initialized"])

    def test_status_table_format(self) -> None:
        dest = self.tmp / "backup-repo"

        rc, out, _ = _run_backup("--status", "--dest", str(dest), "--format", "table")

        self.assertEqual(rc, 0)
        self.assertTrue(out, "table format must render something to stdout")


class TestTargetValidation(MemoryTestCase):
    """Real backup operations require --store or --all-stores."""

    def test_missing_target_returns_validation_error(self) -> None:
        dest = self.tmp / "backup-repo"

        rc, _, _ = _run_backup("--dest", str(dest))

        self.assertEqual(rc, 1)

    def test_store_and_all_stores_mutually_exclusive_returns_1(self) -> None:
        # In the new API, exclusive_store_scope returns 1 (validation error),
        # not SystemExit(2) from argparse.
        dest = self.tmp / "backup-repo"

        rc, _, err = _run_backup(
            "--store=some-slug", "--all-stores", "--dest", str(dest)
        )

        self.assertNotEqual(rc, 0)
        self.assertIn("validation error", err.lower())


class TestStoreDispatch(MemoryTestCase):
    """--store loads a single store by slug; --all-stores discovers every store."""

    def test_store_load_failure_returns_validation_error(self) -> None:
        dest = self.tmp / "backup-repo"

        with patch(
            "memory.commands.backup.load_store",
            side_effect=RuntimeError("no such slug"),
        ):
            rc, _, _ = _run_backup("--store=bad-slug", "--dest", str(dest))

        self.assertEqual(rc, 1)

    def test_store_success_calls_backup_stores_with_single_store_tuple(self) -> None:
        projects_root = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_root)
        dest = self.tmp / "backup-repo"
        fake_result = BackupResult(
            dest=str(dest),
            files_staged=(str(dest / "feedback_worktree.md"),),
            commit_sha="abc1234",
            message="test commit",
            created_repo=True,
        )

        with (
            patch("memory.commands.backup.load_store", return_value=store),
            patch(
                "memory.commands.backup.backup_stores", return_value=fake_result
            ) as mock_backup_stores,
        ):
            rc, out, _ = _run_backup(
                f"--store={store.project_slug}",
                "--dest",
                str(dest),
                "--format",
                "json",
            )
            mock_backup_stores.assert_called_once()
            called_stores = mock_backup_stores.call_args[0][0]
            self.assertEqual(called_stores, (store,))

        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["commit_sha"], "abc1234")
        self.assertEqual(payload["files_staged"], 1)
        self.assertTrue(payload["created_repo"])

    def test_all_stores_dispatches_discover_stores(self) -> None:
        projects_root = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_root)
        dest = self.tmp / "backup-repo"
        fake_result = BackupResult(
            dest=str(dest),
            files_staged=(),
            commit_sha=None,
            message="nothing to do",
            created_repo=False,
        )

        with (
            patch("memory.commands.backup.discover_stores", return_value=(store,)),
            patch(
                "memory.commands.backup.backup_stores", return_value=fake_result
            ) as mock_backup_stores,
        ):
            rc, _, _ = _run_backup("--all-stores", "--dest", str(dest))
            mock_backup_stores.assert_called_once()
            called_stores = mock_backup_stores.call_args[0][0]
            self.assertEqual(called_stores, (store,))

        self.assertEqual(rc, 0)

    def test_all_stores_empty_prints_message_and_returns_0(self) -> None:
        dest = self.tmp / "backup-repo"

        with patch("memory.commands.backup.discover_stores", return_value=()):
            rc, _, err = _run_backup("--all-stores", "--dest", str(dest))

        self.assertEqual(rc, 0)
        self.assertIn("No stores to back up", err)

    def test_backup_stores_raises_prints_error_and_returns_1(self) -> None:
        projects_root = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_root)
        dest = self.tmp / "backup-repo"

        with (
            patch("memory.commands.backup.load_store", return_value=store),
            patch(
                "memory.commands.backup.backup_stores",
                side_effect=RuntimeError("git exploded"),
            ),
        ):
            rc, _, err = _run_backup(f"--store={store.project_slug}", "--dest", str(dest))

        self.assertEqual(rc, 1)
        self.assertIn("backup failed", err)

    def test_custom_message_forwarded_to_backup_stores(self) -> None:
        projects_root = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_root)
        dest = self.tmp / "backup-repo"
        fake_result = BackupResult(
            dest=str(dest),
            files_staged=(),
            commit_sha=None,
            message="custom msg",
            created_repo=False,
        )

        with (
            patch("memory.commands.backup.load_store", return_value=store),
            patch(
                "memory.commands.backup.backup_stores", return_value=fake_result
            ) as mock_backup_stores,
        ):
            rc, _, _ = _run_backup(
                f"--store={store.project_slug}",
                "--dest",
                str(dest),
                "--message",
                "custom msg",
            )
            mock_backup_stores.assert_called_once_with(
                (store,), dest, message="custom msg"
            )

        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
