import os
import unittest

from calendars.importer import parse_csv, load_schedule
from tests.fixtures import TempDirMixin, write_csv_content


CSV_CONTENT = """Subject,Start,End,Location,Notes
One Off,2025-01-10T17:00,2025-01-10T18:00,Ed Sackfield Arena,Test
Recurring,, , ,
"""

CSV_REC_CONTENT = """Subject,Recurrence,ByDay,StartTime,EndTime,StartDate,Until,Location,Notes
Swim Kids,weekly,MO,17:00,17:30,2025-01-01,2025-03-01,Elgin West Pool,Classes
"""


class TestImporterCSV(TempDirMixin, unittest.TestCase):
    def test_parse_csv_one_off(self):
        path = write_csv_content(os.path.join(self.tmpdir, "oneoff.csv"), CSV_CONTENT)
        items = parse_csv(path)
        self.assertTrue(items, "no items parsed")
        # First row should be one-off
        self.assertEqual(items[0].subject, 'One Off')
        self.assertEqual(items[0].start_iso, '2025-01-10T17:00')
        self.assertEqual(items[0].end_iso, '2025-01-10T18:00')

    def test_load_schedule_csv_recurring(self):
        path = write_csv_content(os.path.join(self.tmpdir, "recurring.csv"), CSV_REC_CONTENT)
        items = load_schedule(path, kind='csv')
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it.subject, 'Swim Kids')
        self.assertEqual(it.recurrence, 'weekly')
        self.assertEqual(it.byday, ['MO'])
        self.assertEqual(it.start_time, '17:00')
        self.assertEqual(it.range_start, '2025-01-01')
        self.assertEqual(it.range_until, '2025-03-01')

    def test_load_schedule_auto_detects_csv(self):
        """Test that load_schedule auto-detects CSV files by extension."""
        path = write_csv_content(os.path.join(self.tmpdir, "auto.csv"), CSV_REC_CONTENT)
        # kind='auto' or kind='' should auto-detect
        items = load_schedule(path, kind='auto')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].subject, 'Swim Kids')

        items2 = load_schedule(path, kind='')
        self.assertEqual(len(items2), 1)

        items3 = load_schedule(path)  # no kind specified
        self.assertEqual(len(items3), 1)

    def test_load_schedule_unknown_kind_raises(self):
        """Test that unknown kind raises ValueError."""
        path = write_csv_content(os.path.join(self.tmpdir, "unknown.csv"), CSV_REC_CONTENT)
        with self.assertRaises(ValueError) as ctx:
            load_schedule(path, kind='unknown_format')
        self.assertIn('unknown_format', str(ctx.exception).lower())

    def test_load_schedule_explicit_csv_kind(self):
        """Test that explicit kind='csv' works regardless of extension."""
        # Create file without .csv extension
        path = write_csv_content(os.path.join(self.tmpdir, "data.txt"), CSV_REC_CONTENT)
        items = load_schedule(path, kind='csv')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].subject, 'Swim Kids')


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
