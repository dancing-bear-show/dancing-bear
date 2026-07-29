"""Tests for time-parsing helpers in calendars/importer.py."""

import unittest

from calendars.importer import (
    strip_html_tags,
    normalize_day,
    normalize_days,
    parse_time_range,
    extract_time_ranges,
    to_24h,
)


class TestRegexPatterns(unittest.TestCase):
    """Tests for regex pattern constants."""

    def test_strip_tags_pattern(self):
        import re
        from calendars.importer import RE_STRIP_TAGS

        html = "<strong>Bold</strong> and <em>italic</em>"
        result = re.sub(RE_STRIP_TAGS, '', html)
        self.assertEqual(result, "Bold and italic")

    def test_ampm_pattern(self):
        import re
        from calendars.importer import RE_AMPM

        self.assertIsNotNone(re.search(RE_AMPM, "10:00 a.m."))
        self.assertIsNotNone(re.search(RE_AMPM, "2:30 p.m."))
        self.assertIsNotNone(re.search(RE_AMPM, "10:00 AM"))
        self.assertIsNotNone(re.search(RE_AMPM, "2:30 PM"))

    def test_time_pattern(self):
        import re
        from calendars.importer import RE_TIME

        m = re.match(RE_TIME, "10:30")
        self.assertEqual(m.group(1), "10")
        self.assertEqual(m.group(2), "30")

        m = re.match(RE_TIME, "9")
        self.assertEqual(m.group(1), "9")
        self.assertIsNone(m.group(2))


class TestStripHtmlTags(unittest.TestCase):
    """Tests for strip_html_tags function."""

    def test_removes_simple_tags(self):
        self.assertEqual(strip_html_tags("<p>Hello</p>"), "Hello")

    def test_removes_nested_tags(self):
        self.assertEqual(strip_html_tags("<div><strong>Bold</strong> text</div>"), "Bold text")

    def test_handles_empty_string(self):
        self.assertEqual(strip_html_tags(""), "")

    def test_normalizes_nbsp(self):
        self.assertEqual(strip_html_tags("Hello&nbsp;World"), "Hello World")
        self.assertEqual(strip_html_tags("Hello\xa0World"), "Hello World")

    def test_strips_whitespace(self):
        self.assertEqual(strip_html_tags("  <p>  Text  </p>  "), "Text")


class TestNormalizeDay(unittest.TestCase):
    """Tests for normalize_day function."""

    def test_full_day_names(self):
        self.assertEqual(normalize_day("Monday"), "MO")
        self.assertEqual(normalize_day("Tuesday"), "TU")
        self.assertEqual(normalize_day("Wednesday"), "WE")
        self.assertEqual(normalize_day("Thursday"), "TH")
        self.assertEqual(normalize_day("Friday"), "FR")
        self.assertEqual(normalize_day("Saturday"), "SA")
        self.assertEqual(normalize_day("Sunday"), "SU")

    def test_case_insensitive(self):
        self.assertEqual(normalize_day("MONDAY"), "MO")
        self.assertEqual(normalize_day("friday"), "FR")
        self.assertEqual(normalize_day("SaTuRdAy"), "SA")

    def test_strips_whitespace(self):
        self.assertEqual(normalize_day("  Monday  "), "MO")

    def test_unknown_returns_empty(self):
        self.assertEqual(normalize_day("NotADay"), "")
        self.assertEqual(normalize_day(""), "")


class TestNormalizeDays(unittest.TestCase):
    """Tests for normalize_days function."""

    def test_single_day(self):
        self.assertEqual(normalize_days("Monday"), ["MO"])

    def test_multiple_days_with_and(self):
        self.assertEqual(normalize_days("Mon & Wed"), ["MO", "WE"])

    def test_day_range_mon_to_fri(self):
        self.assertEqual(normalize_days("Mon to Fri"), ["MO", "TU", "WE", "TH", "FR"])

    def test_day_range_with_dash(self):
        self.assertEqual(normalize_days("Mon-Fri"), ["MO", "TU", "WE", "TH", "FR"])

    def test_weekend_range(self):
        self.assertEqual(normalize_days("Sat to Sun"), ["SA", "SU"])

    def test_abbreviated_days(self):
        self.assertEqual(normalize_days("Tue Thu"), ["TU", "TH"])

    def test_full_day_names(self):
        self.assertEqual(normalize_days("Monday Wednesday Friday"), ["MO", "WE", "FR"])

    def test_empty_string(self):
        self.assertEqual(normalize_days(""), [])

    def test_no_duplicate_days(self):
        result = normalize_days("Mon Monday")
        self.assertEqual(result, ["MO"])


class TestTo24h(unittest.TestCase):
    """Tests for to_24h function."""

    def test_12_hour_pm(self):
        self.assertEqual(to_24h("1:45 p.m."), "13:45")
        self.assertEqual(to_24h("3:00 PM"), "15:00")

    def test_12_hour_am(self):
        self.assertEqual(to_24h("9:30 a.m."), "09:30")
        self.assertEqual(to_24h("11:00 AM"), "11:00")

    def test_noon(self):
        self.assertEqual(to_24h("12:00 p.m."), "12:00")

    def test_midnight(self):
        self.assertEqual(to_24h("12:00 a.m."), "00:00")

    def test_hour_only(self):
        self.assertEqual(to_24h("3 p.m."), "15:00")

    def test_with_explicit_suffix(self):
        self.assertEqual(to_24h("2:30", "pm"), "14:30")
        self.assertEqual(to_24h("10:00", "am"), "10:00")

    def test_heuristic_assumes_pm_for_7_to_11(self):
        # Hours 7-11 without am/pm assume PM for evening schedules
        self.assertEqual(to_24h("7:00"), "19:00")
        self.assertEqual(to_24h("8:30"), "20:30")

    def test_invalid_returns_none(self):
        self.assertIsNone(to_24h("not a time"))
        self.assertIsNone(to_24h(""))

    def test_handles_various_formats(self):
        self.assertEqual(to_24h("1:45pm"), "13:45")
        self.assertEqual(to_24h("1:45 pm"), "13:45")
        self.assertEqual(to_24h("1:45p.m."), "13:45")


class TestParseTimeRange(unittest.TestCase):
    """Tests for parse_time_range function."""

    def test_simple_range_pm(self):
        start, end = parse_time_range("1:45 - 3:15 p.m.")
        self.assertEqual(start, "13:45")
        self.assertEqual(end, "15:15")

    def test_mixed_am_pm(self):
        start, end = parse_time_range("11:15 a.m. - 12:15 p.m.")
        self.assertEqual(start, "11:15")
        self.assertEqual(end, "12:15")

    def test_hour_only_range(self):
        start, end = parse_time_range("7 - 8:30 p.m.")
        self.assertEqual(start, "19:00")
        self.assertEqual(end, "20:30")

    def test_handles_en_dash(self):
        start, end = parse_time_range("9:00 a.m. – 10:00 a.m.")
        self.assertEqual(start, "09:00")
        self.assertEqual(end, "10:00")

    def test_handles_to_separator(self):
        start, end = parse_time_range("2:00 p.m. to 4:00 p.m.")
        self.assertEqual(start, "14:00")
        self.assertEqual(end, "16:00")

    def test_empty_string_returns_none(self):
        start, end = parse_time_range("")
        self.assertIsNone(start)
        self.assertIsNone(end)

    def test_nbsp_only_returns_none(self):
        start, end = parse_time_range("\xa0")
        self.assertIsNone(start)
        self.assertIsNone(end)

    def test_invalid_format_returns_none(self):
        start, end = parse_time_range("not a time range")
        self.assertIsNone(start)
        self.assertIsNone(end)


class TestExtractTimeRanges(unittest.TestCase):
    """Tests for extract_time_ranges function."""

    def test_single_range(self):
        ranges = extract_time_ranges("Class is from 10:00 a.m. - 12:00 p.m.")
        self.assertEqual(ranges, [("10:00", "12:00")])

    def test_multiple_ranges(self):
        text = "Morning: 9:00am - 10:30am, Afternoon: 2:00pm - 4:00pm"
        ranges = extract_time_ranges(text)
        self.assertEqual(len(ranges), 2)
        self.assertEqual(ranges[0], ("09:00", "10:30"))
        self.assertEqual(ranges[1], ("14:00", "16:00"))

    def test_strips_asterisks(self):
        ranges = extract_time_ranges("*10:00 a.m. - 11:00 a.m.*")
        self.assertEqual(ranges, [("10:00", "11:00")])

    def test_handles_newlines(self):
        text = "Session 1: 9:00am - 10:00am\nSession 2: 2:00pm - 3:00pm"
        ranges = extract_time_ranges(text)
        self.assertEqual(len(ranges), 2)

    def test_empty_string(self):
        self.assertEqual(extract_time_ranges(""), [])

    def test_no_ranges_found(self):
        self.assertEqual(extract_time_ranges("No times here"), [])


if __name__ == "__main__":
    unittest.main()
