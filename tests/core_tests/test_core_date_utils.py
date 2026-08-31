"""Tests for core/date_utils.py uncovered branches."""

from __future__ import annotations

import datetime
import unittest
from typing import Any, cast

from core.date_utils import (
    RRULE_CODE_TO_WEEKDAY,
    normalize_day,
    normalize_days,
    parse_month,
    to_iso_str,
)


class TestRruleCodeToWeekday(unittest.TestCase):
    """RRULE_CODE_TO_WEEKDAY must track datetime's Monday=0 convention.

    It is derived from DAY_NAMES, so reordering that list would silently
    shift every index. These assertions pin the contract instead.
    """

    def test_covers_all_seven_codes(self):
        self.assertEqual(len(RRULE_CODE_TO_WEEKDAY), 7)
        self.assertEqual(
            set(RRULE_CODE_TO_WEEKDAY),
            {"MO", "TU", "WE", "TH", "FR", "SA", "SU"},
        )

    def test_indices_are_zero_through_six(self):
        self.assertEqual(sorted(RRULE_CODE_TO_WEEKDAY.values()), list(range(7)))

    def test_matches_datetime_weekday(self):
        """Each code maps to the index datetime.date.weekday() reports."""
        # 2024-01-01 is a Monday, so the Nth day is weekday N.
        monday = datetime.date(2024, 1, 1)
        for code, index in RRULE_CODE_TO_WEEKDAY.items():
            actual = monday + datetime.timedelta(days=index)
            self.assertEqual(
                actual.weekday(), index, f"{code} should be weekday {index}"
            )

    def test_monday_is_zero_and_sunday_is_six(self):
        self.assertEqual(RRULE_CODE_TO_WEEKDAY["MO"], 0)
        self.assertEqual(RRULE_CODE_TO_WEEKDAY["SU"], 6)


class TestNormalizeDay(unittest.TestCase):
    def test_abbreviated_day_names(self):
        self.assertEqual(normalize_day("Mon"), "MO")
        self.assertEqual(normalize_day("Tue"), "TU")
        self.assertEqual(normalize_day("Wed"), "WE")
        self.assertEqual(normalize_day("Thu"), "TH")
        self.assertEqual(normalize_day("Fri"), "FR")
        self.assertEqual(normalize_day("Sat"), "SA")
        self.assertEqual(normalize_day("Sun"), "SU")

    def test_case_insensitive(self):
        self.assertEqual(normalize_day("MONDAY"), "MO")
        self.assertEqual(normalize_day("friday"), "FR")

    def test_strips_whitespace(self):
        self.assertEqual(normalize_day("  Mon  "), "MO")

    def test_unknown_day_returns_empty(self):
        self.assertEqual(normalize_day("Holiday"), "")
        self.assertEqual(normalize_day(""), "")

    def test_alternate_abbreviations(self):
        self.assertEqual(normalize_day("tues"), "TU")
        self.assertEqual(normalize_day("thur"), "TH")
        self.assertEqual(normalize_day("thurs"), "TH")


class TestNormalizeDays(unittest.TestCase):
    def test_single_day(self):
        self.assertEqual(normalize_days("Monday"), ["MO"])
        self.assertEqual(normalize_days("Friday"), ["FR"])

    def test_range_mon_to_fri(self):
        result = normalize_days("Mon to Fri")
        self.assertEqual(result, ["MO", "TU", "WE", "TH", "FR"])

    def test_range_with_dash(self):
        result = normalize_days("Mon-Wed")
        self.assertEqual(result, ["MO", "TU", "WE"])

    def test_range_sat_to_sun(self):
        result = normalize_days("Sat-Sun")
        self.assertEqual(result, ["SA", "SU"])

    def test_wraparound_range(self):
        # Fri to Sun wraps around: Fri, Sat, Sun
        result = normalize_days("Fri-Sun")
        self.assertEqual(result, ["FR", "SA", "SU"])

    def test_list_with_ampersand(self):
        result = normalize_days("Mon & Wed")
        self.assertIn("MO", result)
        self.assertIn("WE", result)
        self.assertNotIn("TU", result)

    def test_empty_string(self):
        result = normalize_days("")
        self.assertEqual(result, [])

    def test_none_like_empty(self):
        result = normalize_days(None)
        self.assertEqual(result, [])

    def test_multiple_days_in_list(self):
        result = normalize_days("Tuesday and Thursday")
        self.assertIn("TU", result)
        self.assertIn("TH", result)

    def test_no_duplicates(self):
        result = normalize_days("Mon Mon")
        self.assertEqual(result.count("MO"), 1)


class TestParseMonth(unittest.TestCase):
    def test_full_month_names(self):
        self.assertEqual(parse_month("January"), 1)
        self.assertEqual(parse_month("February"), 2)
        self.assertEqual(parse_month("March"), 3)
        self.assertEqual(parse_month("December"), 12)

    def test_abbreviated_month_names(self):
        self.assertEqual(parse_month("Jan"), 1)
        self.assertEqual(parse_month("Feb"), 2)
        self.assertEqual(parse_month("Dec"), 12)

    def test_case_insensitive(self):
        self.assertEqual(parse_month("JANUARY"), 1)
        self.assertEqual(parse_month("june"), 6)

    def test_strips_whitespace(self):
        self.assertEqual(parse_month("  March  "), 3)

    def test_invalid_month_returns_none(self):
        self.assertIsNone(parse_month("Blah"))
        self.assertIsNone(parse_month(""))

    def test_none_returns_none(self):
        self.assertIsNone(parse_month(None))

    def test_all_months(self):
        names = ["January", "February", "March", "April", "May", "June",
                 "July", "August", "September", "October", "November", "December"]
        for i, name in enumerate(names, start=1):
            self.assertEqual(parse_month(name), i)


class TestToIsoStr(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(to_iso_str(None))

    def test_string_returned_as_is(self):
        s = "2024-01-15T10:30:00"
        self.assertEqual(to_iso_str(s), s)

    def test_datetime_formatted(self):
        dt = datetime.datetime(2024, 3, 15, 14, 30, 0)
        result = to_iso_str(dt)
        self.assertEqual(result, "2024-03-15T14:30:00")

    def test_date_formatted(self):
        d = datetime.date(2024, 6, 1)
        result = to_iso_str(d)
        self.assertEqual(result, "2024-06-01T00:00:00")

    def test_non_date_returns_str(self):
        result = to_iso_str(42)
        self.assertEqual(result, "42")

    def test_object_returns_str(self):
        class Obj:
            def __str__(self):
                return "custom-obj"
        self.assertEqual(to_iso_str(Obj()), "custom-obj")


class TestParseIsoUtcStrict(unittest.TestCase):
    """parse_iso_utc_strict is strict about ERRORS, not about syntax.

    worker's public --not-before flag takes user-supplied timestamps, and
    queue_ops treats a parse failure as "eligible now". Narrowing this to the
    'Z'-only form iso_now() emits would make a '+00:00' not_before silently
    lose its scheduling guarantee instead of deferring the job.
    """

    def test_accepts_z_suffix(self):
        from core.date_utils import parse_iso_utc_strict
        dt = parse_iso_utc_strict("2026-08-11T10:30:00Z")
        self.assertEqual(dt.year, 2026)
        self.assertIsNotNone(dt.tzinfo)

    def test_accepts_explicit_utc_offset(self):
        from core.date_utils import parse_iso_utc_strict
        self.assertEqual(
            parse_iso_utc_strict("2026-08-11T10:30:00+00:00"),
            parse_iso_utc_strict("2026-08-11T10:30:00Z"),
        )

    def test_accepts_fractional_seconds(self):
        from core.date_utils import parse_iso_utc_strict
        self.assertEqual(parse_iso_utc_strict("2026-08-11T10:30:00.500Z").microsecond, 500000)

    def test_round_trips_iso_now(self):
        from core.date_utils import iso_now, parse_iso_utc_strict
        self.assertIsNotNone(parse_iso_utc_strict(iso_now()).tzinfo)

    def test_tolerates_surrounding_whitespace(self):
        """A stray space must not read as "invalid" -> "run now"."""
        from core.date_utils import parse_iso_utc_strict
        expected = parse_iso_utc_strict("2026-08-11T10:30:00Z")
        for padded in (" 2026-08-11T10:30:00Z", "2026-08-11T10:30:00Z ", "\t2026-08-11T10:30:00Z\n"):
            self.assertEqual(parse_iso_utc_strict(padded), expected)

    def test_raises_on_invalid(self):
        from core.date_utils import parse_iso_utc_strict
        for bad in ("", "   ", "garbage", "not-a-time"):
            with self.assertRaises(ValueError):
                parse_iso_utc_strict(bad)


class TestIsoNow(unittest.TestCase):
    def test_format_is_z_suffixed_seconds(self):
        from core.date_utils import iso_now
        self.assertRegex(iso_now(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class TestDayRangeToIso(unittest.TestCase):
    """The window shape the Outlook list-events calls depend on."""

    def test_widens_dates_to_full_day_window(self):
        from core.date_utils import day_range_to_iso
        start, end = day_range_to_iso("2026-01-01", "2026-01-31")
        self.assertEqual(start, "2026-01-01T00:00:00")
        # Inclusive of the final day -- a midnight end would silently drop it.
        self.assertEqual(end, "2026-01-31T23:59:59")

    def test_same_day_range_spans_that_whole_day(self):
        from core.date_utils import day_range_to_iso
        start, end = day_range_to_iso("2026-06-15", "2026-06-15")
        self.assertEqual(start, "2026-06-15T00:00:00")
        self.assertEqual(end, "2026-06-15T23:59:59")

    def test_accepts_full_iso_datetimes_and_truncates_to_day_bounds(self):
        from core.date_utils import day_range_to_iso
        start, end = day_range_to_iso("2026-03-04T09:30:00", "2026-03-05T18:00:00")
        self.assertEqual(start, "2026-03-04T00:00:00")
        self.assertEqual(end, "2026-03-05T23:59:59")

    def test_raises_value_error_on_unparseable_date(self):
        # The three schedule call sites catch ValueError and re-raise as their
        # own error type, so the primitive must stay ValueError.
        from core.date_utils import day_range_to_iso
        for bad in (("garbage", "2026-01-31"), ("2026-01-01", "nope"), ("", "")):
            with self.assertRaises(ValueError):
                day_range_to_iso(*bad)

    def test_raises_value_error_on_none(self):
        # None reached these sites as a TypeError before; callers caught
        # (ValueError, TypeError) together, so it must still raise ValueError.
        # cast exercises the TypeError->ValueError conversion guard.
        from core.date_utils import day_range_to_iso
        with self.assertRaises(ValueError):
            day_range_to_iso(cast(Any, None), cast(Any, None))

    def test_message_names_the_expected_format(self):
        from core.date_utils import day_range_to_iso
        with self.assertRaises(ValueError) as ctx:
            day_range_to_iso("garbage", "2026-01-31")
        self.assertIn("YYYY-MM-DD", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
