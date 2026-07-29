"""Tests for telemetry.otel.utils — parse_time_window."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from telemetry.otel.utils import parse_time_window


class TestParseTimeWindowFalsy(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(parse_time_window(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(parse_time_window(""))


class TestParseTimeWindowValid(unittest.TestCase):
    def _frozen_now(self):
        return datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_one_hour_window(self):
        frozen = self._frozen_now()
        with mock.patch("telemetry.otel.utils.now_utc", return_value=frozen):
            result = parse_time_window("1h")
        self.assertEqual(result, frozen - timedelta(hours=1))

    def test_twenty_four_hour_window(self):
        frozen = self._frozen_now()
        with mock.patch("telemetry.otel.utils.now_utc", return_value=frozen):
            result = parse_time_window("24h")
        self.assertEqual(result, frozen - timedelta(hours=24))

    def test_seven_day_window(self):
        frozen = self._frozen_now()
        with mock.patch("telemetry.otel.utils.now_utc", return_value=frozen):
            result = parse_time_window("7d")
        self.assertEqual(result, frozen - timedelta(days=7))

    def test_plain_number_treated_as_minutes(self):
        # Plain number uses default_unit="minutes" in parse_window.
        frozen = self._frozen_now()
        with mock.patch("telemetry.otel.utils.now_utc", return_value=frozen):
            result = parse_time_window("30")
        self.assertIsInstance(result, datetime)
        self.assertIsNotNone(result)
        self.assertEqual(result, frozen - timedelta(minutes=30))

    def test_result_is_datetime(self):
        frozen = self._frozen_now()
        with mock.patch("telemetry.otel.utils.now_utc", return_value=frozen):
            result = parse_time_window("2h")
        self.assertIsInstance(result, datetime)


class TestParseTimeWindowInvalidFormat(unittest.TestCase):
    def test_garbage_string_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            parse_time_window("xyz")
        msg = str(ctx.exception)
        self.assertIn("xyz", msg)
        self.assertIn("Invalid --since format", msg)

    def test_invalid_format_error_message_includes_hint(self):
        with self.assertRaises(ValueError) as ctx:
            parse_time_window("???")
        msg = str(ctx.exception)
        self.assertIn("Use", msg)

    def test_invalid_format_chains_cause(self):
        with self.assertRaises(ValueError) as ctx:
            parse_time_window("notvalid!")
        self.assertIsNotNone(ctx.exception.__cause__)


class TestParseTimeWindowNegativeDuration(unittest.TestCase):
    def test_negative_timedelta_raises_value_error(self):
        negative_delta = timedelta(hours=-1)
        with mock.patch("telemetry.otel.utils.parse_window", return_value=negative_delta):
            with self.assertRaises(ValueError) as ctx:
                parse_time_window("1h")
        msg = str(ctx.exception)
        self.assertIn("Invalid --since format", msg)
        self.assertIn("1h", msg)

    def test_negative_duration_cause_is_chained(self):
        negative_delta = timedelta(hours=-5)
        with mock.patch("telemetry.otel.utils.parse_window", return_value=negative_delta):
            with self.assertRaises(ValueError) as ctx:
                parse_time_window("5h")
        # The inner ValueError("Duration cannot be negative") is chained as __cause__
        self.assertIsNotNone(ctx.exception.__cause__)
        self.assertIn("negative", str(ctx.exception.__cause__))


if __name__ == "__main__":
    unittest.main()
