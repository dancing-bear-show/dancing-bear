"""Unit tests for core.outlook.models dataclasses."""

from unittest import TestCase, main as unittest_main

from core.outlook.models import (
    EventCreationParams,
    EventSettingsPatch,
    ListCalendarViewRequest,
    ListEventsRequest,
    RecurringEventCreationParams,
    UpdateEventReminderRequest,
)


class TestListEventsRequest(TestCase):
    """Tests for ListEventsRequest dataclass."""

    def test_required_fields(self):
        req = ListEventsRequest(start_iso="2025-01-01T00:00:00", end_iso="2025-01-31T23:59:59")
        self.assertEqual(req.start_iso, "2025-01-01T00:00:00")
        self.assertEqual(req.end_iso, "2025-01-31T23:59:59")

    def test_default_values(self):
        req = ListEventsRequest(start_iso="2025-01-01T00:00:00", end_iso="2025-01-31T23:59:59")
        self.assertIsNone(req.calendar_id)
        self.assertIsNone(req.calendar_name)
        self.assertIsNone(req.subject_filter)
        self.assertEqual(req.top, 50)

    def test_optional_fields(self):
        req = ListEventsRequest(
            start_iso="2025-01-01T00:00:00",
            end_iso="2025-01-31T23:59:59",
            calendar_id="cal-123",
            calendar_name="Work",
            subject_filter="Meeting",
            top=100,
        )
        self.assertEqual(req.calendar_id, "cal-123")
        self.assertEqual(req.calendar_name, "Work")
        self.assertEqual(req.subject_filter, "Meeting")
        self.assertEqual(req.top, 100)


class TestUpdateEventReminderRequest(TestCase):
    """Tests for UpdateEventReminderRequest dataclass."""

    def test_required_fields(self):
        req = UpdateEventReminderRequest(event_id="evt-123", is_on=True)
        self.assertEqual(req.event_id, "evt-123")
        self.assertTrue(req.is_on)

    def test_default_values(self):
        req = UpdateEventReminderRequest(event_id="evt-123", is_on=False)
        self.assertIsNone(req.calendar_id)
        self.assertIsNone(req.calendar_name)
        self.assertIsNone(req.minutes_before_start)

    def test_optional_fields(self):
        req = UpdateEventReminderRequest(
            event_id="evt-123",
            is_on=True,
            calendar_id="cal-456",
            calendar_name="Personal",
            minutes_before_start=15,
        )
        self.assertEqual(req.calendar_id, "cal-456")
        self.assertEqual(req.calendar_name, "Personal")
        self.assertEqual(req.minutes_before_start, 15)

    def test_reminder_off_without_minutes(self):
        req = UpdateEventReminderRequest(event_id="evt-123", is_on=False)
        self.assertFalse(req.is_on)
        self.assertIsNone(req.minutes_before_start)


class TestListCalendarViewRequest(TestCase):
    """Tests for ListCalendarViewRequest dataclass."""

    def test_required_fields(self):
        req = ListCalendarViewRequest(start_iso="2025-01-01T00:00:00", end_iso="2025-01-31T23:59:59")
        self.assertEqual(req.start_iso, "2025-01-01T00:00:00")
        self.assertEqual(req.end_iso, "2025-01-31T23:59:59")

    def test_default_values(self):
        req = ListCalendarViewRequest(start_iso="2025-01-01T00:00:00", end_iso="2025-01-31T23:59:59")
        self.assertIsNone(req.calendar_id)
        self.assertEqual(req.select, "subject,start,end,seriesMasterId,type,createdDateTime,location")
        self.assertEqual(req.top, 200)

    def test_optional_fields(self):
        req = ListCalendarViewRequest(
            start_iso="2025-01-01T00:00:00",
            end_iso="2025-01-31T23:59:59",
            calendar_id="cal-789",
            select="subject,start",
            top=50,
        )
        self.assertEqual(req.calendar_id, "cal-789")
        self.assertEqual(req.select, "subject,start")
        self.assertEqual(req.top, 50)

    def test_larger_page_size_than_list_events(self):
        """ListCalendarViewRequest should have larger default page size for bulk operations."""
        view_req = ListCalendarViewRequest(start_iso="2025-01-01T00:00:00", end_iso="2025-01-31T23:59:59")
        events_req = ListEventsRequest(start_iso="2025-01-01T00:00:00", end_iso="2025-01-31T23:59:59")
        self.assertGreater(view_req.top, events_req.top)


class TestEventCreationParams(TestCase):
    """Tests for EventCreationParams dataclass."""

    def test_required_fields(self):
        params = EventCreationParams(
            subject="Meeting",
            start_iso="2025-01-15T10:00:00",
            end_iso="2025-01-15T11:00:00",
        )
        self.assertEqual(params.subject, "Meeting")
        self.assertEqual(params.start_iso, "2025-01-15T10:00:00")
        self.assertEqual(params.end_iso, "2025-01-15T11:00:00")

    def test_default_values(self):
        params = EventCreationParams(
            subject="Meeting",
            start_iso="2025-01-15T10:00:00",
            end_iso="2025-01-15T11:00:00",
        )
        self.assertIsNone(params.calendar_id)
        self.assertIsNone(params.calendar_name)
        self.assertIsNone(params.tz)
        self.assertIsNone(params.body_html)
        self.assertFalse(params.all_day)
        self.assertIsNone(params.location)
        self.assertFalse(params.no_reminder)
        self.assertIsNone(params.reminder_minutes)


class TestRecurringEventCreationParams(TestCase):
    """Tests for RecurringEventCreationParams dataclass."""

    def test_required_fields(self):
        params = RecurringEventCreationParams(
            subject="Weekly Standup",
            start_time="09:00",
            end_time="09:30",
            repeat="weekly",
        )
        self.assertEqual(params.subject, "Weekly Standup")
        self.assertEqual(params.start_time, "09:00")
        self.assertEqual(params.end_time, "09:30")
        self.assertEqual(params.repeat, "weekly")

    def test_default_interval(self):
        params = RecurringEventCreationParams(
            subject="Daily Sync",
            start_time="10:00",
            end_time="10:15",
            repeat="daily",
        )
        self.assertEqual(params.interval, 1)


class TestEventSettingsPatch(TestCase):
    """Tests for EventSettingsPatch dataclass."""

    def test_required_fields(self):
        patch = EventSettingsPatch(event_id="evt-999")
        self.assertEqual(patch.event_id, "evt-999")

    def test_all_fields_optional_except_event_id(self):
        patch = EventSettingsPatch(event_id="evt-999")
        self.assertIsNone(patch.calendar_id)
        self.assertIsNone(patch.calendar_name)
        self.assertIsNone(patch.categories)
        self.assertIsNone(patch.show_as)
        self.assertIsNone(patch.sensitivity)
        self.assertIsNone(patch.is_reminder_on)
        self.assertIsNone(patch.reminder_minutes)

    def test_patch_with_reminder_settings(self):
        patch = EventSettingsPatch(
            event_id="evt-999",
            is_reminder_on=True,
            reminder_minutes=30,
        )
        self.assertTrue(patch.is_reminder_on)
        self.assertEqual(patch.reminder_minutes, 30)


if __name__ == "__main__":
    unittest_main()
