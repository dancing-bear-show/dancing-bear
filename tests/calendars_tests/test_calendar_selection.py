"""Tests for calendars/selection.py — compute_window and filter_events_by_day_time.

compute_window has no other coverage anywhere in this tree. filter_events_by_day_time
has narrow branch-coverage tests elsewhere (test_producer_outlook_branches.py,
test_producer_output_branches.py — both cover only the "no start_time" branch);
this file adds the combined day+time filter and timezone-offset cases.
"""
from __future__ import annotations

import datetime as _dt
import unittest

from calendars.selection import _parse_dt, compute_window, filter_events_by_day_time


class TestComputeWindow(unittest.TestCase):
    """Tests for compute_window function."""

    def test_from_range_start_date_and_until(self):
        ev = {"range": {"start_date": "2025-01-01", "until": "2025-02-01"}}
        start, end = compute_window(ev)
        self.assertEqual(start, "2025-01-01T00:00:00")
        self.assertEqual(end, "2025-02-01T23:59:59")

    def test_from_range_single_day(self):
        ev = {"range": {"start_date": "2025-01-15"}}
        start, end = compute_window(ev)
        self.assertEqual(start, "2025-01-15T00:00:00")
        self.assertEqual(end, "2025-01-15T23:59:59")

    def test_from_explicit_start_and_end(self):
        ev = {"start": "2025-01-06T17:00:00+00:00", "end": "2025-01-06T17:30:00+00:00"}
        start, end = compute_window(ev)
        self.assertEqual(start, "2025-01-06T17:00:00+00:00")
        self.assertEqual(end, "2025-01-06T17:30:00+00:00")


class TestComputeWindowOpenEndedRecurring(unittest.TestCase):
    """An open-ended weekly series needs a window wider than one day.

    Regression: a series with range.start_date but no `until` got a single-day
    window. When byday names a weekday other than start_date's, that window
    contains no occurrence, so a series that exists reports as missing --
    and a real duplicate would be missed the same way.
    """

    #: 2026-09-21 is a Monday; the live failure was a Saturday series.
    MONDAY = "2026-09-21"

    @staticmethod
    def _weekdays_in(window: tuple[str, str]) -> set:
        start = _dt.date.fromisoformat(window[0][:10])
        end = _dt.date.fromisoformat(window[1][:10])
        out, cur = set(), start
        while cur <= end:
            out.add(cur.strftime("%a"))
            cur += _dt.timedelta(days=1)
        return out

    def test_saturday_series_starting_monday_window_contains_a_saturday(self):
        ev = {
            "subject": "Blas - BJJ",
            "repeat": "weekly",
            "byday": ["SA"],
            "start_time": "10:00",
            "end_time": "11:00",
            "range": {"start_date": self.MONDAY},
        }
        window = compute_window(ev)
        self.assertIn("Sat", self._weekdays_in(window))

    def test_open_ended_window_starts_on_start_date(self):
        ev = {"repeat": "weekly", "byday": ["SA"], "range": {"start_date": self.MONDAY}}
        start, _ = compute_window(ev)
        self.assertEqual(start, "2026-09-21T00:00:00")

    def test_open_ended_window_spans_at_least_four_weeks(self):
        """Two occurrences of every weekday, so one cancellation is not fatal."""
        ev = {"repeat": "weekly", "byday": ["SA"], "range": {"start_date": self.MONDAY}}
        start, end = compute_window(ev)
        span = _dt.date.fromisoformat(end[:10]) - _dt.date.fromisoformat(start[:10])
        self.assertGreaterEqual(span.days, 28)

    def test_every_weekday_reachable_from_every_start_weekday(self):
        """All 49 start-weekday x byday combinations must be satisfiable."""
        codes = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
        names = {"MO": "Mon", "TU": "Tue", "WE": "Wed", "TH": "Thu",
                 "FR": "Fri", "SA": "Sat", "SU": "Sun"}
        for offset in range(7):
            start_date = _dt.date(2026, 9, 21) + _dt.timedelta(days=offset)
            for code in codes:
                ev = {
                    "repeat": "weekly",
                    "byday": [code],
                    "range": {"start_date": start_date.isoformat()},
                }
                with self.subTest(start=start_date.isoformat(), byday=code):
                    covered = self._weekdays_in(compute_window(ev))
                    self.assertIn(names[code], covered)

    def test_biweekly_window_is_wider_than_weekly(self):
        """interval=2 needs more room for two occurrences of the target day."""
        weekly = compute_window(
            {"repeat": "weekly", "byday": ["SA"], "range": {"start_date": self.MONDAY}}
        )
        biweekly = compute_window(
            {"repeat": "weekly", "byday": ["SA"], "interval": 2,
             "range": {"start_date": self.MONDAY}}
        )
        self.assertGreater(biweekly[1], weekly[1])

    def test_absurd_interval_is_capped(self):
        """A bad interval must not ask Graph for an unbounded range."""
        ev = {"repeat": "weekly", "byday": ["SA"], "interval": 9999,
              "range": {"start_date": self.MONDAY}}
        start, end = compute_window(ev)
        span = _dt.date.fromisoformat(end[:10]) - _dt.date.fromisoformat(start[:10])
        self.assertLessEqual(span.days, 120)

    def test_non_integer_interval_falls_back_to_weekly(self):
        ev = {"repeat": "weekly", "byday": ["SA"], "interval": "bogus",
              "range": {"start_date": self.MONDAY}}
        start, end = compute_window(ev)
        span = _dt.date.fromisoformat(end[:10]) - _dt.date.fromisoformat(start[:10])
        self.assertEqual(span.days, 28)

    def test_start_date_and_until_is_not_widened(self):
        """The bounded case was already correct; widening would cost API time."""
        ev = {
            "repeat": "weekly",
            "byday": ["SA"],
            "range": {"start_date": self.MONDAY, "until": "2026-12-20"},
        }
        self.assertEqual(
            compute_window(ev), ("2026-09-21T00:00:00", "2026-12-20T23:59:59")
        )

    def test_non_recurring_event_keeps_single_day_window(self):
        """No byday means one occurrence, on start_date -- do not widen."""
        ev = {"subject": "Dentist", "range": {"start_date": self.MONDAY}}
        self.assertEqual(
            compute_window(ev), ("2026-09-21T00:00:00", "2026-09-21T23:59:59")
        )

    def test_empty_byday_keeps_single_day_window(self):
        ev = {"subject": "Dentist", "byday": [], "range": {"start_date": self.MONDAY}}
        self.assertEqual(
            compute_window(ev), ("2026-09-21T00:00:00", "2026-09-21T23:59:59")
        )

    def test_explicit_start_end_takes_precedence_over_byday(self):
        ev = {
            "byday": ["SA"],
            "start": "2026-09-21T10:00:00",
            "end": "2026-09-21T11:00:00",
        }
        self.assertEqual(
            compute_window(ev), ("2026-09-21T10:00:00", "2026-09-21T11:00:00")
        )

    def test_malformed_start_date_does_not_raise(self):
        ev = {"repeat": "weekly", "byday": ["SA"], "range": {"start_date": "not-a-date"}}
        window = compute_window(ev)
        self.assertIsNotNone(window)

    def test_missing_range_still_returns_none(self):
        self.assertIsNone(compute_window({"subject": "x", "byday": ["SA"]}))


class TestFilterEventsByDayTime(unittest.TestCase):
    """Tests for filter_events_by_day_time function.

    Fixtures here carry a -05:00 offset (Toronto in January) so the wall clock
    in the fixture is the wall clock the filter is asked about. These tests
    cover day/time selection; UTC-to-local conversion is covered separately in
    TestFilterEventsUtcToLocal.
    """

    def test_filters_by_day_and_time_together(self):
        # Monday Jan 6, 2025 vs Tuesday Jan 7, 2025.
        evs = [
            {
                "start": {"dateTime": "2025-01-06T17:00:00-05:00"},
                "end": {"dateTime": "2025-01-06T17:30:00-05:00"},
            },
            {
                "start": {"dateTime": "2025-01-07T17:00:00-05:00"},
                "end": {"dateTime": "2025-01-07T17:30:00-05:00"},
            },
        ]
        matches = filter_events_by_day_time(evs, byday=["MO"], start_time="17:00", end_time="17:30")
        self.assertEqual(len(matches), 1)

    def test_filters_by_day_only(self):
        evs = [
            {"start": {"dateTime": "2025-01-06T10:00:00-05:00"}, "end": {"dateTime": "2025-01-06T11:00:00-05:00"}},
            {"start": {"dateTime": "2025-01-07T10:00:00-05:00"}, "end": {"dateTime": "2025-01-07T11:00:00-05:00"}},
        ]
        matches = filter_events_by_day_time(evs, byday=["MO"])
        self.assertEqual(len(matches), 1)

    def test_filters_by_time_only(self):
        evs = [
            {"start": {"dateTime": "2025-01-06T10:00:00-05:00"}, "end": {"dateTime": "2025-01-06T11:00:00-05:00"}},
            {"start": {"dateTime": "2025-01-07T10:00:00-05:00"}, "end": {"dateTime": "2025-01-07T11:00:00-05:00"}},
        ]
        matches = filter_events_by_day_time(evs, start_time="10:00", end_time="11:00")
        self.assertEqual(len(matches), 2)

    def test_matches_with_timezone_offset(self):
        evs = [
            {"start": {"dateTime": "2025-01-06T17:00:00-05:00"}, "end": {"dateTime": "2025-01-06T17:30:00-05:00"}},
        ]
        matches = filter_events_by_day_time(evs, start_time="17:00", end_time="17:30")
        self.assertEqual(len(matches), 1)


class TestFilterEventsUtcToLocal(unittest.TestCase):
    """Graph returns calendarView times in UTC; plan files carry local wall clock.

    Regression for `outlook verify-from-config` reporting every existing series
    as missing: the comparison was UTC-vs-local and never matched. The events
    below use Graph's real default shape -- a naive dateTime with seven
    fractional digits and timeZone "UTC".
    """

    TZ = "America/Toronto"

    @staticmethod
    def _utc_event(start: str, end: str) -> dict:
        return {
            "start": {"dateTime": f"{start}.0000000", "timeZone": "UTC"},
            "end": {"dateTime": f"{end}.0000000", "timeZone": "UTC"},
        }

    def test_utc_event_matches_local_plan_time(self):
        # 14:30Z on Sun 2026-09-27 is 10:30 EDT.
        evs = [self._utc_event("2026-09-27T14:30:00", "2026-09-27T15:30:00")]
        matches = filter_events_by_day_time(
            evs, byday=["SU"], start_time="10:30", end_time="11:30", tz=self.TZ
        )
        self.assertEqual(len(matches), 1)

    def test_raw_utc_wall_clock_no_longer_matches(self):
        """The old buggy behaviour -- matching on the raw UTC string -- must be gone."""
        evs = [self._utc_event("2026-09-27T14:30:00", "2026-09-27T15:30:00")]
        matches = filter_events_by_day_time(
            evs, byday=["SU"], start_time="14:30", end_time="15:30", tz=self.TZ
        )
        self.assertEqual(matches, [])

    def test_dst_before_changeover_utc_minus_4(self):
        """Oct 25 2026 is EDT: local 10:30 is 14:30Z."""
        evs = [self._utc_event("2026-10-25T14:30:00", "2026-10-25T15:30:00")]
        matches = filter_events_by_day_time(
            evs, byday=["SU"], start_time="10:30", end_time="11:30", tz=self.TZ
        )
        self.assertEqual(len(matches), 1)

    def test_dst_after_changeover_utc_minus_5(self):
        """Nov 8 2026 is EST: the same local 10:30 is now 15:30Z."""
        evs = [self._utc_event("2026-11-08T15:30:00", "2026-11-08T16:30:00")]
        matches = filter_events_by_day_time(
            evs, byday=["SU"], start_time="10:30", end_time="11:30", tz=self.TZ
        )
        self.assertEqual(len(matches), 1)

    def test_dst_offset_is_not_applied_uniformly(self):
        """A fixed -4 offset would wrongly match the post-changeover occurrence.

        Guards against "fix" by constant offset rather than real zone conversion.
        """
        evs = [self._utc_event("2026-11-08T14:30:00", "2026-11-08T15:30:00")]
        matches = filter_events_by_day_time(
            evs, byday=["SU"], start_time="10:30", end_time="11:30", tz=self.TZ
        )
        self.assertEqual(matches, [])

    def test_genuine_non_match_still_rejected(self):
        """A different time of day must not match -- a false duplicate blocks writes."""
        evs = [self._utc_event("2026-09-27T16:30:00", "2026-09-27T17:30:00")]
        matches = filter_events_by_day_time(
            evs, byday=["SU"], start_time="10:30", end_time="11:30", tz=self.TZ
        )
        self.assertEqual(matches, [])

    def test_wrong_weekday_still_rejected(self):
        """14:30Z Mon 2026-09-28 is 10:30 local, but the plan asks for Sunday."""
        evs = [self._utc_event("2026-09-28T14:30:00", "2026-09-28T15:30:00")]
        matches = filter_events_by_day_time(
            evs, byday=["SU"], start_time="10:30", end_time="11:30", tz=self.TZ
        )
        self.assertEqual(matches, [])

    def test_utc_conversion_can_shift_the_weekday(self):
        """01:30Z Mon is 21:30 Sun local -- the weekday must follow the conversion."""
        evs = [self._utc_event("2026-09-28T01:30:00", "2026-09-28T02:30:00")]
        matches = filter_events_by_day_time(
            evs, byday=["SU"], start_time="21:30", end_time="22:30", tz=self.TZ
        )
        self.assertEqual(len(matches), 1)

    def test_default_tz_used_when_none_given(self):
        """Callers that pass no tz get DEFAULT_PLAN_TZ, not raw UTC."""
        evs = [self._utc_event("2026-09-27T14:30:00", "2026-09-27T15:30:00")]
        matches = filter_events_by_day_time(
            evs, byday=["SU"], start_time="10:30", end_time="11:30"
        )
        self.assertEqual(len(matches), 1)

    def test_windows_zone_name_falls_back_to_wall_clock(self):
        """zoneinfo cannot load "Eastern Standard Time"; this must not raise.

        With no loadable zone on either side the value is compared as wall
        clock, which is what a Prefer-header response already delivers.
        """
        evs = [{
            "start": {"dateTime": "2026-09-27T10:30:00", "timeZone": "Eastern Standard Time"},
            "end": {"dateTime": "2026-09-27T11:30:00", "timeZone": "Eastern Standard Time"},
        }]
        matches = filter_events_by_day_time(
            evs, byday=["SU"], start_time="10:30", end_time="11:30",
            tz="Eastern Standard Time",
        )
        self.assertEqual(len(matches), 1)

    def test_naive_event_without_zone_is_treated_as_wall_clock(self):
        """No offset and no timeZone: compare as-is rather than raising."""
        evs = [{
            "start": {"dateTime": "2026-09-27T10:30:00"},
            "end": {"dateTime": "2026-09-27T11:30:00"},
        }]
        matches = filter_events_by_day_time(
            evs, byday=["SU"], start_time="10:30", end_time="11:30", tz=self.TZ
        )
        self.assertEqual(len(matches), 1)

    def test_unparseable_start_does_not_raise(self):
        evs = [{"start": {"dateTime": "not-a-date"}, "end": {"dateTime": "also-bad"}}]
        matches = filter_events_by_day_time(
            evs, byday=["SU"], start_time="10:30", end_time="11:30", tz=self.TZ
        )
        self.assertEqual(matches, [])

    def test_missing_end_block_matches_on_start_alone(self):
        evs = [{"start": {"dateTime": "2026-09-27T14:30:00.0000000", "timeZone": "UTC"}}]
        matches = filter_events_by_day_time(
            evs, byday=["SU"], start_time="10:30", end_time="11:30", tz=self.TZ
        )
        self.assertEqual(len(matches), 1)

    def test_trailing_z_suffix_is_converted(self):
        evs = [{
            "start": {"dateTime": "2026-09-27T14:30:00Z"},
            "end": {"dateTime": "2026-09-27T15:30:00Z"},
        }]
        matches = filter_events_by_day_time(
            evs, byday=["SU"], start_time="10:30", end_time="11:30", tz=self.TZ
        )
        self.assertEqual(len(matches), 1)


class TestParseDtGraphFractionalSeconds(unittest.TestCase):
    """Pin the assumption that let a fraction-trimming fallback be removed.

    ``_parse_dt`` once retried through a helper that stripped an "over-long"
    fractional part, on the premise that ``fromisoformat`` rejects Graph's
    seven digits. It does not, on any Python this project supports, so the
    retry path was unreachable and untested. These tests fail if that premise
    ever stops holding, rather than letting a silent parse failure surface as
    an event that cannot be matched.
    """

    GRAPH_FORMS = (
        "2026-09-27T14:30:00.0000000",
        "2026-09-27T14:30:00.0000000+00:00",
        "2026-09-27T14:30:00.0000000-04:00",
        "2026-09-27T14:30:00.1234567-04:00",
    )

    def test_graph_seven_digit_fraction_parses_directly(self):
        for raw in self.GRAPH_FORMS:
            with self.subTest(raw=raw):
                self.assertIsNotNone(
                    _parse_dt(raw), f"fromisoformat no longer accepts {raw!r}"
                )

    def test_offset_is_preserved_not_collapsed_to_utc(self):
        # The reason this does not delegate to core.date_utils.parse_iso_utc:
        # that helper returns the instant in UTC, losing the local offset
        # _as_local needs to express it in a target zone.
        parsed = _parse_dt("2026-09-27T10:30:00-04:00")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.utcoffset(), _dt.timedelta(hours=-4))
        self.assertEqual(parsed.hour, 10)

    def test_unparseable_returns_none(self):
        for raw in ("", "   ", "not-a-date", "2026-13-45T99:99:99"):
            with self.subTest(raw=raw):
                self.assertIsNone(_parse_dt(raw))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
