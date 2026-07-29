"""Tests for CSV parsing and schedule loading in calendars/importer.py."""

import os
import unittest

from tests.fixtures import TempDirMixin, write_csv_content

from calendars.importer import (
    CSVParser,
    ScheduleParser,
    load_schedule,
)


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
        items = CSVParser().parse(path)

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
        items = CSVParser().parse(path)

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
        items = CSVParser().parse(path)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].subject, "Valid Event")
        self.assertEqual(items[1].subject, "Another Event")

    def test_parse_csv_with_notes(self):
        csv_content = """subject,start,end,notes
Event With Notes,2025-01-15T10:00,2025-01-15T11:00,Remember to bring laptop
"""
        path = self._write_csv("notes.csv", csv_content)
        items = CSVParser().parse(path)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].notes, "Remember to bring laptop")

    def test_parse_csv_with_count(self):
        csv_content = """subject,recurrence,byday,starttime,endtime,count
Limited Series,weekly,MO,10:00,11:00,5
"""
        path = self._write_csv("count.csv", csv_content)
        items = CSVParser().parse(path)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].count, 5)

    def test_parse_csv_count_non_numeric_ignored(self):
        csv_content = """subject,recurrence,count
Event,weekly,not-a-number
"""
        path = self._write_csv("bad_count.csv", csv_content)
        items = CSVParser().parse(path)

        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0].count)

    def test_parse_csv_case_insensitive_headers(self):
        csv_content = """Subject,StartTime,EndTime,ByDay,Recurrence
Morning Yoga,06:00,07:00,"MO,WE,FR",weekly
"""
        path = self._write_csv("caps.csv", csv_content)
        items = CSVParser().parse(path)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].subject, "Morning Yoga")
        self.assertEqual(items[0].start_time, "06:00")
        self.assertEqual(items[0].byday, ["MO", "WE", "FR"])

    def test_parse_csv_empty_file(self):
        csv_content = """subject,start,end
"""
        path = self._write_csv("empty.csv", csv_content)
        items = CSVParser().parse(path)
        self.assertEqual(len(items), 0)

    def test_parse_csv_alternate_column_names(self):
        csv_content = """subject,repeat,start_time,end_time,start_date,enddate,address
Swim Class,weekly,14:00,15:00,2025-01-01,2025-06-30,Community Pool
"""
        path = self._write_csv("alt_names.csv", csv_content)
        items = CSVParser().parse(path)

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


class TestGetField(unittest.TestCase):
    """Tests for _get_field helper function."""

    def test_finds_exact_key(self):
        """Test finds value with exact key match."""
        row = {"subject": "Meeting"}
        result = ScheduleParser._get_field(row, "subject")
        self.assertEqual(result, "Meeting")

    def test_finds_lowercase_variant(self):
        """Test finds value with lowercase key variant."""
        row = {"Subject": "Meeting"}
        result = ScheduleParser._get_field(row, "subject")
        self.assertEqual(result, "Meeting")

    def test_finds_title_variant(self):
        """Test finds value with title-case key variant."""
        row = {"subject": "Meeting"}
        result = ScheduleParser._get_field(row, "SUBJECT")
        self.assertEqual(result, "Meeting")

    def test_returns_first_non_empty(self):
        """Test returns first non-empty value from multiple keys."""
        row = {"name": "", "title": "CEO", "subject": "Meeting"}
        result = ScheduleParser._get_field(row, "name", "title", "subject")
        self.assertEqual(result, "CEO")

    def test_returns_default_when_missing(self):
        """Test returns default when key not found."""
        row = {"other": "value"}
        result = ScheduleParser._get_field(row, "subject", default="Unknown")
        self.assertEqual(result, "Unknown")

    def test_returns_default_when_empty(self):
        """Test returns default when value is empty."""
        row = {"subject": ""}
        result = ScheduleParser._get_field(row, "subject", default="Default")
        self.assertEqual(result, "Default")

    def test_strips_whitespace(self):
        """Test strips leading/trailing whitespace."""
        row = {"subject": "  Meeting  "}
        result = ScheduleParser._get_field(row, "subject")
        self.assertEqual(result, "Meeting")

    def test_handles_none_value(self):
        """Test handles None value in row."""
        row = {"subject": None, "title": "Meeting"}
        result = ScheduleParser._get_field(row, "subject", "title")
        self.assertEqual(result, "Meeting")

    def test_returns_empty_string_default(self):
        """Test default default is empty string."""
        row = {}
        result = ScheduleParser._get_field(row, "subject")
        self.assertEqual(result, "")


class TestRowToScheduleItem(unittest.TestCase):
    """Tests for _row_to_schedule_item helper function."""

    def test_returns_none_for_empty_subject(self):
        """Test returns None when subject is empty."""
        row = {"subject": "", "start": "2025-01-15T10:00"}
        result = ScheduleParser._row_to_schedule_item(row)
        self.assertIsNone(result)

    def test_basic_item(self):
        """Test creates basic ScheduleItem."""
        row = {"subject": "Meeting", "start": "2025-01-15T10:00", "end": "2025-01-15T11:00"}
        result = ScheduleParser._row_to_schedule_item(row)
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
        result = ScheduleParser._row_to_schedule_item(row)
        self.assertEqual(result.recurrence, "weekly")
        self.assertEqual(result.byday, ["MO", "WE", "FR"])
        self.assertEqual(result.start_time, "09:00")
        self.assertEqual(result.end_time, "10:00")

    def test_with_count(self):
        """Test creates item with occurrence count."""
        row = {"subject": "Limited", "count": "10"}
        result = ScheduleParser._row_to_schedule_item(row)
        self.assertEqual(result.count, 10)

    def test_with_location(self):
        """Test creates item with location."""
        row = {"subject": "Meeting", "location": "Room A"}
        result = ScheduleParser._row_to_schedule_item(row)
        self.assertEqual(result.location, "Room A")

    def test_with_notes(self):
        """Test creates item with notes."""
        row = {"subject": "Meeting", "notes": "Bring laptop"}
        result = ScheduleParser._row_to_schedule_item(row)
        self.assertEqual(result.notes, "Bring laptop")

    def test_handles_alternate_keys(self):
        """Test handles alternate key names."""
        row = {"Subject": "Meeting", "Start": "2025-01-15T10:00", "Address": "123 Main St"}
        result = ScheduleParser._row_to_schedule_item(row)
        self.assertEqual(result.subject, "Meeting")
        self.assertEqual(result.start_iso, "2025-01-15T10:00")
        self.assertEqual(result.location, "123 Main St")

    def test_invalid_count_ignored(self):
        """Test invalid count is ignored."""
        row = {"subject": "Meeting", "count": "abc"}
        result = ScheduleParser._row_to_schedule_item(row)
        self.assertIsNone(result.count)

    def test_empty_byday_returns_none(self):
        """Test empty byday returns None."""
        row = {"subject": "Meeting", "byday": ""}
        result = ScheduleParser._row_to_schedule_item(row)
        self.assertIsNone(result.byday)


if __name__ == "__main__":
    unittest.main()
