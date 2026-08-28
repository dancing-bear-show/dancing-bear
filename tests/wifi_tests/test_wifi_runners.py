"""Tests for wifi/diagnostics_runners.py — SubprocessRunner."""
from __future__ import annotations

import subprocess  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B602/B603 review
import unittest
from unittest.mock import patch

from wifi.diagnostics_runners import SubprocessRunner
from tests.wifi_tests.shared_fixtures import FakeRunner  # noqa: F401 — available for test use


class TestSubprocessRunner(unittest.TestCase):
    def test_timeout_expired_bytes_stdout(self):
        runner = SubprocessRunner()
        exc = subprocess.TimeoutExpired(cmd=["ping"], timeout=1)
        exc.stdout = b"partial output"
        exc.stderr = b"timeout error"
        with patch("subprocess.run", side_effect=exc):
            result = runner.run(["ping", "localhost"], timeout=1)
        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.stdout, "partial output")
        self.assertEqual(result.stderr, "timeout error")

    def test_timeout_expired_str_stdout(self):
        runner = SubprocessRunner()
        exc = subprocess.TimeoutExpired(cmd=["ping"], timeout=1)
        exc.stdout = "partial str"
        exc.stderr = None
        with patch("subprocess.run", side_effect=exc):
            result = runner.run(["ping", "localhost"], timeout=1)
        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.stdout, "partial str")
        self.assertEqual(result.stderr, "timeout")

    def test_file_not_found(self):
        runner = SubprocessRunner()
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            result = runner.run(["nonexistent-cmd"], timeout=5)
        self.assertEqual(result.returncode, 127)
        self.assertIn("not found", result.stderr)

    def test_permission_error_is_not_reported_as_not_found(self):
        # rc 127 covers every exec failure. An earlier version rewrote stderr to
        # "<binary>: not found" for ANY 127, so a present-but-not-executable
        # binary looked missing -- misleading in a diagnostics tool, where the
        # remedy for "not installed" and "not executable" differ.
        runner = SubprocessRunner()
        boom = PermissionError(13, "Permission denied")
        with patch("subprocess.run", side_effect=boom):
            result = runner.run(["/usr/local/bin/airport"], timeout=5)
        self.assertEqual(result.returncode, 127)
        self.assertNotIn("not found", result.stderr)
        self.assertIn("Permission denied", result.stderr)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
