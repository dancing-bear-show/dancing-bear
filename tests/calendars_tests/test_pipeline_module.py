"""Tests for calendars.pipeline_base.load_schedule_sources."""
import unittest
from unittest.mock import patch


class TestLoadScheduleSources(unittest.TestCase):
    """Tests for calendars.pipeline_base.load_schedule_sources."""

    def test_empty_sources(self):
        from calendars.pipeline_base import load_schedule_sources
        result = load_schedule_sources([], kind="auto")
        self.assertEqual(result, [])

    def test_single_source_normalizes_events(self):
        from calendars.pipeline_base import load_schedule_sources
        from calendars.importer.model import ScheduleItem

        fake_item = ScheduleItem(
            subject="Swim Class",
            start_iso="2025-01-10T17:00",
            end_iso="2025-01-10T18:00",
        )

        # load_schedule_sources does `from calendars.importer import load_schedule` inside
        with patch("calendars.importer.load_schedule", return_value=[fake_item]) as mock_load:
            results = load_schedule_sources(["schedule.csv"], kind="csv")

        mock_load.assert_called_once_with("schedule.csv", "csv")
        self.assertEqual(len(results), 1)
        # normalize_event should have returned a dict
        self.assertIsInstance(results[0], dict)
        self.assertEqual(results[0].get("subject"), "Swim Class")

    def test_multiple_sources_combined(self):
        from calendars.pipeline_base import load_schedule_sources
        from calendars.importer.model import ScheduleItem

        items_a = [ScheduleItem(subject="Event A", start_iso="2025-01-01T10:00", end_iso="2025-01-01T11:00")]
        items_b = [ScheduleItem(subject="Event B", start_iso="2025-01-02T10:00", end_iso="2025-01-02T11:00")]

        with patch("calendars.importer.load_schedule", side_effect=[items_a, items_b]):
            results = load_schedule_sources(["a.csv", "b.csv"], kind="csv")

        self.assertEqual(len(results), 2)
        subjects = {r.get("subject") for r in results}
        self.assertIn("Event A", subjects)
        self.assertIn("Event B", subjects)

    def test_items_with_none_fields_handled(self):
        """Items with no start/end produce dicts without erroring."""
        from calendars.pipeline_base import load_schedule_sources
        from calendars.importer.model import ScheduleItem

        item = ScheduleItem(subject="Recurring Class")
        with patch("calendars.importer.load_schedule", return_value=[item]):
            results = load_schedule_sources(["sched.csv"], kind="csv")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].get("subject"), "Recurring Class")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
