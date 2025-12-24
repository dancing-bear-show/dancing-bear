import os
import tempfile
import unittest

from calendars.importer import parse_csv


CSV_MIXED_HEADERS = """subject,start,end,address,notes
Mix Lowercase,2025-01-10T09:00,2025-01-10T09:30,Somewhere,Note
"""

CSV_SPACES_HEADERS = """ Subject , Start , End , Location , Notes 
Trim Headers,2025-01-11T10:00,2025-01-11T10:30,Place,Text
"""

CSV_MISSING_SUBJECT = """Start,End,Location,Notes
2025-01-12T10:00,2025-01-12T10:30,Place,No subject row
"""


class TestImporterCsvEdgeCases(unittest.TestCase):
    def _write(self, content: str) -> str:
        tf = tempfile.NamedTemporaryFile('w+', suffix='.csv', delete=False)
        with tf:
            tf.write(content)
            tf.flush()
            return tf.name

    def test_lowercase_headers(self):
        path = self._write(CSV_MIXED_HEADERS)
        try:
            items = parse_csv(path)
            self.assertEqual(len(items), 1)
            it = items[0]
            self.assertEqual(it.subject, 'Mix Lowercase')
            self.assertEqual(it.start_iso, '2025-01-10T09:00')
            self.assertEqual(it.end_iso, '2025-01-10T09:30')
            self.assertEqual(it.location, 'Somewhere')
        finally:
            os.unlink(path)

    def test_headers_with_spaces(self):
        path = self._write(CSV_SPACES_HEADERS)
        try:
            items = parse_csv(path)
            self.assertEqual(len(items), 1)
            it = items[0]
            self.assertEqual(it.subject, 'Trim Headers')
            self.assertEqual(it.location, 'Place')
        finally:
            os.unlink(path)

    def test_missing_subject_row_skipped(self):
        path = self._write(CSV_MISSING_SUBJECT)
        try:
            items = parse_csv(path)
            # Row without subject should be ignored
            self.assertEqual(len(items), 0)
        finally:
            os.unlink(path)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()

