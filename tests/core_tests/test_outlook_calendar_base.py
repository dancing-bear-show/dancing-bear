"""Tests for Outlook calendar base helpers: parse_location, normalize_days, and mixin static methods."""
from __future__ import annotations

import unittest

from core.outlook.calendar import (
    OutlookCalendarMixin,
    _parse_location,
    _normalize_days,
)


# -------------------- Fixtures --------------------

CALENDAR_WORK = {"id": "cal1", "name": "Work"}
CALENDARS_DEFAULT = [CALENDAR_WORK]


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


class TestResolveCalendarId(unittest.TestCase):
    """Tests for _resolve_calendar_id helper method."""

    def test_returns_calendar_id_when_provided(self):
        client = FakeClient(calendars=CALENDARS_DEFAULT)
        result = client._resolve_calendar_id("explicit-id", None)
        self.assertEqual(result, "explicit-id")

    def test_returns_calendar_id_over_name(self):
        client = FakeClient(calendars=CALENDARS_DEFAULT)
        result = client._resolve_calendar_id("explicit-id", "Work")
        self.assertEqual(result, "explicit-id")

    def test_looks_up_by_name_when_no_id(self):
        client = FakeClient(calendars=CALENDARS_DEFAULT)
        result = client._resolve_calendar_id(None, "Work")
        self.assertEqual(result, "cal1")

    def test_returns_none_when_neither_provided(self):
        client = FakeClient(calendars=CALENDARS_DEFAULT)
        result = client._resolve_calendar_id(None, None)
        self.assertIsNone(result)

    def test_returns_none_when_name_not_found(self):
        client = FakeClient(calendars=CALENDARS_DEFAULT)
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

    def test_apply_reminder_non_numeric_minutes_raises_value_error(self):
        payload = {}
        with self.assertRaises(ValueError):
            OutlookCalendarMixin._apply_reminder(payload, no_reminder=False, reminder_minutes="soon")


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

    def test_build_recurrence_range_non_numeric_count_raises_value_error(self):
        with self.assertRaises(ValueError):
            OutlookCalendarMixin._build_recurrence_range("2025-01-01", None, "many")


if __name__ == "__main__":
    unittest.main()
