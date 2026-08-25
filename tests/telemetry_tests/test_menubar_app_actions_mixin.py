"""Tests for ActionsMixin in telemetry/_menubar_app_actions.py.

Tests focus on the pure-Python static methods and the filesystem-cleanup logic
(_clear_stale_project_dir).  GUI-bound methods (_on_configure, _on_clear,
_on_toggle_login_item) require rumps dialogs that block the event loop; those
are not tested here.  _notify and _copy_to_clipboard are covered for the no-op
paths that the non-macOS environment exercises.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from telemetry._menubar_app_actions import ActionsMixin


def _make_host() -> ActionsMixin:
    class _Host(ActionsMixin):
        pass

    host = _Host()
    host._btn_login_item = NS(state=0)
    return host


class TestClearStaleProjectDir_AllStale(unittest.TestCase):
    """All .jsonl files older than cutoff are deleted; empty dir is removed."""

    def test_deletes_all_stale_files_and_removes_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "proj"
            project_dir.mkdir()
            for i in range(3):
                (project_dir / f"session_{i}.jsonl").write_text(f"data{i}")

            cutoff = time.time() + 1  # all files are older than cutoff
            deleted = ActionsMixin._clear_stale_project_dir(project_dir, cutoff)

            self.assertEqual(deleted, 3)
            self.assertFalse(project_dir.exists())

    def test_returns_zero_when_no_jsonl_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "proj"
            project_dir.mkdir()
            # A non-jsonl file should not be touched
            (project_dir / "other.txt").write_text("keep me")

            cutoff = time.time() + 1
            deleted = ActionsMixin._clear_stale_project_dir(project_dir, cutoff)

            self.assertEqual(deleted, 0)
            self.assertTrue(project_dir.exists())


class TestClearStaleProjectDir_MixedAge(unittest.TestCase):
    """Only files older than cutoff are deleted; dir survives if non-empty."""

    def test_deletes_only_stale_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "proj"
            project_dir.mkdir()

            old_file = project_dir / "old.jsonl"
            old_file.write_text("old")
            os.utime(old_file, (0, 0))  # set to epoch — definitely stale

            fresh_file = project_dir / "fresh.jsonl"
            fresh_file.write_text("fresh")
            # fresh_file mtime is "now" — survives

            cutoff = time.time() - 1  # one second ago
            deleted = ActionsMixin._clear_stale_project_dir(project_dir, cutoff)

            self.assertEqual(deleted, 1)
            self.assertFalse(old_file.exists())
            self.assertTrue(fresh_file.exists())
            self.assertTrue(project_dir.exists())

    def test_dir_kept_when_fresh_files_remain(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "proj"
            project_dir.mkdir()

            stale = project_dir / "stale.jsonl"
            stale.write_text("stale")
            os.utime(stale, (0, 0))

            fresh = project_dir / "fresh.jsonl"
            fresh.write_text("fresh")

            cutoff = time.time() - 1
            ActionsMixin._clear_stale_project_dir(project_dir, cutoff)

            self.assertTrue(project_dir.exists(), "Dir should survive: fresh file remains")


class TestClearStaleProjectDir_EmptyAfterDelete(unittest.TestCase):
    """Dir is removed when all files are deleted."""

    def test_dir_removed_when_empty_after_cleanup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "proj"
            project_dir.mkdir()
            (project_dir / "a.jsonl").write_text("a")
            os.utime(project_dir / "a.jsonl", (0, 0))

            cutoff = time.time() - 1
            deleted = ActionsMixin._clear_stale_project_dir(project_dir, cutoff)

            self.assertEqual(deleted, 1)
            self.assertFalse(project_dir.exists())


class TestClearStaleProjectDir_SubdirsIgnored(unittest.TestCase):
    """Subdirectories inside project_dir are not touched."""

    def test_subdirs_not_deleted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "proj"
            project_dir.mkdir()
            subdir = project_dir / "subdir"
            subdir.mkdir()
            # Only a subdir, no jsonl files
            cutoff = time.time() + 1
            deleted = ActionsMixin._clear_stale_project_dir(project_dir, cutoff)

            self.assertEqual(deleted, 0)
            self.assertTrue(subdir.exists())


class TestNotify(unittest.TestCase):
    """_notify swallows ImportError (no rumps) without propagating."""

    def test_notify_does_not_raise_without_rumps(self):
        # In the test environment rumps is unavailable; the method must not raise.
        try:
            ActionsMixin._notify("Title", "Body text here")
        except Exception as exc:  # noqa: BLE001
            self.fail(f"_notify raised unexpectedly: {exc}")

    def test_notify_long_body_handled(self):
        long_body = "x" * 500
        try:
            ActionsMixin._notify("T", long_body)
        except Exception as exc:  # noqa: BLE001
            self.fail(f"_notify raised with long body: {exc}")


class TestCopyToClipboard(unittest.TestCase):
    """_copy_to_clipboard is best-effort; no AppKit in test env falls back to pbcopy."""

    def test_copy_does_not_raise(self):
        try:
            ActionsMixin._copy_to_clipboard("hello test")
        except Exception as exc:  # noqa: BLE001
            self.fail(f"_copy_to_clipboard raised unexpectedly: {exc}")

    def test_copy_empty_string_does_not_raise(self):
        try:
            ActionsMixin._copy_to_clipboard("")
        except Exception as exc:  # noqa: BLE001
            self.fail(f"_copy_to_clipboard raised with empty string: {exc}")

    def test_appkit_path_used_when_available(self):
        """When _HAS_APPKIT is True, the NSPasteboard path is taken."""
        from unittest.mock import MagicMock, patch
        mock_pb = MagicMock()
        mock_appkit_ns = MagicMock()
        mock_appkit_ns.generalPasteboard.return_value = mock_pb

        # Patch _HAS_APPKIT to True and provide a fake NSPasteboard
        with patch("telemetry._menubar_app_actions._HAS_APPKIT", True), \
             patch("telemetry._menubar_app_actions.NSPasteboard", mock_appkit_ns), \
             patch("telemetry._menubar_app_actions.NSPasteboardTypeString", "public.utf8-plain-text"):
            ActionsMixin._copy_to_clipboard("appkit text")

        mock_pb.clearContents.assert_called_once()
        mock_pb.setString_forType_.assert_called_once_with("appkit text", "public.utf8-plain-text")

    def test_appkit_exception_falls_through_to_pbcopy(self):
        """When NSPasteboard raises, execution continues to the pbcopy fallback."""
        from unittest.mock import MagicMock, patch
        mock_appkit_ns = MagicMock()
        mock_appkit_ns.generalPasteboard.side_effect = RuntimeError("AppKit broke")

        pbcopy_calls = []

        def fake_run(cmd, **_kw):
            pbcopy_calls.append(cmd)

        with patch("telemetry._menubar_app_actions._HAS_APPKIT", True), \
             patch("telemetry._menubar_app_actions.NSPasteboard", mock_appkit_ns), \
             patch("subprocess.run", fake_run):
            ActionsMixin._copy_to_clipboard("fallback text")

        self.assertEqual(pbcopy_calls, [["pbcopy"]])


if __name__ == "__main__":
    unittest.main()
