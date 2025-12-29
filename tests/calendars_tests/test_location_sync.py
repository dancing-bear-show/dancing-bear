"""Tests for calendars/location_sync.py LocationSync helpers."""

import unittest
from unittest.mock import MagicMock, patch
from io import StringIO

from tests.calendars_tests.fixtures import FakeCalendarService


class TestLocationSyncCurrentLocationStr(unittest.TestCase):
    """Tests for LocationSync._current_location_str."""

    def _make_sync(self, events=None):
        from calendars.location_sync import LocationSync
        svc = FakeCalendarService(events=events or [])
        return LocationSync(svc=svc)

    def test_extracts_display_name_when_no_address(self):
        sync = self._make_sync()
        ev = {"location": {"displayName": "  Conference Room A  "}}
        result = sync._current_location_str(ev)
        self.assertEqual(result, "Conference Room A")

    def test_extracts_address_parts(self):
        sync = self._make_sync()
        ev = {
            "location": {
                "displayName": "Office",
                "address": {
                    "street": "123 Main St",
                    "city": "Seattle",
                    "state": "WA",
                    "postalCode": "98101",
                    "countryOrRegion": "USA",
                },
            }
        }
        result = sync._current_location_str(ev)
        self.assertEqual(result, "123 Main St, Seattle, WA, 98101, USA")

    def test_address_overrides_display_name(self):
        sync = self._make_sync()
        ev = {
            "location": {
                "displayName": "Office",
                "address": {"city": "Portland"},
            }
        }
        result = sync._current_location_str(ev)
        self.assertEqual(result, "Portland")

    def test_empty_location_returns_empty(self):
        sync = self._make_sync()
        ev = {"location": {}}
        result = sync._current_location_str(ev)
        self.assertEqual(result, "")

    def test_missing_location_returns_empty(self):
        sync = self._make_sync()
        ev = {}
        result = sync._current_location_str(ev)
        self.assertEqual(result, "")

    def test_none_location_returns_empty(self):
        sync = self._make_sync()
        ev = {"location": None}
        result = sync._current_location_str(ev)
        self.assertEqual(result, "")


class TestLocationSyncPlanFromConfig(unittest.TestCase):
    """Tests for LocationSync.plan_from_config."""

    def _make_sync_with_events(self, events):
        from calendars.location_sync import LocationSync
        svc = MagicMock()
        svc.list_events_in_range = MagicMock(return_value=events)
        return LocationSync(svc=svc)

    def test_skips_non_dict_items(self):
        sync = self._make_sync_with_events([])
        items = ["not a dict", 123, None]
        result = sync.plan_from_config(items, calendar="Test", dry_run=True)
        self.assertEqual(result, 0)

    def test_skips_items_without_subject(self):
        sync = self._make_sync_with_events([])
        items = [{"location": "Room A"}, {"subject": "   "}]
        result = sync.plan_from_config(items, calendar="Test", dry_run=True)
        self.assertEqual(result, 0)

    def test_dry_run_counts_updates(self):
        from calendars.location_sync import LocationSync
        svc = MagicMock()
        # Return an event with different location than yaml
        svc.list_events_in_range = MagicMock(return_value=[{
            "id": "evt1",
            "subject": "Meeting",
            "start": {"dateTime": "2024-01-15T09:00:00"},
            "location": {"displayName": "Old Room"},
        }])
        sync = LocationSync(svc=svc)
        items = [{
            "subject": "Meeting",
            "location": "New Room",
            "range": {"start_date": "2024-01-01", "until": "2024-02-01"},
        }]
        result = sync.plan_from_config(items, calendar="Test", dry_run=True)
        self.assertEqual(result, 1)

    def test_skips_when_locations_match(self):
        from calendars.location_sync import LocationSync
        svc = MagicMock()
        svc.list_events_in_range = MagicMock(return_value=[{
            "id": "evt1",
            "subject": "Meeting",
            "start": {"dateTime": "2024-01-15T09:00:00"},
            "location": {"displayName": "Room A"},
        }])
        sync = LocationSync(svc=svc)
        items = [{
            "subject": "Meeting",
            "location": "Room A",
            "range": {"start_date": "2024-01-01", "until": "2024-02-01"},
        }]
        result = sync.plan_from_config(items, calendar="Test", dry_run=True)
        self.assertEqual(result, 0)


class TestLocationSyncApplyFromConfig(unittest.TestCase):
    """Tests for LocationSync.apply_from_config."""

    def test_skips_items_without_subject_or_location(self):
        from calendars.location_sync import LocationSync
        svc = MagicMock()
        sync = LocationSync(svc=svc)
        items = [
            {"subject": "Meeting"},  # No location
            {"location": "Room A"},  # No subject
        ]
        result = sync.apply_from_config(items, calendar="Test", dry_run=True)
        self.assertEqual(result, 0)

    def test_dry_run_prints_message(self):
        from calendars.location_sync import LocationSync
        svc = MagicMock()
        svc.list_events_in_range = MagicMock(return_value=[{
            "id": "evt1",
            "subject": "Meeting",
            "start": {"dateTime": "2024-01-15T09:00:00"},
            "location": {"displayName": "Old Room"},
        }])
        sync = LocationSync(svc=svc)
        items = [{
            "subject": "Meeting",
            "location": "New Room",
            "range": {"start_date": "2024-01-01", "until": "2024-02-01"},
        }]
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            result = sync.apply_from_config(items, calendar="Test", dry_run=True)
        self.assertEqual(result, 1)
        self.assertIn("[dry-run]", mock_stdout.getvalue())

    def test_apply_calls_update_location(self):
        from calendars.location_sync import LocationSync
        svc = MagicMock()
        svc.list_events_in_range = MagicMock(return_value=[{
            "id": "evt1",
            "subject": "Meeting",
            "start": {"dateTime": "2024-01-15T09:00:00"},
            "location": {"displayName": "Old Room"},
        }])
        svc.update_event_location = MagicMock()
        sync = LocationSync(svc=svc)
        items = [{
            "subject": "Meeting",
            "location": "New Room",
            "range": {"start_date": "2024-01-01", "until": "2024-02-01"},
        }]
        with patch('sys.stdout', new_callable=StringIO):
            result = sync.apply_from_config(items, calendar="Test", dry_run=False)
        self.assertEqual(result, 1)
        svc.update_event_location.assert_called_once()

    def test_all_occurrences_updates_series(self):
        from calendars.location_sync import LocationSync
        svc = MagicMock()
        svc.list_events_in_range = MagicMock(return_value=[
            {
                "id": "occ1",
                "seriesMasterId": "series1",
                "subject": "Weekly",
                "start": {"dateTime": "2024-01-15T09:00:00"},
                "location": {"displayName": "Old"},
            },
            {
                "id": "occ2",
                "seriesMasterId": "series1",
                "subject": "Weekly",
                "start": {"dateTime": "2024-01-22T09:00:00"},
                "location": {"displayName": "Old"},
            },
        ])
        svc.update_event_location = MagicMock()
        sync = LocationSync(svc=svc)
        items = [{
            "subject": "Weekly",
            "location": "New Room",
            "range": {"start_date": "2024-01-01", "until": "2024-02-01"},
        }]
        with patch('sys.stdout', new_callable=StringIO):
            result = sync.apply_from_config(items, calendar="Test", all_occurrences=True, dry_run=False)
        # Should update series once (deduped by seriesMasterId)
        self.assertEqual(result, 1)
        svc.update_event_location.assert_called_once_with(
            event_id="series1", calendar_name="Test", location_str="New Room"
        )

    def test_skips_when_location_matches(self):
        from calendars.location_sync import LocationSync
        svc = MagicMock()
        svc.list_events_in_range = MagicMock(return_value=[{
            "id": "evt1",
            "subject": "Meeting",
            "start": {"dateTime": "2024-01-15T09:00:00"},
            "location": {"displayName": "Same Room"},
        }])
        sync = LocationSync(svc=svc)
        items = [{
            "subject": "Meeting",
            "location": "Same Room",
            "range": {"start_date": "2024-01-01", "until": "2024-02-01"},
        }]
        result = sync.apply_from_config(items, calendar="Test", dry_run=False)
        self.assertEqual(result, 0)


class TestLocationSyncSelectMatches(unittest.TestCase):
    """Tests for LocationSync._select_matches."""

    def test_returns_filtered_events(self):
        from calendars.location_sync import LocationSync
        svc = MagicMock()
        svc.list_events_in_range = MagicMock(return_value=[
            {"id": "1", "start": {"dateTime": "2024-01-15T09:00:00"}},
            {"id": "2", "start": {"dateTime": "2024-01-16T09:00:00"}},
        ])
        sync = LocationSync(svc=svc)
        result = sync._select_matches(
            cal_name="Test",
            subj="Meeting",
            win=("2024-01-01T00:00:00", "2024-02-01T23:59:59"),
            byday=[],
            start_time=None,
            end_time=None,
        )
        self.assertEqual(len(result), 2)

    def test_returns_first_when_no_filter_matches(self):
        from calendars.location_sync import LocationSync
        svc = MagicMock()
        # Return events without start.dateTime (filter_events_by_day_time will return empty)
        svc.list_events_in_range = MagicMock(return_value=[
            {"id": "1"},
            {"id": "2"},
        ])
        sync = LocationSync(svc=svc)
        result = sync._select_matches(
            cal_name="Test",
            subj="Meeting",
            win=("2024-01-01T00:00:00", "2024-02-01T23:59:59"),
            byday=["MO"],  # Filter by Monday
            start_time=None,
            end_time=None,
        )
        # Should return first event as fallback
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "1")


if __name__ == "__main__":
    unittest.main()
