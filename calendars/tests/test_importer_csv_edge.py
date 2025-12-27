import os
import unittest

from calendars.importer import parse_csv
from tests.fixtures import TempDirMixin, write_csv_content


CSV_MIXED_HEADERS = """subject,start,end,address,notes
Mix Lowercase,2025-01-10T09:00,2025-01-10T09:30,Somewhere,Note
"""

CSV_SPACES_HEADERS = """ Subject , Start , End , Location , Notes
Trim Headers,2025-01-11T10:00,2025-01-11T10:30,Place,Text
"""

CSV_MISSING_SUBJECT = """Start,End,Location,Notes
2025-01-12T10:00,2025-01-12T10:30,Place,No subject row
"""


class TestImporterCsvEdgeCases(TempDirMixin, unittest.TestCase):
    def test_lowercase_headers(self):
        path = write_csv_content(os.path.join(self.tmpdir, "lowercase.csv"), CSV_MIXED_HEADERS)
        items = parse_csv(path)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it.subject, 'Mix Lowercase')
        self.assertEqual(it.start_iso, '2025-01-10T09:00')
        self.assertEqual(it.end_iso, '2025-01-10T09:30')
        self.assertEqual(it.location, 'Somewhere')

    def test_headers_with_spaces(self):
        path = write_csv_content(os.path.join(self.tmpdir, "spaces.csv"), CSV_SPACES_HEADERS)
        items = parse_csv(path)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it.subject, 'Trim Headers')
        self.assertEqual(it.location, 'Place')

    def test_missing_subject_row_skipped(self):
        path = write_csv_content(os.path.join(self.tmpdir, "missing.csv"), CSV_MISSING_SUBJECT)
        items = parse_csv(path)
        # Row without subject should be ignored
        self.assertEqual(len(items), 0)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
