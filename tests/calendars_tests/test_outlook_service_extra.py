"""Additional tests for calendars/outlook_service.py — list_calendar_view, delete_event_by_id, list_messages, etc."""
import unittest
from unittest.mock import MagicMock, patch

from calendars.outlook_service import OutlookService


# ---------------------------------------------------------------------------
# Fake client / context
# ---------------------------------------------------------------------------

class _FakeClient:
    GRAPH = "https://graph.microsoft.com/v1.0"

    def __init__(self):
        self.created = []
        self.recurring_created = []
        self.reminder_updates = []
        self.settings_updates = []
        self.location_updates = []
        self.subject_updates = []
        self.permissions = []

    def _headers(self):
        return {"Authorization": "Bearer FAKE"}

    def list_events_in_range(self, params):
        return [{"id": "e1", "subject": "Test"}]

    def create_event(self, params):
        self.created.append(params)
        return {"id": "new_single"}

    def create_recurring_event(self, params):
        self.recurring_created.append(params)
        return {"id": "new_recurring"}

    def search_inbox_messages(self, params):
        return ["msg1", "msg2"]

    def get_message(self, message_id, *, select_body=True):
        return {"id": message_id, "subject": "Hello"}

    def get_calendar_id_by_name(self, name):
        return f"cal_{name}" if name else None

    def ensure_calendar(self, name):
        return f"cal_{name}"

    def list_calendars(self):
        return [{"id": "cal1", "name": "Primary"}]

    def update_event_location(self, *, event_id, calendar_id=None, calendar_name=None, location_str):
        self.location_updates.append((event_id, location_str))

    def update_event_reminder(self, params):
        self.reminder_updates.append(params)

    def update_event_settings(self, params):
        self.settings_updates.append(params)

    def update_event_subject(self, *, event_id, calendar_id=None, calendar_name=None, subject):
        self.subject_updates.append((event_id, subject))

    def ensure_calendar_permission(self, calendar_id, recipient, role):
        self.permissions.append((calendar_id, recipient, role))
        return {"id": "perm1"}


class _FakeCtx:
    def ensure_client(self):
        return _FakeClient()


def _make_svc():
    return OutlookService(ctx=_FakeCtx())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOutlookServiceDelegation(unittest.TestCase):
    def test_create_event_delegates(self):
        from core.outlook.models import EventCreationParams
        svc = _make_svc()
        params = EventCreationParams(subject="Meeting", start_iso="2025-01-01T10:00", end_iso="2025-01-01T11:00")
        result = svc.create_event(params)
        self.assertEqual(result["id"], "new_single")

    def test_create_recurring_event_delegates(self):
        from core.outlook.models import RecurringEventCreationParams
        svc = _make_svc()
        params = RecurringEventCreationParams(
            subject="Weekly", repeat="weekly", byday=["MO"],
            start_time="10:00", end_time="11:00",
            range_start_date="2025-01-01", range_until="2025-06-30",
        )
        result = svc.create_recurring_event(params)
        self.assertEqual(result["id"], "new_recurring")

    def test_search_inbox_messages_delegates(self):
        svc = _make_svc()
        msgs = svc.search_inbox_messages("swim class")
        self.assertIn("msg1", msgs)

    def test_get_message_delegates(self):
        svc = _make_svc()
        msg = svc.get_message("MSG123")
        self.assertEqual(msg["id"], "MSG123")

    def test_get_calendar_id_by_name(self):
        svc = _make_svc()
        cal_id = svc.get_calendar_id_by_name("Family")
        self.assertEqual(cal_id, "cal_Family")

    def test_get_calendar_id_by_name_none_returns_none(self):
        svc = _make_svc()
        self.assertIsNone(svc.get_calendar_id_by_name(None))

    def test_find_calendar_id_alias(self):
        svc = _make_svc()
        self.assertEqual(svc.find_calendar_id("Work"), "cal_Work")

    def test_ensure_calendar(self):
        svc = _make_svc()
        self.assertEqual(svc.ensure_calendar("New"), "cal_New")

    def test_ensure_calendar_exists_alias(self):
        svc = _make_svc()
        self.assertEqual(svc.ensure_calendar_exists("New"), "cal_New")

    def test_list_calendars(self):
        svc = _make_svc()
        cals = svc.list_calendars()
        self.assertEqual(len(cals), 1)
        self.assertEqual(cals[0]["name"], "Primary")

    def test_list_calendars_exception_returns_empty(self):
        """When underlying client raises, list_calendars returns []."""
        svc = _make_svc()
        svc.client.list_calendars = MagicMock(side_effect=RuntimeError("no list"))
        result = svc.list_calendars()
        self.assertEqual(result, [])

    def test_update_event_location(self):
        svc = _make_svc()
        svc.update_event_location(event_id="e1", location_str="Test Location")
        self.assertEqual(len(svc.client.location_updates), 1)

    def test_update_event_reminder(self):
        from core.outlook.models import UpdateEventReminderRequest
        svc = _make_svc()
        params = UpdateEventReminderRequest(event_id="e1", is_on=False)
        svc.update_event_reminder(params)
        self.assertEqual(len(svc.client.reminder_updates), 1)

    def test_update_event_settings(self):
        from core.outlook.models import EventSettingsPatch
        svc = _make_svc()
        params = EventSettingsPatch(event_id="e1")
        svc.update_event_settings(params)
        self.assertEqual(len(svc.client.settings_updates), 1)

    def test_update_event_subject(self):
        svc = _make_svc()
        svc.update_event_subject(event_id="e1", subject="New Title")
        self.assertIn(("e1", "New Title"), svc.client.subject_updates)

    def test_ensure_calendar_permission(self):
        svc = _make_svc()
        result = svc.ensure_calendar_permission("cal1", "user@example.com", "write")
        self.assertEqual(result["id"], "perm1")

    def test_headers_returns_dict(self):
        svc = _make_svc()
        hdrs = svc.headers()
        self.assertIn("Authorization", hdrs)

    def test_graph_base_returns_string(self):
        svc = _make_svc()
        self.assertTrue(svc.graph_base().startswith("https://"))


class TestOutlookServiceHTTP(unittest.TestCase):
    """Test list_calendar_view, delete_event_by_id, list_messages (HTTP-dependent)."""

    def _make_response(self, data, status_code=200):
        r = MagicMock()
        r.status_code = status_code
        r.json.return_value = data
        r.raise_for_status = MagicMock()
        return r

    def test_list_calendar_view_single_page(self):
        from core.outlook.models import ListCalendarViewRequest
        svc = _make_svc()
        page_data = {"value": [{"id": "e1"}, {"id": "e2"}]}
        mock_resp = self._make_response(page_data)

        with patch("calendars.outlook_service.requests.get", return_value=mock_resp) as mock_get:
            params = ListCalendarViewRequest(
                calendar_id="cal1",
                start_iso="2025-01-01T00:00:00",
                end_iso="2025-01-31T23:59:59",
                top=50,
                select="id,subject",
            )
            events = svc.list_calendar_view(params)

        mock_get.assert_called_once()
        self.assertEqual(len(events), 2)

    def test_list_calendar_view_pagination(self):
        from core.outlook.models import ListCalendarViewRequest
        svc = _make_svc()
        page1 = {"value": [{"id": "e1"}], "@odata.nextLink": "https://graph.microsoft.com/v1.0/next"}
        page2 = {"value": [{"id": "e2"}]}

        with patch("calendars.outlook_service.requests.get", side_effect=[
            self._make_response(page1),
            self._make_response(page2),
        ]) as mock_get:
            params = ListCalendarViewRequest(
                calendar_id=None,
                start_iso="2025-01-01T00:00:00",
                end_iso="2025-01-31T23:59:59",
                top=1,
                select="id",
            )
            events = svc.list_calendar_view(params)

        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(len(events), 2)

    def test_delete_event_by_id_success_204(self):
        svc = _make_svc()
        mock_resp = MagicMock()
        mock_resp.status_code = 204

        with patch("calendars.outlook_service.requests.delete", return_value=mock_resp):
            result = svc.delete_event_by_id("evt123")

        self.assertTrue(result)

    def test_delete_event_by_id_success_200(self):
        svc = _make_svc()
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("calendars.outlook_service.requests.delete", return_value=mock_resp):
            result = svc.delete_event_by_id("evt123")

        self.assertTrue(result)

    def test_delete_event_by_id_failure(self):
        svc = _make_svc()
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("calendars.outlook_service.requests.delete", return_value=mock_resp):
            result = svc.delete_event_by_id("missing")

        self.assertFalse(result)

    def test_list_messages_single_page(self):
        svc = _make_svc()
        page_data = {"value": [{"id": "m1", "subject": "Hello"}]}
        mock_resp = self._make_response(page_data)

        with patch("calendars.outlook_service.requests.get", return_value=mock_resp):
            msgs = svc.list_messages(folder="inbox", top=5, pages=1)

        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["id"], "m1")

    def test_list_messages_multiple_pages(self):
        svc = _make_svc()
        page1 = {"value": [{"id": "m1"}], "@odata.nextLink": "https://graph.microsoft.com/v1.0/next"}
        page2 = {"value": [{"id": "m2"}]}

        with patch("calendars.outlook_service.requests.get", side_effect=[
            self._make_response(page1),
            self._make_response(page2),
        ]):
            msgs = svc.list_messages(folder="inbox", top=1, pages=2)

        self.assertEqual(len(msgs), 2)

    def test_list_messages_stops_at_page_limit(self):
        """Should not fetch more pages than requested even if nextLink present."""
        svc = _make_svc()
        page_with_next = {"value": [{"id": "m1"}], "@odata.nextLink": "https://graph.next"}
        mock_resp = self._make_response(page_with_next)

        with patch("calendars.outlook_service.requests.get", return_value=mock_resp) as mock_get:
            msgs = svc.list_messages(folder="inbox", top=1, pages=1)

        # Only 1 page fetched even though nextLink exists
        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(len(msgs), 1)

    def test_list_calendar_view_no_calendar_id(self):
        """calendar_id=None should use /me/calendarView endpoint."""
        from core.outlook.models import ListCalendarViewRequest
        svc = _make_svc()
        page_data = {"value": []}
        mock_resp = self._make_response(page_data)

        with patch("calendars.outlook_service.requests.get", return_value=mock_resp) as mock_get:
            params = ListCalendarViewRequest(
                calendar_id=None,
                start_iso="2025-01-01T00:00:00",
                end_iso="2025-01-31T23:59:59",
                top=10,
                select="id",
            )
            svc.list_calendar_view(params)

        url_called = mock_get.call_args[0][0]
        self.assertIn("/me/calendarView", url_called)
        self.assertNotIn("/calendars/", url_called)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
