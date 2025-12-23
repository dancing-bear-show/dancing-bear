"""Tests for metals excel_merge module."""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from metals.excel_merge import (
    _col_letter,
    _read_csv,
    _to_records,
    _records_to_values,
    _merge,
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

    def test_reads_csv(self):
        """Test reading CSV file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            w = csv.writer(f)
            w.writerow(["date", "order_id", "vendor"])
            w.writerow(["2024-01-15", "12345", "TD"])
            f.flush()

            rows = _read_csv(f.name)
            self.assertEqual(len(rows), 2)


class TestToRecords(unittest.TestCase):
    """Tests for _to_records function."""

    def test_converts_values_to_records(self):
        """Test converts values to records."""
        values = [
            ["date", "order_id", "vendor"],
            ["2024-01-15", "12345", "TD"],
            ["2024-01-16", "12346", "Costco"],
        ]
        headers, records = _to_records(values)
        self.assertEqual(headers, ["date", "order_id", "vendor"])
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["date"], "2024-01-15")
        self.assertEqual(records[0]["order_id"], "12345")

    def test_handles_empty_values(self):
        """Test handles empty values."""
        headers, records = _to_records([])
        self.assertEqual(headers, [])
        self.assertEqual(records, [])

    def test_handles_header_only(self):
        """Test handles header only."""
        values = [["date", "order_id"]]
        headers, records = _to_records(values)
        self.assertEqual(headers, ["date", "order_id"])
        self.assertEqual(records, [])

    def test_handles_short_rows(self):
        """Test handles rows shorter than headers."""
        values = [
            ["date", "order_id", "vendor"],
            ["2024-01-15"],  # Short row
        ]
        headers, records = _to_records(values)
        self.assertEqual(records[0]["date"], "2024-01-15")
        self.assertEqual(records[0]["order_id"], "")
        self.assertEqual(records[0]["vendor"], "")


class TestRecordsToValues(unittest.TestCase):
    """Tests for _records_to_values function."""

    def test_converts_records_to_values(self):
        """Test converts records back to values."""
        headers = ["date", "order_id", "vendor"]
        records = [
            {"date": "2024-01-15", "order_id": "12345", "vendor": "TD"},
            {"date": "2024-01-16", "order_id": "12346", "vendor": "Costco"},
        ]
        values = _records_to_values(headers, records)
        self.assertEqual(len(values), 3)  # header + 2 rows
        self.assertEqual(values[0], headers)
        self.assertEqual(values[1], ["2024-01-15", "12345", "TD"])

    def test_handles_empty_records(self):
        """Test handles empty records."""
        headers = ["date", "order_id"]
        values = _records_to_values(headers, [])
        self.assertEqual(len(values), 1)  # header only
        self.assertEqual(values[0], headers)


class TestMerge(unittest.TestCase):
    """Tests for _merge function."""

    def test_merges_new_records(self):
        """Test adds new records."""
        existing = [
            {"date": "2024-01-15", "order_id": "12345", "vendor": "TD", "total_oz": "1.0"},
        ]
        new = [
            {"date": "2024-01-16", "order_id": "12346", "vendor": "Costco", "total_oz": "5.0"},
        ]
        result = _merge(existing, new)
        self.assertEqual(len(result), 2)

    def test_updates_existing_records(self):
        """Test updates existing records by order_id+vendor."""
        existing = [
            {"date": "2024-01-15", "order_id": "12345", "vendor": "TD", "total_oz": "1.0"},
        ]
        new = [
            {"date": "2024-01-16", "order_id": "12345", "vendor": "TD", "total_oz": "2.0"},  # Updated
        ]
        result = _merge(existing, new)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["total_oz"], "2.0")  # Updated value

    def test_preserves_extra_columns(self):
        """Test preserves extra columns from existing."""
        existing = [
            {"date": "2024-01-15", "order_id": "12345", "vendor": "TD", "extra_col": "value"},
        ]
        new = [
            {"date": "2024-01-16", "order_id": "12345", "vendor": "TD", "total_oz": "2.0"},
        ]
        result = _merge(existing, new)
        self.assertEqual(result[0]["extra_col"], "value")
        self.assertEqual(result[0]["total_oz"], "2.0")

    def test_sorts_by_date_then_order_id(self):
        """Test sorts results by date then order_id."""
        existing = []
        new = [
            {"date": "2024-02-15", "order_id": "2", "vendor": "TD"},
            {"date": "2024-01-15", "order_id": "1", "vendor": "TD"},
            {"date": "2024-01-15", "order_id": "3", "vendor": "TD"},
        ]
        result = _merge(existing, new)
        self.assertEqual(result[0]["order_id"], "1")
        self.assertEqual(result[1]["order_id"], "3")
        self.assertEqual(result[2]["order_id"], "2")

    def test_handles_empty_existing(self):
        """Test handles empty existing records."""
        new = [{"date": "2024-01-15", "order_id": "12345", "vendor": "TD"}]
        result = _merge([], new)
        self.assertEqual(len(result), 1)

    def test_handles_empty_new(self):
        """Test handles empty new records."""
        existing = [{"date": "2024-01-15", "order_id": "12345", "vendor": "TD"}]
        result = _merge(existing, [])
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
