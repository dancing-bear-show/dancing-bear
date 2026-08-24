"""Tests for SheetGenerator internals."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from sheets.constants import MAX_COLUMN_WIDTH, MIN_COLUMN_WIDTH
from sheets.generator import SheetGenerator, generate_from_yaml, generate_xlsx
from sheets.schema import HeaderStyle, SheetMetadata, SheetTab, SheetWorkbook


def _make_workbook(sheets=None) -> SheetWorkbook:
    if sheets is None:
        sheets = [SheetTab(name="Sheet1", headers=["A", "B"], rows=[[1, 2], [3, 4]])]
    return SheetWorkbook(metadata=SheetMetadata(title="Test"), sheets=sheets)


class TestNormalizeColor(unittest.TestCase):
    def setUp(self):
        self.gen = SheetGenerator()

    def test_with_hash_prefix(self):
        self.assertEqual(self.gen._normalize_color("#2D3A4F"), "FF2D3A4F")

    def test_without_hash(self):
        self.assertEqual(self.gen._normalize_color("2D3A4F"), "FF2D3A4F")

    def test_already_argb(self):
        self.assertEqual(self.gen._normalize_color("FF2D3A4F"), "FF2D3A4F")

    def test_lowercase_upcased(self):
        self.assertEqual(self.gen._normalize_color("2d3a4f"), "FF2D3A4F")


class TestColumnWidthClamping(unittest.TestCase):
    def setUp(self):
        self.gen = SheetGenerator()

    def test_clamps_to_min(self):
        # A single short value should hit the MIN floor
        width = self.gen._calculate_column_width(["X"])
        self.assertGreaterEqual(width, MIN_COLUMN_WIDTH)

    def test_clamps_to_max(self):
        # A very long value should be capped at MAX
        long_val = "A" * 200
        width = self.gen._calculate_column_width([long_val])
        self.assertEqual(width, MAX_COLUMN_WIDTH)

    def test_auto_fit_from_content(self):
        values = ["Col", "short", "a longer value here"]
        width = self.gen._calculate_column_width(values)
        self.assertGreaterEqual(width, MIN_COLUMN_WIDTH)
        self.assertLessEqual(width, MAX_COLUMN_WIDTH)

    def test_explicit_column_widths_used_when_provided(self):
        sheet = SheetTab(
            name="S",
            headers=["A", "B"],
            rows=[],
            column_widths=[15, 25],
        )
        widths = self.gen._resolve_column_widths(sheet)
        self.assertEqual(widths, [15, 25])

    def test_auto_widths_when_not_provided(self):
        sheet = SheetTab(name="S", headers=["A", "B"], rows=[["x", "y"]])
        widths = self.gen._resolve_column_widths(sheet)
        self.assertEqual(len(widths), 2)
        for w in widths:
            self.assertGreaterEqual(w, MIN_COLUMN_WIDTH)
            self.assertLessEqual(w, MAX_COLUMN_WIDTH)


class TestFreezePanes(unittest.TestCase):
    def setUp(self):
        self.gen = SheetGenerator()

    def test_no_freeze_when_both_zero(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        self.gen._apply_freeze_panes(ws, 0, 0)
        self.assertIsNone(ws.freeze_panes)

    def test_freeze_one_row(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        self.gen._apply_freeze_panes(ws, 1, 0)
        self.assertEqual(ws.freeze_panes, "A2")

    def test_freeze_row_and_col(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        self.gen._apply_freeze_panes(ws, 2, 1)
        self.assertEqual(ws.freeze_panes, "B3")


class TestGenerateXlsx(unittest.TestCase):
    def test_generate_creates_file_with_expected_sheets(self):
        wb_def = _make_workbook()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = str(Path(tmpdir) / "out.xlsx")
            result = generate_xlsx(wb_def, out)
            self.assertEqual(result, out)
            self.assertTrue(Path(out).exists())
            wb = load_workbook(out)
            self.assertIn("Sheet1", wb.sheetnames)

    def test_generate_from_yaml_end_to_end(self):
        import yaml
        wb_def = {
            "title": "E2E",
            "sheets": [
                {"name": "Data", "headers": ["X", "Y"], "rows": [[1, 2]]}
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = str(Path(tmpdir) / "wb.yaml")
            with open(yaml_path, "w") as f:
                yaml.dump(wb_def, f)
            out = str(Path(tmpdir) / "out.xlsx")
            result = generate_from_yaml(yaml_path, out)
            self.assertTrue(Path(result).exists())
            wb = load_workbook(result)
            self.assertEqual(wb.sheetnames, ["Data"])
            ws = wb["Data"]
            self.assertEqual(ws.cell(1, 1).value, "X")
            self.assertEqual(ws.cell(2, 1).value, 1)

    def test_multi_tab_workbook_all_sheets_present(self):
        wb_def = SheetWorkbook(
            metadata=SheetMetadata(title="Multi"),
            sheets=[
                SheetTab(name="Alpha", headers=["A"], rows=[]),
                SheetTab(name="Beta", headers=["B"], rows=[]),
            ],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            out = str(Path(tmpdir) / "multi.xlsx")
            generate_xlsx(wb_def, out)
            wb = load_workbook(out)
            self.assertEqual(set(wb.sheetnames), {"Alpha", "Beta"})

    def test_header_styling_applied(self):
        style = HeaderStyle(bg_color="#FF0000", text_color="#FFFFFF", bold=True, font_size=14)
        wb_def = SheetWorkbook(
            metadata=SheetMetadata(title="Styled"),
            sheets=[SheetTab(name="S", headers=["Col"], rows=[], header_style=style)],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            out = str(Path(tmpdir) / "styled.xlsx")
            generate_xlsx(wb_def, out)
            wb = load_workbook(out)
            ws = wb["S"]
            cell = ws.cell(1, 1)
            # Header should be bold
            self.assertTrue(cell.font.bold)
            self.assertEqual(cell.font.size, 14)

    def test_alternating_rows_applied(self):
        wb_def = SheetWorkbook(
            metadata=SheetMetadata(title="Zebra"),
            sheets=[SheetTab(name="Z", headers=["A"], rows=[["x"], ["y"], ["z"]], alternating_rows=True)],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            out = str(Path(tmpdir) / "zebra.xlsx")
            generate_xlsx(wb_def, out)
            wb = load_workbook(out)
            ws = wb["Z"]
            # Row 2 (first data row, index 0 = even) gets ALTERNATING_ROW_COLOR_1
            # Row 3 (second data row, index 1 = odd) gets ALTERNATING_ROW_COLOR_2
            fill_row2 = ws.cell(2, 1).fill.fgColor.rgb
            fill_row3 = ws.cell(3, 1).fill.fgColor.rgb
            self.assertNotEqual(fill_row2, fill_row3)
