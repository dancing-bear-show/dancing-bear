"""Tests for core/date_utils.py uncovered branches."""

from __future__ import annotations

import datetime
import unittest

from core.date_utils import (
    normalize_day,
    normalize_days,
    parse_month,
    to_iso_str,
    DAY_MAP,
    DAY_NAMES,
    MONTH_MAP,
)


class TestNormalizeDay(unittest.TestCase):
    def test_full_day_names(self):
        self.assertEqual(normalize_day("Monday"), "MO")
        self.assertEqual(normalize_day("Tuesday"), "TU")
        self.assertEqual(normalize_day("Wednesday"), "WE")
        self.assertEqual(normalize_day("Thursday"), "TH")
        self.assertEqual(normalize_day("Friday"), "FR")
        self.assertEqual(normalize_day("Saturday"), "SA")
        self.assertEqual(normalize_day("Sunday"), "SU")

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


if __name__ == "__main__":
    unittest.main()
