"""Unit tests for OutlookCalendarProvider.

Covers:
- one-off event round-trip
- weekly recurring series (repeat/byday/interval/range, uppercase 2-char byday)
- all-day event
- unsupported recurrence patterns skipped and recorded (not returned degraded)
- add_event routing: single and recurring
- isinstance(provider, CalendarProvider) conformance
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Fake service
# ---------------------------------------------------------------------------

@dataclass
class _FakeSvc:
    """Minimal fake that satisfies OutlookCalendarProvider's service contract."""

    events: list[dict[str, Any]] = field(default_factory=list)
    # event_id -> master dict (for get_event)
    masters: dict[str, dict[str, Any]] = field(default_factory=dict)
    created: list[tuple[str, Any]] = field(default_factory=list)

    def list_events_in_range(self, params) -> list[dict[str, Any]]:  # NOSONAR - fake interface
        return list(self.events)

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        return self.masters.get(event_id)

    def get_mailbox_timezone(self) -> str | None:
        return "America/Toronto"

    def create_event(self, params) -> dict[str, Any]:
        evt = {"id": f"new_evt_{len(self.created)}", "subject": params.subject}
        self.created.append(("single", params))
        return evt

    def create_recurring_event(self, params) -> dict[str, Any]:
        evt = {"id": f"new_rec_{len(self.created)}", "subject": params.subject}
        self.created.append(("recurring", params))
        return evt


# ---------------------------------------------------------------------------
# Graph dict factories
# ---------------------------------------------------------------------------

def _single(
    event_id: str,
    subject: str,
    start_dt: str,
    end_dt: str,
    tz: str = "America/Toronto",
    location: str | None = None,
) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "id": event_id,
        "type": "singleInstance",
        "subject": subject,
        "start": {"dateTime": start_dt, "timeZone": tz},
        "end": {"dateTime": end_dt, "timeZone": tz},
        "location": {"displayName": location} if location else {},
    }
    return ev


def _allday(event_id: str, subject: str, date: str) -> dict[str, Any]:
    return {
        "id": event_id,
        "type": "singleInstance",
        "isAllDay": True,
        "subject": subject,
        "start": {"date": date},
        "end": {"date": date},
        "location": {},
    }


def _occurrence(subject: str, master_id: str) -> dict[str, Any]:
    return {
        "type": "occurrence",
        "subject": subject,
        "seriesMasterId": master_id,
        "start": {"dateTime": "2026-01-06T18:00:00", "timeZone": "America/Toronto"},
        "end": {"dateTime": "2026-01-06T19:00:00", "timeZone": "America/Toronto"},
        "location": {},
    }


def _weekly_master(
    master_id: str,
    subject: str,
    days_of_week: list[str],
    start_date: str,
    end_date: str,
    tz: str = "America/Toronto",
    interval: int = 1,
) -> dict[str, Any]:
    return {
        "id": master_id,
        "type": "seriesMaster",
        "subject": subject,
        "start": {"dateTime": f"{start_date}T18:00:00", "timeZone": tz},
        "end": {"dateTime": f"{start_date}T19:00:00", "timeZone": tz},
        "location": {},
        "recurrence": {
            "pattern": {
                "type": "weekly",
                "interval": interval,
                "daysOfWeek": days_of_week,
            },
            "range": {
                "type": "endDate",
                "startDate": start_date,
                "endDate": end_date,
            },
        },
    }


def _unsupported_master(master_id: str, subject: str, pattern_type: str) -> dict[str, Any]:
    return {
        "id": master_id,
        "type": "seriesMaster",
        "subject": subject,
        "start": {"dateTime": "2026-01-01T09:00:00", "timeZone": "America/Toronto"},
        "end": {"dateTime": "2026-01-01T10:00:00", "timeZone": "America/Toronto"},
        "location": {},
        "recurrence": {
            "pattern": {
                "type": pattern_type,
                "interval": 1,
            },
            "range": {
                "type": "noEnd",
                "startDate": "2026-01-01",
            },
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProtocolConformance(unittest.TestCase):
    """isinstance check — proves shape, not behaviour."""

    def test_provider_satisfies_protocol(self):
        from calendars.importer.base import CalendarProvider
        from calendars.importer.outlook_provider import OutlookCalendarProvider

        provider = OutlookCalendarProvider(svc=_FakeSvc())
        self.assertIsInstance(provider, CalendarProvider)


class TestListEventsOneOff(unittest.TestCase):
    """One-off event round-trip."""

    def setUp(self):
        from calendars.importer.outlook_provider import OutlookCalendarProvider

        ev = _single(
            "evt-001",
            "Synthetic Meeting",
            "2026-03-10T09:00:00",
            "2026-03-10T10:00:00",
            tz="America/Toronto",
            location="Room A",
        )
        svc = _FakeSvc(events=[ev])
        self.provider = OutlookCalendarProvider(svc=svc, calendar_name="Work")

    def test_returns_one_event(self):
        events = self.provider.list_events(("2026-03-01", "2026-03-31"))
        self.assertEqual(len(events), 1)

    def test_id_field(self):
        events = self.provider.list_events(("2026-03-01", "2026-03-31"))
        self.assertEqual(events[0].id, "evt-001")

    def test_subject_field(self):
        events = self.provider.list_events(("2026-03-01", "2026-03-31"))
        self.assertEqual(events[0].subject, "Synthetic Meeting")

    def test_start_and_end_fields(self):
        events = self.provider.list_events(("2026-03-01", "2026-03-31"))
        self.assertIn("2026-03-10", events[0].start)
        self.assertIn("2026-03-10", events[0].end)

    def test_tz_field(self):
        events = self.provider.list_events(("2026-03-01", "2026-03-31"))
        self.assertEqual(events[0].tz, "America/Toronto")

    def test_location_field(self):
        events = self.provider.list_events(("2026-03-01", "2026-03-31"))
        self.assertEqual(events[0].location, "Room A")

    def test_no_skipped(self):
        self.provider.list_events(("2026-03-01", "2026-03-31"))
        self.assertEqual(self.provider.skipped, [])


class TestListEventsWeeklySeries(unittest.TestCase):
    """Weekly recurring series yields correct recurrence fields."""

    def setUp(self):
        from calendars.importer.outlook_provider import OutlookCalendarProvider

        master_id = "master-weekly-001"
        master = _weekly_master(
            master_id,
            "Synthetic Swim Class",
            ["tuesday", "thursday"],
            "2026-01-06",
            "2026-06-30",
            tz="America/Toronto",
            interval=1,
        )
        occ = _occurrence("Synthetic Swim Class", master_id)
        svc = _FakeSvc(events=[occ], masters={master_id: master})
        self.provider = OutlookCalendarProvider(svc=svc, calendar_name="Activities")

    def _event(self):
        events = self.provider.list_events(("2026-01-01", "2026-06-30"))
        self.assertEqual(len(events), 1, f"Expected 1 event, got {len(events)}: {events}")
        return events[0]

    def test_repeat_field(self):
        self.assertEqual(self._event().repeat, "weekly")

    def test_byday_field_is_list(self):
        byday = self._event().byday
        self.assertIsInstance(byday, list)

    def test_byday_contains_tu_th(self):
        byday = self._event().byday
        self.assertIn("TU", byday)
        self.assertIn("TH", byday)

    def test_byday_all_uppercase_2char(self):
        byday = self._event().byday
        for code in byday:
            self.assertEqual(code, code.upper(), f"Day code not uppercase: {code!r}")
            self.assertEqual(len(code), 2, f"Day code not 2 chars: {code!r}")

    def test_interval_none_when_1(self):
        # interval==1 should be omitted (None) per model conventions
        self.assertIsNone(self._event().interval)

    def test_range_field_present(self):
        rng = self._event().range
        self.assertIsNotNone(rng)
        self.assertIn("start_date", rng)

    def test_start_time_field(self):
        # start_time should be "18:00"
        self.assertEqual(self._event().start_time, "18:00")

    def test_end_time_field(self):
        self.assertEqual(self._event().end_time, "19:00")

    def test_no_skipped(self):
        self.provider.list_events(("2026-01-01", "2026-06-30"))
        self.assertEqual(self.provider.skipped, [])


class TestListEventsWeeklySeriesIntervalGt1(unittest.TestCase):
    """Weekly series with interval > 1 sets the interval field."""

    def setUp(self):
        from calendars.importer.outlook_provider import OutlookCalendarProvider

        master_id = "master-bi-weekly"
        master = _weekly_master(
            master_id,
            "Synthetic Biweekly Standup",
            ["monday"],
            "2026-01-05",
            "2026-12-31",
            interval=2,
        )
        occ = _occurrence("Synthetic Biweekly Standup", master_id)
        svc = _FakeSvc(events=[occ], masters={master_id: master})
        self.provider = OutlookCalendarProvider(svc=svc)

    def test_interval_set_when_gt1(self):
        events = self.provider.list_events(("2026-01-01", "2026-12-31"))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].interval, 2)


class TestListEventsAllDay(unittest.TestCase):
    """All-day event round-trip."""

    def setUp(self):
        from calendars.importer.outlook_provider import OutlookCalendarProvider

        ev = _allday("evt-allday-001", "Synthetic Holiday", "2026-12-25")
        svc = _FakeSvc(events=[ev])
        self.provider = OutlookCalendarProvider(svc=svc)

    def test_all_day_event_returned(self):
        events = self.provider.list_events(("2026-12-01", "2026-12-31"))
        self.assertEqual(len(events), 1)

    def test_all_day_start_field(self):
        events = self.provider.list_events(("2026-12-01", "2026-12-31"))
        self.assertIn("2026-12-25", events[0].start)

    def test_all_day_no_tz(self):
        # All-day events carry no timezone
        events = self.provider.list_events(("2026-12-01", "2026-12-31"))
        self.assertIsNone(events[0].tz)

    def test_all_day_no_recurrence_fields(self):
        events = self.provider.list_events(("2026-12-01", "2026-12-31"))
        ev = events[0]
        self.assertIsNone(ev.repeat)
        self.assertIsNone(ev.interval)
        self.assertIsNone(ev.range)


class TestUnsupportedPatternSkipped(unittest.TestCase):
    """Unsupported recurrence patterns are skipped — never returned degraded."""

    UNSUPPORTED = ["relativeMonthly", "absoluteYearly", "relativeYearly"]

    def _run_with_pattern(self, pattern_type: str):
        from calendars.importer.outlook_provider import OutlookCalendarProvider

        master_id = f"master-{pattern_type}"
        master = _unsupported_master(master_id, f"Synthetic {pattern_type} Event", pattern_type)
        occ = _occurrence(f"Synthetic {pattern_type} Event", master_id)
        svc = _FakeSvc(events=[occ], masters={master_id: master})
        provider = OutlookCalendarProvider(svc=svc)
        events = provider.list_events(("2026-01-01", "2026-12-31"))
        return events, provider.skipped

    def test_relative_monthly_returns_no_events(self):
        events, _ = self._run_with_pattern("relativeMonthly")
        self.assertEqual(events, [])

    def test_relative_monthly_records_skip(self):
        _, skipped = self._run_with_pattern("relativeMonthly")
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["reason"], "unsupported_pattern")

    def test_absolute_yearly_returns_no_events(self):
        events, _ = self._run_with_pattern("absoluteYearly")
        self.assertEqual(events, [])

    def test_absolute_yearly_records_skip(self):
        _, skipped = self._run_with_pattern("absoluteYearly")
        self.assertEqual(len(skipped), 1)

    def test_relative_yearly_returns_no_events(self):
        events, _ = self._run_with_pattern("relativeYearly")
        self.assertEqual(events, [])

    def test_relative_yearly_records_skip(self):
        _, skipped = self._run_with_pattern("relativeYearly")
        self.assertEqual(len(skipped), 1)

    def test_skipped_has_pattern_type_key(self):
        _, skipped = self._run_with_pattern("relativeMonthly")
        self.assertIn("pattern_type", skipped[0])

    def test_all_three_unsupported_skipped(self):
        total_events = []
        total_skipped = []
        for ptype in self.UNSUPPORTED:
            events, skipped = self._run_with_pattern(ptype)
            total_events.extend(events)
            total_skipped.extend(skipped)
        self.assertEqual(total_events, [])
        self.assertEqual(len(total_skipped), 3)


class TestSkippedResetPerCall(unittest.TestCase):
    """skipped list is reset on each list_events call."""

    def test_skipped_resets(self):
        from calendars.importer.outlook_provider import OutlookCalendarProvider

        master_id = "master-reset"
        master = _unsupported_master(master_id, "Synthetic Reset Event", "relativeMonthly")
        occ = _occurrence("Synthetic Reset Event", master_id)
        svc = _FakeSvc(events=[occ], masters={master_id: master})
        provider = OutlookCalendarProvider(svc=svc)

        provider.list_events(("2026-01-01", "2026-12-31"))
        self.assertEqual(len(provider.skipped), 1)

        # Second call with no unsupported events
        svc2 = _FakeSvc(
            events=[_single("e1", "Synthetic Clean Event", "2026-06-01T09:00:00", "2026-06-01T10:00:00")]
        )
        provider2 = OutlookCalendarProvider(svc=svc2)
        provider2.list_events(("2026-01-01", "2026-12-31"))
        self.assertEqual(provider2.skipped, [])


class TestAddEventSingle(unittest.TestCase):
    """add_event creates a one-time Graph event."""

    def setUp(self):
        from calendars.importer.outlook_provider import OutlookCalendarProvider
        from calendars.gmail_pipelines import CalendarEvent

        self.svc = _FakeSvc()
        self.provider = OutlookCalendarProvider(svc=self.svc, calendar_name="Work")
        self.event = CalendarEvent(
            id="",
            subject="Synthetic Doctor Appointment",
            start="2026-04-15T14:00:00",
            end="2026-04-15T15:00:00",
            calendar="Work",
            tz="America/Toronto",
            location="Medical Centre",
        )

    def test_single_event_created(self):
        self.provider.add_event(self.event)
        self.assertEqual(len(self.svc.created), 1)
        kind, _ = self.svc.created[0]
        self.assertEqual(kind, "single")

    def test_returns_calendar_event(self):
        from calendars.gmail_pipelines import CalendarEvent
        result = self.provider.add_event(self.event)
        self.assertIsInstance(result, CalendarEvent)

    def test_returned_subject(self):
        result = self.provider.add_event(self.event)
        self.assertEqual(result.subject, "Synthetic Doctor Appointment")

    def test_returned_id_non_empty(self):
        result = self.provider.add_event(self.event)
        self.assertNotEqual(result.id, "")

    def test_single_params_subject(self):
        self.provider.add_event(self.event)
        _, params = self.svc.created[0]
        self.assertEqual(params.subject, "Synthetic Doctor Appointment")

    def test_single_params_tz(self):
        self.provider.add_event(self.event)
        _, params = self.svc.created[0]
        self.assertEqual(params.tz, "America/Toronto")


class TestAddEventRecurring(unittest.TestCase):
    """add_event routes to create_recurring_event when repeat is set."""

    def setUp(self):
        from calendars.importer.outlook_provider import OutlookCalendarProvider
        from calendars.gmail_pipelines import CalendarEvent

        self.svc = _FakeSvc()
        self.provider = OutlookCalendarProvider(svc=self.svc, calendar_name="Activities")
        self.event = CalendarEvent(
            id="",
            subject="Synthetic Hockey Practice",
            start="18:00",
            end="19:30",
            calendar="Activities",
            tz="America/Toronto",
            repeat="weekly",
            byday=["MO", "WE"],
            interval=None,
            range={"start_date": "2026-09-01", "until": "2026-12-15"},
            start_time="18:00",
            end_time="19:30",
        )

    def test_recurring_event_created(self):
        self.provider.add_event(self.event)
        self.assertEqual(len(self.svc.created), 1)
        kind, _ = self.svc.created[0]
        self.assertEqual(kind, "recurring")

    def test_returns_calendar_event(self):
        from calendars.gmail_pipelines import CalendarEvent
        result = self.provider.add_event(self.event)
        self.assertIsInstance(result, CalendarEvent)

    def test_recurring_params_repeat(self):
        self.provider.add_event(self.event)
        _, params = self.svc.created[0]
        self.assertEqual(params.repeat, "weekly")

    def test_recurring_params_byday(self):
        self.provider.add_event(self.event)
        _, params = self.svc.created[0]
        self.assertIn("MO", params.byday)
        self.assertIn("WE", params.byday)

    def test_recurring_params_range(self):
        self.provider.add_event(self.event)
        _, params = self.svc.created[0]
        self.assertEqual(params.range_start_date, "2026-09-01")
        self.assertEqual(params.range_until, "2026-12-15")

    def test_returned_repeat(self):
        result = self.provider.add_event(self.event)
        self.assertEqual(result.repeat, "weekly")

    def test_returned_byday(self):
        result = self.provider.add_event(self.event)
        self.assertIn("MO", result.byday)
        self.assertIn("WE", result.byday)


class TestOrphanedMasterSkipped(unittest.TestCase):
    """Series master not found in get_event is skipped."""

    def test_orphaned_master_skipped(self):
        from calendars.importer.outlook_provider import OutlookCalendarProvider

        occ = _occurrence("Synthetic Orphan", "nonexistent-master")
        svc = _FakeSvc(events=[occ], masters={})  # no master stored
        provider = OutlookCalendarProvider(svc=svc)
        events = provider.list_events(("2026-01-01", "2026-12-31"))

        self.assertEqual(events, [])
        self.assertEqual(len(provider.skipped), 1)
        self.assertEqual(provider.skipped[0]["reason"], "orphaned_master")


if __name__ == "__main__":
    unittest.main()
