"""Tests for telemetry/menubar.py — the menubar shim module.

What is NOT tested here:
- __main__ block (starts the app event loop)
- Import-time _HAS_FCNTL=False / _HAS_APPKIT=True branches (module-level try/except
  at import time; cannot be re-exercised after import without reimporting the module)

What IS tested:
- _load_config / _save_config delegation to _menubar_config with the shim's _CONFIG_PATH
- _window_since correctness
- _build_version (mocked subprocess)
- _get_app_version caching
- _acquire_instance_lock when _HAS_FCNTL is False (no-op path)
- _acquire_instance_lock when fcntl raises BlockingIOError (already-running path)
- _compose_icon_attributed with all token kinds (lit, score var, known var, unknown var/braced)
- Re-exported names are accessible from menubar module namespace
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

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
        import subprocess  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B602/B603 review
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
        """When fcntl.flock raises BlockingIOError, _acquire_instance_lock raises CLIError."""
        from core.cli_errors import CLIError, ExitCode
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
                 patch.object(menubar.os, "close"):
                with self.assertRaises(CLIError) as ctx:
                    menubar._acquire_instance_lock()
            self.assertEqual(ctx.exception.code, ExitCode.ERROR)


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


class TestComposeIconAttributed(unittest.TestCase):
    """_compose_icon_attributed with all AppKit symbols mocked.

    All AppKit symbols (NSFont, NSMutableAttributedString, NSAttributedString,
    NSFontAttributeName, NSForegroundColorAttributeName) are injected into the
    menubar module's namespace via patch.multiple so the function body runs
    without importing AppKit.
    """

    def _make_appkit_mocks(self):
        """Return a dict of mocked AppKit symbols for patch.multiple."""
        mock_font = MagicMock(name="font")
        mock_ns_font = MagicMock(name="NSFont")
        mock_ns_font.menuBarFontOfSize_.return_value = mock_font

        mock_attributed = MagicMock(name="NSAttributedString_inst")
        mock_ns_attributed = MagicMock(name="NSAttributedString")
        mock_ns_attributed.alloc.return_value.initWithString_attributes_.return_value = mock_attributed

        mock_out = MagicMock(name="NSMutableAttributedString_inst")
        mock_ns_mutable = MagicMock(name="NSMutableAttributedString")
        mock_ns_mutable.alloc.return_value.init.return_value = mock_out

        mock_ns_color = MagicMock(name="NSColor")
        mock_ns_color.systemGreenColor.return_value = "green"
        mock_ns_color.systemOrangeColor.return_value = "orange"
        mock_ns_color.systemRedColor.return_value = "red"

        return {
            "font": mock_font,
            "NSFont": mock_ns_font,
            "NSAttributedString": mock_ns_attributed,
            "NSMutableAttributedString": mock_ns_mutable,
            "NSColor": mock_ns_color,
            "NSFontAttributeName": "NSFont",
            "NSForegroundColorAttributeName": "NSForeground",
            "out": mock_out,
        }

    def _run_compose(self, template: str, extra_values: dict | None = None) -> MagicMock:
        """Run _compose_icon_attributed with mocked AppKit, returning the output mock."""
        mocks = self._make_appkit_mocks()
        # icon_ctx drives _icon_substitutions; provide minimal data
        icon_ctx: dict = {}
        # Patch the _icon_substitutions to return a simple controlled dict
        default_values = {"mtd": "$1.23", "score": "5", "today": "$0.10"}
        if extra_values:
            default_values.update(extra_values)

        with patch.multiple(
            menubar,
            NSFont=mocks["NSFont"],
            NSAttributedString=mocks["NSAttributedString"],
            NSMutableAttributedString=mocks["NSMutableAttributedString"],
            NSColor=mocks["NSColor"],
            NSFontAttributeName=mocks["NSFontAttributeName"],
            NSForegroundColorAttributeName=mocks["NSForegroundColorAttributeName"],
            create=True,
        ), patch("telemetry.menubar._icon_substitutions", return_value=default_values):
            menubar._compose_icon_attributed(template, icon_ctx, mtd_cost=1.23, score=3)

        return mocks["out"]

    def test_literal_token_appends_attributed_string(self) -> None:
        """A plain literal in the template results in appendAttributedString_ being called."""
        out = self._run_compose("Hello")
        out.appendAttributedString_.assert_called()

    def test_empty_literal_is_skipped(self) -> None:
        """An empty literal token does not call appendAttributedString_.

        Patch _icon_token_stream to produce an explicit empty-literal token so
        the `if text:` False branch inside `kind == 'lit'` is exercised.
        """
        mocks = self._make_appkit_mocks()
        icon_ctx: dict = {}
        default_values = {"score": "3", "mtd": "$0.10"}

        with patch.multiple(
            menubar,
            NSFont=mocks["NSFont"],
            NSAttributedString=mocks["NSAttributedString"],
            NSMutableAttributedString=mocks["NSMutableAttributedString"],
            NSColor=mocks["NSColor"],
            NSFontAttributeName=mocks["NSFontAttributeName"],
            NSForegroundColorAttributeName=mocks["NSForegroundColorAttributeName"],
            create=True,
        ), patch("telemetry.menubar._icon_substitutions", return_value=default_values), \
           patch("telemetry.menubar._icon_token_stream", return_value=[("lit", "")]):
            menubar._compose_icon_attributed("", icon_ctx, mtd_cost=0.0, score=3)

        mocks["out"].appendAttributedString_.assert_not_called()

    def test_score_variable_uses_score_attributes(self) -> None:
        """$score token calls appendAttributedString_ (with the coloured score attrs)."""
        out = self._run_compose("$score")
        out.appendAttributedString_.assert_called()

    def test_known_variable_appends_value(self) -> None:
        """A known variable like $mtd appends its value from the substitution dict."""
        out = self._run_compose("Cost: $mtd")
        out.appendAttributedString_.assert_called()

    def test_unknown_braced_variable_appended_as_literal(self) -> None:
        """An unrecognised braced variable like ${unknown} is emitted verbatim."""
        out = self._run_compose("${unknown_var}")
        out.appendAttributedString_.assert_called()

    def test_unknown_bare_variable_appended_as_literal(self) -> None:
        """An unrecognised bare variable like $xyz is emitted verbatim."""
        out = self._run_compose("$xyz_notknown")
        out.appendAttributedString_.assert_called()

    def test_score_high_uses_red_color(self) -> None:
        """score >= 7 should invoke systemRedColor."""
        mocks = self._make_appkit_mocks()
        icon_ctx: dict = {}
        default_values = {"score": "8", "mtd": "$5.00"}

        with patch.multiple(
            menubar,
            NSFont=mocks["NSFont"],
            NSAttributedString=mocks["NSAttributedString"],
            NSMutableAttributedString=mocks["NSMutableAttributedString"],
            NSColor=mocks["NSColor"],
            NSFontAttributeName=mocks["NSFontAttributeName"],
            NSForegroundColorAttributeName=mocks["NSForegroundColorAttributeName"],
            create=True,
        ), patch("telemetry.menubar._icon_substitutions", return_value=default_values):
            menubar._compose_icon_attributed("$score", icon_ctx, mtd_cost=5.0, score=8)

        mocks["NSColor"].systemRedColor.assert_called()

    def test_score_mid_uses_orange_color(self) -> None:
        """score 4-6 should invoke systemOrangeColor."""
        mocks = self._make_appkit_mocks()
        icon_ctx: dict = {}
        default_values = {"score": "5", "mtd": "$2.00"}

        with patch.multiple(
            menubar,
            NSFont=mocks["NSFont"],
            NSAttributedString=mocks["NSAttributedString"],
            NSMutableAttributedString=mocks["NSMutableAttributedString"],
            NSColor=mocks["NSColor"],
            NSFontAttributeName=mocks["NSFontAttributeName"],
            NSForegroundColorAttributeName=mocks["NSForegroundColorAttributeName"],
            create=True,
        ), patch("telemetry.menubar._icon_substitutions", return_value=default_values):
            menubar._compose_icon_attributed("$score", icon_ctx, mtd_cost=2.0, score=5)

        mocks["NSColor"].systemOrangeColor.assert_called()


class TestMenubarBuildVersionFileNotFound(unittest.TestCase):
    """Cover the FileNotFoundError branch in _build_version."""

    def test_file_not_found_returns_version_only(self) -> None:
        with patch.object(menubar.subprocess, "check_output",
                          side_effect=FileNotFoundError("git not found")):
            result = menubar._build_version()
        self.assertEqual(result, menubar._VERSION)


if __name__ == "__main__":
    unittest.main()
