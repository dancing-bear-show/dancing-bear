"""Tests for telemetry.timeutil — format_latency and nano_to_datetime."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from telemetry.timeutil import format_latency, nano_to_datetime


class TestFormatLatencySubSecond(unittest.TestCase):
    def test_zero_ms_is_sub_second(self):
        self.assertEqual(format_latency(0), "0ms")

    def test_500ms(self):
        self.assertEqual(format_latency(500), "500ms")

    def test_999ms_stays_ms(self):
        self.assertEqual(format_latency(999), "999ms")

    def test_sub_second_fractional(self):
        # 999.4 rounds down to 999ms under :.0f
        self.assertEqual(format_latency(999.4), "999ms")


class TestFormatLatencySeconds(unittest.TestCase):
    def test_1000ms_becomes_1_point_0s(self):
        self.assertEqual(format_latency(1000), "1.0s")

    def test_1500ms_becomes_1_point_5s(self):
        self.assertEqual(format_latency(1500), "1.5s")

    def test_59999ms_stays_seconds(self):
        # 59999ms < 60000ms, stays in the seconds branch
        self.assertEqual(format_latency(59999), "60.0s")


class TestFormatLatencyExactMinutes(unittest.TestCase):
    def test_exact_one_minute_no_seconds(self):
        # 60000ms == exactly 1 minute, seconds == 0 -> "1m"
        self.assertEqual(format_latency(60_000), "1m")

    def test_exact_two_minutes_no_seconds(self):
        self.assertEqual(format_latency(120_000), "2m")

    def test_large_exact_minutes_no_seconds(self):
        # 3600 seconds = 60 minutes, seconds == 0
        self.assertEqual(format_latency(3_600_000), "60m")


class TestFormatLatencyMinutesAndSeconds(unittest.TestCase):
    def test_one_minute_thirty_seconds(self):
        self.assertEqual(format_latency(90_000), "1m 30s")

    def test_two_minutes_thirty_seconds(self):
        self.assertEqual(format_latency(150_000), "2m 30s")

    def test_ten_minutes_five_seconds(self):
        # 605000ms = 10m 5s
        self.assertEqual(format_latency(605_000), "10m 5s")

    def test_one_minute_one_second(self):
        self.assertEqual(format_latency(61_000), "1m 1s")


class TestNanoToDatetime(unittest.TestCase):
    def test_known_value(self):
        # 1_700_000_000_000_000_000 ns -> 2023-11-14T22:13:20Z
        result = nano_to_datetime(1_700_000_000_000_000_000)
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertEqual(result.year, 2023)
        self.assertEqual(result.month, 11)
        self.assertEqual(result.day, 14)

    def test_microsecond_precision(self):
        # 1500 ns -> microsecond = 1 (floor division 1500 // 1000)
        base_ns = 1_700_000_000_000_000_000
        result = nano_to_datetime(base_ns + 1500)
        self.assertEqual(result.microsecond, 1)

    def test_zero_nanoseconds_is_epoch(self):
        result = nano_to_datetime(0)
        self.assertEqual(result, datetime(1970, 1, 1, tzinfo=timezone.utc))
