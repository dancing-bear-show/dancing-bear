"""Tests for Outlook calendar event creation, updates, deletion, and listing."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.outlook.calendar import OutlookCalendarMixin
from core.outlook.models import EventCreationParams, RecurringEventCreationParams


# -------------------- Fixtures --------------------

EVENT_BASIC = {"id": "event-1", "subject": "Meeting"}
EVENT_SERIES = {"id": "series-1", "subject": "Recurring"}
EVENTS_LIST = [
    {"id": "e1", "subject": "Team Meeting"},
    {"id": "e2", "subject": "Lunch Break"},
    {"id": "e3", "subject": "Team Standup"},
]


def make_mock_response(json_data=None, status_code=200, text=None):
    """Create a mock HTTP response object."""
    resp = MagicMock()
    resp.status_code = status_code
    fallback_text = str(json_data) if json_data else ""
    resp.text = text if text is not None else fallback_text
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


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


class OutlookCalendarTestBase(unittest.TestCase):
    """Base class for Outlook calendar tests with common helpers."""

    def _setup_mock_requests(self, mock_requests_fn):
        """Set up mock requests and return the mock object."""
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests
        return mock_requests


class TestEventOperations(OutlookCalendarTestBase):
    """Tests for event creation and management."""

    def test_resolve_tz_with_provided_tz(self):
        result = OutlookCalendarMixin._resolve_tz(FakeClient(timezone="America/New_York"), "Europe/London")
        self.assertEqual(result, "Europe/London")

    def test_resolve_tz_from_mailbox(self):
        result = OutlookCalendarMixin._resolve_tz(FakeClient(timezone="America/New_York"), None)
        self.assertEqual(result, "America/New_York")

    def test_resolve_tz_fallback(self):
        result = OutlookCalendarMixin._resolve_tz(FakeClient(timezone=None), None)
        self.assertEqual(result, "America/Toronto")

    @patch("core.outlook.calendar._requests")
    def test_create_event_basic(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response(EVENT_BASIC)

        result = OutlookCalendarMixin.create_event(
            FakeClient(timezone="America/Toronto"),
            EventCreationParams(subject="Meeting", start_iso="2025-01-15T10:00:00", end_iso="2025-01-15T11:00:00"),
        )

        self.assertEqual(result["subject"], "Meeting")
        mock_requests.post.assert_called_once()

    @patch("core.outlook.calendar._requests")
    def test_create_event_with_location(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "e1"})

        OutlookCalendarMixin.create_event(
            FakeClient(timezone="America/Toronto"),
            EventCreationParams(
                subject="Meeting", start_iso="2025-01-15T10:00:00", end_iso="2025-01-15T11:00:00",
                calendar_id="cal1", location="Conference Room A",
            ),
        )

        self.assertIn("location", mock_requests.post.call_args.kwargs["json"])

    @patch("core.outlook.calendar._requests")
    def test_create_event_all_day(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "e1"})

        OutlookCalendarMixin.create_event(
            FakeClient(timezone="America/Toronto"),
            EventCreationParams(subject="Holiday", start_iso="2025-01-15", end_iso="2025-01-16", all_day=True),
        )

        self.assertTrue(mock_requests.post.call_args.kwargs["json"].get("isAllDay"))

    @patch("core.outlook.calendar._requests")
    def test_create_event_no_reminder(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "e1"})

        OutlookCalendarMixin.create_event(
            FakeClient(timezone="America/Toronto"),
            EventCreationParams(
                subject="Silent Meeting", start_iso="2025-01-15T10:00:00", end_iso="2025-01-15T11:00:00",
                no_reminder=True,
            ),
        )

        self.assertFalse(mock_requests.post.call_args.kwargs["json"].get("isReminderOn"))

    @patch("core.outlook.calendar._requests")
    def test_create_event_with_reminder_minutes(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "e1"})

        OutlookCalendarMixin.create_event(
            FakeClient(timezone="America/Toronto"),
            EventCreationParams(
                subject="Reminded Meeting", start_iso="2025-01-15T10:00:00", end_iso="2025-01-15T11:00:00",
                reminder_minutes=30,
            ),
        )

        payload = mock_requests.post.call_args.kwargs["json"]
        self.assertTrue(payload.get("isReminderOn"))
        self.assertEqual(payload.get("reminderMinutesBeforeStart"), 30)


class TestRecurringEvents(OutlookCalendarTestBase):
    """Tests for recurring event creation."""

    @patch("core.outlook.calendar._requests")
    def test_create_recurring_event_daily(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response(EVENT_SERIES)

        result = OutlookCalendarMixin.create_recurring_event(
            FakeClient(timezone="America/Toronto"),
            RecurringEventCreationParams(
                subject="Daily Standup", start_time="09:00:00", end_time="09:15:00",
                repeat="daily", range_start_date="2025-01-15", range_until="2025-03-15",
            ),
        )

        self.assertEqual(result["id"], "series-1")
        self.assertEqual(mock_requests.post.call_args.kwargs["json"]["recurrence"]["pattern"]["type"], "daily")

    @patch("core.outlook.calendar._requests")
    def test_create_recurring_event_weekly(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response(EVENT_SERIES)

        OutlookCalendarMixin.create_recurring_event(
            FakeClient(timezone="America/Toronto"),
            RecurringEventCreationParams(
                subject="Weekly Review", start_time="14:00:00", end_time="15:00:00",
                repeat="weekly", byday=["MO", "WE", "FR"], range_start_date="2025-01-15", count=10,
            ),
        )

        payload = mock_requests.post.call_args.kwargs["json"]
        self.assertEqual(payload["recurrence"]["pattern"]["type"], "weekly")
        self.assertIn("monday", payload["recurrence"]["pattern"]["daysOfWeek"])

    @patch("core.outlook.calendar._requests")
    def test_create_recurring_event_monthly(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response(EVENT_SERIES)

        OutlookCalendarMixin.create_recurring_event(
            FakeClient(timezone="America/Toronto"),
            RecurringEventCreationParams(
                subject="Monthly Review", start_time="10:00:00", end_time="11:00:00",
                repeat="monthly", range_start_date="2025-01-15",
            ),
        )

        self.assertEqual(
            mock_requests.post.call_args.kwargs["json"]["recurrence"]["pattern"]["type"],
            "absoluteMonthly"
        )

    def test_create_recurring_event_invalid_repeat(self):
        with self.assertRaises(ValueError) as ctx:
            OutlookCalendarMixin.create_recurring_event(
                FakeClient(timezone="America/Toronto"),
                RecurringEventCreationParams(
                    subject="Invalid", start_time="10:00:00", end_time="11:00:00",
                    repeat="yearly", range_start_date="2025-01-15",
                ),
            )
        self.assertIn("Unsupported repeat", str(ctx.exception))


class TestEventUpdates(OutlookCalendarTestBase):
    """Tests for event update methods."""

    @patch("core.outlook.calendar._requests")
    def test_update_event_location(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.patch.return_value = make_mock_response({"id": "e1"}, text='{"id": "e1"}')

        OutlookCalendarMixin.update_event_location(FakeClient(), event_id="event-1", location_str="New Location")

        mock_requests.patch.assert_called_once()

    def test_update_event_location_no_location_raises(self):
        with self.assertRaises((ValueError, TypeError)):
            OutlookCalendarMixin.update_event_location(FakeClient(), event_id="event-1", location_str="")

    @patch("core.outlook.calendar._requests")
    def test_update_event_reminder(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.patch.return_value = make_mock_response({"id": "e1"}, text='{"id": "e1"}')

        from core.outlook.models import UpdateEventReminderRequest
        OutlookCalendarMixin.update_event_reminder(
            FakeClient(),
            UpdateEventReminderRequest(event_id="event-1", is_on=True, minutes_before_start=15)
        )

        payload = mock_requests.patch.call_args.kwargs["json"]
        self.assertTrue(payload["isReminderOn"])
        self.assertEqual(payload["reminderMinutesBeforeStart"], 15)

    @patch("core.outlook.calendar._requests")
    def test_update_event_settings(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.patch.return_value = make_mock_response({"id": "e1"}, text='{"id": "e1"}')

        from core.outlook.models import EventSettingsPatch
        OutlookCalendarMixin.update_event_settings(
            FakeClient(),
            EventSettingsPatch(
                event_id="event-1", categories=["Work", "Important"],
                show_as="busy", sensitivity="private"
            ),
        )

        payload = mock_requests.patch.call_args.kwargs["json"]
        self.assertEqual(payload["categories"], ["Work", "Important"])
        self.assertEqual(payload["showAs"], "busy")
        self.assertEqual(payload["sensitivity"], "private")

    @patch("core.outlook.calendar._requests")
    def test_update_event_settings_empty_returns_empty(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)

        from core.outlook.models import EventSettingsPatch
        result = OutlookCalendarMixin.update_event_settings(
            FakeClient(), EventSettingsPatch(event_id="event-1")
        )

        self.assertEqual(result, {})
        mock_requests.patch.assert_not_called()

    @patch("core.outlook.calendar._requests")
    def test_update_event_subject(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.patch.return_value = make_mock_response({"id": "e1"}, text='{"id": "e1"}')

        OutlookCalendarMixin.update_event_subject(FakeClient(), event_id="event-1", subject="New Title")

        self.assertEqual(mock_requests.patch.call_args.kwargs["json"]["subject"], "New Title")


class TestEventDeletion(OutlookCalendarTestBase):
    """Tests for event deletion methods."""

    @patch("core.outlook.calendar._requests")
    def test_delete_event(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.delete.return_value = make_mock_response(status_code=204, text="")

        OutlookCalendarMixin.delete_event(FakeClient(), "event-1")

        mock_requests.delete.assert_called_once()

    @patch("core.outlook.calendar._requests")
    def test_delete_event_with_calendar_id(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.delete.return_value = make_mock_response(status_code=204, text="")

        OutlookCalendarMixin.delete_event(FakeClient(), "event-1", calendar_id="cal-1")

        self.assertIn("cal-1", mock_requests.delete.call_args[0][0])

    @patch("core.outlook.calendar._requests")
    def test_delete_event_by_id_success(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.delete.return_value = make_mock_response(status_code=204, text="")

        self.assertTrue(OutlookCalendarMixin.delete_event_by_id(FakeClient(), "event-1"))

    @patch("core.outlook.calendar._requests")
    def test_delete_event_by_id_failure(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.delete.side_effect = Exception("Network error")

        self.assertFalse(OutlookCalendarMixin.delete_event_by_id(FakeClient(), "event-1"))


class TestListEvents(OutlookCalendarTestBase):
    """Tests for event listing methods."""

    @patch("core.outlook.calendar._requests")
    def test_list_events_in_range(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": EVENTS_LIST[:2]})

        from core.outlook.models import ListEventsRequest
        result = OutlookCalendarMixin.list_events_in_range(
            FakeClient(),
            ListEventsRequest(start_iso="2025-01-01T00:00:00", end_iso="2025-01-31T23:59:59"),
        )

        self.assertEqual(len(result), 2)

    @patch("core.outlook.calendar._requests")
    def test_list_events_in_range_with_subject_filter(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": EVENTS_LIST})

        from core.outlook.models import ListEventsRequest
        result = OutlookCalendarMixin.list_events_in_range(
            FakeClient(),
            ListEventsRequest(
                start_iso="2025-01-01T00:00:00", end_iso="2025-01-31T23:59:59",
                subject_filter="Team"
            ),
        )

        self.assertEqual(len(result), 2)
        subjects = [e["subject"] for e in result]
        self.assertIn("Team Meeting", subjects)
        self.assertIn("Team Standup", subjects)
        self.assertNotIn("Lunch Break", subjects)

    @patch("core.outlook.calendar._requests")
    def test_list_calendar_view(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": [{"id": "e1"}, {"id": "e2"}]})

        from core.outlook.models import ListCalendarViewRequest
        result = OutlookCalendarMixin.list_calendar_view(
            FakeClient(),
            ListCalendarViewRequest(start_iso="2025-01-01T00:00:00", end_iso="2025-01-31T23:59:59"),
        )

        self.assertEqual(len(result), 2)

    @patch("core.outlook.calendar._requests")
    def test_list_calendar_view_with_calendar_id(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": []})

        from core.outlook.models import ListCalendarViewRequest
        OutlookCalendarMixin.list_calendar_view(
            FakeClient(),
            ListCalendarViewRequest(
                calendar_id="cal-123",
                start_iso="2025-01-01T00:00:00",
                end_iso="2025-01-31T23:59:59"
            ),
        )

        self.assertIn("cal-123", mock_requests.get.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
