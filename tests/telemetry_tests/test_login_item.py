"""Tests for telemetry/login_item.py — LaunchAgent management helpers."""
from __future__ import annotations

import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import telemetry.login_item as login_item
from telemetry.login_item import (
    _BUNDLE_ID,
    _PLIST_NAME,
    build_plist,
    bundle_path,
    disable,
    enable,
    is_bundle_mode,
    is_enabled,
    plist_path,
)


class TestBundlePath(unittest.TestCase):
    def test_not_bundled_returns_none(self) -> None:
        # In CI/test environment, sys.executable is not inside a .app bundle
        result = bundle_path()
        self.assertIsNone(result)

    def test_bundled_executable_returns_app_path(self) -> None:
        fake_exe = Path("/Applications/ClaudeStats.app/Contents/MacOS/python")
        with patch.object(sys, "executable", str(fake_exe)):
            result = bundle_path()
            self.assertIsNotNone(result)
            self.assertEqual(result.suffix, ".app")
            self.assertEqual(result.name, "ClaudeStats.app")

    def test_non_macos_layout_returns_none(self) -> None:
        # A regular Python install path — not inside MacOS/Contents
        fake_exe = Path("/usr/local/bin/python3")
        with patch.object(sys, "executable", str(fake_exe)):
            result = bundle_path()
            self.assertIsNone(result)

    def test_app_suffix_required(self) -> None:
        # Path that looks like MacOS/Contents but no .app suffix
        fake_exe = Path("/some/notapp/Contents/MacOS/python")
        with patch.object(sys, "executable", str(fake_exe)):
            result = bundle_path()
            self.assertIsNone(result)

    def test_dot_app_name_rejected(self) -> None:
        # Edge case: bundle named ".app" is invalid
        fake_exe = Path("/some/.app/Contents/MacOS/python")
        with patch.object(sys, "executable", str(fake_exe)):
            result = bundle_path()
            self.assertIsNone(result)


class TestIsBundleMode(unittest.TestCase):
    def test_not_bundled_returns_false(self) -> None:
        self.assertFalse(is_bundle_mode())

    def test_bundled_returns_true(self) -> None:
        fake_exe = Path("/Applications/ClaudeStats.app/Contents/MacOS/python")
        with patch.object(sys, "executable", str(fake_exe)):
            self.assertTrue(is_bundle_mode())


class TestPlistPath(unittest.TestCase):
    def test_returns_path_ending_with_plist_name(self) -> None:
        result = plist_path()
        self.assertEqual(result.name, _PLIST_NAME)

    def test_contains_bundle_id(self) -> None:
        result = plist_path()
        self.assertIn(_BUNDLE_ID, str(result))


class TestBuildPlist(unittest.TestCase):
    def test_returns_bytes(self) -> None:
        bundle = Path("/Applications/ClaudeStats.app")
        data = build_plist(bundle)
        self.assertIsInstance(data, bytes)

    def test_plist_parseable(self) -> None:
        bundle = Path("/Applications/ClaudeStats.app")
        data = build_plist(bundle)
        parsed = plistlib.loads(data)
        self.assertIsInstance(parsed, dict)

    def test_plist_has_correct_label(self) -> None:
        bundle = Path("/Applications/ClaudeStats.app")
        data = build_plist(bundle)
        parsed = plistlib.loads(data)
        self.assertEqual(parsed["Label"], _BUNDLE_ID)

    def test_plist_references_bundle_path(self) -> None:
        bundle = Path("/Applications/ClaudeStats.app")
        data = build_plist(bundle)
        parsed = plistlib.loads(data)
        self.assertIn(str(bundle), parsed["ProgramArguments"])

    def test_plist_run_at_load_true(self) -> None:
        bundle = Path("/Applications/ClaudeStats.app")
        data = build_plist(bundle)
        parsed = plistlib.loads(data)
        self.assertTrue(parsed["RunAtLoad"])

    def test_plist_keep_alive_false(self) -> None:
        bundle = Path("/Applications/ClaudeStats.app")
        data = build_plist(bundle)
        parsed = plistlib.loads(data)
        self.assertFalse(parsed["KeepAlive"])


class TestIsEnabled(unittest.TestCase):
    def test_returns_false_when_plist_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_plist = Path(tmpdir) / _PLIST_NAME
            with patch.object(login_item, "_LAUNCH_AGENTS_DIR", Path(tmpdir)):
                # Patch plist_path to return the fake path
                with patch("telemetry.login_item.plist_path", return_value=fake_plist):
                    self.assertFalse(is_enabled())

    def test_returns_true_when_plist_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_plist = Path(tmpdir) / _PLIST_NAME
            fake_plist.write_bytes(b"dummy")
            with patch("telemetry.login_item.plist_path", return_value=fake_plist):
                self.assertTrue(is_enabled())


class TestEnable(unittest.TestCase):
    def test_raises_runtime_error_when_not_bundled(self) -> None:
        with self.assertRaises(RuntimeError):
            enable()

    def test_writes_plist_when_bundled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_plist = Path(tmpdir) / _PLIST_NAME
            fake_bundle = Path("/Applications/ClaudeStats.app")

            with patch("telemetry.login_item.bundle_path", return_value=fake_bundle), \
                 patch("telemetry.login_item.plist_path", return_value=fake_plist):
                enable()

            self.assertTrue(fake_plist.exists())
            parsed = plistlib.loads(fake_plist.read_bytes())
            self.assertEqual(parsed["Label"], _BUNDLE_ID)

    def test_enable_no_temp_files_remain(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_plist = Path(tmpdir) / _PLIST_NAME
            fake_bundle = Path("/Applications/ClaudeStats.app")

            with patch("telemetry.login_item.bundle_path", return_value=fake_bundle), \
                 patch("telemetry.login_item.plist_path", return_value=fake_plist):
                enable()

            tmp_files = list(Path(tmpdir).glob("*.tmp"))
            self.assertEqual(tmp_files, [])


class TestDisable(unittest.TestCase):
    def test_no_op_when_plist_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_plist = Path(tmpdir) / _PLIST_NAME
            with patch("telemetry.login_item.plist_path", return_value=fake_plist):
                # Should not raise
                disable()

    def test_removes_plist_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_plist = Path(tmpdir) / _PLIST_NAME
            fake_plist.write_bytes(b"dummy")
            with patch("telemetry.login_item.plist_path", return_value=fake_plist):
                disable()
            self.assertFalse(fake_plist.exists())


class TestEnableWriteErrorCleanup(unittest.TestCase):
    """Test that enable() cleans up the temp file on write errors."""

    def test_write_error_removes_tmp_file(self) -> None:
        """enable() should clean up the .tmp file when os.replace fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / _PLIST_NAME
            fake_bundle = Path("/Applications/ClaudeStats.app")

            with patch("telemetry.login_item.bundle_path", return_value=fake_bundle), \
                 patch("telemetry.login_item.plist_path", return_value=target), \
                 patch("os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    enable()

            # After the error, no .tmp files should remain
            tmp_files = list(Path(tmpdir).glob("*.tmp"))
            self.assertEqual(tmp_files, [])

    def test_write_error_with_unlink_failure_still_raises(self) -> None:
        """enable() re-raises the original error even if os.unlink also fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / _PLIST_NAME
            fake_bundle = Path("/Applications/ClaudeStats.app")

            with patch("telemetry.login_item.bundle_path", return_value=fake_bundle), \
                 patch("telemetry.login_item.plist_path", return_value=target), \
                 patch("os.replace", side_effect=OSError("disk full")), \
                 patch("os.unlink", side_effect=OSError("unlink failed")):
                with self.assertRaises(OSError) as cm:
                    enable()
            # The original error (disk full) should be the one raised
            self.assertIn("disk full", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
