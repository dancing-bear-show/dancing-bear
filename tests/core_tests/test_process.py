"""Tests for core.process.run_binary.

These drive the real ``subprocess`` rather than mocking it wherever the
behaviour under test IS the subprocess interaction -- a mocked ``run_binary``
would assert only that the mock was configured correctly. The commands used
(``echo``, ``sh -c``, ``pwd``) are POSIX built-ins already relied on by the
suite's environment.
"""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from unittest.mock import patch

from core.process import RC_NOT_FOUND, RC_TIMEOUT, CompletedRun, run_binary


class RunBinarySuccessTests(unittest.TestCase):
    def test_captures_stdout_and_marks_ok(self):
        res = run_binary(["echo", "hello"])
        self.assertTrue(res.ok)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), "hello")
        self.assertFalse(res.timed_out)
        self.assertFalse(res.not_found)

    def test_captures_stderr_separately_from_stdout(self):
        res = run_binary(["sh", "-c", "echo out; echo err >&2"])
        self.assertEqual(res.stdout.strip(), "out")
        self.assertEqual(res.stderr.strip(), "err")

    def test_records_the_command_it_ran(self):
        res = run_binary(["echo", "x"])
        self.assertEqual(res.command, ("echo", "x"))

    def test_coerces_non_str_arguments(self):
        # Path objects and ints are common in call sites building arg vectors.
        res = run_binary(["echo", 42])
        self.assertEqual(res.stdout.strip(), "42")

    def test_honours_cwd(self):
        res = run_binary(["pwd"], cwd="/")
        self.assertEqual(res.stdout.strip(), "/")

    def test_honours_env(self):
        res = run_binary(
            ["sh", "-c", "echo $DB_TEST_VAR"],
            env={"DB_TEST_VAR": "sentinel", "PATH": "/usr/bin:/bin"},
        )
        self.assertEqual(res.stdout.strip(), "sentinel")


class RunBinaryFailureTests(unittest.TestCase):
    """The failure modes callers depend on being return values, not raises."""

    def test_nonzero_exit_is_returned_not_raised(self):
        # Load-bearing: qlty uses rc 1 for "issues found", so a non-zero exit
        # must never be promoted to an exception here.
        res = run_binary(["sh", "-c", "exit 3"])
        self.assertEqual(res.returncode, 3)
        self.assertFalse(res.ok)
        self.assertFalse(res.timed_out)
        self.assertFalse(res.not_found)

    def test_missing_binary_maps_to_rc_not_found(self):
        res = run_binary(["/nonexistent/definitely-not-a-binary"])
        self.assertEqual(res.returncode, RC_NOT_FOUND)
        self.assertTrue(res.not_found)
        self.assertFalse(res.ok)
        self.assertIn("/nonexistent/definitely-not-a-binary", res.stderr)
        self.assertIn("not found", res.stderr)

    def test_non_executable_binary_is_not_reported_as_missing(self):
        # rc 127 covers every exec failure, not just ENOENT. A file that exists
        # but lacks +x must NOT say "not found" -- that sends someone debugging
        # a permissions problem looking for a missing install instead.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "not-executable")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("#!/bin/sh\necho hi\n")
            os.chmod(path, stat.S_IRUSR)  # readable, deliberately not +x

            res = run_binary([path])

        self.assertEqual(res.returncode, RC_NOT_FOUND)
        self.assertNotIn(
            "not found",
            res.stderr,
            "a permission error was mislabelled as a missing binary",
        )
        self.assertIn("Permission denied", res.stderr)
        self.assertIn(path, res.stderr)

    def test_timeout_maps_to_rc_timeout(self):
        res = run_binary(["sleep", "5"], timeout=0.25)
        self.assertEqual(res.returncode, RC_TIMEOUT)
        self.assertTrue(res.timed_out)
        self.assertFalse(res.ok)
        self.assertTrue(res.stderr)

    def test_empty_command_reports_a_usable_stderr(self):
        # An empty vector raises IndexError inside subprocess; the wrapper must
        # still produce a message rather than crash on command[0].
        res = run_binary([])
        self.assertEqual(res.returncode, RC_NOT_FOUND)
        self.assertIn("<empty>", res.stderr)


class TimeoutOutputDecodingTests(unittest.TestCase):
    """TimeoutExpired carries bytes, str, or None depending on the platform."""

    def _timeout(self, stdout, stderr):
        import subprocess

        return subprocess.TimeoutExpired(
            cmd=["x"], timeout=1, output=stdout, stderr=stderr
        )

    def test_decodes_bytes_partial_output(self):
        with patch("core.process.subprocess.run", side_effect=self._timeout(b"partial", b"warn")):
            res = run_binary(["x"], timeout=1)
        self.assertEqual(res.stdout, "partial")
        self.assertEqual(res.stderr, "warn")
        self.assertTrue(res.timed_out)

    def test_passes_through_str_partial_output(self):
        with patch("core.process.subprocess.run", side_effect=self._timeout("partial", "warn")):
            res = run_binary(["x"], timeout=1)
        self.assertEqual(res.stdout, "partial")
        self.assertEqual(res.stderr, "warn")

    def test_none_output_falls_back_to_timeout_marker(self):
        with patch("core.process.subprocess.run", side_effect=self._timeout(None, None)):
            res = run_binary(["x"], timeout=1)
        self.assertEqual(res.stdout, "")
        # Probes surface stderr to the user, so it must never be empty here.
        self.assertEqual(res.stderr, "timeout")


class CompletedRunTests(unittest.TestCase):
    def test_is_frozen(self):
        res = CompletedRun(stdout="", stderr="", returncode=0)
        with self.assertRaises(Exception):
            res.returncode = 1

    def test_sentinel_properties_are_exclusive(self):
        self.assertTrue(CompletedRun("", "", RC_TIMEOUT).timed_out)
        self.assertFalse(CompletedRun("", "", RC_TIMEOUT).not_found)
        self.assertTrue(CompletedRun("", "", RC_NOT_FOUND).not_found)
        self.assertFalse(CompletedRun("", "", RC_NOT_FOUND).timed_out)
        self.assertTrue(CompletedRun("", "", 0).ok)


if __name__ == "__main__":
    unittest.main()
