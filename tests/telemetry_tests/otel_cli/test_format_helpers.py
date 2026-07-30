"""Tests for telemetry/otel/cli/_format_helpers.py."""

from __future__ import annotations

import argparse
import io
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from telemetry.otel.cli._format_helpers import (
    add_data_dir_argument,
    add_format_argument,
    add_since_argument,
    format_duration,
    format_timestamp,
    format_validation_error,
    resolve_data_dir,
    resolve_since,
    sort_sessions,
    truncate_sid,
)


# ---------------------------------------------------------------------------
# format_validation_error
# ---------------------------------------------------------------------------


class TestFormatValidationError(unittest.TestCase):
    def test_returns_2(self):
        buf = io.StringIO()
        with patch("sys.stderr", buf):
            result = format_validation_error("--since", "bad value")
        self.assertEqual(result, 2)

    def test_prints_to_stderr(self):
        buf = io.StringIO()
        with patch("sys.stderr", buf):
            format_validation_error("--since", "bad value")
        self.assertIn("--since", buf.getvalue())
        self.assertIn("bad value", buf.getvalue())


# ---------------------------------------------------------------------------
# add_format_argument
# ---------------------------------------------------------------------------


class TestAddFormatArgument(unittest.TestCase):
    def test_default_choices(self):
        parser = argparse.ArgumentParser()
        add_format_argument(parser)
        args = parser.parse_args([])
        self.assertEqual(args.format, "table")

    def test_custom_choices(self):
        parser = argparse.ArgumentParser()
        add_format_argument(parser, formats=["text", "json"], default="text")
        args = parser.parse_args([])
        self.assertEqual(args.format, "text")

    def test_json_choice_accepted(self):
        parser = argparse.ArgumentParser()
        add_format_argument(parser)
        args = parser.parse_args(["--format", "json"])
        self.assertEqual(args.format, "json")


# ---------------------------------------------------------------------------
# truncate_sid
# ---------------------------------------------------------------------------


class TestTruncateSid(unittest.TestCase):
    def test_short_sid_unchanged(self):
        self.assertEqual(truncate_sid("abc123"), "abc123")

    def test_long_sid_truncated(self):
        sid = "a" * 8 + "x" * 10 + "b" * 8
        result = truncate_sid(sid)
        self.assertEqual(len(result), 19)  # 8 + 3 + 8
        self.assertTrue(result.startswith("a" * 8))
        self.assertTrue(result.endswith("b" * 8))
        self.assertIn("...", result)

    def test_exactly_max_len_unchanged(self):
        sid = "x" * 20
        self.assertEqual(truncate_sid(sid), sid)


# ---------------------------------------------------------------------------
# add_data_dir_argument / add_since_argument
# ---------------------------------------------------------------------------


class TestAddArguments(unittest.TestCase):
    def test_add_data_dir_argument(self):
        parser = argparse.ArgumentParser()
        add_data_dir_argument(parser)
        args = parser.parse_args(["--data-dir", "/tmp/otel"])
        self.assertEqual(args.data_dir, "/tmp/otel")

    def test_add_since_argument(self):
        parser = argparse.ArgumentParser()
        add_since_argument(parser)
        args = parser.parse_args(["--since", "24h"])
        self.assertEqual(args.since, "24h")


# ---------------------------------------------------------------------------
# resolve_data_dir
# ---------------------------------------------------------------------------


class TestResolveDataDir(unittest.TestCase):
    def test_returns_none_when_allow_none_and_no_data_dir(self):
        args = argparse.Namespace(data_dir=None)
        result = resolve_data_dir(args, allow_none=True)
        self.assertIsNone(result)

    def test_returns_otelpdatadir_from_path(self):
        args = argparse.Namespace(data_dir="/tmp/otel")
        result = resolve_data_dir(args, allow_none=True)
        self.assertIsNotNone(result)

    def test_falls_back_to_from_env_when_no_data_dir(self):
        args = argparse.Namespace(data_dir=None)
        mock_dir = MagicMock()
        with patch("telemetry.otel.cli._format_helpers.OTLPDataDir.from_env", return_value=mock_dir):
            result = resolve_data_dir(args, allow_none=False)
        self.assertIs(result, mock_dir)


# ---------------------------------------------------------------------------
# resolve_since
# ---------------------------------------------------------------------------


class TestResolveSince(unittest.TestCase):
    def test_valid_since_returns_datetime_and_none(self):
        args = argparse.Namespace(since="24h")
        dt, err = resolve_since(args)
        self.assertIsNotNone(dt)
        self.assertIsNone(err)

    def test_none_since_returns_none_and_none(self):
        args = argparse.Namespace(since=None)
        dt, err = resolve_since(args)
        self.assertIsNone(dt)
        self.assertIsNone(err)

    def test_invalid_since_returns_none_and_error_code(self):
        args = argparse.Namespace(since="bad-value")
        dt, err = resolve_since(args)
        self.assertIsNone(dt)
        self.assertEqual(err, 2)


# ---------------------------------------------------------------------------
# format_timestamp
# ---------------------------------------------------------------------------


class TestFormatTimestamp(unittest.TestCase):
    def test_none_returns_unknown(self):
        self.assertEqual(format_timestamp(None), "unknown")

    def test_datetime_formatted(self):
        dt = datetime(2026, 4, 16, 10, 30, 0, tzinfo=timezone.utc)
        result = format_timestamp(dt)
        self.assertIn("2026-04-16", result)
        self.assertIn("10:30", result)


# ---------------------------------------------------------------------------
# format_duration
# ---------------------------------------------------------------------------


class TestFormatDuration(unittest.TestCase):
    def test_none_returns_empty(self):
        self.assertEqual(format_duration(None), "")

    def test_less_than_one_minute(self):
        self.assertEqual(format_duration(0.5), "<1m")

    def test_minutes_only(self):
        self.assertEqual(format_duration(45), "45m")

    def test_exact_hour(self):
        self.assertEqual(format_duration(60), "1h")

    def test_hours_and_minutes(self):
        self.assertEqual(format_duration(90), "1h30m")


# ---------------------------------------------------------------------------
# sort_sessions
# ---------------------------------------------------------------------------


class TestSortSessions(unittest.TestCase):
    def _make_session(self, cost=0.0, billable_tokens=0, perf=None, last_seen=None):
        s = MagicMock()
        s.cost = cost
        s.billable_tokens = billable_tokens
        s.perf = perf
        s.last_seen = last_seen
        s.first_seen = last_seen
        return s

    def test_sort_by_cost(self):
        sessions = [
            self._make_session(cost=0.5),
            self._make_session(cost=2.0),
            self._make_session(cost=0.1),
        ]
        result = sort_sessions(sessions, "cost")
        self.assertEqual(result[0].cost, 2.0)

    def test_sort_by_tokens(self):
        sessions = [
            self._make_session(billable_tokens=100),
            self._make_session(billable_tokens=1000),
        ]
        result = sort_sessions(sessions, "tokens")
        self.assertEqual(result[0].billable_tokens, 1000)

    def test_sort_by_errors(self):
        perf_a = MagicMock()
        perf_a.error_count = 5
        perf_a.tool_failures = 0
        perf_b = MagicMock()
        perf_b.error_count = 1
        perf_b.tool_failures = 0
        sessions = [
            self._make_session(perf=perf_b),
            self._make_session(perf=perf_a),
        ]
        result = sort_sessions(sessions, "errors")
        self.assertEqual(result[0].perf.error_count, 5)

    def test_sort_by_time_default(self):
        dt1 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        dt2 = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
        sessions = [
            self._make_session(last_seen=dt1),
            self._make_session(last_seen=dt2),
        ]
        result = sort_sessions(sessions, "time")
        self.assertEqual(result[0].last_seen, dt2)


if __name__ == "__main__":
    unittest.main()
