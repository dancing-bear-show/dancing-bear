"""Tests for excel chart helpers: summary values, charts, filter views, spot/profit series."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from metals.excel_all import (
    _build_summary_values,
    _add_chart,
    _write_filter_view,
    _spot_cad_series,
    _build_profit_series,
)
from metals.workbook import WorkbookContext

def _make_wb(client=None):
    """Helper to create a mock WorkbookContext."""
    if client is None:
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}
    return WorkbookContext(client, "drive123", "item456")


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

class TestAddChart(unittest.TestCase):
    """Tests for _add_chart function."""

    @patch("requests.patch")
    @patch("requests.post")
    def test_creates_chart(self, mock_post, mock_patch):
        """Test creates chart with correct parameters."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "chart123"},
        )
        mock_patch.return_value = MagicMock(status_code=200)

        _add_chart(_make_wb(), "Sheet1", "Line", "A1:B10")

        mock_post.assert_called_once()
        call_data = json.loads(mock_post.call_args[1]["data"])
        self.assertEqual(call_data["type"], "Line")

    @patch("requests.post")
    def test_handles_chart_error(self, mock_post):
        """Test handles chart creation error gracefully."""
        mock_post.return_value = MagicMock(status_code=400)

        # Should not raise
        _add_chart(_make_wb(), "Sheet1", "Line", "A1:B10")

class TestWriteFilterView(unittest.TestCase):
    """Tests for _write_filter_view function."""

    @patch("requests.post")
    @patch("requests.patch")
    def test_writes_filter_formula(self, mock_patch, mock_post):
        """Test writes FILTER formula to sheet."""
        mock_post.return_value = MagicMock(status_code=200)
        mock_patch.return_value = MagicMock(status_code=200)

        _write_filter_view(_make_wb(), "All", "Gold", "gold")

        # Should write header and formula
        self.assertGreater(mock_patch.call_count, 0)
        # Check formula contains FILTER
        for call in mock_patch.call_args_list:
            data = call[1].get("data", "{}")
            if "FILTER" in data:
                self.assertIn("gold", data)
                break

class TestSpotCadSeries(unittest.TestCase):
    """Tests for _spot_cad_series function."""

    @patch("metals.excel_chart._fetch_yahoo_series")
    def test_returns_primary_cad_series(self, mock_fetch):
        """Test returns primary CAD series when available."""
        mock_fetch.side_effect = lambda sym, start, end: (
            {"2024-01-01": 2500.0} if "CAD" in sym else {}
        )

        result = _spot_cad_series("gold", "2024-01-01", "2024-01-01")

        self.assertEqual(result.get("2024-01-01"), 2500.0)

    @patch("metals.excel_chart._fetch_yahoo_series")
    def test_falls_back_to_usd_conversion(self, mock_fetch):
        """Test falls back to USD * USDCAD when CAD unavailable."""
        def mock_series(sym, start, end):
            if "XAUUSD" in sym:
                return {"2024-01-01": 2000.0}
            elif "USDCAD" in sym:
                return {"2024-01-01": 1.35}
            return {}
        mock_fetch.side_effect = mock_series

        result = _spot_cad_series("gold", "2024-01-01", "2024-01-01")

        self.assertAlmostEqual(result.get("2024-01-01"), 2700.0, places=1)

    def test_invalid_metal_returns_empty(self):
        """Test invalid metal returns empty dict."""
        result = _spot_cad_series("platinum", "2024-01-01", "2024-01-01")
        self.assertEqual(result, {})

class TestBuildProfitSeries(unittest.TestCase):
    """Tests for _build_profit_series function."""

    @patch("metals.excel_chart._spot_cad_series")
    def test_builds_profit_series_with_headers(self, mock_spot):
        """Test builds series with correct headers."""
        mock_spot.return_value = {"2024-01-15": 2600.0}
        recs = [
            {"date": "2024-01-15", "metal": "gold", "total_oz": "1.0", "cost_per_oz": "2500.0"},
        ]

        result = _build_profit_series(recs)

        self.assertEqual(result[0][0], "date")
        self.assertIn("gold_pnl", result[0])
        self.assertIn("portfolio_pnl", result[0])

    @patch("metals.excel_chart._spot_cad_series")
    def test_calculates_profit(self, mock_spot):
        """Test calculates profit correctly."""
        mock_spot.return_value = {"2024-01-15": 2600.0}
        recs = [
            {"date": "2024-01-15", "metal": "gold", "total_oz": "1.0", "cost_per_oz": "2500.0"},
        ]

        result = _build_profit_series(recs)

        self.assertEqual(len(result), 2)  # Header + 1 data row
        pnl_idx = result[0].index("gold_pnl")
        self.assertEqual(result[1][pnl_idx], "100.00")

    def test_handles_empty_records(self):
        """Test handles empty records."""
        result = _build_profit_series([])
        self.assertEqual(result, [])

    @patch("metals.excel_chart._spot_cad_series")
    def test_handles_invalid_data(self, mock_spot):
        """Test skips records with invalid data."""
        mock_spot.return_value = {}
        recs = [
            {"date": "", "metal": "gold", "total_oz": "invalid"},
            {"date": "2024-01-15", "metal": "unknown", "total_oz": "1.0"},
        ]

        result = _build_profit_series(recs)

        # Should return empty since no valid records
        self.assertEqual(result, [])

if __name__ == "__main__":
    unittest.main()
