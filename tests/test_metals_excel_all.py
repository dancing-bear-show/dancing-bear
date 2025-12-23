"""Tests for metals excel_all module."""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from metals.excel_all import (
    _col_letter,
    _read_csv,
    _to_records,
    _merge_all,
)


class TestColLetter(unittest.TestCase):
    """Tests for _col_letter function."""

    def test_single_letters(self):
        """Test single letter columns."""
        self.assertEqual(_col_letter(1), "A")
        self.assertEqual(_col_letter(26), "Z")

    def test_double_letters(self):
        """Test double letter columns."""
        self.assertEqual(_col_letter(27), "AA")
        self.assertEqual(_col_letter(52), "AZ")


class TestReadCsv(unittest.TestCase):
    """Tests for _read_csv function."""

    def test_reads_csv_as_dicts(self):
        """Test reads CSV as list of dicts."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            w = csv.writer(f)
            w.writerow(["date", "order_id", "vendor"])
            w.writerow(["2024-01-15", "12345", "TD"])
            w.writerow(["2024-01-16", "12346", "Costco"])
            f.flush()

            rows = _read_csv(f.name)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["date"], "2024-01-15")
            self.assertEqual(rows[0]["order_id"], "12345")

    def test_adds_metal_column(self):
        """Test adds metal column when specified."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            w = csv.writer(f)
            w.writerow(["date", "order_id"])
            w.writerow(["2024-01-15", "12345"])
            f.flush()

            rows = _read_csv(f.name, metal="gold")
            self.assertEqual(rows[0]["metal"], "gold")


class TestToRecords(unittest.TestCase):
    """Tests for _to_records function."""

    def test_converts_values_to_records(self):
        """Test converts values to records."""
        values = [
            ["date", "order_id", "metal"],
            ["2024-01-15", "12345", "gold"],
            ["2024-01-16", "12346", "silver"],
        ]
        headers, records = _to_records(values)
        self.assertEqual(headers, ["date", "order_id", "metal"])
        self.assertEqual(len(records), 2)

    def test_adds_assumed_metal(self):
        """Test adds assumed metal when missing."""
        values = [
            ["date", "order_id", "metal"],
            ["2024-01-15", "12345", ""],  # Empty metal
        ]
        headers, records = _to_records(values, assumed_metal="gold")
        self.assertEqual(records[0]["metal"], "gold")

    def test_handles_empty_values(self):
        """Test handles empty values."""
        headers, records = _to_records([])
        self.assertEqual(headers, [])
        self.assertEqual(records, [])


class TestMergeAll(unittest.TestCase):
    """Tests for _merge_all function."""

    def test_merges_records_by_key(self):
        """Test merges records by order_id+vendor+metal."""
        existing = [
            {"date": "2024-01-15", "order_id": "12345", "vendor": "TD", "metal": "gold", "total_oz": "1.0"},
        ]
        new = [
            {"date": "2024-01-16", "order_id": "12346", "vendor": "Costco", "metal": "silver", "total_oz": "10.0"},
        ]
        result = _merge_all(existing, new)
        self.assertEqual(len(result), 2)

    def test_updates_existing_records(self):
        """Test updates existing records."""
        existing = [
            {"date": "2024-01-15", "order_id": "12345", "vendor": "TD", "metal": "gold", "total_oz": "1.0"},
        ]
        new = [
            {"date": "2024-01-16", "order_id": "12345", "vendor": "TD", "metal": "gold", "total_oz": "2.0"},
        ]
        result = _merge_all(existing, new)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["total_oz"], "2.0")

    def test_distinguishes_by_metal(self):
        """Test same order_id+vendor but different metal are separate."""
        existing = [
            {"date": "2024-01-15", "order_id": "12345", "vendor": "TD", "metal": "gold"},
        ]
        new = [
            {"date": "2024-01-15", "order_id": "12345", "vendor": "TD", "metal": "silver"},
        ]
        result = _merge_all(existing, new)
        self.assertEqual(len(result), 2)

    def test_sorts_by_date_order_metal(self):
        """Test sorts results by date, order_id, metal."""
        existing = []
        new = [
            {"date": "2024-02-15", "order_id": "2", "vendor": "TD", "metal": "gold"},
            {"date": "2024-01-15", "order_id": "1", "vendor": "TD", "metal": "silver"},
            {"date": "2024-01-15", "order_id": "1", "vendor": "TD", "metal": "gold"},
        ]
        result = _merge_all(existing, new)
        self.assertEqual(result[0]["metal"], "gold")  # gold < silver alphabetically
        self.assertEqual(result[1]["metal"], "silver")
        self.assertEqual(result[2]["order_id"], "2")


if __name__ == "__main__":
    unittest.main()
