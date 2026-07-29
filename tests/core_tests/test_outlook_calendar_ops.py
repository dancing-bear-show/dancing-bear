"""Tests for Outlook calendar mixin operations: paginated_get, patch_event, list_calendars, permissions."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.outlook.calendar import OutlookCalendarMixin


# -------------------- Fixtures --------------------

CALENDAR_WORK = {"id": "cal1", "name": "Work"}
CALENDAR_PERSONAL = {"id": "cal2", "name": "Personal"}
CALENDARS_MULTIPLE = [CALENDAR_WORK, CALENDAR_PERSONAL]

PERMISSION_READ = {"id": "p1", "role": "read"}
PERMISSION_WRITE = {"id": "p2", "role": "write"}
PERMISSION_WITH_EMAIL = {"id": "p1", "emailAddress": {"address": "user@example.com"}, "role": "write"}


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


class TestPaginatedGet(OutlookCalendarTestBase):
    """Tests for _paginated_get helper method."""

    @patch("core.outlook.calendar._requests")
    def test_single_page(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": [{"id": "1"}, {"id": "2"}]})

        result = FakeClient()._paginated_get("https://example.com/api")

        self.assertEqual(len(result), 2)
        self.assertEqual(mock_requests.get.call_count, 1)

    @patch("core.outlook.calendar._requests")
    def test_multiple_pages(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": [{"id": "1"}], "@odata.nextLink": "https://example.com/page2"}),
            make_mock_response({"value": [{"id": "2"}], "@odata.nextLink": "https://example.com/page3"}),
            make_mock_response({"value": [{"id": "3"}]}),
        ]

        result = FakeClient()._paginated_get("https://example.com/api")

        self.assertEqual(len(result), 3)
        self.assertEqual(mock_requests.get.call_count, 3)

    @patch("core.outlook.calendar._requests")
    def test_empty_response(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": []})

        self.assertEqual(FakeClient()._paginated_get("https://example.com/api"), [])

    @patch("core.outlook.calendar._requests")
    def test_null_value_field(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": None})

        self.assertEqual(FakeClient()._paginated_get("https://example.com/api"), [])


class TestPatchEvent(OutlookCalendarTestBase):
    """Tests for _patch_event helper method."""

    @patch("core.outlook.calendar._requests")
    def test_patch_without_calendar_id(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.patch.return_value = make_mock_response({"id": "e1"}, text='{"id": "e1"}')

        result = FakeClient()._patch_event("event-1", None, None, {"subject": "Test"})

        self.assertEqual(result["id"], "e1")
        call_url = mock_requests.patch.call_args[0][0]
        self.assertIn("events/event-1", call_url)
        self.assertNotIn("calendars", call_url)

    @patch("core.outlook.calendar._requests")
    def test_patch_with_calendar_id(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.patch.return_value = make_mock_response({"id": "e1"}, text='{"id": "e1"}')

        FakeClient()._patch_event("event-1", "cal-1", None, {"subject": "Test"})

        call_url = mock_requests.patch.call_args[0][0]
        self.assertIn("calendars/cal-1", call_url)
        self.assertIn("events/event-1", call_url)

    @patch("core.outlook.calendar._requests")
    def test_patch_with_calendar_name(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.patch.return_value = make_mock_response({"id": "e1"}, text='{"id": "e1"}')

        FakeClient(calendars=[{"id": "cal-from-name", "name": "Work"}])._patch_event(
            "event-1", None, "Work", {"subject": "Test"}
        )

        self.assertIn("calendars/cal-from-name", mock_requests.patch.call_args[0][0])

    @patch("core.outlook.calendar._requests")
    def test_patch_empty_response(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.patch.return_value = make_mock_response(None, text="")

        self.assertEqual(FakeClient()._patch_event("event-1", None, None, {"subject": "Test"}), {})


class TestOutlookCalendarMixin(OutlookCalendarTestBase):
    """Tests for OutlookCalendarMixin methods."""

    @patch("core.outlook.calendar._requests")
    def test_list_calendars(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": CALENDARS_MULTIPLE})

        result = OutlookCalendarMixin.list_calendars(FakeClient())

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Work")

    @patch("core.outlook.calendar._requests")
    def test_list_calendars_pagination(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": [CALENDAR_WORK], "@odata.nextLink": "http://next"}),
            make_mock_response({"value": [CALENDAR_PERSONAL]}),
        ]

        result = OutlookCalendarMixin.list_calendars(FakeClient())

        self.assertEqual(len(result), 2)
        self.assertEqual(mock_requests.get.call_count, 2)

    @patch("core.outlook.calendar._requests")
    def test_create_calendar(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "new-cal", "name": "New Calendar"})

        result = OutlookCalendarMixin.create_calendar(FakeClient(), "New Calendar")

        self.assertEqual(result["id"], "new-cal")
        mock_requests.post.assert_called_once()

    def test_ensure_calendar_empty_name_raises(self):
        with self.assertRaises(ValueError):
            OutlookCalendarMixin.ensure_calendar(FakeClient(), "")

    @patch("core.outlook.calendar._requests")
    def test_ensure_calendar_exists_returns_existing(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)

        result = OutlookCalendarMixin.ensure_calendar(
            FakeClient(calendars=[{"id": "existing-id", "name": "Work"}]), "Work"
        )

        self.assertEqual(result, "existing-id")
        mock_requests.post.assert_not_called()

    @patch("core.outlook.calendar._requests")
    def test_ensure_calendar_creates_when_missing(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": []})
        mock_requests.post.return_value = make_mock_response({"id": "new-id", "name": "New"})

        result = OutlookCalendarMixin.ensure_calendar(FakeClient(), "New")

        self.assertEqual(result, "new-id")
        mock_requests.post.assert_called_once()

    def test_get_calendar_id_by_name_empty(self):
        self.assertIsNone(FakeClient(calendars=[CALENDAR_WORK]).get_calendar_id_by_name(""))

    def test_get_calendar_id_by_name_found(self):
        self.assertEqual(FakeClient(calendars=[CALENDAR_WORK]).get_calendar_id_by_name("Work"), "cal1")

    def test_get_calendar_id_by_name_not_found(self):
        self.assertIsNone(FakeClient(calendars=[CALENDAR_WORK]).get_calendar_id_by_name("Personal"))

    def test_get_calendar_id_by_name_case_insensitive(self):
        client = FakeClient(calendars=[{"id": "cal1", "name": "Work Calendar"}])
        self.assertEqual(client.get_calendar_id_by_name("work calendar"), "cal1")


class TestCalendarPermissions(OutlookCalendarTestBase):
    """Tests for calendar permission methods."""

    @patch("core.outlook.calendar._requests")
    def test_list_calendar_permissions(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": [PERMISSION_READ, PERMISSION_WRITE]})

        result = OutlookCalendarMixin.list_calendar_permissions(FakeClient(), "cal-id")

        self.assertEqual(len(result), 2)

    @patch("core.outlook.calendar._requests")
    def test_ensure_calendar_permission_creates_new(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": []})
        mock_requests.post.return_value = make_mock_response({"id": "new-perm", "role": "write"})

        result = OutlookCalendarMixin.ensure_calendar_permission(
            FakeClient(), "cal-id", "user@example.com", "write"
        )

        self.assertEqual(result["role"], "write")
        mock_requests.post.assert_called_once()

    @patch("core.outlook.calendar._requests")
    def test_ensure_calendar_permission_returns_existing(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": [PERMISSION_WITH_EMAIL]})

        result = OutlookCalendarMixin.ensure_calendar_permission(
            FakeClient(), "cal-id", "user@example.com", "write"
        )

        self.assertEqual(result["id"], "p1")
        mock_requests.post.assert_not_called()
        mock_requests.patch.assert_not_called()

    @patch("core.outlook.calendar._requests")
    def test_ensure_calendar_permission_updates_role(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        existing = [{"id": "p1", "emailAddress": {"address": "user@example.com"}, "role": "read"}]
        mock_requests.get.return_value = make_mock_response({"value": existing})
        mock_requests.patch.return_value = make_mock_response({"id": "p1", "role": "write"})

        result = OutlookCalendarMixin.ensure_calendar_permission(
            FakeClient(), "cal-id", "user@example.com", "write"
        )

        self.assertEqual(result["role"], "write")
        mock_requests.patch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
