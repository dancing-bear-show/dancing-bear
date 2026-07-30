"""Tests for telemetry/menubar.py — the menubar shim module.

What is NOT tested here:
- _compose_icon_attributed (requires live AppKit objects — calls NSFont, NSMutableAttributedString
  chain that can't be fully replaced with simple mocks without reimplementing the ObjC bridge)
- __main__ block (starts the app event loop)

What IS tested:
- _load_config / _save_config delegation to _menubar_config with the shim's _CONFIG_PATH
- _window_since correctness
- _build_version (mocked subprocess)
- _get_app_version caching
- _acquire_instance_lock when _HAS_FCNTL is False (no-op path)
- _acquire_instance_lock when fcntl raises BlockingIOError (already-running path)
- Re-exported names are accessible from menubar module namespace
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import telemetry.menubar as menubar


class TestMenubarReExports(unittest.TestCase):
    """Verify public names re-exported from menubar module are accessible."""

    def test_budget_score_accessible(self) -> None:
        self.assertTrue(callable(menubar._budget_score))

    def test_safe_float_accessible(self) -> None:
        self.assertTrue(callable(menubar._safe_float))

    def test_safe_int_accessible(self) -> None:
        self.assertTrue(callable(menubar._safe_int))

    def test_icon_substitutions_accessible(self) -> None:
        self.assertTrue(callable(menubar._icon_substitutions))

    def test_render_icon_plain_accessible(self) -> None:
        self.assertTrue(callable(menubar._render_icon_plain))

    def test_sparkline_accessible(self) -> None:
        self.assertTrue(callable(menubar._sparkline))

    def test_has_appkit_is_bool(self) -> None:
        self.assertIsInstance(menubar._HAS_APPKIT, bool)

    def test_has_rumps_is_bool(self) -> None:
        self.assertIsInstance(menubar._HAS_RUMPS, bool)

    def test_version_constant(self) -> None:
        self.assertIsInstance(menubar._VERSION, str)
        self.assertTrue(menubar._VERSION.startswith("v"))


class TestMenubarLoadConfig(unittest.TestCase):
    def test_delegates_to_impl_with_local_path(self) -> None:
        with patch("telemetry.menubar._load_config_impl") as mock_load:
            mock_load.return_value = {"monthly_budget": 1000.0, "sections": {}}
            result = menubar._load_config()
            mock_load.assert_called_once_with(config_path=menubar._CONFIG_PATH)
            self.assertEqual(result["monthly_budget"], 1000.0)


class TestMenubarSaveConfig(unittest.TestCase):
    def test_delegates_to_impl_with_local_path(self) -> None:
        cfg = {"monthly_budget": 500.0}
        with patch("telemetry.menubar._save_config_impl") as mock_save:
            menubar._save_config(cfg)
            mock_save.assert_called_once_with(cfg, config_path=menubar._CONFIG_PATH)


class TestMenubarWindowSince(unittest.TestCase):
    def test_with_seconds_returns_past_datetime(self) -> None:
        result = menubar._window_since(3600)
        self.assertIsInstance(result, datetime)
        self.assertIsNotNone(result.tzinfo)
        diff = (datetime.now(timezone.utc) - result).total_seconds()
        self.assertGreater(diff, 3500)
        self.assertLess(diff, 3700)

    def test_none_returns_local_midnight_utc(self) -> None:
        result = menubar._window_since(None)
        local = result.astimezone()
        self.assertEqual(local.hour, 0)
        self.assertEqual(local.minute, 0)
        self.assertEqual(local.second, 0)


class TestMenubarBuildVersion(unittest.TestCase):
    def test_success_returns_version_sha(self) -> None:
        with patch.object(menubar.subprocess, "check_output", return_value="abc1234\n"):
            result = menubar._build_version()
        self.assertIn("abc1234", result)
        self.assertIn(menubar._VERSION, result)

    def test_error_returns_version_only(self) -> None:
        import subprocess
        with patch.object(menubar.subprocess, "check_output",
                          side_effect=subprocess.CalledProcessError(1, "git")):
            result = menubar._build_version()
        self.assertEqual(result, menubar._VERSION)


class TestMenubarGetAppVersion(unittest.TestCase):
    def setUp(self) -> None:
        menubar._app_version_cache_shim = None

    def test_caches_result(self) -> None:
        with patch("telemetry.menubar._build_version", return_value="v99 (sha)") as mock_bv:
            menubar._get_app_version()
            menubar._get_app_version()
        mock_bv.assert_called_once()

    def tearDown(self) -> None:
        menubar._app_version_cache_shim = None


class TestAcquireInstanceLockNoFcntl(unittest.TestCase):
    def test_no_op_when_has_fcntl_false(self) -> None:
        """When _HAS_FCNTL is False, _acquire_instance_lock should be a no-op."""
        with patch.object(menubar, "_HAS_FCNTL", False):
            # Should not raise; no file operations
            menubar._acquire_instance_lock()


class TestAcquireInstanceLockAlreadyRunning(unittest.TestCase):
    def test_exits_when_blocking_io_error(self) -> None:
        """When fcntl.flock raises BlockingIOError, process should exit(0)."""
        mock_fcntl = MagicMock()
        mock_fcntl.flock.side_effect = BlockingIOError()
        mock_fcntl.LOCK_EX = 2
        mock_fcntl.LOCK_NB = 4

        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "claudestats.lock"
            with patch.object(menubar, "_HAS_FCNTL", True), \
                 patch.object(menubar, "fcntl", mock_fcntl), \
                 patch.object(menubar, "_CLAUDE_DIR", Path(tmpdir)), \
                 patch.object(menubar, "_LOCK_PATH", lock_path), \
                 patch.object(menubar.os, "open", return_value=99), \
                 patch.object(menubar.os, "close"), \
                 patch.object(menubar.sys, "exit") as mock_exit:
                menubar._acquire_instance_lock()
            mock_exit.assert_called_once_with(0)


class TestMenubarConfigPath(unittest.TestCase):
    def test_config_path_is_in_claude_dir(self) -> None:
        self.assertIn(".claude", str(menubar._CONFIG_PATH))
        self.assertTrue(str(menubar._CONFIG_PATH).endswith(".json"))


class TestScoreColor(unittest.TestCase):
    """Test _score_color with mocked NSColor injected into the module namespace."""

    def _mock_ns_color(self) -> MagicMock:
        mock = MagicMock()
        mock.systemGreenColor.return_value = "green"
        mock.systemOrangeColor.return_value = "orange"
        mock.systemRedColor.return_value = "red"
        return mock

    def test_score_le_3_returns_green(self) -> None:
        ns_color = self._mock_ns_color()
        # Inject NSColor directly into the module namespace (it doesn't exist without AppKit)
        menubar.NSColor = ns_color  # type: ignore[attr-defined]
        try:
            result = menubar._score_color(3)
        finally:
            del menubar.NSColor  # type: ignore[attr-defined]
        self.assertEqual(result, "green")

    def test_score_4_to_6_returns_orange(self) -> None:
        ns_color = self._mock_ns_color()
        menubar.NSColor = ns_color  # type: ignore[attr-defined]
        try:
            result = menubar._score_color(5)
        finally:
            del menubar.NSColor  # type: ignore[attr-defined]
        self.assertEqual(result, "orange")

    def test_score_7_plus_returns_red(self) -> None:
        ns_color = self._mock_ns_color()
        menubar.NSColor = ns_color  # type: ignore[attr-defined]
        try:
            result = menubar._score_color(9)
        finally:
            del menubar.NSColor  # type: ignore[attr-defined]
        self.assertEqual(result, "red")


class TestAcquireInstanceLockSuccess(unittest.TestCase):
    """Test the successful lock acquisition path (writes PID, stores fd)."""

    def test_acquires_lock_and_stores_fd(self) -> None:
        mock_fcntl = MagicMock()
        mock_fcntl.LOCK_EX = 2
        mock_fcntl.LOCK_NB = 4
        mock_fcntl.flock.return_value = None  # success

        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "claudestats.lock"
            with patch.object(menubar, "_HAS_FCNTL", True), \
                 patch.object(menubar, "fcntl", mock_fcntl), \
                 patch.object(menubar, "_CLAUDE_DIR", Path(tmpdir)), \
                 patch.object(menubar, "_LOCK_PATH", lock_path), \
                 patch.object(menubar.os, "open", return_value=77), \
                 patch.object(menubar.os, "write") as mock_write, \
                 patch.object(menubar.os, "close"):
                menubar._instance_lock_fd = None
                menubar._acquire_instance_lock()
                self.assertEqual(menubar._instance_lock_fd, 77)
                mock_write.assert_called_once()


if __name__ == "__main__":
    unittest.main()
