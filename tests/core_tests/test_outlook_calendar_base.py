"""Tests for Outlook calendar base helpers: unique tests not covered by test_core_outlook_calendar.py."""
from __future__ import annotations

import unittest

from core.outlook.calendar import OutlookCalendarMixin


class TestApplyReminder(unittest.TestCase):
    """Tests for _apply_reminder static method."""

    def test_apply_reminder_non_numeric_minutes_raises_value_error(self):
        payload = {}
        with self.assertRaises(ValueError):
            OutlookCalendarMixin._apply_reminder(payload, no_reminder=False, reminder_minutes="soon")


class TestBuildRecurrenceRange(unittest.TestCase):
    """Tests for _build_recurrence_range static method."""

    def test_build_recurrence_range_non_numeric_count_raises_value_error(self):
        with self.assertRaises(ValueError):
            OutlookCalendarMixin._build_recurrence_range("2025-01-01", None, "many")


if __name__ == "__main__":
    unittest.main()
