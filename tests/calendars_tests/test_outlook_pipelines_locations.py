"""Unit tests for calendars/outlook_pipelines/locations.py."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest import TestCase, main as unittest_main
from unittest.mock import MagicMock, patch

from calendars.outlook_pipelines._base import ERR_CODE_CALENDAR
from calendars.outlook_pipelines.locations import (
    OutlookLocationsEnrichRequest,
    OutlookLocationsEnrichResult,
    OutlookLocationsEnrichProcessor,
    OutlookLocationsEnrichProducer,
    OutlookLocationsRequest,
    OutlookLocationsResult,
    OutlookLocationsUpdateProcessor,
    OutlookLocationsApplyProcessor,
    OutlookLocationsProducer,
)


# =============================================================================
# OutlookLocationsEnrichProcessor Tests
# =============================================================================


class TestOutlookLocationsEnrichProcessor(TestCase):
    """Tests for OutlookLocationsEnrichProcessor."""

    def _make_processor(self, today_factory=None, enricher=None):
        return OutlookLocationsEnrichProcessor(today_factory=today_factory, enricher=enricher)

    def _make_request(self, service="DEFAULT", calendar="Test", from_date=None, to_date=None, dry_run=False):
        svc = MagicMock() if service == "DEFAULT" else service
        return OutlookLocationsEnrichRequest(
            service=svc,
            calendar=calendar,
            from_date=from_date,
            to_date=to_date,
            dry_run=dry_run,
        )

    def test_returns_error_when_service_none(self):
        proc = self._make_processor()
        req = self._make_request(service=None)
        result = proc.process(req)
        self.assertEqual(result.status, "error")

    def test_returns_error_when_calendar_not_found(self):
        proc = self._make_processor()
        svc = MagicMock()
        svc.find_calendar_id.return_value = None
        req = self._make_request(service=svc, calendar="NonExistent")
        result = proc.process(req)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.diagnostics["code"], ERR_CODE_CALENDAR)
        self.assertIn("NonExistent", result.diagnostics["message"])

    def test_returns_error_on_list_events_exception(self):
        proc = self._make_processor()
        svc = MagicMock()
        svc.find_calendar_id.return_value = "cal-123"
        svc.list_events_in_range.side_effect = RuntimeError("API failure")
        req = self._make_request(service=svc)
        result = proc.process(req)
        self.assertEqual(result.status, "error")
        self.assertIn("API failure", result.diagnostics["message"])

    def test_returns_success_with_zero_updated_when_no_matching_series(self):
        proc = self._make_processor()
        svc = MagicMock()
        svc.find_calendar_id.return_value = "cal-123"
        svc.list_events_in_range.return_value = [
            {"id": "e1", "subject": "Meeting"},
            {"id": "e2", "subject": "Call"},
        ]
        req = self._make_request(service=svc)
        result = proc.process(req)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.payload.updated, 0)

    def test_matches_public_skating_events(self):
        proc = self._make_processor(enricher=lambda loc: f"{loc} (enriched)")
        svc = MagicMock()
        svc.find_calendar_id.return_value = "cal-123"
        svc.list_events_in_range.return_value = [
            {"id": "e1", "subject": "Public Skating", "location": {"displayName": "Rink"}},
        ]
        req = self._make_request(service=svc, dry_run=False)
        result = proc.process(req)
        self.assertEqual(result.status, "success")
        svc.update_event_location.assert_called()

    def test_matches_leisure_swim_events(self):
        proc = self._make_processor(enricher=lambda loc: f"{loc} (enriched)")
        svc = MagicMock()
        svc.find_calendar_id.return_value = "cal-123"
        svc.list_events_in_range.return_value = [
            {"id": "e1", "subject": "Leisure Swim", "location": {"displayName": "Pool"}},
        ]
        req = self._make_request(service=svc, dry_run=False)
        result = proc.process(req)
        self.assertEqual(result.status, "success")
        svc.update_event_location.assert_called()

    def test_matches_fun_n_fit_events(self):
        proc = self._make_processor(enricher=lambda loc: f"{loc} (enriched)")
        svc = MagicMock()
        svc.find_calendar_id.return_value = "cal-123"
        svc.list_events_in_range.return_value = [
            {"id": "e1", "subject": "Fun n Fit Class", "location": {"displayName": "Gym"}},
        ]
        req = self._make_request(service=svc, dry_run=False)
        result = proc.process(req)
        self.assertEqual(result.status, "success")
        svc.update_event_location.assert_called()

    def test_dedupes_by_series_master_id(self):
        proc = self._make_processor(enricher=lambda loc: f"{loc} (enriched)")
        svc = MagicMock()
        svc.find_calendar_id.return_value = "cal-123"
        svc.list_events_in_range.return_value = [
            {"id": "e1", "seriesMasterId": "master-1", "subject": "Public Skating", "location": {"displayName": "Rink"}},
            {"id": "e2", "seriesMasterId": "master-1", "subject": "Public Skating", "location": {"displayName": "Rink"}},
        ]
        req = self._make_request(service=svc, dry_run=False)
        result = proc.process(req)
        self.assertEqual(result.status, "success")
        # Should only call update once for the deduplicated series
        self.assertEqual(svc.update_event_location.call_count, 1)

    def test_dry_run_does_not_update(self):
        proc = self._make_processor(enricher=lambda loc: f"{loc} (enriched)")
        svc = MagicMock()
        svc.find_calendar_id.return_value = "cal-123"
        svc.list_events_in_range.return_value = [
            {"id": "e1", "subject": "Public Skating", "location": {"displayName": "Rink"}},
        ]
        req = self._make_request(service=svc, dry_run=True)
        result = proc.process(req)
        self.assertEqual(result.status, "success")
        self.assertTrue(result.payload.dry_run)
        svc.update_event_location.assert_not_called()
        self.assertIn("[dry-run]", result.diagnostics["logs"][0])

    def test_skips_when_enricher_returns_none(self):
        proc = self._make_processor(enricher=lambda loc: None)
        svc = MagicMock()
        svc.find_calendar_id.return_value = "cal-123"
        svc.list_events_in_range.return_value = [
            {"id": "e1", "subject": "Public Skating", "location": {"displayName": "Rink"}},
        ]
        req = self._make_request(service=svc)
        result = proc.process(req)
        self.assertEqual(result.payload.updated, 0)
        svc.update_event_location.assert_not_called()

    def test_skips_when_enricher_returns_same_value(self):
        proc = self._make_processor(enricher=lambda loc: loc)  # returns same
        svc = MagicMock()
        svc.find_calendar_id.return_value = "cal-123"
        svc.list_events_in_range.return_value = [
            {"id": "e1", "subject": "Public Skating", "location": {"displayName": "Rink"}},
        ]
        req = self._make_request(service=svc)
        result = proc.process(req)
        self.assertEqual(result.payload.updated, 0)
        svc.update_event_location.assert_not_called()

    def test_handles_update_exception(self):
        proc = self._make_processor(enricher=lambda loc: f"{loc} (enriched)")
        svc = MagicMock()
        svc.find_calendar_id.return_value = "cal-123"
        svc.list_events_in_range.return_value = [
            {"id": "e1", "subject": "Public Skating", "location": {"displayName": "Rink"}},
        ]
        svc.update_event_location.side_effect = RuntimeError("Update failed")
        req = self._make_request(service=svc, dry_run=False)
        result = proc.process(req)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.payload.updated, 0)
        self.assertIn("Failed to update", result.diagnostics["logs"][0])

    def test_handles_empty_location(self):
        proc = self._make_processor(enricher=lambda loc: f"{loc} (enriched)" if loc else None)
        svc = MagicMock()
        svc.find_calendar_id.return_value = "cal-123"
        svc.list_events_in_range.return_value = [
            {"id": "e1", "subject": "Public Skating", "location": {}},
        ]
        req = self._make_request(service=svc)
        result = proc.process(req)
        self.assertEqual(result.payload.updated, 0)

    def test_uses_default_enricher_when_none_provided(self):
        proc = self._make_processor(enricher=None)
        svc = MagicMock()
        svc.find_calendar_id.return_value = "cal-123"
        svc.list_events_in_range.return_value = []
        req = self._make_request(service=svc)
        # Should not raise - will import default enricher
        result = proc.process(req)
        self.assertEqual(result.status, "success")


class TestOutlookLocationsEnrichProducer(TestCase):
    """Tests for OutlookLocationsEnrichProducer."""

    def test_prints_logs(self):
        producer = OutlookLocationsEnrichProducer()
        payload = OutlookLocationsEnrichResult(updated=2, dry_run=False)
        captured = io.StringIO()
        sys.stdout = captured
        try:
            producer._produce_success(payload, {"logs": ["Log 1", "Log 2"]})
        finally:
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn("Log 1", output)
        self.assertIn("Log 2", output)
        self.assertIn("Updated locations on 2 series", output)

    def test_prints_preview_message_on_dry_run(self):
        producer = OutlookLocationsEnrichProducer()
        payload = OutlookLocationsEnrichResult(updated=0, dry_run=True)
        captured = io.StringIO()
        sys.stdout = captured
        try:
            producer._produce_success(payload, {"logs": []})
        finally:
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn("Preview complete", output)


# =============================================================================
# OutlookLocationsUpdateProcessor Tests
# =============================================================================


class TestOutlookLocationsUpdateProcessor(TestCase):
    """Tests for OutlookLocationsUpdateProcessor."""

    def _make_processor(self, config_loader=None):
        return OutlookLocationsUpdateProcessor(config_loader=config_loader)

    def _make_request(self, config_path="/path/to/config.yaml", calendar=None, dry_run=False, service=None):
        return OutlookLocationsRequest(
            config_path=Path(config_path),
            calendar=calendar,
            dry_run=dry_run,
            service=service or MagicMock(),
        )

    def test_returns_error_on_config_load_failure(self):
        def bad_loader(path):
            raise FileNotFoundError("not found")

        proc = self._make_processor(config_loader=bad_loader)
        req = self._make_request()
        result = proc.process(req)
        self.assertEqual(result.status, "error")

    @patch("calendars.outlook_pipelines.locations.LocationSync")
    def test_dry_run_returns_preview_message(self, mock_sync_cls):
        mock_sync = MagicMock()
        mock_sync.plan_from_config.return_value = 3
        mock_sync_cls.return_value = mock_sync

        proc = self._make_processor(config_loader=lambda p: {"events": [{"event": "test"}]})
        req = self._make_request(dry_run=True)
        result = proc.process(req)
        self.assertEqual(result.status, "success")
        self.assertIn("Preview complete", result.payload.message)

    @patch("calendars.outlook_pipelines.locations.LocationSync")
    @patch("calendars.yamlio.dump_config")
    def test_writes_config_when_updated(self, mock_dump, mock_sync_cls):
        mock_sync = MagicMock()
        mock_sync.plan_from_config.return_value = 2
        mock_sync_cls.return_value = mock_sync

        proc = self._make_processor(config_loader=lambda p: {"events": [{"event": "test"}]})
        req = self._make_request(dry_run=False)
        result = proc.process(req)
        self.assertEqual(result.status, "success")
        mock_dump.assert_called_once()
        self.assertIn("updated 2", result.payload.message)

    @patch("calendars.outlook_pipelines.locations.LocationSync")
    def test_no_changes_message_when_nothing_updated(self, mock_sync_cls):
        mock_sync = MagicMock()
        mock_sync.plan_from_config.return_value = 0
        mock_sync_cls.return_value = mock_sync

        proc = self._make_processor(config_loader=lambda p: {"events": [{"event": "test"}]})
        req = self._make_request(dry_run=False)
        result = proc.process(req)
        self.assertEqual(result.status, "success")
        self.assertIn("No location changes", result.payload.message)


# =============================================================================
# OutlookLocationsApplyProcessor Tests
# =============================================================================


class TestOutlookLocationsApplyProcessor(TestCase):
    """Tests for OutlookLocationsApplyProcessor."""

    def _make_processor(self, config_loader=None):
        return OutlookLocationsApplyProcessor(config_loader=config_loader)

    def _make_request(self, config_path="/path/to/config.yaml", calendar=None, dry_run=False, all_occurrences=False, service=None):
        return OutlookLocationsRequest(
            config_path=Path(config_path),
            calendar=calendar,
            dry_run=dry_run,
            all_occurrences=all_occurrences,
            service=service or MagicMock(),
        )

    def test_returns_error_on_config_load_failure(self):
        def bad_loader(path):
            raise FileNotFoundError("not found")

        proc = self._make_processor(config_loader=bad_loader)
        req = self._make_request()
        result = proc.process(req)
        self.assertEqual(result.status, "error")

    @patch("calendars.outlook_pipelines.locations.LocationSync")
    def test_dry_run_returns_preview_message(self, mock_sync_cls):
        mock_sync = MagicMock()
        mock_sync.apply_from_config.return_value = 3
        mock_sync_cls.return_value = mock_sync

        proc = self._make_processor(config_loader=lambda p: {"events": [{"event": "test"}]})
        req = self._make_request(dry_run=True)
        result = proc.process(req)
        self.assertEqual(result.status, "success")
        self.assertIn("Preview complete", result.payload.message)

    @patch("calendars.outlook_pipelines.locations.LocationSync")
    def test_apply_returns_updated_count(self, mock_sync_cls):
        mock_sync = MagicMock()
        mock_sync.apply_from_config.return_value = 5
        mock_sync_cls.return_value = mock_sync

        proc = self._make_processor(config_loader=lambda p: {"events": [{"event": "test"}]})
        req = self._make_request(dry_run=False)
        result = proc.process(req)
        self.assertEqual(result.status, "success")
        self.assertIn("Applied 5 location update", result.payload.message)

    @patch("calendars.outlook_pipelines.locations.LocationSync")
    def test_passes_all_occurrences_flag(self, mock_sync_cls):
        mock_sync = MagicMock()
        mock_sync.apply_from_config.return_value = 0
        mock_sync_cls.return_value = mock_sync

        proc = self._make_processor(config_loader=lambda p: {"events": []})
        req = self._make_request(all_occurrences=True)
        proc.process(req)
        mock_sync.apply_from_config.assert_called_once()
        call_kwargs = mock_sync.apply_from_config.call_args[1]
        self.assertTrue(call_kwargs["all_occurrences"])


# =============================================================================
# OutlookLocationsProducer Tests
# =============================================================================


class TestOutlookLocationsProducer(TestCase):
    """Tests for OutlookLocationsProducer."""

    def test_prints_message(self):
        producer = OutlookLocationsProducer()
        payload = OutlookLocationsResult(message="Test message output")
        captured = io.StringIO()
        sys.stdout = captured
        try:
            producer._produce_success(payload, None)
        finally:
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn("Test message output", output)


# =============================================================================
# Dataclass Tests
# =============================================================================


class TestDataclasses(TestCase):
    """Tests for dataclass structures."""

    def test_enrich_request_fields(self):
        req = OutlookLocationsEnrichRequest(
            service=MagicMock(),
            calendar="Family",
            from_date="2025-01-01",
            to_date="2025-12-31",
            dry_run=True,
        )
        self.assertEqual(req.calendar, "Family")
        self.assertEqual(req.from_date, "2025-01-01")
        self.assertEqual(req.to_date, "2025-12-31")
        self.assertTrue(req.dry_run)

    def test_enrich_result_fields(self):
        result = OutlookLocationsEnrichResult(updated=5, dry_run=False)
        self.assertEqual(result.updated, 5)
        self.assertFalse(result.dry_run)

    def test_locations_request_defaults(self):
        req = OutlookLocationsRequest(
            config_path=Path("/test.yaml"),
            calendar=None,
            dry_run=False,
        )
        self.assertFalse(req.all_occurrences)
        self.assertIsNone(req.service)

    def test_locations_result_fields(self):
        result = OutlookLocationsResult(message="Success")
        self.assertEqual(result.message, "Success")


if __name__ == "__main__":
    unittest_main()
