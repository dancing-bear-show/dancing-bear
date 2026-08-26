"""Unit tests for GoogleCalendarProvider.

Covers:
- RRULE parsing: weekly with BYDAY+INTERVAL, daily, monthly, UNTIL vs COUNT
- Unrepresentable forms (FREQ=YEARLY, BYSETPOS, BYMONTHDAY, multiple RRULEs, RDATE) skipped
- EXDATE -> exdates
- All-day event
- add_event emits a correct RRULE for a recurring CalendarEvent
- isinstance(provider, CalendarProvider) conformance
- Scope regression: calendar scope present in SCOPES
- Stale-scope detection: stored token missing calendar scope -> clear message
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Fake GoogleCalendarService
# ---------------------------------------------------------------------------

@dataclass
class _FakeSvc:
    """Minimal fake satisfying GoogleCalendarService's interface."""

    events: list[dict[str, Any]] = field(default_factory=list)
    inserted: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    _insert_result: dict[str, Any] = field(default_factory=dict)

    def list_events(self, calendar_id: str, time_min: str, time_max: str) -> list[dict[str, Any]]:
        return list(self.events)

    def insert_event(self, calendar_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.inserted.append((calendar_id, body))
        result = {"id": "new_ev_1", "summary": body.get("summary", "")}
        result.update(self._insert_result)
        return result


# ---------------------------------------------------------------------------
# Helpers to build Google Calendar API event dicts
# ---------------------------------------------------------------------------

def _timed_event(
    ev_id: str,
    summary: str,
    start_dt: str,
    end_dt: str,
    tz: str = "America/Toronto",
    location: str | None = None,
    recurrence: list[str] | None = None,
) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "id": ev_id,
        "summary": summary,
        "start": {"dateTime": start_dt, "timeZone": tz},
        "end": {"dateTime": end_dt, "timeZone": tz},
    }
    if location:
        ev["location"] = location
    if recurrence:
        ev["recurrence"] = recurrence
    return ev


def _allday_event(ev_id: str, summary: str, date: str) -> dict[str, Any]:
    return {
        "id": ev_id,
        "summary": summary,
        "start": {"date": date},
        "end": {"date": date},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGoogleCalendarProviderConformance(unittest.TestCase):
    """Verify CalendarProvider protocol conformance."""

    def test_isinstance_calendar_provider(self) -> None:
        from calendars.importer.google_provider import GoogleCalendarProvider
        from calendars.importer.base import CalendarProvider

        svc = _FakeSvc()
        provider = GoogleCalendarProvider(svc=svc)
        self.assertIsInstance(provider, CalendarProvider)


class TestListEventsNonRecurring(unittest.TestCase):
    def _make_provider(self, events: list[dict[str, Any]]):
        from calendars.importer.google_provider import GoogleCalendarProvider
        svc = _FakeSvc(events=events)
        return GoogleCalendarProvider(svc=svc, calendar_id="primary")

    def test_single_timed_event(self) -> None:
        ev = _timed_event("e1", "Meeting", "2026-03-01T10:00:00", "2026-03-01T11:00:00")
        provider = self._make_provider([ev])
        results = provider.list_events(("2026-03-01", "2026-04-01"))

        self.assertEqual(len(results), 1)
        ce = results[0]
        self.assertEqual(ce.id, "e1")
        self.assertEqual(ce.subject, "Meeting")
        self.assertEqual(ce.start, "2026-03-01T10:00:00")
        self.assertEqual(ce.end, "2026-03-01T11:00:00")
        self.assertEqual(ce.tz, "America/Toronto")
        self.assertIsNone(ce.repeat)
        self.assertEqual(ce.byday, [])

    def test_all_day_event(self) -> None:
        ev = _allday_event("e2", "Holiday", "2026-07-01")
        provider = self._make_provider([ev])
        results = provider.list_events(("2026-07-01", "2026-08-01"))

        self.assertEqual(len(results), 1)
        ce = results[0]
        self.assertEqual(ce.id, "e2")
        self.assertEqual(ce.subject, "Holiday")
        self.assertEqual(ce.start, "2026-07-01")
        self.assertEqual(ce.end, "2026-07-01")
        self.assertIsNone(ce.tz)
        self.assertIsNone(ce.repeat)

    def test_event_with_location(self) -> None:
        ev = _timed_event("e3", "Gym", "2026-03-01T09:00:00", "2026-03-01T10:00:00", location="The Gym")
        provider = self._make_provider([ev])
        results = provider.list_events(("2026-03-01", "2026-04-01"))
        self.assertEqual(results[0].location, "The Gym")


class TestRRULEParsing(unittest.TestCase):
    """RRULE parsing: assert CalendarEvent fields key-by-key."""

    def _provider_with(self, ev: dict[str, Any]):
        from calendars.importer.google_provider import GoogleCalendarProvider
        svc = _FakeSvc(events=[ev])
        return GoogleCalendarProvider(svc=svc, calendar_id="primary")

    def test_weekly_byday_interval_until(self) -> None:
        ev = _timed_event(
            "r1", "Class",
            "2026-01-05T09:00:00", "2026-01-05T10:00:00",
            recurrence=["RRULE:FREQ=WEEKLY;BYDAY=MO,WE;INTERVAL=2;UNTIL=20260630T235959Z"],
        )
        provider = self._provider_with(ev)
        results = provider.list_events(("2026-01-01", "2026-07-01"))

        self.assertEqual(len(results), 1)
        ce = results[0]
        self.assertEqual(ce.repeat, "weekly")
        self.assertEqual(ce.byday, ["MO", "WE"])  # uppercase 2-char
        self.assertEqual(ce.interval, 2)           # > 1, so set
        self.assertIsNotNone(ce.range)
        self.assertEqual(ce.range["until"], "2026-06-30")
        self.assertIsNone(ce.count)
        self.assertEqual(ce.start_time, "09:00")
        self.assertEqual(ce.end_time, "10:00")

    def test_weekly_no_interval_uses_none(self) -> None:
        """interval=1 must produce None, not 1."""
        ev = _timed_event(
            "r2", "Standup",
            "2026-02-02T14:00:00", "2026-02-02T14:30:00",
            recurrence=["RRULE:FREQ=WEEKLY;BYDAY=MO;INTERVAL=1"],
        )
        provider = self._provider_with(ev)
        results = provider.list_events(("2026-02-01", "2026-03-01"))

        self.assertEqual(len(results), 1)
        ce = results[0]
        self.assertEqual(ce.repeat, "weekly")
        self.assertEqual(ce.byday, ["MO"])
        self.assertIsNone(ce.interval)  # interval=1 -> None

    def test_daily_no_byday(self) -> None:
        ev = _timed_event(
            "r3", "Morning Run",
            "2026-04-01T07:00:00", "2026-04-01T07:30:00",
            recurrence=["RRULE:FREQ=DAILY;COUNT=10"],
        )
        provider = self._provider_with(ev)
        results = provider.list_events(("2026-04-01", "2026-04-30"))

        self.assertEqual(len(results), 1)
        ce = results[0]
        self.assertEqual(ce.repeat, "daily")
        self.assertEqual(ce.byday, [])
        self.assertIsNone(ce.interval)
        self.assertEqual(ce.count, 10)
        self.assertIsNone(ce.range)

    def test_monthly_with_until(self) -> None:
        ev = _timed_event(
            "r4", "Monthly Review",
            "2026-01-15T13:00:00", "2026-01-15T14:00:00",
            recurrence=["RRULE:FREQ=MONTHLY;UNTIL=20261215T235959Z"],
        )
        provider = self._provider_with(ev)
        results = provider.list_events(("2026-01-01", "2026-12-31"))

        self.assertEqual(len(results), 1)
        ce = results[0]
        self.assertEqual(ce.repeat, "monthly")
        self.assertIsNone(ce.interval)
        self.assertIsNone(ce.count)
        self.assertIsNotNone(ce.range)
        self.assertEqual(ce.range["until"], "2026-12-15")

    def test_byday_values_are_uppercase(self) -> None:
        """RRULE already uses uppercase; verify we don't accidentally lowercase them."""
        ev = _timed_event(
            "r5", "Triathalon Prep",
            "2026-05-01T06:00:00", "2026-05-01T07:00:00",
            recurrence=["RRULE:FREQ=WEEKLY;BYDAY=TU,TH,SA"],
        )
        provider = self._provider_with(ev)
        results = provider.list_events(("2026-05-01", "2026-06-01"))
        ce = results[0]
        for day in ce.byday:
            self.assertEqual(day, day.upper(), f"byday value {day!r} should be uppercase")


class TestUnrepresentableRRULEsSkipped(unittest.TestCase):
    """Unrepresentable recurrence forms must be skipped and recorded — never returned degraded."""

    def _provider_with(self, ev: dict[str, Any]):
        from calendars.importer.google_provider import GoogleCalendarProvider
        svc = _FakeSvc(events=[ev])
        return GoogleCalendarProvider(svc=svc, calendar_id="primary")

    def _assert_skipped_not_returned(self, ev: dict[str, Any], reason_fragment: str) -> None:
        provider = self._provider_with(ev)
        results = provider.list_events(("2026-01-01", "2026-12-31"))
        self.assertEqual(results, [], "Unrepresentable event must not be returned")
        self.assertEqual(len(provider.skipped), 1, "Unrepresentable event must be recorded in skipped")
        skip = provider.skipped[0]
        self.assertIn("reason", skip, "skipped entry must have a 'reason' key")
        self.assertIn(
            reason_fragment.lower(), skip["reason"].lower(),
            f"Expected {reason_fragment!r} in reason {skip['reason']!r}",
        )

    def test_freq_yearly_skipped(self) -> None:
        ev = _timed_event("s1", "Anniversary",
                          "2026-06-15T12:00:00", "2026-06-15T13:00:00",
                          recurrence=["RRULE:FREQ=YEARLY"])
        self._assert_skipped_not_returned(ev, "yearly")

    def test_bysetpos_skipped(self) -> None:
        ev = _timed_event("s2", "Third Monday",
                          "2026-03-16T09:00:00", "2026-03-16T10:00:00",
                          recurrence=["RRULE:FREQ=MONTHLY;BYDAY=MO;BYSETPOS=3"])
        self._assert_skipped_not_returned(ev, "bysetpos")

    def test_bymonthday_skipped(self) -> None:
        ev = _timed_event("s3", "15th of Month",
                          "2026-01-15T10:00:00", "2026-01-15T11:00:00",
                          recurrence=["RRULE:FREQ=MONTHLY;BYMONTHDAY=15"])
        self._assert_skipped_not_returned(ev, "bymonthday")

    def test_multiple_rrules_skipped(self) -> None:
        ev = _timed_event("s4", "Complex Recur",
                          "2026-02-02T08:00:00", "2026-02-02T09:00:00",
                          recurrence=[
                              "RRULE:FREQ=WEEKLY;BYDAY=MO",
                              "RRULE:FREQ=MONTHLY;BYMONTHDAY=1",
                          ])
        self._assert_skipped_not_returned(ev, "multiple_rrules")

    def test_rdate_skipped(self) -> None:
        ev = _timed_event("s5", "One-off Extra",
                          "2026-03-01T10:00:00", "2026-03-01T11:00:00",
                          recurrence=["RDATE;TZID=America/Toronto:20260301T100000"])
        self._assert_skipped_not_returned(ev, "rdate")

    def test_skipped_is_reset_on_each_list_events_call(self) -> None:
        """provider.skipped resets each call — stale skip data must not accumulate."""
        from calendars.importer.google_provider import GoogleCalendarProvider
        ev_bad = _timed_event("s6", "Yearly", "2026-01-01T00:00:00", "2026-01-01T01:00:00",
                              recurrence=["RRULE:FREQ=YEARLY"])
        ev_ok = _timed_event("s7", "Good", "2026-01-01T00:00:00", "2026-01-01T01:00:00")
        svc = _FakeSvc(events=[ev_bad])
        provider = GoogleCalendarProvider(svc=svc)
        provider.list_events(("2026-01-01", "2026-12-31"))
        self.assertEqual(len(provider.skipped), 1)

        svc.events = [ev_ok]
        results = provider.list_events(("2026-01-01", "2026-12-31"))
        self.assertEqual(provider.skipped, [], "skipped must reset on each call")
        self.assertEqual(len(results), 1)


class TestEXDATEParsing(unittest.TestCase):
    """EXDATE lines in the recurrence list must become exdates on CalendarEvent."""

    def test_exdate_single(self) -> None:
        from calendars.importer.google_provider import GoogleCalendarProvider
        ev = _timed_event(
            "ex1", "Weekly",
            "2026-05-04T09:00:00", "2026-05-04T10:00:00",
            recurrence=[
                "RRULE:FREQ=WEEKLY;BYDAY=MO",
                "EXDATE;TZID=America/Toronto:20260511T090000",
            ],
        )
        svc = _FakeSvc(events=[ev])
        provider = GoogleCalendarProvider(svc=svc)
        results = provider.list_events(("2026-05-01", "2026-06-01"))

        self.assertEqual(len(results), 1)
        ce = results[0]
        self.assertIn("2026-05-11", ce.exdates)

    def test_exdate_multiple(self) -> None:
        from calendars.importer.google_provider import GoogleCalendarProvider
        ev = _timed_event(
            "ex2", "Daily",
            "2026-06-01T08:00:00", "2026-06-01T09:00:00",
            recurrence=[
                "RRULE:FREQ=DAILY",
                "EXDATE:20260603,20260610",
            ],
        )
        svc = _FakeSvc(events=[ev])
        provider = GoogleCalendarProvider(svc=svc)
        results = provider.list_events(("2026-06-01", "2026-06-30"))

        self.assertEqual(len(results), 1)
        ce = results[0]
        self.assertIn("2026-06-03", ce.exdates)
        self.assertIn("2026-06-10", ce.exdates)


class TestAddEvent(unittest.TestCase):
    """add_event translates CalendarEvent to calendar/v3 body and returns persisted event."""

    def _provider(self):
        from calendars.importer.google_provider import GoogleCalendarProvider
        svc = _FakeSvc()
        return GoogleCalendarProvider(svc=svc, calendar_id="primary"), svc

    def test_add_single_timed_event(self) -> None:
        from calendars.gmail_pipelines import CalendarEvent
        provider, svc = self._provider()
        event = CalendarEvent(
            id="",
            subject="Team Lunch",
            start="2026-09-10T12:00:00",
            end="2026-09-10T13:00:00",
            calendar="primary",
            tz="America/Toronto",
            location="Cafe",
        )
        result = provider.add_event(event)

        self.assertEqual(len(svc.inserted), 1)
        _cal_id, body = svc.inserted[0]
        self.assertEqual(_cal_id, "primary")
        self.assertEqual(body["summary"], "Team Lunch")
        self.assertEqual(body["location"], "Cafe")
        self.assertEqual(body["start"]["dateTime"], "2026-09-10T12:00:00")
        self.assertNotIn("recurrence", body)
        self.assertEqual(result.id, "new_ev_1")
        # A non-recurring event must come back non-recurring — the recurrence
        # carry-forward must not invent a repeat that was never submitted.
        self.assertEqual(result.subject, "Team Lunch")
        self.assertIsNone(result.repeat)
        self.assertEqual(result.byday, [])
        self.assertEqual(result.location, "Cafe")

    def test_add_recurring_weekly_emits_rrule(self) -> None:
        from calendars.gmail_pipelines import CalendarEvent
        provider, svc = self._provider()
        event = CalendarEvent(
            id="",
            subject="Yoga",
            start="2026-10-05T07:00:00",
            end="2026-10-05T08:00:00",
            calendar="primary",
            tz="America/Toronto",
            repeat="weekly",
            byday=["MO", "WE", "FR"],
            interval=1,
            range={"start_date": "2026-10-05", "until": "2026-12-31"},
        )
        result = provider.add_event(event)

        # The persisted event must come back with its recurrence intact — a
        # caller reads the return value, not the request it just sent.
        self.assertEqual(result.subject, "Yoga")
        self.assertEqual(result.repeat, "weekly")
        self.assertEqual(result.byday, ["MO", "WE", "FR"])

        self.assertEqual(len(svc.inserted), 1)
        _cal_id, body = svc.inserted[0]
        recurrence = body.get("recurrence", [])
        self.assertTrue(any("RRULE:" in r for r in recurrence), "RRULE must be present in recurrence")
        rrule_line = next(r for r in recurrence if "RRULE:" in r)
        self.assertIn("FREQ=WEEKLY", rrule_line)
        self.assertIn("BYDAY=MO,WE,FR", rrule_line)
        # interval=1 -> omitted from RRULE
        self.assertNotIn("INTERVAL", rrule_line)
        self.assertIn("UNTIL=20261231", rrule_line)

    def test_add_recurring_daily_with_count(self) -> None:
        from calendars.gmail_pipelines import CalendarEvent
        provider, svc = self._provider()
        event = CalendarEvent(
            id="",
            subject="Sprint Daily",
            start="2026-11-01T09:00:00",
            end="2026-11-01T09:15:00",
            calendar="primary",
            repeat="daily",
            count=10,
        )
        provider.add_event(event)

        _cal_id, body = svc.inserted[0]
        rrule_line = next(r for r in body["recurrence"] if "RRULE:" in r)
        self.assertIn("FREQ=DAILY", rrule_line)
        self.assertIn("COUNT=10", rrule_line)
        self.assertNotIn("UNTIL", rrule_line)

    def test_add_event_with_interval_gt_1(self) -> None:
        from calendars.gmail_pipelines import CalendarEvent
        provider, svc = self._provider()
        event = CalendarEvent(
            id="",
            subject="Bi-weekly",
            start="2026-10-01T10:00:00",
            end="2026-10-01T11:00:00",
            calendar="primary",
            repeat="weekly",
            byday=["TH"],
            interval=2,
        )
        provider.add_event(event)

        _cal_id, body = svc.inserted[0]
        rrule_line = next(r for r in body["recurrence"] if "RRULE:" in r)
        self.assertIn("INTERVAL=2", rrule_line)


class TestScopeRegression(unittest.TestCase):
    """Verify that the calendar scope is present in SCOPES and stale detection works."""

    def test_calendar_scope_in_scopes(self) -> None:
        from mail.gmail_api import SCOPES
        self.assertIn(
            "https://www.googleapis.com/auth/calendar",
            SCOPES,
            "Calendar scope must be present in mail.gmail_api.SCOPES",
        )

    def test_stale_scope_detection_prints_message_and_returns_none(self) -> None:
        """A stored token that lacks the calendar scope should print a message and return None."""
        from mail.gmail_api import GmailClient, SCOPES

        # Build a fake token JSON that omits the calendar scope
        stale_scopes = [s for s in SCOPES if s != "https://www.googleapis.com/auth/calendar"]
        token_data = {
            "token": "fake_access_token",
            "refresh_token": "fake_refresh_token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "fake_client_id",
            "client_secret": "fake_client_secret",
            "scopes": stale_scopes,
            "expiry": "2099-01-01T00:00:00Z",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(token_data, f)
            token_path = f.name

        try:
            client = GmailClient(credentials_path="/dev/null", token_path=token_path)

            # Use the REAL google.oauth2 Credentials here. Mocking it and
            # hand-setting mock_creds.scopes to the stale list manufactures
            # behaviour the library does not have: from_authorized_user_file
            # sets creds.scopes to the SCOPES argument it is given, NOT to what
            # the file records. A mocked version of this test passes against an
            # implementation that reads creds.scopes and can therefore never
            # detect a missing scope — which is exactly the bug it missed.
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                result = client._load_token()

            self.assertIsNone(result, "_load_token must return None for stale scopes")
            output = buf.getvalue()
            self.assertIn("calendar", output.lower(), "Message must name the missing scope")
            self.assertIn("./bin/mail auth", output, "Message must direct user to ./bin/mail auth")
        finally:
            os.unlink(token_path)

    def test_missing_token_file_no_warning(self) -> None:
        """A token file that does not exist at all is a first-time-auth case — no warning."""
        from mail.gmail_api import GmailClient

        client = GmailClient(credentials_path="/dev/null", token_path="/nonexistent/token.json")

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            result = client._load_token()

        self.assertIsNone(result)
        self.assertEqual(buf.getvalue(), "", "No warning for missing token file (first-time auth)")


if __name__ == "__main__":
    unittest.main()
