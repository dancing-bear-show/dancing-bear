"""Tests for core/outlook/calendar.py calendar operations."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.outlook.calendar import (
    OutlookCalendarMixin,
    _parse_location,
    _normalize_days,
)


class TestParseLocation(unittest.TestCase):
    """Tests for _parse_location helper function."""

    def test_simple_name(self):
        result = _parse_location("Conference Room A")
        self.assertEqual(result["displayName"], "Conference Room A")
        self.assertNotIn("address", result)

    def test_empty_string(self):
        result = _parse_location("")
        self.assertEqual(result["displayName"], "")

    def test_whitespace_only(self):
        result = _parse_location("   ")
        self.assertEqual(result["displayName"], "")

    def test_name_with_parens_address(self):
        result = _parse_location("Office (123 Main St)")
        self.assertEqual(result["displayName"], "Office")
        self.assertIn("address", result)
        self.assertEqual(result["address"]["street"], "123 Main St")

    def test_name_at_address(self):
        result = _parse_location("Meeting at 456 Oak Ave")
        self.assertEqual(result["displayName"], "Meeting")
        self.assertIn("address", result)

    def test_full_address_with_city_state(self):
        result = _parse_location("Office (123 Main St, Toronto, ON M5V 1A1)")
        self.assertEqual(result["displayName"], "Office")
        self.assertIn("address", result)
        addr = result["address"]
        self.assertIn("street", addr)

    def test_address_with_country(self):
        result = _parse_location("HQ (100 King St, Toronto, ON, M5V 1A1, Canada)")
        self.assertEqual(result["displayName"], "HQ")
        self.assertIn("address", result)

    def test_street_number_detection(self):
        result = _parse_location("123 Main Street")
        # Should detect number and split
        self.assertIn("address", result)

    def test_canadian_postal_code(self):
        result = _parse_location("Office (123 Main, ON M5V 1A1)")
        addr = result.get("address", {})
        # Should parse Canadian postal code
        self.assertIn("postalCode", addr)


class TestNormalizeDays(unittest.TestCase):
    """Tests for _normalize_days helper function."""

    def test_short_codes(self):
        result = _normalize_days(["MO", "TU", "WE"])
        self.assertEqual(result, ["monday", "tuesday", "wednesday"])

    def test_full_names_lowercase(self):
        result = _normalize_days(["monday", "friday"])
        self.assertEqual(result, ["monday", "friday"])

    def test_mixed_case(self):
        result = _normalize_days(["MO", "friday", "SA"])
        self.assertEqual(result, ["monday", "friday", "saturday"])

    def test_all_days(self):
        result = _normalize_days(["MO", "TU", "WE", "TH", "FR", "SA", "SU"])
        expected = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        self.assertEqual(result, expected)

    def test_empty_list(self):
        result = _normalize_days([])
        self.assertEqual(result, [])

    def test_filters_empty_strings(self):
        result = _normalize_days(["MO", "", "WE", None])
        self.assertEqual(result, ["monday", "wednesday"])

    def test_deduplicates(self):
        result = _normalize_days(["MO", "MO", "TU", "MO"])
        self.assertEqual(result, ["monday", "tuesday"])

    def test_whitespace_handling(self):
        result = _normalize_days(["  MO  ", " TU "])
        self.assertEqual(result, ["monday", "tuesday"])


class FakeClient(OutlookCalendarMixin):
    """Fake client for testing mixin methods."""

    def __init__(self, calendars=None, timezone=None):
        self._calendars = calendars or []
        self._timezone = timezone

    def _headers(self):
        return {"Authorization": "Bearer fake-token"}

    def get_mailbox_timezone(self):
        return self._timezone

    def list_calendars(self):
        """Override to return mock calendars without network calls."""
        return self._calendars


class TestResolveCalendarId(unittest.TestCase):
    """Tests for _resolve_calendar_id helper method."""

    def test_returns_calendar_id_when_provided(self):
        client = FakeClient(calendars=[{"id": "cal1", "name": "Work"}])
        result = client._resolve_calendar_id("explicit-id", None)
        self.assertEqual(result, "explicit-id")

    def test_returns_calendar_id_over_name(self):
        client = FakeClient(calendars=[{"id": "cal1", "name": "Work"}])
        result = client._resolve_calendar_id("explicit-id", "Work")
        self.assertEqual(result, "explicit-id")

    def test_looks_up_by_name_when_no_id(self):
        client = FakeClient(calendars=[{"id": "cal1", "name": "Work"}])
        result = client._resolve_calendar_id(None, "Work")
        self.assertEqual(result, "cal1")

    def test_returns_none_when_neither_provided(self):
        client = FakeClient(calendars=[{"id": "cal1", "name": "Work"}])
        result = client._resolve_calendar_id(None, None)
        self.assertIsNone(result)

    def test_returns_none_when_name_not_found(self):
        client = FakeClient(calendars=[{"id": "cal1", "name": "Work"}])
        result = client._resolve_calendar_id(None, "Nonexistent")
        self.assertIsNone(result)


class TestEventEndpoint(unittest.TestCase):
    """Tests for _event_endpoint static method."""

    def test_without_calendar_id_or_event_id(self):
        result = OutlookCalendarMixin._event_endpoint(None, None)
        self.assertEqual(result, "https://graph.microsoft.com/v1.0/me/events")

    def test_with_calendar_id_only(self):
        result = OutlookCalendarMixin._event_endpoint("cal-123", None)
        self.assertEqual(result, "https://graph.microsoft.com/v1.0/me/calendars/cal-123/events")

    def test_with_event_id_only(self):
        result = OutlookCalendarMixin._event_endpoint(None, "event-456")
        self.assertEqual(result, "https://graph.microsoft.com/v1.0/me/events/event-456")

    def test_with_both_ids(self):
        result = OutlookCalendarMixin._event_endpoint("cal-123", "event-456")
        self.assertEqual(result, "https://graph.microsoft.com/v1.0/me/calendars/cal-123/events/event-456")


class TestApplyReminder(unittest.TestCase):
    """Tests for _apply_reminder static method."""

    def test_no_reminder_sets_false(self):
        payload = {}
        OutlookCalendarMixin._apply_reminder(payload, no_reminder=True, reminder_minutes=None)
        self.assertFalse(payload["isReminderOn"])

    def test_no_reminder_ignores_minutes(self):
        payload = {}
        OutlookCalendarMixin._apply_reminder(payload, no_reminder=True, reminder_minutes=30)
        self.assertFalse(payload["isReminderOn"])
        self.assertNotIn("reminderMinutesBeforeStart", payload)

    def test_reminder_minutes_sets_values(self):
        payload = {}
        OutlookCalendarMixin._apply_reminder(payload, no_reminder=False, reminder_minutes=15)
        self.assertTrue(payload["isReminderOn"])
        self.assertEqual(payload["reminderMinutesBeforeStart"], 15)

    def test_neither_leaves_payload_unchanged(self):
        payload = {"existing": "value"}
        OutlookCalendarMixin._apply_reminder(payload, no_reminder=False, reminder_minutes=None)
        self.assertEqual(payload, {"existing": "value"})


class TestBuildRecurrencePattern(unittest.TestCase):
    """Tests for _build_recurrence_pattern static method."""

    def test_daily_pattern(self):
        result = OutlookCalendarMixin._build_recurrence_pattern("daily", 1, None)
        self.assertEqual(result["type"], "daily")
        self.assertEqual(result["interval"], 1)

    def test_daily_with_interval(self):
        result = OutlookCalendarMixin._build_recurrence_pattern("daily", 3, None)
        self.assertEqual(result["interval"], 3)

    def test_weekly_pattern(self):
        result = OutlookCalendarMixin._build_recurrence_pattern("weekly", 1, ["MO", "WE", "FR"])
        self.assertEqual(result["type"], "weekly")
        self.assertEqual(result["daysOfWeek"], ["monday", "wednesday", "friday"])

    def test_weekly_empty_days(self):
        result = OutlookCalendarMixin._build_recurrence_pattern("weekly", 1, [])
        self.assertEqual(result["type"], "weekly")
        self.assertEqual(result["daysOfWeek"], [])

    def test_monthly_pattern(self):
        result = OutlookCalendarMixin._build_recurrence_pattern("monthly", 1, None)
        self.assertEqual(result["type"], "absoluteMonthly")

    def test_absoluteMonthly_alias(self):
        result = OutlookCalendarMixin._build_recurrence_pattern("absoluteMonthly", 2, None)
        self.assertEqual(result["type"], "absoluteMonthly")
        self.assertEqual(result["interval"], 2)

    def test_case_insensitive(self):
        result = OutlookCalendarMixin._build_recurrence_pattern("DAILY", 1, None)
        self.assertEqual(result["type"], "daily")

    def test_invalid_repeat_raises(self):
        with self.assertRaises(ValueError) as ctx:
            OutlookCalendarMixin._build_recurrence_pattern("yearly", 1, None)
        self.assertIn("Unsupported repeat", str(ctx.exception))

    def test_minimum_interval(self):
        result = OutlookCalendarMixin._build_recurrence_pattern("daily", 0, None)
        self.assertEqual(result["interval"], 1)

    def test_negative_interval(self):
        result = OutlookCalendarMixin._build_recurrence_pattern("daily", -5, None)
        self.assertEqual(result["interval"], 1)


class TestBuildRecurrenceRange(unittest.TestCase):
    """Tests for _build_recurrence_range static method."""

    def test_end_date_range(self):
        result = OutlookCalendarMixin._build_recurrence_range("2025-01-01", "2025-12-31", None)
        self.assertEqual(result["type"], "endDate")
        self.assertEqual(result["startDate"], "2025-01-01")
        self.assertEqual(result["endDate"], "2025-12-31")

    def test_numbered_range(self):
        result = OutlookCalendarMixin._build_recurrence_range("2025-01-01", None, 10)
        self.assertEqual(result["type"], "numbered")
        self.assertEqual(result["startDate"], "2025-01-01")
        self.assertEqual(result["numberOfOccurrences"], 10)

    def test_no_end_range(self):
        result = OutlookCalendarMixin._build_recurrence_range("2025-01-01", None, None)
        self.assertEqual(result["type"], "noEnd")
        self.assertEqual(result["startDate"], "2025-01-01")

    def test_until_takes_precedence_over_count(self):
        result = OutlookCalendarMixin._build_recurrence_range("2025-01-01", "2025-06-01", 10)
        self.assertEqual(result["type"], "endDate")
        self.assertNotIn("numberOfOccurrences", result)


class TestPaginatedGet(unittest.TestCase):
    """Tests for _paginated_get helper method."""

    def _make_mock_response(self, json_data=None, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        return resp

    @patch("core.outlook.calendar._requests")
    def test_single_page(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        data = {"value": [{"id": "1"}, {"id": "2"}]}
        mock_requests.get.return_value = self._make_mock_response(data)

        client = FakeClient()
        result = client._paginated_get("https://example.com/api")

        self.assertEqual(len(result), 2)
        self.assertEqual(mock_requests.get.call_count, 1)

    @patch("core.outlook.calendar._requests")
    def test_multiple_pages(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        page1 = {"value": [{"id": "1"}], "@odata.nextLink": "https://example.com/page2"}
        page2 = {"value": [{"id": "2"}], "@odata.nextLink": "https://example.com/page3"}
        page3 = {"value": [{"id": "3"}]}

        mock_requests.get.side_effect = [
            self._make_mock_response(page1),
            self._make_mock_response(page2),
            self._make_mock_response(page3),
        ]

        client = FakeClient()
        result = client._paginated_get("https://example.com/api")

        self.assertEqual(len(result), 3)
        self.assertEqual(mock_requests.get.call_count, 3)

    @patch("core.outlook.calendar._requests")
    def test_empty_response(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.get.return_value = self._make_mock_response({"value": []})

        client = FakeClient()
        result = client._paginated_get("https://example.com/api")

        self.assertEqual(result, [])

    @patch("core.outlook.calendar._requests")
    def test_null_value_field(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.get.return_value = self._make_mock_response({"value": None})

        client = FakeClient()
        result = client._paginated_get("https://example.com/api")

        self.assertEqual(result, [])


class TestPatchEvent(unittest.TestCase):
    """Tests for _patch_event helper method."""

    def _make_mock_response(self, json_data=None, status_code=200, text=""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text or (str(json_data) if json_data else "")
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        return resp

    @patch("core.outlook.calendar._requests")
    def test_patch_without_calendar_id(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.patch.return_value = self._make_mock_response({"id": "e1"}, text='{"id": "e1"}')

        client = FakeClient()
        result = client._patch_event("event-1", None, None, {"subject": "Test"})

        self.assertEqual(result["id"], "e1")
        call_url = mock_requests.patch.call_args[0][0]
        self.assertIn("events/event-1", call_url)
        self.assertNotIn("calendars", call_url)

    @patch("core.outlook.calendar._requests")
    def test_patch_with_calendar_id(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.patch.return_value = self._make_mock_response({"id": "e1"}, text='{"id": "e1"}')

        client = FakeClient()
        result = client._patch_event("event-1", "cal-1", None, {"subject": "Test"})

        call_url = mock_requests.patch.call_args[0][0]
        self.assertIn("calendars/cal-1", call_url)
        self.assertIn("events/event-1", call_url)

    @patch("core.outlook.calendar._requests")
    def test_patch_with_calendar_name(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.patch.return_value = self._make_mock_response({"id": "e1"}, text='{"id": "e1"}')

        client = FakeClient(calendars=[{"id": "cal-from-name", "name": "Work"}])
        client._patch_event("event-1", None, "Work", {"subject": "Test"})

        call_url = mock_requests.patch.call_args[0][0]
        self.assertIn("calendars/cal-from-name", call_url)

    @patch("core.outlook.calendar._requests")
    def test_patch_empty_response(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.patch.return_value = self._make_mock_response(None, text="")

        client = FakeClient()
        result = client._patch_event("event-1", None, None, {"subject": "Test"})

        self.assertEqual(result, {})


class TestOutlookCalendarMixin(unittest.TestCase):
    """Tests for OutlookCalendarMixin methods."""

    def _make_mock_response(self, json_data=None, status_code=200, text=""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text or (str(json_data) if json_data else "")
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        return resp

    @patch("core.outlook.calendar._requests")
    def test_list_calendars(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        calendars = [{"id": "cal1", "name": "Work"}, {"id": "cal2", "name": "Personal"}]
        mock_requests.get.return_value = self._make_mock_response({"value": calendars})

        client = FakeClient()
        # Call the mixin method directly
        result = OutlookCalendarMixin.list_calendars(client)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Work")

    @patch("core.outlook.calendar._requests")
    def test_list_calendars_pagination(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        # First page with nextLink
        page1 = {"value": [{"id": "cal1", "name": "Cal1"}], "@odata.nextLink": "http://next"}
        page2 = {"value": [{"id": "cal2", "name": "Cal2"}]}

        mock_requests.get.side_effect = [
            self._make_mock_response(page1),
            self._make_mock_response(page2),
        ]

        client = FakeClient()
        result = OutlookCalendarMixin.list_calendars(client)

        self.assertEqual(len(result), 2)
        self.assertEqual(mock_requests.get.call_count, 2)

    @patch("core.outlook.calendar._requests")
    def test_create_calendar(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        created = {"id": "new-cal", "name": "New Calendar"}
        mock_requests.post.return_value = self._make_mock_response(created)

        client = FakeClient()
        result = OutlookCalendarMixin.create_calendar(client, "New Calendar")

        self.assertEqual(result["id"], "new-cal")
        mock_requests.post.assert_called_once()

    def test_ensure_calendar_empty_name_raises(self):
        client = FakeClient()
        with self.assertRaises(ValueError):
            OutlookCalendarMixin.ensure_calendar(client, "")

    @patch("core.outlook.calendar._requests")
    def test_ensure_calendar_exists_returns_existing(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        calendars = [{"id": "existing-id", "name": "Work"}]
        # Pass calendars to FakeClient since list_calendars is overridden
        client = FakeClient(calendars=calendars)
        result = OutlookCalendarMixin.ensure_calendar(client, "Work")

        self.assertEqual(result, "existing-id")
        # Should not call POST since calendar exists
        mock_requests.post.assert_not_called()

    @patch("core.outlook.calendar._requests")
    def test_ensure_calendar_creates_when_missing(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        # Empty list - no calendars
        mock_requests.get.return_value = self._make_mock_response({"value": []})
        mock_requests.post.return_value = self._make_mock_response({"id": "new-id", "name": "New"})

        client = FakeClient()
        result = OutlookCalendarMixin.ensure_calendar(client, "New")

        self.assertEqual(result, "new-id")
        mock_requests.post.assert_called_once()

    def test_get_calendar_id_by_name_empty(self):
        client = FakeClient(calendars=[{"id": "cal1", "name": "Work"}])
        result = OutlookCalendarMixin.get_calendar_id_by_name(client, "")
        self.assertIsNone(result)

    def test_get_calendar_id_by_name_found(self):
        client = FakeClient(calendars=[{"id": "cal1", "name": "Work"}])
        # Use FakeClient's implementation which we're testing through
        result = client.get_calendar_id_by_name("Work")
        self.assertEqual(result, "cal1")

    def test_get_calendar_id_by_name_not_found(self):
        client = FakeClient(calendars=[{"id": "cal1", "name": "Work"}])
        result = client.get_calendar_id_by_name("Personal")
        self.assertIsNone(result)

    def test_get_calendar_id_by_name_case_insensitive(self):
        client = FakeClient(calendars=[{"id": "cal1", "name": "Work Calendar"}])
        result = client.get_calendar_id_by_name("work calendar")
        self.assertEqual(result, "cal1")


class TestCalendarPermissions(unittest.TestCase):
    """Tests for calendar permission methods."""

    def _make_mock_response(self, json_data=None, status_code=200, text=""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text or (str(json_data) if json_data else "")
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        return resp

    @patch("core.outlook.calendar._requests")
    def test_list_calendar_permissions(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        perms = [{"id": "p1", "role": "read"}, {"id": "p2", "role": "write"}]
        mock_requests.get.return_value = self._make_mock_response({"value": perms})

        client = FakeClient()
        result = OutlookCalendarMixin.list_calendar_permissions(client, "cal-id")

        self.assertEqual(len(result), 2)

    @patch("core.outlook.calendar._requests")
    def test_ensure_calendar_permission_creates_new(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        # No existing permissions
        mock_requests.get.return_value = self._make_mock_response({"value": []})
        mock_requests.post.return_value = self._make_mock_response({"id": "new-perm", "role": "write"})

        client = FakeClient()
        result = OutlookCalendarMixin.ensure_calendar_permission(client, "cal-id", "user@example.com", "write")

        self.assertEqual(result["role"], "write")
        mock_requests.post.assert_called_once()

    @patch("core.outlook.calendar._requests")
    def test_ensure_calendar_permission_returns_existing(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        existing = [{"id": "p1", "emailAddress": {"address": "user@example.com"}, "role": "write"}]
        mock_requests.get.return_value = self._make_mock_response({"value": existing})

        client = FakeClient()
        result = OutlookCalendarMixin.ensure_calendar_permission(client, "cal-id", "user@example.com", "write")

        self.assertEqual(result["id"], "p1")
        mock_requests.post.assert_not_called()
        mock_requests.patch.assert_not_called()

    @patch("core.outlook.calendar._requests")
    def test_ensure_calendar_permission_updates_role(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        existing = [{"id": "p1", "emailAddress": {"address": "user@example.com"}, "role": "read"}]
        mock_requests.get.return_value = self._make_mock_response({"value": existing})
        mock_requests.patch.return_value = self._make_mock_response({"id": "p1", "role": "write"})

        client = FakeClient()
        result = OutlookCalendarMixin.ensure_calendar_permission(client, "cal-id", "user@example.com", "write")

        self.assertEqual(result["role"], "write")
        mock_requests.patch.assert_called_once()


class TestEventOperations(unittest.TestCase):
    """Tests for event creation and management."""

    def _make_mock_response(self, json_data=None, status_code=200, text=""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text or (str(json_data) if json_data else "")
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        return resp

    def test_resolve_tz_with_provided_tz(self):
        client = FakeClient(timezone="America/New_York")
        result = OutlookCalendarMixin._resolve_tz(client, "Europe/London")
        self.assertEqual(result, "Europe/London")

    def test_resolve_tz_from_mailbox(self):
        client = FakeClient(timezone="America/New_York")
        result = OutlookCalendarMixin._resolve_tz(client, None)
        self.assertEqual(result, "America/New_York")

    def test_resolve_tz_fallback(self):
        client = FakeClient(timezone=None)
        result = OutlookCalendarMixin._resolve_tz(client, None)
        self.assertEqual(result, "America/Toronto")

    @patch("core.outlook.calendar._requests")
    def test_create_event_basic(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        created = {"id": "event-1", "subject": "Meeting"}
        mock_requests.post.return_value = self._make_mock_response(created)

        client = FakeClient(timezone="America/Toronto")
        result = OutlookCalendarMixin.create_event(
            client,
            calendar_id=None,
            calendar_name=None,
            subject="Meeting",
            start_iso="2025-01-15T10:00:00",
            end_iso="2025-01-15T11:00:00",
        )

        self.assertEqual(result["subject"], "Meeting")
        mock_requests.post.assert_called_once()

    @patch("core.outlook.calendar._requests")
    def test_create_event_with_location(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.post.return_value = self._make_mock_response({"id": "e1"})

        client = FakeClient(timezone="America/Toronto")
        OutlookCalendarMixin.create_event(
            client,
            calendar_id="cal1",
            calendar_name=None,
            subject="Meeting",
            start_iso="2025-01-15T10:00:00",
            end_iso="2025-01-15T11:00:00",
            location="Conference Room A",
        )

        call_args = mock_requests.post.call_args
        payload = call_args.kwargs["json"]
        self.assertIn("location", payload)

    @patch("core.outlook.calendar._requests")
    def test_create_event_all_day(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.post.return_value = self._make_mock_response({"id": "e1"})

        client = FakeClient(timezone="America/Toronto")
        OutlookCalendarMixin.create_event(
            client,
            calendar_id=None,
            calendar_name=None,
            subject="Holiday",
            start_iso="2025-01-15",
            end_iso="2025-01-16",
            all_day=True,
        )

        call_args = mock_requests.post.call_args
        payload = call_args.kwargs["json"]
        self.assertTrue(payload.get("isAllDay"))

    @patch("core.outlook.calendar._requests")
    def test_create_event_no_reminder(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.post.return_value = self._make_mock_response({"id": "e1"})

        client = FakeClient(timezone="America/Toronto")
        OutlookCalendarMixin.create_event(
            client,
            calendar_id=None,
            calendar_name=None,
            subject="Silent Meeting",
            start_iso="2025-01-15T10:00:00",
            end_iso="2025-01-15T11:00:00",
            no_reminder=True,
        )

        call_args = mock_requests.post.call_args
        payload = call_args.kwargs["json"]
        self.assertFalse(payload.get("isReminderOn"))

    @patch("core.outlook.calendar._requests")
    def test_create_event_with_reminder_minutes(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.post.return_value = self._make_mock_response({"id": "e1"})

        client = FakeClient(timezone="America/Toronto")
        OutlookCalendarMixin.create_event(
            client,
            calendar_id=None,
            calendar_name=None,
            subject="Reminded Meeting",
            start_iso="2025-01-15T10:00:00",
            end_iso="2025-01-15T11:00:00",
            reminder_minutes=30,
        )

        call_args = mock_requests.post.call_args
        payload = call_args.kwargs["json"]
        self.assertTrue(payload.get("isReminderOn"))
        self.assertEqual(payload.get("reminderMinutesBeforeStart"), 30)


class TestRecurringEvents(unittest.TestCase):
    """Tests for recurring event creation."""

    def _make_mock_response(self, json_data=None, status_code=200, text=""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text or (str(json_data) if json_data else "")
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        return resp

    @patch("core.outlook.calendar._requests")
    def test_create_recurring_event_daily(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.post.return_value = self._make_mock_response({"id": "series-1"})

        client = FakeClient(timezone="America/Toronto")
        result = OutlookCalendarMixin.create_recurring_event(
            client,
            calendar_id=None,
            calendar_name=None,
            subject="Daily Standup",
            start_time="09:00:00",
            end_time="09:15:00",
            tz=None,
            repeat="daily",
            range_start_date="2025-01-15",
            range_until="2025-03-15",
        )

        self.assertEqual(result["id"], "series-1")
        call_args = mock_requests.post.call_args
        payload = call_args.kwargs["json"]
        self.assertEqual(payload["recurrence"]["pattern"]["type"], "daily")

    @patch("core.outlook.calendar._requests")
    def test_create_recurring_event_weekly(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.post.return_value = self._make_mock_response({"id": "series-1"})

        client = FakeClient(timezone="America/Toronto")
        OutlookCalendarMixin.create_recurring_event(
            client,
            calendar_id=None,
            calendar_name=None,
            subject="Weekly Review",
            start_time="14:00:00",
            end_time="15:00:00",
            tz=None,
            repeat="weekly",
            byday=["MO", "WE", "FR"],
            range_start_date="2025-01-15",
            count=10,
        )

        call_args = mock_requests.post.call_args
        payload = call_args.kwargs["json"]
        self.assertEqual(payload["recurrence"]["pattern"]["type"], "weekly")
        self.assertIn("monday", payload["recurrence"]["pattern"]["daysOfWeek"])

    @patch("core.outlook.calendar._requests")
    def test_create_recurring_event_monthly(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.post.return_value = self._make_mock_response({"id": "series-1"})

        client = FakeClient(timezone="America/Toronto")
        OutlookCalendarMixin.create_recurring_event(
            client,
            calendar_id=None,
            calendar_name=None,
            subject="Monthly Review",
            start_time="10:00:00",
            end_time="11:00:00",
            tz=None,
            repeat="monthly",
            range_start_date="2025-01-15",
        )

        call_args = mock_requests.post.call_args
        payload = call_args.kwargs["json"]
        self.assertEqual(payload["recurrence"]["pattern"]["type"], "absoluteMonthly")

    def test_create_recurring_event_invalid_repeat(self):
        client = FakeClient(timezone="America/Toronto")
        with self.assertRaises(ValueError) as ctx:
            OutlookCalendarMixin.create_recurring_event(
                client,
                calendar_id=None,
                calendar_name=None,
                subject="Invalid",
                start_time="10:00:00",
                end_time="11:00:00",
                tz=None,
                repeat="yearly",  # Not supported
                range_start_date="2025-01-15",
            )
        self.assertIn("Unsupported repeat", str(ctx.exception))


class TestEventUpdates(unittest.TestCase):
    """Tests for event update methods."""

    def _make_mock_response(self, json_data=None, status_code=200, text=""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text or (str(json_data) if json_data else "")
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        return resp

    @patch("core.outlook.calendar._requests")
    def test_update_event_location(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.patch.return_value = self._make_mock_response({"id": "e1"}, text='{"id": "e1"}')

        client = FakeClient()
        OutlookCalendarMixin.update_event_location(
            client,
            event_id="event-1",
            location_str="New Location",
        )

        mock_requests.patch.assert_called_once()

    def test_update_event_location_no_location_raises(self):
        client = FakeClient()
        with self.assertRaises(ValueError):
            OutlookCalendarMixin.update_event_location(
                client,
                event_id="event-1",
            )

    @patch("core.outlook.calendar._requests")
    def test_update_event_reminder(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.patch.return_value = self._make_mock_response({"id": "e1"}, text='{"id": "e1"}')

        client = FakeClient()
        OutlookCalendarMixin.update_event_reminder(
            client,
            event_id="event-1",
            is_on=True,
            minutes_before_start=15,
        )

        call_args = mock_requests.patch.call_args
        payload = call_args.kwargs["json"]
        self.assertTrue(payload["isReminderOn"])
        self.assertEqual(payload["reminderMinutesBeforeStart"], 15)

    @patch("core.outlook.calendar._requests")
    def test_update_event_settings(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.patch.return_value = self._make_mock_response({"id": "e1"}, text='{"id": "e1"}')

        client = FakeClient()
        OutlookCalendarMixin.update_event_settings(
            client,
            event_id="event-1",
            categories=["Work", "Important"],
            show_as="busy",
            sensitivity="private",
        )

        call_args = mock_requests.patch.call_args
        payload = call_args.kwargs["json"]
        self.assertEqual(payload["categories"], ["Work", "Important"])
        self.assertEqual(payload["showAs"], "busy")
        self.assertEqual(payload["sensitivity"], "private")

    @patch("core.outlook.calendar._requests")
    def test_update_event_settings_empty_returns_empty(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        client = FakeClient()
        result = OutlookCalendarMixin.update_event_settings(
            client,
            event_id="event-1",
        )

        self.assertEqual(result, {})
        mock_requests.patch.assert_not_called()

    @patch("core.outlook.calendar._requests")
    def test_update_event_subject(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.patch.return_value = self._make_mock_response({"id": "e1"}, text='{"id": "e1"}')

        client = FakeClient()
        OutlookCalendarMixin.update_event_subject(
            client,
            event_id="event-1",
            subject="New Title",
        )

        call_args = mock_requests.patch.call_args
        payload = call_args.kwargs["json"]
        self.assertEqual(payload["subject"], "New Title")


class TestEventDeletion(unittest.TestCase):
    """Tests for event deletion methods."""

    def _make_mock_response(self, json_data=None, status_code=200, text=""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text or ""
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        return resp

    @patch("core.outlook.calendar._requests")
    def test_delete_event(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.delete.return_value = self._make_mock_response(status_code=204)

        client = FakeClient()
        # Should not raise
        OutlookCalendarMixin.delete_event(client, "event-1")

        mock_requests.delete.assert_called_once()

    @patch("core.outlook.calendar._requests")
    def test_delete_event_with_calendar_id(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.delete.return_value = self._make_mock_response(status_code=204)

        client = FakeClient()
        OutlookCalendarMixin.delete_event(client, "event-1", calendar_id="cal-1")

        call_url = mock_requests.delete.call_args[0][0]
        self.assertIn("cal-1", call_url)

    @patch("core.outlook.calendar._requests")
    def test_delete_event_by_id_success(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.delete.return_value = self._make_mock_response(status_code=204)

        client = FakeClient()
        result = OutlookCalendarMixin.delete_event_by_id(client, "event-1")

        self.assertTrue(result)

    @patch("core.outlook.calendar._requests")
    def test_delete_event_by_id_failure(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.delete.side_effect = Exception("Network error")

        client = FakeClient()
        result = OutlookCalendarMixin.delete_event_by_id(client, "event-1")

        self.assertFalse(result)


class TestListEvents(unittest.TestCase):
    """Tests for event listing methods."""

    def _make_mock_response(self, json_data=None, status_code=200, text=""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text or (str(json_data) if json_data else "")
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        return resp

    @patch("core.outlook.calendar._requests")
    def test_list_events_in_range(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        events = [{"id": "e1", "subject": "Meeting 1"}, {"id": "e2", "subject": "Meeting 2"}]
        mock_requests.get.return_value = self._make_mock_response({"value": events})

        client = FakeClient()
        result = OutlookCalendarMixin.list_events_in_range(
            client,
            start_iso="2025-01-01T00:00:00",
            end_iso="2025-01-31T23:59:59",
        )

        self.assertEqual(len(result), 2)

    @patch("core.outlook.calendar._requests")
    def test_list_events_in_range_with_subject_filter(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        events = [
            {"id": "e1", "subject": "Team Meeting"},
            {"id": "e2", "subject": "Lunch Break"},
            {"id": "e3", "subject": "Team Standup"},
        ]
        mock_requests.get.return_value = self._make_mock_response({"value": events})

        client = FakeClient()
        result = OutlookCalendarMixin.list_events_in_range(
            client,
            start_iso="2025-01-01T00:00:00",
            end_iso="2025-01-31T23:59:59",
            subject_filter="Team",
        )

        self.assertEqual(len(result), 2)
        subjects = [e["subject"] for e in result]
        self.assertIn("Team Meeting", subjects)
        self.assertIn("Team Standup", subjects)
        self.assertNotIn("Lunch Break", subjects)

    @patch("core.outlook.calendar._requests")
    def test_list_calendar_view(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        events = [{"id": "e1"}, {"id": "e2"}]
        mock_requests.get.return_value = self._make_mock_response({"value": events})

        client = FakeClient()
        result = OutlookCalendarMixin.list_calendar_view(
            client,
            start_iso="2025-01-01T00:00:00",
            end_iso="2025-01-31T23:59:59",
        )

        self.assertEqual(len(result), 2)

    @patch("core.outlook.calendar._requests")
    def test_list_calendar_view_with_calendar_id(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.get.return_value = self._make_mock_response({"value": []})

        client = FakeClient()
        OutlookCalendarMixin.list_calendar_view(
            client,
            calendar_id="cal-123",
            start_iso="2025-01-01T00:00:00",
            end_iso="2025-01-31T23:59:59",
        )

        call_url = mock_requests.get.call_args[0][0]
        self.assertIn("cal-123", call_url)


if __name__ == "__main__":
    unittest.main()
