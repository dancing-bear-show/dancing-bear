"""Tests for ActionsMixin in telemetry/_menubar_app_actions.py.

Covers:
- Pure-Python static methods and filesystem-cleanup logic (_clear_stale_project_dir)
- _notify (happy path with mocked rumps, error swallow path)
- _copy_to_clipboard (AppKit path, pbcopy fallback, both exception swallows)
- _on_configure (save, cancel, save-failure, rejected-keys paths — all rumps interactions mocked)
- _on_toggle_login_item (not-bundle-mode, enable/disable, OSError paths)
- _on_clear (cancel, delete, OSError paths)
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from telemetry._menubar_app_actions import ActionsMixin


def _make_host() -> ActionsMixin:
    class _Host(ActionsMixin):
        # Satisfy attribute access used in the GUI-bound methods
        _btn_login_item = NS(state=0)
        _last_cfg: dict = {}

        def _rebuild_menu(self, cfg: dict) -> None:
            pass

        def _refresh(self, sender: object) -> None:
            pass

    return _Host()


class TestClearStaleProjectDirAllStale(unittest.TestCase):
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


class TestClearStaleProjectDirMixedAge(unittest.TestCase):
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


class TestClearStaleProjectDirEmptyAfterDelete(unittest.TestCase):
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


class TestClearStaleProjectDirSubdirsIgnored(unittest.TestCase):
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

    def test_notify_calls_rumps_notification_when_available(self):
        """Happy path: rumps is importable and notification is called with truncated body."""
        mock_rumps = MagicMock()
        with patch.dict("sys.modules", {"rumps": mock_rumps}):
            ActionsMixin._notify("MyTitle", "Hello world")
        mock_rumps.notification.assert_called_once_with(
            title="MyTitle", subtitle="", message="Hello world"
        )

    def test_notify_truncates_body_to_200_chars(self):
        """Body longer than 200 chars is truncated before passing to rumps."""
        mock_rumps = MagicMock()
        long_body = "A" * 300
        with patch.dict("sys.modules", {"rumps": mock_rumps}):
            ActionsMixin._notify("T", long_body)
        call_kwargs = mock_rumps.notification.call_args[1]
        self.assertEqual(len(call_kwargs["message"]), 200)

    def test_notify_swallows_exception_from_rumps(self):
        """If rumps.notification raises, the exception is swallowed."""
        mock_rumps = MagicMock()
        mock_rumps.notification.side_effect = RuntimeError("rumps broke")
        with patch.dict("sys.modules", {"rumps": mock_rumps}):
            # Should not raise
            ActionsMixin._notify("T", "body")


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
        mock_pb = MagicMock()
        mock_appkit_ns = MagicMock()
        mock_appkit_ns.generalPasteboard.return_value = mock_pb

        # create=True is required: NSPasteboard/NSPasteboardTypeString are only
        # bound when the AppKit import succeeds. On Linux CI the except-ImportError
        # branch runs, so the names do not exist on the module and a plain patch
        # raises AttributeError before the test body runs.
        with patch("telemetry._menubar_app_actions._HAS_APPKIT", True), \
             patch("telemetry._menubar_app_actions.NSPasteboard", mock_appkit_ns, create=True), \
             patch("telemetry._menubar_app_actions.NSPasteboardTypeString",
                   "public.utf8-plain-text", create=True):
            ActionsMixin._copy_to_clipboard("appkit text")

        mock_pb.clearContents.assert_called_once()
        mock_pb.setString_forType_.assert_called_once_with("appkit text", "public.utf8-plain-text")

    def test_appkit_exception_falls_through_to_pbcopy(self):
        """When NSPasteboard raises, execution continues to the pbcopy fallback."""
        mock_appkit_ns = MagicMock()
        mock_appkit_ns.generalPasteboard.side_effect = RuntimeError("AppKit broke")

        pbcopy_calls = []

        def fake_run(cmd, **_kw):
            pbcopy_calls.append(cmd)

        # create=True: NSPasteboard is unbound on non-macOS (see note above).
        with patch("telemetry._menubar_app_actions._HAS_APPKIT", True), \
             patch("telemetry._menubar_app_actions.NSPasteboard", mock_appkit_ns, create=True), \
             patch("subprocess.run", fake_run):
            ActionsMixin._copy_to_clipboard("fallback text")

        self.assertEqual(pbcopy_calls, [["pbcopy"]])

    def test_pbcopy_exception_is_swallowed(self):
        """When pbcopy subprocess.run raises, the exception is swallowed."""
        with patch("telemetry._menubar_app_actions._HAS_APPKIT", False), \
             patch("subprocess.run", side_effect=OSError("no pbcopy")):
            # Should not raise
            ActionsMixin._copy_to_clipboard("text")


# ---------------------------------------------------------------------------
# _on_configure tests — all GUI interactions (rumps.Window, rumps.alert) mocked
# ---------------------------------------------------------------------------

def _make_mock_rumps(*, clicked: int = 1, text: str = "", alert_side_effect=None):
    """Build a mock rumps module for configure tests."""
    mock = MagicMock()
    response = NS(clicked=clicked, text=text)
    mock.Window.return_value.run.return_value = response
    if alert_side_effect is not None:
        mock.alert.side_effect = alert_side_effect
    return mock


class TestOnConfigure(unittest.TestCase):
    """_on_configure is fully mocked at the rumps boundary."""

    def _patch_rumps(self, mock_rumps):
        return patch.dict("sys.modules", {"rumps": mock_rumps})

    def _patch_config(self, cfg=None, updated=None, rejected=None):
        """Patch the config helpers used inside _on_configure."""
        cfg = cfg or {}
        updated = updated if updated is not None else cfg
        rejected = rejected or []
        load = patch("telemetry._menubar_config._load_config", return_value=cfg)
        config_to_text = patch(
            "telemetry._menubar_app_actions._config_to_text", return_value="cfg_text"
        )
        parse = patch(
            "telemetry._menubar_app_actions._parse_config_text",
            return_value=(updated, rejected),
        )
        save = patch("telemetry._menubar_app_actions._save_config")
        return load, config_to_text, parse, save

    def test_save_path_calls_rebuild_and_refresh(self):
        """Happy path: user clicks Save, config is persisted, menu rebuilt."""
        host = _make_host()
        mock_rumps = _make_mock_rumps(clicked=1, text="some_text")
        cfg = {"monthly_budget": 100.0}
        updated = {"monthly_budget": 200.0}
        load, ctt, parse, save = self._patch_config(cfg=cfg, updated=updated, rejected=[])

        with self._patch_rumps(mock_rumps), load, ctt, parse, save as mock_save:
            host._on_configure(None)

        mock_save.assert_called_once_with(updated)
        self.assertIs(host._last_cfg, updated)

    def test_cancel_path_returns_early(self):
        """When user cancels (clicked != 1), nothing is saved."""
        host = _make_host()
        mock_rumps = _make_mock_rumps(clicked=0)
        load, ctt, parse, save = self._patch_config()

        with self._patch_rumps(mock_rumps), load, ctt, parse, save as mock_save:
            host._on_configure(None)

        mock_save.assert_not_called()

    def test_save_failure_shows_alert_and_returns(self):
        """If _save_config raises, an alert is shown and rebuild is NOT called."""
        host = _make_host()
        mock_rumps = _make_mock_rumps(clicked=1, text="cfg")
        load, ctt, parse, save = self._patch_config()

        rebuild_called = []
        host._rebuild_menu = lambda _: rebuild_called.append(True)

        with self._patch_rumps(mock_rumps), load, ctt, parse, \
             patch("telemetry._menubar_app_actions._save_config", side_effect=OSError("disk full")):
            host._on_configure(None)

        mock_rumps.alert.assert_called_once()
        alert_kwargs = mock_rumps.alert.call_args[1]
        self.assertIn("disk full", alert_kwargs["message"])
        self.assertEqual(rebuild_called, [])

    def test_rejected_keys_shows_second_alert(self):
        """When some config keys are rejected, a second alert is shown."""
        host = _make_host()
        mock_rumps = _make_mock_rumps(clicked=1, text="cfg")
        rejected = ["bad_key = xyz", "another_key = abc"]
        load, ctt, parse, save = self._patch_config(rejected=rejected)

        with self._patch_rumps(mock_rumps), load, ctt, parse, save:
            host._on_configure(None)

        # First call is the "Some settings weren't applied" alert
        self.assertTrue(mock_rumps.alert.called)
        call_args = mock_rumps.alert.call_args[1]
        self.assertIn("weren't applied", call_args["title"])

    def test_many_rejected_keys_shows_ellipsis(self):
        """More than 8 rejected keys triggers the '...and N more' message."""
        host = _make_host()
        mock_rumps = _make_mock_rumps(clicked=1, text="cfg")
        rejected = [f"key_{i} = val" for i in range(12)]
        load, ctt, parse, save = self._patch_config(rejected=rejected)

        with self._patch_rumps(mock_rumps), load, ctt, parse, save:
            host._on_configure(None)

        call_args = mock_rumps.alert.call_args[1]
        self.assertIn("more", call_args["message"])


# ---------------------------------------------------------------------------
# _on_toggle_login_item tests
# ---------------------------------------------------------------------------

class TestOnToggleLoginItem(unittest.TestCase):
    """_on_toggle_login_item branching logic."""

    def _patch_rumps(self, mock_rumps=None):
        if mock_rumps is None:
            mock_rumps = MagicMock()
        return patch.dict("sys.modules", {"rumps": mock_rumps}), mock_rumps

    def test_not_bundle_mode_shows_alert_and_returns(self):
        """When not in bundle mode, an alert is shown and nothing else happens."""
        host = _make_host()
        ctx, mock_rumps = self._patch_rumps()

        with ctx, \
             patch("telemetry._menubar_app_actions._login_item") as mock_li:
            mock_li.is_bundle_mode.return_value = False
            host._on_toggle_login_item(None)

        mock_rumps.alert.assert_called_once()
        mock_li.enable.assert_not_called()
        mock_li.disable.assert_not_called()

    def test_bundle_mode_enabled_calls_disable(self):
        """When login item is currently enabled, toggling disables it."""
        host = _make_host()
        ctx, _ = self._patch_rumps()

        with ctx, \
             patch("telemetry._menubar_app_actions._login_item") as mock_li:
            mock_li.is_bundle_mode.return_value = True
            mock_li.is_enabled.side_effect = [True, False]  # before toggle, after toggle
            host._on_toggle_login_item(None)

        mock_li.disable.assert_called_once()
        self.assertEqual(host._btn_login_item.state, 0)

    def test_bundle_mode_disabled_calls_enable(self):
        """When login item is currently disabled, toggling enables it."""
        host = _make_host()
        ctx, _ = self._patch_rumps()

        with ctx, \
             patch("telemetry._menubar_app_actions._login_item") as mock_li:
            mock_li.is_bundle_mode.return_value = True
            mock_li.is_enabled.side_effect = [False, True]  # before toggle, after toggle
            host._on_toggle_login_item(None)

        mock_li.enable.assert_called_once()
        self.assertEqual(host._btn_login_item.state, 1)

    def test_oserror_shows_alert(self):
        """OSError from enable/disable is caught and shown as an alert."""
        host = _make_host()
        ctx, mock_rumps = self._patch_rumps()

        with ctx, \
             patch("telemetry._menubar_app_actions._login_item") as mock_li:
            mock_li.is_bundle_mode.return_value = True
            mock_li.is_enabled.side_effect = [False, False]
            mock_li.enable.side_effect = OSError("permission denied")
            host._on_toggle_login_item(None)

        mock_rumps.alert.assert_called_once()
        call_kwargs = mock_rumps.alert.call_args[1]
        self.assertIn("permission denied", call_kwargs["message"])

    def test_runtime_error_shows_alert(self):
        """RuntimeError from enable/disable is caught and shown as an alert."""
        host = _make_host()
        ctx, mock_rumps = self._patch_rumps()

        with ctx, \
             patch("telemetry._menubar_app_actions._login_item") as mock_li:
            mock_li.is_bundle_mode.return_value = True
            mock_li.is_enabled.side_effect = [True, True]
            mock_li.disable.side_effect = RuntimeError("smc error")
            host._on_toggle_login_item(None)

        mock_rumps.alert.assert_called_once()
        call_kwargs = mock_rumps.alert.call_args[1]
        self.assertIn("smc error", call_kwargs["message"])


# ---------------------------------------------------------------------------
# _on_clear tests
# ---------------------------------------------------------------------------

class TestOnClear(unittest.TestCase):
    """_on_clear branching: cancel, delete, iterdir failure."""

    def _patch_rumps(self, mock_rumps=None):
        if mock_rumps is None:
            mock_rumps = MagicMock()
        return patch.dict("sys.modules", {"rumps": mock_rumps}), mock_rumps

    def test_cancel_does_nothing(self):
        """When user cancels (response != 1), no files are deleted."""
        host = _make_host()
        mock_rumps = MagicMock()
        mock_rumps.alert.return_value = 0  # Cancel
        ctx, _ = self._patch_rumps(mock_rumps)

        refresh_called = []
        host._refresh = lambda _: refresh_called.append(True)

        with ctx:
            host._on_clear(None)

        self.assertEqual(refresh_called, [])
        mock_rumps.notification.assert_not_called()

    def test_delete_path_calls_refresh_and_notifies(self):
        """Happy path: user confirms, stale files are deleted, notification shown."""
        host = _make_host()
        mock_rumps = MagicMock()
        mock_rumps.alert.return_value = 1  # Delete
        ctx, _ = self._patch_rumps(mock_rumps)

        refresh_called = []
        host._refresh = lambda _: refresh_called.append(True)

        with ctx, \
             patch.object(ActionsMixin, "_clear_stale_project_dir", return_value=2):
            with tempfile.TemporaryDirectory() as tmpdir:
                projects_dir = Path(tmpdir) / ".claude" / "projects"
                projects_dir.mkdir(parents=True)
                (projects_dir / "proj").mkdir()
                with patch("telemetry._menubar_app_actions.Path.home", return_value=Path(tmpdir)):
                    host._on_clear(None)

        mock_rumps.notification.assert_called()
        notif_kwargs = mock_rumps.notification.call_args[1]
        self.assertEqual(notif_kwargs["title"], "Sessions cleared")
        self.assertIn(True, refresh_called)

    def test_iterdir_exception_shows_failure_notification(self):
        """If iterating the projects dir raises, a failure notification is shown."""
        host = _make_host()
        mock_rumps = MagicMock()
        mock_rumps.alert.return_value = 1  # Delete
        ctx, _ = self._patch_rumps(mock_rumps)

        refresh_called = []
        host._refresh = lambda _: refresh_called.append(True)

        with ctx:
            # Make Path.home() return a real temp dir, but make iterdir() raise
            with tempfile.TemporaryDirectory() as tmpdir:
                with patch("telemetry._menubar_app_actions.Path.home", return_value=Path(tmpdir)):
                    with patch.object(Path, "iterdir", side_effect=OSError("no access")):
                        host._on_clear(None)

        mock_rumps.notification.assert_called_once()
        notif_kwargs = mock_rumps.notification.call_args[1]
        self.assertEqual(notif_kwargs["title"], "Clear failed")
        self.assertEqual(refresh_called, [])

    def test_delete_single_file_uses_singular_label(self):
        """Deleting exactly 1 file uses 'file' (not 'files') in notification subtitle."""
        host = _make_host()
        mock_rumps = MagicMock()
        mock_rumps.alert.return_value = 1
        ctx, _ = self._patch_rumps(mock_rumps)
        host._refresh = lambda _: None

        # Patch _clear_stale_project_dir to return 1 deleted file
        with ctx, \
             patch.object(ActionsMixin, "_clear_stale_project_dir", return_value=1):
            with tempfile.TemporaryDirectory() as tmpdir:
                projects_dir = Path(tmpdir) / ".claude" / "projects"
                projects_dir.mkdir(parents=True)
                (projects_dir / "proj").mkdir()
                with patch("telemetry._menubar_app_actions.Path.home", return_value=Path(tmpdir)):
                    host._on_clear(None)

        notif_kwargs = mock_rumps.notification.call_args[1]
        self.assertIn("1 file", notif_kwargs["subtitle"])
        self.assertNotIn("files", notif_kwargs["subtitle"])

    def test_delete_multiple_files_uses_plural_label(self):
        """Deleting more than 1 file uses 'files' in notification subtitle."""
        host = _make_host()
        mock_rumps = MagicMock()
        mock_rumps.alert.return_value = 1
        ctx, _ = self._patch_rumps(mock_rumps)
        host._refresh = lambda _: None

        with ctx, \
             patch.object(ActionsMixin, "_clear_stale_project_dir", return_value=3):
            with tempfile.TemporaryDirectory() as tmpdir:
                projects_dir = Path(tmpdir) / ".claude" / "projects"
                projects_dir.mkdir(parents=True)
                (projects_dir / "proj").mkdir()
                with patch("telemetry._menubar_app_actions.Path.home", return_value=Path(tmpdir)):
                    host._on_clear(None)

        notif_kwargs = mock_rumps.notification.call_args[1]
        self.assertIn("files", notif_kwargs["subtitle"])

    def test_non_directory_entries_in_projects_dir_are_skipped(self):
        """A plain file inside the projects dir (not a subdirectory) is ignored."""
        host = _make_host()
        mock_rumps = MagicMock()
        mock_rumps.alert.return_value = 1
        ctx, _ = self._patch_rumps(mock_rumps)
        host._refresh = lambda _: None

        with ctx:
            with tempfile.TemporaryDirectory() as tmpdir:
                projects_dir = Path(tmpdir) / ".claude" / "projects"
                projects_dir.mkdir(parents=True)
                # Place a plain file (not a directory) in the projects dir
                (projects_dir / "not_a_dir.jsonl").write_text("data")

                with patch("telemetry._menubar_app_actions.Path.home", return_value=Path(tmpdir)):
                    host._on_clear(None)

        # The notification should be "Sessions cleared" with 0 files deleted
        notif_kwargs = mock_rumps.notification.call_args[1]
        self.assertEqual(notif_kwargs["title"], "Sessions cleared")
        self.assertIn("0 file", notif_kwargs["subtitle"])


if __name__ == "__main__":
    unittest.main()
