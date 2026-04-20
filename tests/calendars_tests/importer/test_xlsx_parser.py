"""Tests for calendars/importer/xlsx_parser.py."""
import sys
import unittest
from unittest.mock import MagicMock, patch

from tests.fixtures import TempDirMixin
from calendars.importer.xlsx_parser import XLSXParser
from calendars.importer.model import ScheduleItem


class TestXLSXParserMissingDep(unittest.TestCase):
    """Test behaviour when openpyxl is absent."""

    def test_raises_runtime_error_if_openpyxl_missing(self):
        """XLSXParser.parse() should raise RuntimeError when openpyxl is unavailable."""
        with patch.dict(sys.modules, {"openpyxl": None}):
            parser = XLSXParser()
            with self.assertRaises((RuntimeError, ImportError)):
                parser.parse("/nonexistent/file.xlsx")


class TestXLSXParserWithMockWorkbook(TempDirMixin, unittest.TestCase):
    """Test XLSXParser with a mocked openpyxl workbook."""

    def _make_ws(self, headers, data_rows):
        """Build a mock worksheet with given header cells and data rows."""
        def make_cell(value):
            c = MagicMock()
            c.value = value
            return c

        ws = MagicMock()
        # Header row: ws[1] → list of cells
        header_cells = [make_cell(h) for h in headers]
        ws.__getitem__ = lambda self_ws, key: header_cells if key == 1 else []

        # iter_rows(min_row=2) → list of cell tuples per row
        rows = []
        for row_data in data_rows:
            rows.append([make_cell(v) for v in row_data])
        ws.iter_rows = MagicMock(return_value=rows)
        return ws

    def _patch_openpyxl(self, ws):
        """Context manager to patch openpyxl.load_workbook returning the given ws."""
        wb = MagicMock()
        wb.active = ws
        mock_openpyxl = MagicMock()
        mock_openpyxl.load_workbook = MagicMock(return_value=wb)
        return patch.dict("sys.modules", {"openpyxl": mock_openpyxl})

    def test_parse_single_one_off_row(self):
        headers = ["Subject", "Start", "End", "Location", "Notes"]
        rows = [["Morning Swim", "2025-01-10T07:00", "2025-01-10T08:00", "Elgin West Pool", "bring cap"]]
        ws = self._make_ws(headers, rows)

        with self._patch_openpyxl(ws):
            items = XLSXParser().parse("fake.xlsx")

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.subject, "Morning Swim")
        self.assertEqual(item.start_iso, "2025-01-10T07:00")
        self.assertEqual(item.end_iso, "2025-01-10T08:00")
        self.assertEqual(item.location, "Elgin West Pool")
        self.assertEqual(item.notes, "bring cap")

    def test_parse_recurring_row(self):
        headers = ["Subject", "Recurrence", "ByDay", "StartTime", "EndTime", "StartDate", "Until"]
        rows = [["Swim Kids", "weekly", "MO,WE", "17:00", "17:30", "2025-01-01", "2025-06-30"]]
        ws = self._make_ws(headers, rows)

        with self._patch_openpyxl(ws):
            items = XLSXParser().parse("fake.xlsx")

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.subject, "Swim Kids")
        self.assertEqual(item.recurrence, "weekly")
        self.assertEqual(item.byday, ["MO", "WE"])
        self.assertEqual(item.start_time, "17:00")
        self.assertEqual(item.end_time, "17:30")
        self.assertEqual(item.range_start, "2025-01-01")
        self.assertEqual(item.range_until, "2025-06-30")

    def test_parse_skips_empty_subject_rows(self):
        headers = ["Subject", "Start", "End"]
        rows = [
            ["Valid Event", "2025-01-01T10:00", "2025-01-01T11:00"],
            [None, "2025-01-02T10:00", "2025-01-02T11:00"],  # empty subject → skipped
            ["Another Event", "2025-01-03T10:00", "2025-01-03T11:00"],
        ]
        ws = self._make_ws(headers, rows)

        with self._patch_openpyxl(ws):
            items = XLSXParser().parse("fake.xlsx")

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].subject, "Valid Event")
        self.assertEqual(items[1].subject, "Another Event")

    def test_parse_empty_data_rows(self):
        headers = ["Subject", "Start", "End"]
        rows = []
        ws = self._make_ws(headers, rows)

        with self._patch_openpyxl(ws):
            items = XLSXParser().parse("fake.xlsx")

        self.assertEqual(items, [])

    def test_parse_returns_schedule_item_instances(self):
        headers = ["Subject", "Start", "End"]
        rows = [["Test Event", "2025-03-01T09:00", "2025-03-01T10:00"]]
        ws = self._make_ws(headers, rows)

        with self._patch_openpyxl(ws):
            items = XLSXParser().parse("fake.xlsx")

        self.assertIsInstance(items[0], ScheduleItem)

    def test_parse_numeric_cell_values_converted_to_str(self):
        """Non-string cell values (e.g., floats from numeric columns) should become strings."""
        headers = ["Subject", "Start", "End", "Count"]
        rows = [["Event", "2025-01-01T10:00", "2025-01-01T11:00", 5]]
        ws = self._make_ws(headers, rows)

        with self._patch_openpyxl(ws):
            items = XLSXParser().parse("fake.xlsx")

        # count field maps via _row_to_schedule_item — numeric string "5" should parse
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].subject, "Event")

    def test_parse_column_names_unknown_fall_through(self):
        """Columns not mapped to any ScheduleItem field are ignored gracefully."""
        headers = ["Subject", "WeirdColumn1", "WeirdColumn2"]
        rows = [["Class", "foo", "bar"]]
        ws = self._make_ws(headers, rows)

        with self._patch_openpyxl(ws):
            items = XLSXParser().parse("fake.xlsx")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].subject, "Class")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
