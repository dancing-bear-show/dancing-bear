"""Tests for Outlook calendar mixin operations — unique tests not covered by test_core_outlook_calendar.py."""
from __future__ import annotations

import unittest

from core.outlook.calendar import OutlookCalendarMixin


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


CALENDAR_WORK = {"id": "cal1", "name": "Work"}


class TestOutlookCalendarMixin(unittest.TestCase):
    """Tests for OutlookCalendarMixin methods — unique behaviors."""

    def test_get_calendar_id_by_name_empty(self):
        self.assertIsNone(FakeClient(calendars=[CALENDAR_WORK]).get_calendar_id_by_name(""))

    def test_get_calendar_id_by_name_found(self):
        self.assertEqual(FakeClient(calendars=[CALENDAR_WORK]).get_calendar_id_by_name("Work"), "cal1")

    def test_get_calendar_id_by_name_not_found(self):
        self.assertIsNone(FakeClient(calendars=[CALENDAR_WORK]).get_calendar_id_by_name("Personal"))

if __name__ == "__main__":
    unittest.main()
