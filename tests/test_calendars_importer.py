"""Tests for calendars/importer.py schedule parsing."""

import os
import tempfile
import unittest

from calendars.importer import (
    ScheduleItem,
    parse_csv,
    load_schedule,
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


class TestParseCsv(unittest.TestCase):
    """Tests for parse_csv function."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_csv(self, name: str, content: str) -> str:
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

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


class TestLoadSchedule(unittest.TestCase):
    """Tests for load_schedule routing function."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_csv(self, name: str, content: str) -> str:
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

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


if __name__ == "__main__":
    unittest.main()
