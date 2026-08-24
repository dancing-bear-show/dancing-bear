"""Tests for sheets schema parsing and defaults."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sheets.generator import load_workbook_from_yaml


class TestLoadWorkbookFromYaml(unittest.TestCase):
    """Tests for load_workbook_from_yaml."""

    def _write_yaml(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        f.write(content)
        f.flush()
        f.close()
        return f.name

    def test_minimal_yaml_defaults(self):
        path = self._write_yaml("title: Test\nsheets: []\n")
        try:
            wb = load_workbook_from_yaml(path)
            self.assertEqual(wb.metadata.title, "Test")
            self.assertIsNone(wb.metadata.author)
            self.assertIsNone(wb.metadata.date)
            self.assertEqual(wb.sheets, [])
        finally:
            Path(path).unlink()

    def test_missing_file_returns_defaults(self):
        wb = load_workbook_from_yaml("/nonexistent/file.yaml")
        self.assertEqual(wb.metadata.title, "Untitled")
        self.assertEqual(wb.sheets, [])

    def test_all_metadata_fields(self):
        yaml = "title: Report\nauthor: Alice\ndate: 2026-01-15\nsheets: []\n"
        path = self._write_yaml(yaml)
        try:
            wb = load_workbook_from_yaml(path)
            self.assertEqual(wb.metadata.title, "Report")
            self.assertEqual(wb.metadata.author, "Alice")
            self.assertEqual(wb.metadata.date, "2026-01-15")
        finally:
            Path(path).unlink()

    def test_multi_tab_workbook(self):
        yaml = """
title: Multi
sheets:
  - name: Alpha
    headers: [A, B]
    rows: [[1, 2]]
  - name: Beta
    headers: [X, Y, Z]
    rows: []
"""
        path = self._write_yaml(yaml)
        try:
            wb = load_workbook_from_yaml(path)
            self.assertEqual(len(wb.sheets), 2)
            self.assertEqual(wb.sheets[0].name, "Alpha")
            self.assertEqual(wb.sheets[0].headers, ["A", "B"])
            self.assertEqual(wb.sheets[0].rows, [[1, 2]])
            self.assertEqual(wb.sheets[1].name, "Beta")
            self.assertEqual(len(wb.sheets[1].headers), 3)
        finally:
            Path(path).unlink()

    def test_sheet_defaults_when_fields_absent(self):
        """A sheet with only a name gets sensible defaults for all optional fields."""
        yaml = "title: T\nsheets:\n  - name: MySheet\n"
        path = self._write_yaml(yaml)
        try:
            wb = load_workbook_from_yaml(path)
            sheet = wb.sheets[0]
            self.assertEqual(sheet.headers, [])
            self.assertEqual(sheet.rows, [])
            self.assertIsNone(sheet.header_style)
            self.assertTrue(sheet.alternating_rows)
            self.assertIsNone(sheet.column_widths)
            self.assertEqual(sheet.freeze_rows, 1)
            self.assertEqual(sheet.freeze_cols, 0)
        finally:
            Path(path).unlink()

    def test_custom_header_style_parsed(self):
        yaml = """
title: Styled
sheets:
  - name: S
    headers: [Col]
    rows: []
    header_style:
      bg_color: "#1A3A5C"
      text_color: "#EEEEEE"
      bold: false
      font_size: 14
"""
        path = self._write_yaml(yaml)
        try:
            wb = load_workbook_from_yaml(path)
            hs = wb.sheets[0].header_style
            self.assertIsNotNone(hs)
            self.assertEqual(hs.bg_color, "#1A3A5C")
            self.assertEqual(hs.text_color, "#EEEEEE")
            self.assertFalse(hs.bold)
            self.assertEqual(hs.font_size, 14)
        finally:
            Path(path).unlink()

    def test_freeze_panes_parsed(self):
        yaml = "title: T\nsheets:\n  - name: S\n    freeze_rows: 2\n    freeze_cols: 1\n"
        path = self._write_yaml(yaml)
        try:
            wb = load_workbook_from_yaml(path)
            self.assertEqual(wb.sheets[0].freeze_rows, 2)
            self.assertEqual(wb.sheets[0].freeze_cols, 1)
        finally:
            Path(path).unlink()

    def test_alternating_rows_disabled(self):
        yaml = "title: T\nsheets:\n  - name: S\n    alternating_rows: false\n"
        path = self._write_yaml(yaml)
        try:
            wb = load_workbook_from_yaml(path)
            self.assertFalse(wb.sheets[0].alternating_rows)
        finally:
            Path(path).unlink()
