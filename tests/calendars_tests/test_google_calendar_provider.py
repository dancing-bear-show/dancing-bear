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
    # If set, returned by get_calendar_timezone(); None simulates a lookup failure.
    _calendar_tz: str | None = None

    def list_events(self, calendar_id: str, time_min: str, time_max: str) -> list[dict[str, Any]]:
        return list(self.events)

    def insert_event(self, calendar_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.inserted.append((calendar_id, body))
        result = {"id": "new_ev_1", "summary": body.get("summary", "")}
        result.update(self._insert_result)
        return result

    def get_calendar_timezone(self, calendar_id: str) -> str | None:
        return self._calendar_tz


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


def _allday_event(ev_id: str, summary: str, date: str, days: int = 1) -> dict[str, Any]:
    """Build an all-day event the way calendar/v3 really returns one.

    Google's end.date is EXCLUSIVE — the day AFTER the last covered day — so a
    single-day event on 2026-07-01 comes back as end.date 2026-07-02. The
    earlier fixture set end == start, which no real response does, and so could
    not catch an off-by-one in the exclusive->inclusive conversion.
    """
    import datetime as _d

    start = _d.date.fromisoformat(date)
    return {
        "id": ev_id,
        "summary": summary,
        "start": {"date": date},
        "end": {"date": (start + _d.timedelta(days=days)).isoformat()},
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
            "r5", "Triathlon Prep",
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

    def test_malformed_interval_skipped_not_silently_dropped(self) -> None:
        """A non-integer INTERVAL must skip, not degrade to plain weekly.

        Swallowing the ValueError left interval=None, so a series declaring
        INTERVAL=abc exported as an ordinary weekly event — a wrong plan that
        still passes every count-based check.
        """
        ev = _timed_event("s10", "Class",
                          "2026-01-05T09:00:00", "2026-01-05T10:00:00",
                          recurrence=["RRULE:FREQ=WEEKLY;BYDAY=MO;INTERVAL=abc"])
        self._assert_skipped_not_returned(ev, "malformed_interval")

    def test_malformed_count_skipped_not_silently_dropped(self) -> None:
        """A non-integer COUNT must skip, not turn a bounded series unbounded."""
        ev = _timed_event("s11", "Standup",
                          "2026-02-02T14:00:00", "2026-02-02T14:30:00",
                          recurrence=["RRULE:FREQ=DAILY;COUNT=xyz"])
        self._assert_skipped_not_returned(ev, "malformed_count")

    def test_valid_interval_and_count_still_parse(self) -> None:
        """The skip must not fire on well-formed values — no regression."""
        provider = self._provider_with(_timed_event(
            "ok1", "Class", "2026-01-05T09:00:00", "2026-01-05T10:00:00",
            recurrence=["RRULE:FREQ=WEEKLY;BYDAY=MO;INTERVAL=3"],
        ))
        results = provider.list_events(("2026-01-01", "2026-12-31"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].interval, 3)
        self.assertEqual(provider.skipped, [])

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
            # interval omitted: CalendarEvent's documented semantics are that
            # 1 is represented as absent/None, so passing interval=1 here would
            # contradict the shared model and could mask a normalization bug.
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


class TestBuildRruleRefusesUnknownRepeat(unittest.TestCase):
    """An unrecognised repeat must raise, not silently become WEEKLY.

    Defaulting to WEEKLY persists a recurrence the caller never asked for —
    writing a wrong rule into a real calendar, which is worse than the
    read-side degradation this provider already refuses.
    """

    def test_unknown_repeat_raises(self) -> None:
        from calendars.gmail_pipelines import CalendarEvent
        from calendars.importer.google_provider import _build_rrule

        event = CalendarEvent(
            id="", subject="Anniversary", start="2026-06-15T12:00:00",
            end="2026-06-15T13:00:00", calendar="primary", repeat="yearly",
        )
        with self.assertRaises(ValueError) as ctx:
            _build_rrule(event)
        self.assertIn("yearly", str(ctx.exception))

    def test_known_repeats_still_build(self) -> None:
        from calendars.gmail_pipelines import CalendarEvent
        from calendars.importer.google_provider import _build_rrule

        for repeat, freq in (("daily", "DAILY"), ("weekly", "WEEKLY"), ("monthly", "MONTHLY")):
            with self.subTest(repeat=repeat):
                event = CalendarEvent(
                    id="", subject="X", start="2026-06-15T12:00:00",
                    end="2026-06-15T13:00:00", calendar="primary", repeat=repeat,
                )
                self.assertIn(f"FREQ={freq}", _build_rrule(event))


class TestTimezoneResolution(unittest.TestCase):
    """_resolve_tz resolution order: event.tz > calendar API > America/Toronto fallback.

    The bug: ``event.tz or "UTC"`` silently shifted non-UTC users' events.
    These tests guard the corrected resolution order on the insert/write path.
    """

    def _provider(self, calendar_tz: str | None = "America/Vancouver") -> tuple[Any, Any]:
        """Return (provider, svc) with an optional calendar timezone lookup stub."""
        from calendars.importer.google_provider import GoogleCalendarProvider
        svc = _FakeSvc(_calendar_tz=calendar_tz)
        return GoogleCalendarProvider(svc=svc, calendar_id="primary"), svc

    # ------------------------------------------------------------------
    # Explicit event.tz wins
    # ------------------------------------------------------------------

    def test_explicit_event_tz_is_used(self) -> None:
        """event.tz, when set, takes priority over any calendar lookup."""
        from calendars.gmail_pipelines import CalendarEvent
        provider, svc = self._provider(calendar_tz="America/Vancouver")
        event = CalendarEvent(
            id="", subject="Meeting",
            start="2026-09-01T10:00:00", end="2026-09-01T11:00:00",
            calendar="primary", tz="America/New_York",
        )
        provider.add_event(event)
        _, body = svc.inserted[0]
        self.assertEqual(body["start"]["timeZone"], "America/New_York")
        self.assertEqual(body["end"]["timeZone"], "America/New_York")

    def test_explicit_event_tz_is_used_even_when_calendar_api_differs(self) -> None:
        """Caller's tz is not overridden by the calendar API result."""
        from calendars.gmail_pipelines import CalendarEvent
        provider, svc = self._provider(calendar_tz="Europe/London")
        event = CalendarEvent(
            id="", subject="Standup",
            start="2026-09-02T14:00:00", end="2026-09-02T14:30:00",
            calendar="primary", tz="America/Toronto",
        )
        provider.add_event(event)
        _, body = svc.inserted[0]
        self.assertEqual(body["start"]["timeZone"], "America/Toronto")

    # ------------------------------------------------------------------
    # Calendar API lookup when event.tz is absent
    # ------------------------------------------------------------------

    def test_absent_tz_resolves_calendar_api(self) -> None:
        """When event.tz is None the calendar's own timezone is used."""
        from calendars.gmail_pipelines import CalendarEvent
        provider, svc = self._provider(calendar_tz="America/Vancouver")
        event = CalendarEvent(
            id="", subject="Yoga",
            start="2026-09-03T07:00:00", end="2026-09-03T08:00:00",
            calendar="primary",
            # tz intentionally omitted — CalendarEvent.tz defaults to None
        )
        provider.add_event(event)
        _, body = svc.inserted[0]
        self.assertEqual(body["start"]["timeZone"], "America/Vancouver")

    def test_calendar_api_is_called_only_once(self) -> None:
        """The calendar timezone lookup is cached — not repeated per event."""
        from calendars.gmail_pipelines import CalendarEvent
        provider, _svc = self._provider(calendar_tz="America/Chicago")
        call_count = [0]
        original = _svc.get_calendar_timezone

        def _counting(cal_id: str) -> str | None:
            call_count[0] += 1
            return original(cal_id)

        _svc.get_calendar_timezone = _counting

        for i in range(3):
            event = CalendarEvent(
                id="", subject=f"Event {i}",
                start="2026-09-01T10:00:00", end="2026-09-01T11:00:00",
                calendar="primary",
            )
            provider.add_event(event)

        self.assertEqual(call_count[0], 1, "get_calendar_timezone must be called at most once")

    # ------------------------------------------------------------------
    # Fallback when calendar API returns nothing
    # ------------------------------------------------------------------

    def test_fallback_when_calendar_api_returns_none(self) -> None:
        """When the API returns None, fall back to America/Toronto — not UTC."""
        from calendars.gmail_pipelines import CalendarEvent
        provider, svc = self._provider(calendar_tz=None)
        event = CalendarEvent(
            id="", subject="Fallback Event",
            start="2026-09-04T17:00:00", end="2026-09-04T18:00:00",
            calendar="primary",
        )
        provider.add_event(event)
        _, body = svc.inserted[0]
        self.assertEqual(body["start"]["timeZone"], "America/Toronto")

    # ------------------------------------------------------------------
    # Regression guard: UTC must NOT appear when calendar is non-UTC and
    # event.tz is unset — this is the exact defect from PR #254.
    # ------------------------------------------------------------------

    def test_no_utc_default_for_non_utc_calendar(self) -> None:
        """Regression: body timeZone must not be UTC when calendar is non-UTC and event.tz is unset.

        This is the exact defect from PR #254: ``event.tz or "UTC"`` shifted a
        5:00 pm America/Toronto event to 9:00 pm UTC in the stored calendar.
        """
        from calendars.gmail_pipelines import CalendarEvent
        provider, svc = self._provider(calendar_tz="America/Toronto")
        event = CalendarEvent(
            id="", subject="Doctor Appointment",
            start="2026-10-01T17:00:00", end="2026-10-01T17:30:00",
            calendar="primary",
            # tz is unset — this was the bug trigger
        )
        provider.add_event(event)
        _, body = svc.inserted[0]
        self.assertNotEqual(
            body["start"]["timeZone"], "UTC",
            "body timeZone must not be UTC when the calendar is America/Toronto and event.tz is unset",
        )
        self.assertEqual(body["start"]["timeZone"], "America/Toronto")

    # ------------------------------------------------------------------
    # All-day branch stays timezone-free
    # ------------------------------------------------------------------

    def test_all_day_event_has_no_timezone(self) -> None:
        """All-day events use date (not dateTime) and must have no timeZone field."""
        from calendars.gmail_pipelines import CalendarEvent
        provider, svc = self._provider(calendar_tz="America/Toronto")
        event = CalendarEvent(
            id="", subject="Holiday",
            start="2026-12-25", end="2026-12-25",
            calendar="primary",
        )
        provider.add_event(event)
        _, body = svc.inserted[0]
        # All-day uses the date key, not dateTime
        self.assertIn("date", body["start"])
        self.assertNotIn("timeZone", body["start"])
        self.assertNotIn("dateTime", body["start"])
        self.assertIn("date", body["end"])
        self.assertNotIn("timeZone", body["end"])


def _scopes() -> list[str]:
    from mail.gmail_api import SCOPES

    return list(SCOPES)


def _write_token(scopes: list[str]) -> str:
    """Write a temp token file recording ``scopes``; return its path."""
    token_data = {
        "token": "fake_access_token",
        "refresh_token": "fake_refresh_token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "fake_client_id",
        "client_secret": "fake_client_secret",
        "scopes": scopes,
        "expiry": "2099-01-01T00:00:00Z",
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(token_data, f)
        return f.name


class TestScopeRegression(unittest.TestCase):
    """Verify that the calendar scope is present in SCOPES and stale detection works."""

    def test_calendar_scope_in_scopes(self) -> None:
        from mail.gmail_api import SCOPES
        self.assertIn(
            "https://www.googleapis.com/auth/calendar",
            SCOPES,
            "Calendar scope must be present in mail.gmail_api.SCOPES",
        )

    def test_stale_scope_records_missing_and_authenticate_raises(self) -> None:
        """_load_token records the missing scopes; authenticate() raises.

        It does not print — the message a user sees comes from the AuthError
        hint raised by authenticate(). Naming the test for printing would
        misdescribe the contract and make a failure harder to read.
        """
        from mail.gmail_api import GmailClient

        stale_scopes = [s for s in _scopes() if s != "https://www.googleapis.com/auth/calendar"]
        token_path = _write_token(stale_scopes)

        try:
            client = GmailClient(credentials_path="/dev/null", token_path=token_path)

            # Use the REAL google.oauth2 Credentials here. Mocking it and
            # hand-setting mock_creds.scopes to the stale list manufactures
            # behaviour the library does not have: from_authorized_user_file
            # sets creds.scopes to the SCOPES argument it is given, NOT to what
            # the file records. A mocked version of this test passes against an
            # implementation that reads creds.scopes and can therefore never
            # detect a missing scope — which is exactly the bug it missed.
            result = client._load_token()

            self.assertIsNone(result, "_load_token must return None for stale scopes")
            self.assertIn(
                "https://www.googleapis.com/auth/calendar",
                getattr(client, "_stale_scopes", []),
                "_load_token must record which scopes are missing",
            )

            # Returning None is not enough on its own: authenticate() cannot
            # tell "no token" from "stale token" by that signal alone, and
            # would open a browser for both. The default path must hard-stop.
            from core.cli_errors import AuthError

            with self.assertRaises(AuthError) as ctx:
                client.authenticate()
            self.assertIn("calendar", str(ctx.exception).lower())
        finally:
            os.unlink(token_path)

    def test_stale_scope_does_not_launch_browser_by_default(self) -> None:
        """A non-auth command must never be ambushed by a consent screen."""
        stale = [s for s in _scopes() if s != "https://www.googleapis.com/auth/calendar"]
        token_path = _write_token(stale)
        try:
            from core.cli_errors import AuthError
            from mail.gmail_api import GmailClient

            client = GmailClient(credentials_path="/dev/null", token_path=token_path)
            with patch.object(GmailClient, "_run_auth_flow_and_save") as flow:
                with self.assertRaises(AuthError):
                    client.authenticate()
            flow.assert_not_called()
        finally:
            os.unlink(token_path)

    def test_explicit_auth_entrypoint_may_re_consent(self) -> None:
        """`mail auth` opts in, so re-consent stays possible."""
        stale = [s for s in _scopes() if s != "https://www.googleapis.com/auth/calendar"]
        token_path = _write_token(stale)
        try:
            from mail.gmail_api import GmailClient

            client = GmailClient(credentials_path="/dev/null", token_path=token_path)
            with patch.object(GmailClient, "_run_auth_flow_and_save") as flow:
                with patch("mail.gmail_api.build"):
                    client.authenticate(allow_interactive=True)
            flow.assert_called_once()
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
