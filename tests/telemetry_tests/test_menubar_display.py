"""Tests for telemetry/_menubar_display.py — display formatting helpers."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from telemetry._menubar_display import (
    _age_str,
    _model_short,
    _rate_str,
    _sparkline,
    _window_since_impl,
    _BLOCK_CHARS,
    _BLOCK_LEVELS,
)


class TestSparkline(unittest.TestCase):
    def test_empty_list_returns_no_activity(self) -> None:
        self.assertEqual(_sparkline([]), "  (no activity)")

    def test_all_zeroes_returns_no_activity(self) -> None:
        self.assertEqual(_sparkline([0.0, 0.0, 0.0]), "  (no activity)")

    def test_single_positive_value_returns_full_block(self) -> None:
        result = _sparkline([1.0])
        self.assertTrue(result.startswith("  "))
        self.assertEqual(len(result), 3)  # "  " + one block char
        # Single value at 100% should be highest level block
        self.assertEqual(result[2], _BLOCK_CHARS[_BLOCK_LEVELS])

    def test_prefix_is_two_spaces(self) -> None:
        result = _sparkline([1.0, 2.0, 3.0])
        self.assertTrue(result.startswith("  "))

    def test_length_equals_input_length_plus_two(self) -> None:
        data = [0.0, 1.0, 2.0, 3.0, 4.0]
        result = _sparkline(data)
        self.assertEqual(len(result), len(data) + 2)

    def test_zero_values_render_as_space(self) -> None:
        result = _sparkline([0.0, 5.0, 0.0])
        # index 2 of result is first char (after "  ")
        self.assertEqual(result[2], _BLOCK_CHARS[0])  # space for zero
        self.assertEqual(result[4], _BLOCK_CHARS[0])  # space for zero

    def test_peak_renders_as_highest_block(self) -> None:
        result = _sparkline([0.0, 100.0])
        self.assertEqual(result[3], _BLOCK_CHARS[_BLOCK_LEVELS])

    def test_mixed_values_ascending(self) -> None:
        result = _sparkline([1.0, 4.0, 8.0])
        # levels should be ascending (first char < last char ordinal)
        self.assertLessEqual(result[2], result[4])

    def test_negative_costs_treated_as_zero(self) -> None:
        # Negative values fall through the <= 0.0 check, so treated like zero
        result = _sparkline([-1.0, 5.0])
        self.assertEqual(result[2], _BLOCK_CHARS[0])

    def test_all_same_positive_value(self) -> None:
        result = _sparkline([3.0, 3.0, 3.0])
        # All at 100% of peak — each gets max level
        for ch in result[2:]:
            self.assertEqual(ch, _BLOCK_CHARS[_BLOCK_LEVELS])


class TestRateStr(unittest.TestCase):
    def test_basic_rate_no_flag(self) -> None:
        result = _rate_str(cost=1.0, window_secs=3600, avg_hourly=0.5)
        self.assertIn("Rate: $1.00/hr", result)
        self.assertIn("avg $0.50/hr", result)
        self.assertNotIn("!", result)

    def test_high_rate_adds_flag(self) -> None:
        # current_rate = 4/hr, avg = 1/hr -> 4 > 2*1 -> flag
        result = _rate_str(cost=4.0, window_secs=3600, avg_hourly=1.0)
        self.assertIn("!", result)

    def test_no_flag_when_avg_is_zero(self) -> None:
        result = _rate_str(cost=100.0, window_secs=3600, avg_hourly=0.0)
        self.assertNotIn("!", result)

    def test_window_secs_zero_treated_as_one(self) -> None:
        # max(window_secs, 1) prevents division by zero
        result = _rate_str(cost=1.0, window_secs=0, avg_hourly=0.0)
        self.assertIn("Rate:", result)

    def test_half_hour_window_doubles_rate(self) -> None:
        # cost=2.0 over 1800s (0.5h) -> rate = 4/hr
        result = _rate_str(cost=2.0, window_secs=1800, avg_hourly=0.0)
        self.assertIn("$4.00/hr", result)


class TestModelShort(unittest.TestCase):
    def test_strips_claude_prefix(self) -> None:
        self.assertEqual(_model_short("claude-sonnet-4"), "sonnet-4")

    def test_no_prefix_unchanged(self) -> None:
        self.assertEqual(_model_short("gpt-4"), "gpt-4")

    def test_truncated_to_18_chars(self) -> None:
        long_name = "claude-" + "a" * 30
        result = _model_short(long_name)
        self.assertEqual(len(result), 18)

    def test_empty_string(self) -> None:
        self.assertEqual(_model_short(""), "")

    def test_exact_18_chars_after_strip(self) -> None:
        name = "claude-" + "b" * 18
        result = _model_short(name)
        self.assertEqual(len(result), 18)


class TestWindowSinceImpl(unittest.TestCase):
    def test_with_seconds_returns_past_datetime(self) -> None:
        result = _window_since_impl(3600)
        self.assertIsInstance(result, datetime)
        self.assertIsNotNone(result.tzinfo)
        now = datetime.now(timezone.utc)
        diff = now - result
        # Should be approximately 3600 seconds ago
        self.assertGreater(diff.total_seconds(), 3500)
        self.assertLess(diff.total_seconds(), 3700)

    def test_none_returns_local_midnight_utc(self) -> None:
        result = _window_since_impl(None)
        self.assertIsInstance(result, datetime)
        self.assertIsNotNone(result.tzinfo)
        # Result should be at midnight (hour=0, minute=0, second=0)
        # Converting to local tz first
        local_result = result.astimezone()
        self.assertEqual(local_result.hour, 0)
        self.assertEqual(local_result.minute, 0)
        self.assertEqual(local_result.second, 0)

    def test_with_zero_seconds_is_approximately_now(self) -> None:
        result = _window_since_impl(0)
        now = datetime.now(timezone.utc)
        diff = abs((now - result).total_seconds())
        self.assertLess(diff, 2)


class TestAgeStr(unittest.TestCase):
    def test_minutes_format_for_under_one_hour(self) -> None:
        self.assertEqual(_age_str(600), "10m ago")

    def test_zero_seconds(self) -> None:
        self.assertEqual(_age_str(0), "0m ago")

    def test_59_minutes(self) -> None:
        self.assertEqual(_age_str(3599), "59m ago")

    def test_one_hour_uses_hours_format(self) -> None:
        self.assertEqual(_age_str(3600), "1.0h ago")

    def test_two_hours(self) -> None:
        self.assertEqual(_age_str(7200), "2.0h ago")

    def test_fractional_hours(self) -> None:
        # 5400s = 1.5h
        self.assertEqual(_age_str(5400), "1.5h ago")


if __name__ == "__main__":
    unittest.main()
