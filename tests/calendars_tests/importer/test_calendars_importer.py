"""Tests for calendars/importer.py schedule parsing."""

import os
import unittest

from tests.fixtures import TempDirMixin
from tests.calendars_tests.fixtures import write_csv_content

from calendars.importer import (
    ScheduleItem,
    _get_field,
    _row_to_schedule_item,
    extract_time_ranges,
    normalize_day,
    normalize_days,
    parse_csv,
    parse_time_range,
    load_schedule,
    strip_html_tags,
    to_24h,
)


class TestScheduleItem(unittest.TestCase):
    """Tests for ScheduleItem dataclass."""

    def test_schedule_item_defaults(self):
        item = ScheduleItem(subject="Test Event")
        self.assertEqual(item.subject, "Test Event")
        self.assertIsNone(item.start_iso)
        self.assertIsNone(item.end_iso)
        self.assertIsNone(item.recurrence)
        self.assertIsNone(item.byday)
        self.assertIsNone(item.location)

    def test_schedule_item_with_recurrence(self):
        item = ScheduleItem(
            subject="Weekly Meeting",
            recurrence="weekly",
            byday=["MO", "WE", "FR"],
            start_time="09:00",
            end_time="10:00",
            range_start="2025-01-01",
            range_until="2025-12-31",
        )
        self.assertEqual(item.recurrence, "weekly")
        self.assertEqual(item.byday, ["MO", "WE", "FR"])
        self.assertEqual(item.start_time, "09:00")
        self.assertEqual(item.end_time, "10:00")

    def test_schedule_item_with_one_off(self):
        item = ScheduleItem(
            subject="One-time Event",
            start_iso="2025-03-15T14:00",
            end_iso="2025-03-15T15:30",
            location="Conference Room A",
        )
        self.assertEqual(item.start_iso, "2025-03-15T14:00")
        self.assertEqual(item.end_iso, "2025-03-15T15:30")
        self.assertEqual(item.location, "Conference Room A")


class TestParseCsv(TempDirMixin, unittest.TestCase):
    """Tests for parse_csv function."""

    def _write_csv(self, name: str, content: str) -> str:
        return write_csv_content(os.path.join(self.tmpdir, name), content)

    def test_parse_csv_basic(self):
        csv_content = """subject,start,end,location
Team Meeting,2025-01-15T10:00,2025-01-15T11:00,Room 101
Lunch Break,2025-01-15T12:00,2025-01-15T13:00,Cafeteria
"""
        path = self._write_csv("basic.csv", csv_content)
        items = parse_csv(path)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].subject, "Team Meeting")
        self.assertEqual(items[0].start_iso, "2025-01-15T10:00")
        self.assertEqual(items[0].end_iso, "2025-01-15T11:00")
        self.assertEqual(items[0].location, "Room 101")

        self.assertEqual(items[1].subject, "Lunch Break")
        self.assertEqual(items[1].location, "Cafeteria")

    def test_parse_csv_with_recurrence(self):
        csv_content = """subject,recurrence,byday,starttime,endtime,startdate,until,location
Weekly Standup,weekly,"MO,TU,WE,TH,FR",09:00,09:15,2025-01-06,2025-12-31,Virtual
"""
        path = self._write_csv("recurring.csv", csv_content)
        items = parse_csv(path)

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.subject, "Weekly Standup")
        self.assertEqual(item.recurrence, "weekly")
        self.assertEqual(item.byday, ["MO", "TU", "WE", "TH", "FR"])
        self.assertEqual(item.start_time, "09:00")
        self.assertEqual(item.end_time, "09:15")
        self.assertEqual(item.range_start, "2025-01-06")
        self.assertEqual(item.range_until, "2025-12-31")

    def test_parse_csv_skips_empty_subject(self):
        csv_content = """subject,start,end
Valid Event,2025-01-15T10:00,2025-01-15T11:00
,2025-01-15T12:00,2025-01-15T13:00
Another Event,2025-01-15T14:00,2025-01-15T15:00
"""
        path = self._write_csv("skip_empty.csv", csv_content)
        items = parse_csv(path)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].subject, "Valid Event")
        self.assertEqual(items[1].subject, "Another Event")

    def test_parse_csv_with_notes(self):
        csv_content = """subject,start,end,notes
Event With Notes,2025-01-15T10:00,2025-01-15T11:00,Remember to bring laptop
"""
        path = self._write_csv("notes.csv", csv_content)
        items = parse_csv(path)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].notes, "Remember to bring laptop")

    def test_parse_csv_with_count(self):
        csv_content = """subject,recurrence,byday,starttime,endtime,count
Limited Series,weekly,MO,10:00,11:00,5
"""
        path = self._write_csv("count.csv", csv_content)
        items = parse_csv(path)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].count, 5)

    def test_parse_csv_count_non_numeric_ignored(self):
        csv_content = """subject,recurrence,count
Event,weekly,not-a-number
"""
        path = self._write_csv("bad_count.csv", csv_content)
        items = parse_csv(path)

        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0].count)

    def test_parse_csv_case_insensitive_headers(self):
        csv_content = """Subject,StartTime,EndTime,ByDay,Recurrence
Morning Yoga,06:00,07:00,"MO,WE,FR",weekly
"""
        path = self._write_csv("caps.csv", csv_content)
        items = parse_csv(path)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].subject, "Morning Yoga")
        self.assertEqual(items[0].start_time, "06:00")
        self.assertEqual(items[0].byday, ["MO", "WE", "FR"])

    def test_parse_csv_empty_file(self):
        csv_content = """subject,start,end
"""
        path = self._write_csv("empty.csv", csv_content)
        items = parse_csv(path)
        self.assertEqual(len(items), 0)

    def test_parse_csv_alternate_column_names(self):
        csv_content = """subject,repeat,start_time,end_time,start_date,enddate,address
Swim Class,weekly,14:00,15:00,2025-01-01,2025-06-30,Community Pool
"""
        path = self._write_csv("alt_names.csv", csv_content)
        items = parse_csv(path)

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.recurrence, "weekly")
        self.assertEqual(item.start_time, "14:00")
        self.assertEqual(item.end_time, "15:00")
        self.assertEqual(item.range_start, "2025-01-01")
        self.assertEqual(item.range_until, "2025-06-30")
        self.assertEqual(item.location, "Community Pool")


class TestLoadSchedule(TempDirMixin, unittest.TestCase):
    """Tests for load_schedule routing function."""

    def _write_csv(self, name: str, content: str) -> str:
        return write_csv_content(os.path.join(self.tmpdir, name), content)

    def test_load_schedule_auto_csv_by_extension(self):
        csv_content = """subject,start,end
Auto Test,2025-01-15T10:00,2025-01-15T11:00
"""
        path = self._write_csv("auto.csv", csv_content)
        items = load_schedule(path)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].subject, "Auto Test")

    def test_load_schedule_explicit_csv_kind(self):
        csv_content = """subject,start,end
Explicit CSV,2025-01-15T10:00,2025-01-15T11:00
"""
        # Use .txt extension but specify csv kind
        path = self._write_csv("data.txt", csv_content)
        items = load_schedule(path, kind="csv")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].subject, "Explicit CSV")

    def test_load_schedule_unknown_kind_raises(self):
        path = self._write_csv("test.csv", "subject\nTest\n")
        with self.assertRaises(ValueError) as ctx:
            load_schedule(path, kind="unknown_format")
        self.assertIn("Unknown schedule kind", str(ctx.exception))

    def test_load_schedule_auto_defaults_to_csv(self):
        # File without recognized extension defaults to CSV
        csv_content = """subject,start,end
Default CSV,2025-01-15T10:00,2025-01-15T11:00
"""
        path = self._write_csv("schedule", csv_content)  # No extension
        items = load_schedule(path, kind="auto")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].subject, "Default CSV")


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


class TestGetField(unittest.TestCase):
    """Tests for _get_field helper function."""

    def test_finds_exact_key(self):
        """Test finds value with exact key match."""
        row = {"subject": "Meeting"}
        result = _get_field(row, "subject")
        self.assertEqual(result, "Meeting")

    def test_finds_lowercase_variant(self):
        """Test finds value with lowercase key variant."""
        row = {"Subject": "Meeting"}
        result = _get_field(row, "subject")
        self.assertEqual(result, "Meeting")

    def test_finds_title_variant(self):
        """Test finds value with title-case key variant."""
        row = {"subject": "Meeting"}
        result = _get_field(row, "SUBJECT")
        self.assertEqual(result, "Meeting")

    def test_returns_first_non_empty(self):
        """Test returns first non-empty value from multiple keys."""
        row = {"name": "", "title": "CEO", "subject": "Meeting"}
        result = _get_field(row, "name", "title", "subject")
        self.assertEqual(result, "CEO")

    def test_returns_default_when_missing(self):
        """Test returns default when key not found."""
        row = {"other": "value"}
        result = _get_field(row, "subject", default="Unknown")
        self.assertEqual(result, "Unknown")

    def test_returns_default_when_empty(self):
        """Test returns default when value is empty."""
        row = {"subject": ""}
        result = _get_field(row, "subject", default="Default")
        self.assertEqual(result, "Default")

    def test_strips_whitespace(self):
        """Test strips leading/trailing whitespace."""
        row = {"subject": "  Meeting  "}
        result = _get_field(row, "subject")
        self.assertEqual(result, "Meeting")

    def test_handles_none_value(self):
        """Test handles None value in row."""
        row = {"subject": None, "title": "Meeting"}
        result = _get_field(row, "subject", "title")
        self.assertEqual(result, "Meeting")

    def test_returns_empty_string_default(self):
        """Test default default is empty string."""
        row = {}
        result = _get_field(row, "subject")
        self.assertEqual(result, "")


class TestRowToScheduleItem(unittest.TestCase):
    """Tests for _row_to_schedule_item helper function."""

    def test_returns_none_for_empty_subject(self):
        """Test returns None when subject is empty."""
        row = {"subject": "", "start": "2025-01-15T10:00"}
        result = _row_to_schedule_item(row)
        self.assertIsNone(result)

    def test_basic_item(self):
        """Test creates basic ScheduleItem."""
        row = {"subject": "Meeting", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}
        result = _row_to_schedule_item(row)
        self.assertIsNotNone(result)
        self.assertEqual(result.subject, "Meeting")
        self.assertEqual(result.start_iso, "2025-01-15T10:00")
        self.assertEqual(result.end_iso, "2025-01-15T11:00")

    def test_with_recurrence(self):
        """Test creates item with recurrence."""
        row = {
            "subject": "Weekly",
            "recurrence": "WEEKLY",
            "byday": "MO,WE,FR",
            "starttime": "09:00",
            "endtime": "10:00",
        }
        result = _row_to_schedule_item(row)
        self.assertEqual(result.recurrence, "weekly")
        self.assertEqual(result.byday, ["MO", "WE", "FR"])
        self.assertEqual(result.start_time, "09:00")
        self.assertEqual(result.end_time, "10:00")

    def test_with_count(self):
        """Test creates item with occurrence count."""
        row = {"subject": "Limited", "count": "10"}
        result = _row_to_schedule_item(row)
        self.assertEqual(result.count, 10)

    def test_with_location(self):
        """Test creates item with location."""
        row = {"subject": "Meeting", "location": "Room A"}
        result = _row_to_schedule_item(row)
        self.assertEqual(result.location, "Room A")

    def test_with_notes(self):
        """Test creates item with notes."""
        row = {"subject": "Meeting", "notes": "Bring laptop"}
        result = _row_to_schedule_item(row)
        self.assertEqual(result.notes, "Bring laptop")

    def test_handles_alternate_keys(self):
        """Test handles alternate key names."""
        row = {"Subject": "Meeting", "Start": "2025-01-15T10:00", "Address": "123 Main St"}
        result = _row_to_schedule_item(row)
        self.assertEqual(result.subject, "Meeting")
        self.assertEqual(result.start_iso, "2025-01-15T10:00")
        self.assertEqual(result.location, "123 Main St")

    def test_invalid_count_ignored(self):
        """Test invalid count is ignored."""
        row = {"subject": "Meeting", "count": "abc"}
        result = _row_to_schedule_item(row)
        self.assertIsNone(result.count)

    def test_empty_byday_returns_none(self):
        """Test empty byday returns None."""
        row = {"subject": "Meeting", "byday": ""}
        result = _row_to_schedule_item(row)
        self.assertIsNone(result.byday)


if __name__ == "__main__":
    unittest.main()
