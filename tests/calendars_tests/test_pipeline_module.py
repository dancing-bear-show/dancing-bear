"""Tests for calendars/pipeline.py — re-export completeness and _load_schedule_sources."""
import unittest
from unittest.mock import MagicMock, patch


class TestPipelineReExports(unittest.TestCase):
    """Verify all expected names are importable from calendars.pipeline."""

    def test_base_utilities_importable(self):
        from calendars.pipeline import (
            GmailAuth,
            GmailServiceBuilder,
            DateWindowResolver,
            BaseProducer,
            RequestConsumer,
            to_iso_str,
            dedupe_events,
            parse_month,
            MONTH_MAP,
            DAY_MAP,
        )
        self.assertIsNotNone(GmailAuth)
        self.assertIsNotNone(DateWindowResolver)
        self.assertIsNotNone(dedupe_events)
        self.assertIsNotNone(MONTH_MAP)
        self.assertIsNotNone(DAY_MAP)

    def test_gmail_pipeline_names_importable(self):
        from calendars.pipeline import (
            GmailReceiptsRequest,
            GmailReceiptsProcessor,
            GmailPlanProducer,
            GmailScanClassesRequest,
            GmailScanClassesProcessor,
            GmailScanClassesProducer,
            GmailMailListRequest,
            GmailMailListProcessor,
            GmailMailListProducer,
            GmailSweepTopRequest,
            GmailSweepTopProcessor,
            GmailSweepTopProducer,
        )
        for cls in [
            GmailReceiptsRequest, GmailReceiptsProcessor, GmailPlanProducer,
            GmailScanClassesRequest, GmailScanClassesProcessor, GmailScanClassesProducer,
            GmailMailListRequest, GmailMailListProcessor, GmailMailListProducer,
            GmailSweepTopRequest, GmailSweepTopProcessor, GmailSweepTopProducer,
        ]:
            self.assertIsNotNone(cls)

    def test_outlook_pipeline_names_importable(self):
        from calendars.pipeline import (
            OutlookVerifyRequest,
            OutlookAddRequest,
            OutlookScheduleImportRequest,
            OutlookListOneOffsRequest,
            OutlookCalendarShareRequest,
            OutlookAddEventRequest,
            OutlookAddRecurringRequest,
            OutlookLocationsRequest,
            OutlookRemoveRequest,
            OutlookRemindersRequest,
            OutlookSettingsRequest,
            OutlookDedupRequest,
            OutlookMailListRequest,
        )
        for cls in [
            OutlookVerifyRequest, OutlookAddRequest, OutlookScheduleImportRequest,
            OutlookListOneOffsRequest, OutlookCalendarShareRequest,
            OutlookAddEventRequest, OutlookAddRecurringRequest,
            OutlookLocationsRequest, OutlookRemoveRequest,
            OutlookRemindersRequest, OutlookSettingsRequest,
            OutlookDedupRequest, OutlookMailListRequest,
        ]:
            self.assertIsNotNone(cls)

    def test_load_schedule_sources_in_all(self):
        from calendars.pipeline import __all__
        self.assertIn("_load_schedule_sources", __all__)


class TestLoadScheduleSources(unittest.TestCase):
    """Tests for calendars.pipeline._load_schedule_sources."""

    def test_empty_sources(self):
        from calendars.pipeline import _load_schedule_sources
        result = _load_schedule_sources([], kind="auto")
        self.assertEqual(result, [])

    def test_single_source_normalizes_events(self):
        from calendars.pipeline import _load_schedule_sources
        from calendars.importer.model import ScheduleItem

        fake_item = ScheduleItem(
            subject="Swim Class",
            start_iso="2025-01-10T17:00",
            end_iso="2025-01-10T18:00",
        )

        # _load_schedule_sources does `from calendars.importer import load_schedule` inside
        with patch("calendars.importer.load_schedule", return_value=[fake_item]) as mock_load:
            results = _load_schedule_sources(["schedule.csv"], kind="csv")

        mock_load.assert_called_once_with("schedule.csv", "csv")
        self.assertEqual(len(results), 1)
        # normalize_event should have returned a dict
        self.assertIsInstance(results[0], dict)
        self.assertEqual(results[0].get("subject"), "Swim Class")

    def test_multiple_sources_combined(self):
        from calendars.pipeline import _load_schedule_sources
        from calendars.importer.model import ScheduleItem

        items_a = [ScheduleItem(subject="Event A", start_iso="2025-01-01T10:00", end_iso="2025-01-01T11:00")]
        items_b = [ScheduleItem(subject="Event B", start_iso="2025-01-02T10:00", end_iso="2025-01-02T11:00")]

        with patch("calendars.importer.load_schedule", side_effect=[items_a, items_b]):
            results = _load_schedule_sources(["a.csv", "b.csv"], kind="csv")

        self.assertEqual(len(results), 2)
        subjects = {r.get("subject") for r in results}
        self.assertIn("Event A", subjects)
        self.assertIn("Event B", subjects)

    def test_items_with_none_fields_handled(self):
        """Items with no start/end produce dicts without erroring."""
        from calendars.pipeline import _load_schedule_sources
        from calendars.importer.model import ScheduleItem

        item = ScheduleItem(subject="Recurring Class")
        with patch("calendars.importer.load_schedule", return_value=[item]):
            results = _load_schedule_sources(["sched.csv"], kind="csv")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].get("subject"), "Recurring Class")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
