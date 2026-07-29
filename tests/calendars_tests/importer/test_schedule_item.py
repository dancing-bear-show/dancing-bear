"""Tests for ScheduleItem dataclass."""

import unittest

from calendars.importer import ScheduleItem


class TestScheduleItem(unittest.TestCase):
    """Tests for ScheduleItem dataclass."""

    def test_schedule_item_defaults(self):
        item = ScheduleItem(subject="Test Event")
        self.assertEqual(item.subject, "Test Event")
        self.assertIsNone(item.start_iso)
        self.assertIsNone(item.end_iso)
        self.assertIsNone(item.recurrence)
        self.assertIsNone(item.byday)
        self.assertIsNone(item.location)

    def test_schedule_item_with_recurrence(self):
        item = ScheduleItem(
            subject="Weekly Meeting",
            recurrence="weekly",
            byday=["MO", "WE", "FR"],
            start_time="09:00",
            end_time="10:00",
            range_start="2025-01-01",
            range_until="2025-12-31",
        )
        self.assertEqual(item.recurrence, "weekly")
        self.assertEqual(item.byday, ["MO", "WE", "FR"])
        self.assertEqual(item.start_time, "09:00")
        self.assertEqual(item.end_time, "10:00")

    def test_schedule_item_with_one_off(self):
        item = ScheduleItem(
            subject="One-time Event",
            start_iso="2025-03-15T14:00",
            end_iso="2025-03-15T15:30",
            location="Conference Room A",
        )
        self.assertEqual(item.start_iso, "2025-03-15T14:00")
        self.assertEqual(item.end_iso, "2025-03-15T15:30")
        self.assertEqual(item.location, "Conference Room A")


if __name__ == "__main__":
    unittest.main()
