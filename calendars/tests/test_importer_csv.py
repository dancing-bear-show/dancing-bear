import os
import tempfile
import unittest

from calendars.importer import parse_csv, load_schedule


CSV_CONTENT = """Subject,Start,End,Location,Notes
One Off,2025-01-10T17:00,2025-01-10T18:00,Ed Sackfield Arena,Test
Recurring,, , , 
"""

CSV_REC_CONTENT = """Subject,Recurrence,ByDay,StartTime,EndTime,StartDate,Until,Location,Notes
Swim Kids,weekly,MO,17:00,17:30,2025-01-01,2025-03-01,Elgin West Pool,Classes
"""


class TestImporterCSV(unittest.TestCase):
    def test_parse_csv_one_off(self):
        with tempfile.NamedTemporaryFile('w+', suffix='.csv', delete=False) as tf:
            tf.write(CSV_CONTENT)
            tf.flush()
            path = tf.name
        try:
            items = parse_csv(path)
            self.assertTrue(items, "no items parsed")
            # First row should be one-off
            self.assertEqual(items[0].subject, 'One Off')
            self.assertEqual(items[0].start_iso, '2025-01-10T17:00')
            self.assertEqual(items[0].end_iso, '2025-01-10T18:00')
        finally:
            os.unlink(path)

    def test_load_schedule_csv_recurring(self):
        with tempfile.NamedTemporaryFile('w+', suffix='.csv', delete=False) as tf:
            tf.write(CSV_REC_CONTENT)
            tf.flush()
            path = tf.name
        try:
            items = load_schedule(path, kind='csv')
            self.assertEqual(len(items), 1)
            it = items[0]
            self.assertEqual(it.subject, 'Swim Kids')
            self.assertEqual(it.recurrence, 'weekly')
            self.assertEqual(it.byday, ['MO'])
            self.assertEqual(it.start_time, '17:00')
            self.assertEqual(it.range_start, '2025-01-01')
            self.assertEqual(it.range_until, '2025-03-01')
        finally:
            os.unlink(path)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()

