"""Tests for calendars.google_calendar_service.GoogleCalendarService.

Target: 0% -> 90%+

Covers:
- RuntimeError raised when googleapiclient is absent
- list_events: single-page (no nextPageToken)
- list_events: multi-page walk accumulates all items and passes pageToken on second call
- list_events: API raises mid-walk (exception propagates)
- list_events: empty items list (response returns no 'items')
- insert_event: happy path
- get_calendar_timezone: returns the timezone string
- get_calendar_timezone: returns None for empty/whitespace timezone
- get_calendar_timezone: returns None when the API raises (swallow path)
"""
from __future__ import annotations

import sys
import unittest
from typing import Any
from unittest.mock import MagicMock, patch


def _make_fake_service(responses: list[dict[str, Any]], inserted: list | None = None, tz_response: dict | None = None) -> MagicMock:
    """Build a fake googleapiclient service object.

    Parameters
    ----------
    responses
        A list of dicts to return, one per ``events().list().execute()`` call.
        Raises ``KeyError`` if an extra call is made beyond the list.
    inserted
        A mutable list to collect (calendar_id, body) tuples from insert_event.
    tz_response
        The dict returned by ``calendars().get().execute()``.
        If None, raises RuntimeError to simulate an API error.
    """
    service = MagicMock()
    _calls = iter(responses)

    def _execute():
        try:
            return next(_calls)
        except StopIteration:
            raise AssertionError("list().execute() called more times than expected")

    list_mock = MagicMock()
    list_mock.execute.side_effect = _execute
    service.events.return_value.list.return_value = list_mock

    # insert
    if inserted is not None:
        def _insert_execute():
            return {"id": "new-ev", "summary": "inserted"}

        insert_mock = MagicMock()
        insert_mock.execute.side_effect = _insert_execute
        service.events.return_value.insert.return_value = insert_mock

    # calendars().get()
    if tz_response is not None:
        get_mock = MagicMock()
        get_mock.execute.return_value = tz_response
        service.calendars.return_value.get.return_value = get_mock
    else:
        get_mock = MagicMock()
        get_mock.execute.side_effect = RuntimeError("API error")
        service.calendars.return_value.get.return_value = get_mock

    return service


def _build_service_with_fake(fake_service: MagicMock) -> "Any":
    """Patch googleapiclient.discovery.build and construct a GoogleCalendarService."""
    from calendars.google_calendar_service import GoogleCalendarService

    with patch("calendars.google_calendar_service.GoogleCalendarService.__init__", return_value=None):
        svc = GoogleCalendarService.__new__(GoogleCalendarService)
        svc._service = fake_service
    return svc


class TestGoogleCalendarServiceImportError(unittest.TestCase):
    """RuntimeError is raised when googleapiclient is not installed."""

    def test_init_raises_runtime_error_when_googleapiclient_missing(self):
        """Constructing GoogleCalendarService without googleapiclient raises RuntimeError."""
        from calendars.google_calendar_service import GoogleCalendarService

        # Remove googleapiclient from sys.modules so the lazy import fails.
        saved = {k: v for k, v in sys.modules.items() if "googleapiclient" in k}
        for k in list(saved):
            sys.modules.pop(k, None)

        # Patch builtins.__import__ to raise ImportError for googleapiclient.

        import builtins

        real_import = builtins.__import__

        def _failing_import(name, *args, **kwargs):
            if "googleapiclient" in name:
                raise ImportError(f"No module named {name!r}")
            return real_import(name, *args, **kwargs)

        try:
            with patch("builtins.__import__", side_effect=_failing_import):
                with self.assertRaises(RuntimeError) as ctx:
                    GoogleCalendarService(credentials=MagicMock())
        finally:
            # Restore saved modules.
            sys.modules.update(saved)

        self.assertIn("Google API libraries not installed", str(ctx.exception))

    def test_init_happy_path_builds_service(self):
        """When googleapiclient is available, __init__ calls build() and stores _service."""
        from calendars.google_calendar_service import GoogleCalendarService

        mock_service = MagicMock()
        with patch("calendars.google_calendar_service.build", return_value=mock_service, create=True):
            # Patch the lazy import inside __init__ to use our mock build.
            with patch("googleapiclient.discovery.build", return_value=mock_service):
                creds = MagicMock()
                svc = GoogleCalendarService(creds)
        self.assertIs(svc._service, mock_service)


class TestListEventsSinglePage(unittest.TestCase):
    """list_events terminates after one page when nextPageToken is absent."""

    def test_single_page_returns_all_items(self):
        items = [{"id": "ev1", "summary": "Event One"}, {"id": "ev2", "summary": "Event Two"}]
        response = {"items": items}  # no nextPageToken
        fake_svc = _make_fake_service([response])
        svc = _build_service_with_fake(fake_svc)

        result = svc.list_events("primary", "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")

        self.assertEqual(result, items)
        fake_svc.events.return_value.list.assert_called_once_with(
            calendarId="primary",
            timeMin="2026-01-01T00:00:00Z",
            timeMax="2026-02-01T00:00:00Z",
            singleEvents=False,
        )

    def test_single_page_empty_items_returns_empty_list(self):
        """Response with no 'items' key returns an empty list."""
        response = {}  # items absent
        fake_svc = _make_fake_service([response])
        svc = _build_service_with_fake(fake_svc)

        result = svc.list_events("primary", "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")

        self.assertEqual(result, [])

    def test_single_page_null_items_returns_empty_list(self):
        """Response with items=None is treated as an empty page."""
        response = {"items": None}
        fake_svc = _make_fake_service([response])
        svc = _build_service_with_fake(fake_svc)

        result = svc.list_events("primary", "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")

        self.assertEqual(result, [])


class TestListEventsMultiPage(unittest.TestCase):
    """list_events walks multiple pages via nextPageToken."""

    def test_two_page_walk_accumulates_all_items(self):
        page1 = {"items": [{"id": "ev1"}], "nextPageToken": "tok-abc"}
        page2 = {"items": [{"id": "ev2"}, {"id": "ev3"}]}
        fake_svc = _make_fake_service([page1, page2])
        svc = _build_service_with_fake(fake_svc)

        result = svc.list_events("cal@example.com", "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")

        self.assertEqual(len(result), 3)
        self.assertEqual([e["id"] for e in result], ["ev1", "ev2", "ev3"])

    def test_second_page_call_passes_page_token(self):
        """pageToken must be included in the second call but NOT the first."""
        page1 = {"items": [{"id": "a"}], "nextPageToken": "page-token-2"}
        page2 = {"items": [{"id": "b"}]}
        fake_svc = _make_fake_service([page1, page2])
        svc = _build_service_with_fake(fake_svc)

        svc.list_events("primary", "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")

        calls = fake_svc.events.return_value.list.call_args_list
        self.assertEqual(len(calls), 2)
        # First call must NOT include pageToken
        first_kwargs = calls[0][1]
        self.assertNotIn("pageToken", first_kwargs)
        # Second call must pass the token from page 1
        second_kwargs = calls[1][1]
        self.assertEqual(second_kwargs["pageToken"], "page-token-2")

    def test_three_page_walk_accumulates_all_items(self):
        page1 = {"items": [{"id": "x1"}], "nextPageToken": "tok1"}
        page2 = {"items": [{"id": "x2"}], "nextPageToken": "tok2"}
        page3 = {"items": [{"id": "x3"}]}
        fake_svc = _make_fake_service([page1, page2, page3])
        svc = _build_service_with_fake(fake_svc)

        result = svc.list_events("primary", "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")

        self.assertEqual([e["id"] for e in result], ["x1", "x2", "x3"])

    def test_api_raises_during_multi_page_walk_propagates(self):
        """If the API raises on the second page, the exception propagates to the caller."""
        page1 = {"items": [{"id": "ev1"}], "nextPageToken": "tok"}
        fake_svc = _make_fake_service([page1])
        # Override: second execute() call raises
        call_count = [0]

        def _execute_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return page1
            raise RuntimeError("API error on page 2")

        fake_svc.events.return_value.list.return_value.execute.side_effect = _execute_side_effect
        svc = _build_service_with_fake(fake_svc)

        with self.assertRaises(RuntimeError) as ctx:
            svc.list_events("primary", "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")

        self.assertIn("API error on page 2", str(ctx.exception))


class TestInsertEvent(unittest.TestCase):
    """insert_event delegates to the API and returns the created resource."""

    def test_insert_event_returns_created_resource(self):
        fake_svc = MagicMock()
        created = {"id": "new-ev-id", "summary": "My Event"}
        fake_svc.events.return_value.insert.return_value.execute.return_value = created
        svc = _build_service_with_fake(fake_svc)

        body = {"summary": "My Event", "start": {"date": "2026-01-01"}, "end": {"date": "2026-01-02"}}
        result = svc.insert_event("primary", body)

        self.assertEqual(result, created)
        fake_svc.events.return_value.insert.assert_called_once_with(
            calendarId="primary", body=body
        )

    def test_insert_event_api_error_propagates(self):
        """API error during insert propagates to the caller."""
        fake_svc = MagicMock()
        fake_svc.events.return_value.insert.return_value.execute.side_effect = RuntimeError("insert failed")
        svc = _build_service_with_fake(fake_svc)

        with self.assertRaises(RuntimeError) as ctx:
            svc.insert_event("primary", {"summary": "Failing Event"})

        self.assertIn("insert failed", str(ctx.exception))


class TestGetCalendarTimezone(unittest.TestCase):
    """get_calendar_timezone returns the tz string or None on various failure modes."""

    def test_returns_timezone_string_when_present(self):
        fake_svc = _make_fake_service([], tz_response={"timeZone": "America/Toronto"})
        svc = _build_service_with_fake(fake_svc)

        tz = svc.get_calendar_timezone("primary")

        self.assertEqual(tz, "America/Toronto")
        fake_svc.calendars.return_value.get.assert_called_once_with(calendarId="primary")

    def test_returns_none_when_timezone_is_empty_string(self):
        """An empty timeZone value must return None, not an empty string."""
        fake_svc = _make_fake_service([], tz_response={"timeZone": ""})
        svc = _build_service_with_fake(fake_svc)

        tz = svc.get_calendar_timezone("primary")

        self.assertIsNone(tz)

    def test_returns_none_when_timezone_is_whitespace(self):
        """A whitespace-only timeZone must return None after stripping."""
        fake_svc = _make_fake_service([], tz_response={"timeZone": "   "})
        svc = _build_service_with_fake(fake_svc)

        tz = svc.get_calendar_timezone("primary")

        self.assertIsNone(tz)

    def test_returns_none_when_timezone_key_absent(self):
        """Response dict without 'timeZone' key returns None."""
        fake_svc = _make_fake_service([], tz_response={})
        svc = _build_service_with_fake(fake_svc)

        tz = svc.get_calendar_timezone("primary")

        self.assertIsNone(tz)

    def test_returns_none_when_api_raises_does_not_propagate(self):
        """API exception must be swallowed and None returned — never re-raised.

        This is the critical failure-mode for get_calendar_timezone: callers
        fall back to a default timezone when this returns None. If the exception
        propagated instead, the caller would crash rather than fall back.
        """
        fake_svc = _make_fake_service([], tz_response=None)  # configured to raise
        svc = _build_service_with_fake(fake_svc)

        # Must NOT raise — must return None.
        tz = svc.get_calendar_timezone("primary")

        self.assertIsNone(tz)

    def test_happy_path_timezone_matches_resource_field(self):
        """Timezone from the resource dict is returned verbatim (no casing changes)."""
        fake_svc = _make_fake_service([], tz_response={"timeZone": "Europe/London"})
        svc = _build_service_with_fake(fake_svc)

        tz = svc.get_calendar_timezone("cal@example.com")

        self.assertEqual(tz, "Europe/London")


if __name__ == "__main__":
    unittest.main()
