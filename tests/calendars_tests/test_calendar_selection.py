"""Tests for calendars/selection.py — compute_window and filter_events_by_day_time.

compute_window has no other coverage anywhere in this tree. filter_events_by_day_time
has narrow branch-coverage tests elsewhere (test_producer_outlook_branches.py,
test_producer_output_branches.py — both cover only the "no start_time" branch);
this file adds the combined day+time filter and timezone-offset cases.
"""
from __future__ import annotations

import unittest

from calendars.selection import compute_window, filter_events_by_day_time


class TestComputeWindow(unittest.TestCase):
    """Tests for compute_window function."""

    def test_from_range_start_date_and_until(self):
        ev = {"range": {"start_date": "2025-01-01", "until": "2025-02-01"}}
        start, end = compute_window(ev)
        self.assertEqual(start, "2025-01-01T00:00:00")
        self.assertEqual(end, "2025-02-01T23:59:59")

    def test_from_range_single_day(self):
        ev = {"range": {"start_date": "2025-01-15"}}
        start, end = compute_window(ev)
        self.assertEqual(start, "2025-01-15T00:00:00")
        self.assertEqual(end, "2025-01-15T23:59:59")

    def test_from_explicit_start_and_end(self):
        ev = {"start": "2025-01-06T17:00:00+00:00", "end": "2025-01-06T17:30:00+00:00"}
        start, end = compute_window(ev)
        self.assertEqual(start, "2025-01-06T17:00:00+00:00")
        self.assertEqual(end, "2025-01-06T17:30:00+00:00")


class TestFilterEventsByDayTime(unittest.TestCase):
    """Tests for filter_events_by_day_time function."""

    def test_filters_by_day_and_time_together(self):
        # Monday Jan 6, 2025 vs Tuesday Jan 7, 2025.
        evs = [
            {
                "start": {"dateTime": "2025-01-06T17:00:00+00:00"},
                "end": {"dateTime": "2025-01-06T17:30:00+00:00"},
            },
            {
                "start": {"dateTime": "2025-01-07T17:00:00+00:00"},
                "end": {"dateTime": "2025-01-07T17:30:00+00:00"},
            },
        ]
        matches = filter_events_by_day_time(evs, byday=["MO"], start_time="17:00", end_time="17:30")
        self.assertEqual(len(matches), 1)

    def test_filters_by_day_only(self):
        evs = [
            {"start": {"dateTime": "2025-01-06T10:00:00+00:00"}, "end": {"dateTime": "2025-01-06T11:00:00+00:00"}},
            {"start": {"dateTime": "2025-01-07T10:00:00+00:00"}, "end": {"dateTime": "2025-01-07T11:00:00+00:00"}},
        ]
        matches = filter_events_by_day_time(evs, byday=["MO"])
        self.assertEqual(len(matches), 1)

    def test_filters_by_time_only(self):
        evs = [
            {"start": {"dateTime": "2025-01-06T10:00:00+00:00"}, "end": {"dateTime": "2025-01-06T11:00:00+00:00"}},
            {"start": {"dateTime": "2025-01-07T10:00:00+00:00"}, "end": {"dateTime": "2025-01-07T11:00:00+00:00"}},
        ]
        matches = filter_events_by_day_time(evs, start_time="10:00", end_time="11:00")
        self.assertEqual(len(matches), 2)

    def test_matches_with_timezone_offset(self):
        evs = [
            {"start": {"dateTime": "2025-01-06T17:00:00-05:00"}, "end": {"dateTime": "2025-01-06T17:30:00-05:00"}},
        ]
        matches = filter_events_by_day_time(evs, start_time="17:00", end_time="17:30")
        self.assertEqual(len(matches), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
