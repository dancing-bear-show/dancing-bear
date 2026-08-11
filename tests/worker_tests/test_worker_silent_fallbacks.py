"""Sad-path tests for worker error branches that swallow failures silently.

Each branch covered here catches an exception and returns a default instead of
surfacing it. That is deliberate (these are best-effort paths), but it means a
regression inside them is invisible: no exception, no log a user would see,
just a subtly wrong result. These tests pin the intended behaviour so the
silence stays intentional rather than becoming a hiding place.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path


class TestParseTimestampSafeFormats(unittest.TestCase):
    """_parse_timestamp_safe returns None on bad input -- but must not treat a
    VALID non-'Z' timestamp as bad. Existing tests only covered 'Z' and
    obviously-invalid input, so a parser narrowing would slip through.
    """

    def _parse(self, value: str):
        from worker.queue import _parse_timestamp_safe
        return _parse_timestamp_safe(value, Path("/tmp/x.json"), "updated_at")  # nosec B108 - test only

    def test_explicit_utc_offset_parses(self):
        result = self._parse("2025-01-01T00:00:00+00:00")
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2025)

    def test_fractional_seconds_parses(self):
        result = self._parse("2025-01-01T00:00:00.500Z")
        self.assertIsNotNone(result)
        self.assertEqual(result.microsecond, 500000)

    def test_surrounding_whitespace_parses(self):
        self.assertIsNotNone(self._parse(" 2025-01-01T00:00:00Z "))

    def test_offset_and_z_agree(self):
        self.assertEqual(
            self._parse("2025-01-01T00:00:00+00:00"),
            self._parse("2025-01-01T00:00:00Z"),
        )

    def test_whitespace_only_returns_none(self):
        self.assertIsNone(self._parse("   "))


class TestThroughputMalformedLogLines(unittest.TestCase):
    """commands.py skips malformed JSONL lines (`except Exception: continue`).

    A malformed line must not abort the whole throughput calculation -- the
    valid lines around it should still be counted.
    """

    def setUp(self):
        import os
        from worker._helpers import DATE_FORMAT_YMD

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # _calculate_throughput derives its path from cwd + today's date.
        self._orig_cwd = os.getcwd()
        self.addCleanup(os.chdir, self._orig_cwd)
        os.chdir(self.tmp.name)

        # setUp and _calculate_throughput each call datetime.now(UTC)
        # independently, so a UTC midnight rollover between them would point
        # at different filenames and flake. Write both days' names; the method
        # reads whichever one it computes.
        logs_dir = Path(self.tmp.name) / "_data" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC)
        self._logs = [
            logs_dir / f"perf-worker-{(now + timedelta(days=d)).strftime(DATE_FORMAT_YMD)}.jsonl"
            for d in (0, 1)
        ]
        self.log = self._logs[0]

    def _write_lines(self, lines: list[str]) -> None:
        body = "\n".join(lines) + "\n"
        for path in self._logs:
            path.write_text(body, encoding="utf-8")

    def _ok_line(self, ts: str, duration_ms: int = 100) -> str:
        return json.dumps({
            "ts": ts,
            "args": ["daemon", "run_cli", "ok"],
            "duration_ms": duration_ms,
        })

    def _throughput(self):
        from worker.commands import StatusCommand
        return StatusCommand._calculate_throughput()

    def test_malformed_line_between_valid_ones_is_skipped(self):
        start = datetime.now(UTC) - timedelta(minutes=5)
        self._write_lines([
            self._ok_line(start.strftime("%Y-%m-%dT%H:%M:%SZ")),
            "{not valid json",
            "",
            self._ok_line((start + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ])
        result = self._throughput()
        self.assertIsNotNone(result)
        self.assertIn("Throughput", result)

    def test_all_lines_malformed_returns_none(self):
        self._write_lines(["{bad", "also bad", "[]"])
        self.assertIsNone(self._throughput())

    def test_no_matching_rows_returns_none(self):
        """Lines that parse but do not match the run_cli filter yield nothing."""
        self._write_lines([json.dumps({"ts": "2025-01-01T00:00:00Z", "args": ["other"]})])
        self.assertIsNone(self._throughput())

    def test_missing_file_returns_none(self):
        for path in self._logs:
            path.unlink(missing_ok=True)
        self.assertIsNone(self._throughput())


if __name__ == "__main__":
    unittest.main()
