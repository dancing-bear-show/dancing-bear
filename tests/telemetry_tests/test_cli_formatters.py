"""Tests for telemetry/cli_formatters.py — pure formatting helpers."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

import click

from telemetry.cli import (
    _fmt_duration,
    _fmt_tokens,
    _parse_since_cli,
    _truncate_id,
)

from tests.telemetry_tests.shared_fixtures import _make_session_summary


# ---------------------------------------------------------------------------
# _fmt_tokens
# ---------------------------------------------------------------------------

class TestFmtTokens(unittest.TestCase):
    def test_small(self):
        self.assertEqual(_fmt_tokens(500), "500")

    def test_thousands(self):
        self.assertEqual(_fmt_tokens(1500), "2K")

    def test_millions(self):
        self.assertEqual(_fmt_tokens(2_500_000), "2.5M")

    def test_exactly_one_thousand(self):
        self.assertEqual(_fmt_tokens(1000), "1K")

    def test_just_under_one_thousand(self):
        self.assertEqual(_fmt_tokens(999), "999")

    def test_just_under_rounding_boundary(self):
        self.assertEqual(_fmt_tokens(1499), "1K")

    def test_rounding_boundary_rounds_up(self):
        self.assertEqual(_fmt_tokens(1500), "2K")

    def test_half_boundary_at_2500_uses_banker_rounding(self):
        # Python's f"{x:.0f}" uses round-half-to-even: 2.5 -> 2, not 3.
        self.assertEqual(_fmt_tokens(2500), "2K")

    def test_last_value_that_still_renders_as_k(self):
        self.assertEqual(_fmt_tokens(999_499), "999K")

    def test_rounds_over_to_m_rather_than_four_k_digits(self):
        # 999_500 rounds to 1000K, which must roll over to 1.0M — the M
        # threshold is checked after rounding so no four-digit K value exists.
        for value in (999_500, 999_999):
            with self.subTest(value=value):
                self.assertEqual(_fmt_tokens(value), "1.0M")


# ---------------------------------------------------------------------------
# _fmt_duration
# ---------------------------------------------------------------------------

class TestFmtDuration(unittest.TestCase):
    def test_minutes_only(self):
        s = _make_session_summary()
        result = _fmt_duration(s)
        self.assertEqual(result, "30m")

    def test_hours_and_minutes(self):
        start = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 16, 11, 15, 0, tzinfo=timezone.utc)
        s = _make_session_summary()
        s.start_time = start
        s.end_time = end
        result = _fmt_duration(s)
        self.assertEqual(result, "1h15m")

    def test_none_end_time(self):
        s = _make_session_summary()
        s.end_time = None
        result = _fmt_duration(s)
        self.assertEqual(result, "—")

    def test_non_session_object_returns_dash(self):
        result = _fmt_duration("not a session")
        self.assertEqual(result, "—")


# ---------------------------------------------------------------------------
# _truncate_id
# ---------------------------------------------------------------------------

class TestTruncateId(unittest.TestCase):
    def test_short_id_unchanged(self):
        self.assertEqual(_truncate_id("abc"), "abc")

    def test_long_id_truncated(self):
        result = _truncate_id("a" * 20)
        self.assertLessEqual(len(result), 16)
        self.assertIn("…", result)


# ---------------------------------------------------------------------------
# _parse_since_cli
# ---------------------------------------------------------------------------

class TestParseSinceCli(unittest.TestCase):
    def test_valid_window_string(self):
        result = _parse_since_cli("7d")
        self.assertIsInstance(result, datetime)
        now = datetime.now(tz=timezone.utc)
        diff = now - result
        self.assertAlmostEqual(diff.days, 7, delta=1)

    def test_bare_integer_raises_bad_parameter(self):
        with self.assertRaises(click.BadParameter):
            _parse_since_cli("7")

    def test_invalid_window_string_raises_bad_parameter(self):
        with self.assertRaises(click.BadParameter):
            _parse_since_cli("notawindow")


if __name__ == "__main__":
    unittest.main()
