"""Tests for telemetry/_menubar_app.py — pure logic outside the GUI event loop.

What is NOT tested here (genuinely GUI-only, requires rumps/AppKit):
- TelemetryMenubarApp.__init__ and all methods that call rumps.MenuItem/rumps.Timer
- TelemetryMenubarApp._rebuild_menu (calls self.menu.clear(), self.menu = ...)
- TelemetryMenubarApp._refresh (calls rumps.Timer, rumps.Window)
- TelemetryMenubarApp._on_configure (calls rumps.Window, rumps.alert)
- TelemetryMenubarApp._on_toggle_login_item (calls rumps.alert)
- TelemetryMenubarApp._on_clear (calls rumps.alert, rumps.notification)
- TelemetryMenubarApp._notify (calls rumps.notification)
- TelemetryMenubarApp._copy_to_clipboard (calls NSPasteboard / pbcopy)
- _update_menu / _update_otel_sections_* (mutate rumps.MenuItem.title)
- _set_icon (calls self._nsapp.nsstatusitem.setAttributedTitle_)

What IS tested:
- _build_version (mocked subprocess)
- _get_app_version (caching behavior)
- _month_since (pure datetime)
- _window_since (delegates to _window_since_impl)
- _project_short (pure string logic)
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import telemetry._menubar_app as _app_module
from telemetry._menubar_app import (
    _VERSION,
    _build_version,
    _get_app_version,
    _month_since,
    _project_short,
    _window_since,
    _WINDOWS,
    _OTEL_WINDOWS,
    _STORAGE_WARN_DAYS,
)
from telemetry.models import SessionSummary


def _make_session(
    session_id: str = "abc123",
    project_path: str | None = "/home/user/my-project",
) -> SessionSummary:
    now = datetime.now(timezone.utc)
    return SessionSummary(
        session_id=session_id,
        project_path=project_path,
        start_time=now,
        end_time=now,
        model="claude-sonnet",
        total_cost=0.01,
        cost_is_estimated=False,
        total_events=1,
        efficiency_score=80.0,
        input_tokens=100,
        output_tokens=50,
    )


class TestBuildVersion(unittest.TestCase):
    def test_success_returns_version_with_sha(self) -> None:
        with patch("telemetry._menubar_app.subprocess.check_output", return_value="abc1234\n"):
            result = _build_version()
        self.assertEqual(result, f"{_VERSION} (abc1234)")

    def test_subprocess_error_returns_version_only(self) -> None:
        import subprocess  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B602/B603 review
        with patch("telemetry._menubar_app.subprocess.check_output",
                   side_effect=subprocess.CalledProcessError(1, "git")):
            result = _build_version()
        self.assertEqual(result, _VERSION)

    def test_file_not_found_returns_version_only(self) -> None:
        with patch("telemetry._menubar_app.subprocess.check_output",
                   side_effect=FileNotFoundError):
            result = _build_version()
        self.assertEqual(result, _VERSION)


class TestGetAppVersion(unittest.TestCase):
    def setUp(self) -> None:
        # Reset cache before each test
        _app_module._app_version_cache = None

    def test_calls_build_version_on_first_call(self) -> None:
        with patch("telemetry._menubar_app._build_version", return_value="v1.0.0 (abc)") as mock_bv:
            result = _get_app_version()
        self.assertEqual(result, "v1.0.0 (abc)")
        mock_bv.assert_called_once()

    def test_cached_on_second_call(self) -> None:
        with patch("telemetry._menubar_app._build_version", return_value="v1.0.0 (abc)") as mock_bv:
            _get_app_version()
            _get_app_version()
        mock_bv.assert_called_once()

    def tearDown(self) -> None:
        _app_module._app_version_cache = None


class TestMonthSince(unittest.TestCase):
    def test_returns_utc_datetime(self) -> None:
        result = _month_since()
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.tzinfo, timezone.utc)

    def test_day_is_one(self) -> None:
        result = _month_since()
        self.assertEqual(result.day, 1)

    def test_time_is_midnight(self) -> None:
        result = _month_since()
        self.assertEqual(result.hour, 0)
        self.assertEqual(result.minute, 0)
        self.assertEqual(result.second, 0)
        self.assertEqual(result.microsecond, 0)


class TestWindowSince(unittest.TestCase):
    def test_with_seconds_is_approximately_correct(self) -> None:
        result = _window_since(3600)
        now = datetime.now(timezone.utc)
        diff = (now - result).total_seconds()
        self.assertGreater(diff, 3500)
        self.assertLess(diff, 3700)

    def test_none_returns_midnight(self) -> None:
        result = _window_since(None)
        local = result.astimezone()
        self.assertEqual(local.hour, 0)
        self.assertEqual(local.minute, 0)


class TestProjectShort(unittest.TestCase):
    def test_last_path_component(self) -> None:
        s = _make_session(project_path="/home/user/my-project")
        self.assertEqual(_project_short(s), "my-project")

    def test_truncated_to_28_chars(self) -> None:
        long_name = "a" * 40
        s = _make_session(project_path=f"/home/user/{long_name}")
        result = _project_short(s)
        self.assertEqual(len(result), 28)

    def test_no_project_path_uses_session_id(self) -> None:
        s = _make_session(session_id="deadbeef1234abcd", project_path=None)
        result = _project_short(s)
        self.assertEqual(result, "deadbeef")

    def test_empty_project_path_uses_session_id(self) -> None:
        s = _make_session(session_id="abcd1234efgh5678", project_path="")
        result = _project_short(s)
        self.assertEqual(result, "abcd1234")

    def test_root_path_uses_session_id(self) -> None:
        s = _make_session(session_id="xyzwabcd", project_path="/")
        # parts = [] -> falls back to session_id[:8]
        result = _project_short(s)
        self.assertEqual(result, "xyzwabcd")

    def test_nested_path(self) -> None:
        s = _make_session(project_path="/a/b/c/dancing-bear")
        self.assertEqual(_project_short(s), "dancing-bear")


class TestWindowsConstants(unittest.TestCase):
    def test_windows_has_four_entries(self) -> None:
        self.assertEqual(len(_WINDOWS), 4)

    def test_windows_has_labels_and_secs(self) -> None:
        for label, secs in _WINDOWS:
            self.assertIsInstance(label, str)
            self.assertTrue(secs is None or isinstance(secs, int))

    def test_otel_windows_has_four_entries(self) -> None:
        self.assertEqual(len(_OTEL_WINDOWS), 4)

    def test_storage_warn_days_is_positive(self) -> None:
        self.assertGreater(_STORAGE_WARN_DAYS, 0)


if __name__ == "__main__":
    unittest.main()
