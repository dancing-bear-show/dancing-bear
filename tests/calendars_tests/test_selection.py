"""Tests for calendars/selection.py event filtering helpers."""
import datetime as _dt
import unittest

from calendars.selection import (
    compute_window,
    filter_events_by_day_time,
    _weekday_code,
    _local_time_hhmm,
    _event_matches_criteria,
)
from tests.builders import EventBuilder


class TestComputeWindow(unittest.TestCase):
    """Tests for compute_window function."""

    def test_compute_window_with_start_and_end(self):
        """compute_window should use start/end when both present."""
        event = {
            "start": "2025-01-06T17:00:00",
            "end": "2025-01-06T17:30:00",
        }
        result = compute_window(event)
        self.assertEqual(result, ("2025-01-06T17:00:00", "2025-01-06T17:30:00"))

    def test_compute_window_with_range_start_and_until(self):
        """compute_window should use range start_date and until."""
        event = {
            "range": {
                "start_date": "2025-01-01",
                "until": "2025-03-01",
            }
        }
        result = compute_window(event)
        self.assertEqual(result, ("2025-01-01T00:00:00", "2025-03-01T23:59:59"))

    def test_compute_window_with_only_start_date(self):
        """compute_window should handle only start_date in range."""
        event = {
            "range": {
                "start_date": "2025-01-15",
            }
        }
        result = compute_window(event)
        self.assertEqual(result, ("2025-01-15T00:00:00", "2025-01-15T23:59:59"))

    def test_compute_window_returns_none_for_empty_event(self):
        """compute_window should return None for empty event."""
        result = compute_window({})
        self.assertIsNone(result)

    def test_compute_window_returns_none_for_partial_data(self):
        """compute_window should return None when data is incomplete."""
        event = {"start": "2025-01-01T10:00:00"}  # Missing end
        result = compute_window(event)
        self.assertIsNone(result)


class TestWeekdayCode(unittest.TestCase):
    """Tests for _weekday_code helper."""

    def test_weekday_code_monday(self):
        """_weekday_code should return MO for Monday."""
        dt = _dt.datetime(2025, 1, 6)  # Monday
        self.assertEqual(_weekday_code(dt), "MO")

    def test_weekday_code_sunday(self):
        """_weekday_code should return SU for Sunday."""
        dt = _dt.datetime(2025, 1, 5)  # Sunday
        self.assertEqual(_weekday_code(dt), "SU")

    def test_weekday_code_friday(self):
        """_weekday_code should return FR for Friday."""
        dt = _dt.datetime(2025, 1, 10)  # Friday
        self.assertEqual(_weekday_code(dt), "FR")


class TestLocalTimeHHMM(unittest.TestCase):
    """Tests for _local_time_hhmm helper."""

    def test_local_time_hhmm_with_valid_iso(self):
        """_local_time_hhmm should extract HH:MM from ISO datetime."""
        result = _local_time_hhmm("2025-01-06T17:30:00")
        self.assertEqual(result, "17:30")

    def test_local_time_hhmm_with_z_suffix(self):
        """_local_time_hhmm should handle Z suffix."""
        result = _local_time_hhmm("2025-01-06T17:30:00Z")
        self.assertEqual(result, "17:30")

    def test_local_time_hhmm_with_offset(self):
        """_local_time_hhmm should handle timezone offset."""
        result = _local_time_hhmm("2025-01-06T17:30:00+05:00")
        self.assertEqual(result, "17:30")

    def test_local_time_hhmm_fallback_on_invalid(self):
        """_local_time_hhmm should fallback to string slicing on parse error."""
        # Invalid ISO format - should fallback to slicing
        result = _local_time_hhmm("2025-01-06T17:30:invalid")
        self.assertEqual(result, "17:30")

    def test_local_time_hhmm_returns_empty_for_no_time_part(self):
        """_local_time_hhmm should parse date-only strings as midnight."""
        # Date-only strings parse as datetime with time 00:00:00
        result = _local_time_hhmm("2025-01-06")
        self.assertEqual(result, "00:00")


class TestEventMatchesCriteria(unittest.TestCase):
    """Tests for _event_matches_criteria helper."""

    def test_event_matches_criteria_day_match(self):
        """_event_matches_criteria should match events by weekday."""
        event = (
            EventBuilder()
            .start("2025-01-06T17:00:00")  # Monday
            .end("2025-01-06T17:30:00")
            .build()
        )
        result = _event_matches_criteria(event, {"mo"}, None, None)
        self.assertTrue(result)

    def test_event_matches_criteria_day_mismatch(self):
        """_event_matches_criteria should reject events on wrong weekday."""
        event = (
            EventBuilder()
            .start("2025-01-06T17:00:00")  # Monday
            .end("2025-01-06T17:30:00")
            .build()
        )
        result = _event_matches_criteria(event, {"tu"}, None, None)
        self.assertFalse(result)

    def test_event_matches_criteria_start_time_match(self):
        """_event_matches_criteria should match events by start time."""
        event = (
            EventBuilder()
            .start("2025-01-06T17:00:00")
            .end("2025-01-06T17:30:00")
            .build()
        )
        result = _event_matches_criteria(event, set(), "17:00", None)
        self.assertTrue(result)

    def test_event_matches_criteria_start_time_mismatch(self):
        """_event_matches_criteria should reject events with wrong start time."""
        event = (
            EventBuilder()
            .start("2025-01-06T17:00:00")
            .end("2025-01-06T17:30:00")
            .build()
        )
        result = _event_matches_criteria(event, set(), "18:00", None)
        self.assertFalse(result)

    def test_event_matches_criteria_end_time_match(self):
        """_event_matches_criteria should match events by end time."""
        event = (
            EventBuilder()
            .start("2025-01-06T17:00:00")
            .end("2025-01-06T17:30:00")
            .build()
        )
        result = _event_matches_criteria(event, set(), None, "17:30")
        self.assertTrue(result)

    def test_event_matches_criteria_returns_false_for_missing_start(self):
        """_event_matches_criteria should return False when start is missing."""
        event = {"end": {"dateTime": "2025-01-06T17:30:00"}}
        result = _event_matches_criteria(event, set(), None, None)
        self.assertFalse(result)


class TestFilterEventsByDayTime(unittest.TestCase):
    """Tests for filter_events_by_day_time function."""

    def test_filter_events_by_day(self):
        """filter_events_by_day_time should filter by weekday."""
        events = [
            EventBuilder().start("2025-01-06T17:00:00").end("2025-01-06T17:30:00").build(),  # Monday
            EventBuilder().start("2025-01-07T17:00:00").end("2025-01-07T17:30:00").build(),  # Tuesday
            EventBuilder().start("2025-01-08T17:00:00").end("2025-01-08T17:30:00").build(),  # Wednesday
        ]
        result = filter_events_by_day_time(events, byday=["MO", "WE"])
        self.assertEqual(len(result), 2)

    def test_filter_events_by_start_time(self):
        """filter_events_by_day_time should filter by start time."""
        events = [
            EventBuilder().start("2025-01-06T17:00:00").end("2025-01-06T17:30:00").build(),
            EventBuilder().start("2025-01-06T18:00:00").end("2025-01-06T18:30:00").build(),
        ]
        result = filter_events_by_day_time(events, start_time="17:00")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["start"]["dateTime"], "2025-01-06T17:00:00")

    def test_filter_events_by_end_time(self):
        """filter_events_by_day_time should filter by end time."""
        events = [
            EventBuilder().start("2025-01-06T17:00:00").end("2025-01-06T17:30:00").build(),
            EventBuilder().start("2025-01-06T17:00:00").end("2025-01-06T18:00:00").build(),
        ]
        result = filter_events_by_day_time(events, end_time="17:30")
        self.assertEqual(len(result), 1)

    def test_filter_events_returns_all_when_no_criteria(self):
        """filter_events_by_day_time should return all events when no criteria."""
        events = [
            EventBuilder().start("2025-01-06T17:00:00").end("2025-01-06T17:30:00").build(),
            EventBuilder().start("2025-01-07T18:00:00").end("2025-01-07T18:30:00").build(),
        ]
        result = filter_events_by_day_time(events)
        self.assertEqual(len(result), 2)

    def test_filter_events_combines_day_and_time_criteria(self):
        """filter_events_by_day_time should combine day and time filters."""
        events = [
            EventBuilder().start("2025-01-06T17:00:00").end("2025-01-06T17:30:00").build(),  # Monday 17:00
            EventBuilder().start("2025-01-06T18:00:00").end("2025-01-06T18:30:00").build(),  # Monday 18:00
            EventBuilder().start("2025-01-07T17:00:00").end("2025-01-07T17:30:00").build(),  # Tuesday 17:00
        ]
        result = filter_events_by_day_time(events, byday=["MO"], start_time="17:00")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["start"]["dateTime"], "2025-01-06T17:00:00")
