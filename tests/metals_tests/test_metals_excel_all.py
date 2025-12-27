"""Tests for metals excel_all module."""
from __future__ import annotations

import csv
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from metals.excel_all import (
    _col_letter,
    _read_csv,
    _to_records,
    _merge_all,
    _to_values_all,
    _build_summary_values,
    _set_sheet_position,
    _set_sheet_visibility,
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


class TestToValuesAll(unittest.TestCase):
    """Tests for _to_values_all function."""

    def test_converts_records_to_values(self):
        """Test converts records to 2D list."""
        recs = [
            {"date": "2024-01-15", "order_id": "12345", "vendor": "TD", "metal": "gold", "total_oz": "1.0", "cost_per_oz": "2500.00"},
        ]
        result = _to_values_all(recs)
        self.assertEqual(result[0], ["date", "order_id", "vendor", "metal", "total_oz", "cost_per_oz"])
        self.assertEqual(result[1], ["2024-01-15", "12345", "TD", "gold", "1.0", "2500.00"])

    def test_handles_empty_records(self):
        """Test handles empty records list."""
        result = _to_values_all([])
        self.assertEqual(len(result), 1)  # Just headers
        self.assertEqual(result[0], ["date", "order_id", "vendor", "metal", "total_oz", "cost_per_oz"])

    def test_handles_missing_fields(self):
        """Test handles records with missing fields."""
        recs = [{"date": "2024-01-15"}]
        result = _to_values_all(recs)
        self.assertEqual(result[1][0], "2024-01-15")
        self.assertEqual(result[1][1], "")  # Missing order_id


class TestBuildSummaryValues(unittest.TestCase):
    """Tests for _build_summary_values function."""

    def test_aggregates_by_metal(self):
        """Test aggregates totals by metal."""
        recs = [
            {"date": "2024-01-15", "metal": "gold", "total_oz": "1.0", "cost_per_oz": "2500.00"},
            {"date": "2024-01-16", "metal": "gold", "total_oz": "2.0", "cost_per_oz": "2600.00"},
            {"date": "2024-01-17", "metal": "silver", "total_oz": "10.0", "cost_per_oz": "30.00"},
        ]
        values, _ = _build_summary_values(recs)
        # Find the metal totals section
        metal_idx = None
        for i, row in enumerate(values):
            if row and row[0] == "Totals by Metal":
                metal_idx = i
                break
        self.assertIsNotNone(metal_idx)
        # Gold: 1.0 + 2.0 = 3.0 oz, avg = (1*2500 + 2*2600) / 3 = 7700/3 = 2566.67
        gold_row = values[metal_idx + 2]  # Skip title and header
        self.assertEqual(gold_row[0], "gold")
        self.assertEqual(gold_row[1], "3.00")
        self.assertAlmostEqual(float(gold_row[2]), 2566.67, places=1)

    def test_aggregates_by_vendor(self):
        """Test aggregates totals by vendor."""
        recs = [
            {"date": "2024-01-15", "metal": "gold", "vendor": "TD", "total_oz": "1.0", "cost_per_oz": "2500.00"},
            {"date": "2024-01-16", "metal": "silver", "vendor": "TD", "total_oz": "10.0", "cost_per_oz": "30.00"},
            {"date": "2024-01-17", "metal": "gold", "vendor": "Costco", "total_oz": "2.0", "cost_per_oz": "2600.00"},
        ]
        values, anchors = _build_summary_values(recs)
        # Find vendor section
        vendor_idx = None
        for i, row in enumerate(values):
            if row and row[0] == "Totals by Vendor":
                vendor_idx = i
                break
        self.assertIsNotNone(vendor_idx)
        self.assertIn("Totals by Vendor", anchors)

    def test_aggregates_monthly(self):
        """Test aggregates by month and metal."""
        recs = [
            {"date": "2024-01-15", "metal": "gold", "total_oz": "1.0", "cost_per_oz": "2500.00"},
            {"date": "2024-02-15", "metal": "gold", "total_oz": "2.0", "cost_per_oz": "2600.00"},
        ]
        _, anchors = _build_summary_values(recs)
        # Check monthly sections exist
        self.assertIn("Monthly Avg Cost by Metal", anchors)
        self.assertIn("Monthly Ounces by Metal", anchors)

    def test_handles_empty_records(self):
        """Test handles empty records."""
        values, _ = _build_summary_values([])
        self.assertGreater(len(values), 0)  # Should still have section headers

    def test_handles_invalid_numbers(self):
        """Test handles invalid number values gracefully."""
        recs = [
            {"date": "2024-01-15", "metal": "gold", "total_oz": "invalid", "cost_per_oz": "also_invalid"},
        ]
        values, _ = _build_summary_values(recs)
        # Should not raise, just skip invalid values
        self.assertGreater(len(values), 0)

    def test_skips_zero_values(self):
        """Test skips records with zero oz or cost."""
        recs = [
            {"date": "2024-01-15", "metal": "gold", "total_oz": "0", "cost_per_oz": "2500.00"},
            {"date": "2024-01-16", "metal": "silver", "total_oz": "10.0", "cost_per_oz": "0"},
        ]
        values, _ = _build_summary_values(recs)
        # Zero values should be skipped in aggregations
        self.assertGreater(len(values), 0)


class TestSetSheetPosition(unittest.TestCase):
    """Tests for _set_sheet_position function."""

    @patch("requests.patch")
    def test_calls_patch_with_position(self, mock_patch):
        """Test calls PATCH with correct position."""
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {"Authorization": "Bearer token"}

        _set_sheet_position(client, "drive123", "item456", "Sheet1", 2)

        mock_patch.assert_called_once()
        call_args = mock_patch.call_args
        self.assertIn("worksheets('Sheet1')", call_args[0][0])
        self.assertIn('"position": 2', call_args[1]["data"])


class TestSetSheetVisibility(unittest.TestCase):
    """Tests for _set_sheet_visibility function."""

    @patch("requests.patch")
    def test_sets_visible(self, mock_patch):
        """Test sets visibility to Visible."""
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        _set_sheet_visibility(client, "drive123", "item456", "Sheet1", True)

        call_args = mock_patch.call_args
        self.assertIn('"visibility": "Visible"', call_args[1]["data"])

    @patch("requests.patch")
    def test_sets_hidden(self, mock_patch):
        """Test sets visibility to Hidden."""
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        _set_sheet_visibility(client, "drive123", "item456", "Sheet1", False)

        call_args = mock_patch.call_args
        self.assertIn('"visibility": "Hidden"', call_args[1]["data"])


if __name__ == "__main__":
    unittest.main()
