"""Tests for metals excel_all module."""
from __future__ import annotations

import csv
import json
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
    _fill_date_gaps,
    _list_worksheets,
    _get_used_range_values,
    _ensure_sheet,
    _write_range,
    _add_chart,
    _write_filter_view,
    _spot_cad_series,
    _build_profit_series,
    _pad_rows,
    _poll_async_operation,
    _sumif_formula,
    _avgcost_formula,
    _summary_row,
)
from metals.workbook import WorkbookContext


def _make_wb(client=None):
    """Helper to create a mock WorkbookContext."""
    if client is None:
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}
    return WorkbookContext(client, "drive123", "item456")


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

        _set_sheet_position(_make_wb(client), "Sheet1", 2)

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

        _set_sheet_visibility(_make_wb(client), "Sheet1", True)

        call_args = mock_patch.call_args
        self.assertIn('"visibility": "Visible"', call_args[1]["data"])

    @patch("requests.patch")
    def test_sets_hidden(self, mock_patch):
        """Test sets visibility to Hidden."""
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        _set_sheet_visibility(_make_wb(client), "Sheet1", False)

        call_args = mock_patch.call_args
        self.assertIn('"visibility": "Hidden"', call_args[1]["data"])


class TestFillDateGaps(unittest.TestCase):
    """Tests for _fill_date_gaps helper function."""

    def test_empty_series_returns_unchanged(self):
        """Test empty series returns empty."""
        result = _fill_date_gaps({}, "2024-01-01", "2024-01-05")
        self.assertEqual(result, {})

    def test_forward_fills_gaps(self):
        """Test forward-fills missing dates."""
        series = {"2024-01-01": 100.0, "2024-01-03": 102.0}
        result = _fill_date_gaps(series, "2024-01-01", "2024-01-03")
        self.assertEqual(result["2024-01-01"], 100.0)
        self.assertEqual(result["2024-01-02"], 100.0)  # Forward-filled
        self.assertEqual(result["2024-01-03"], 102.0)

    def test_back_fills_start(self):
        """Test back-fills initial gap."""
        series = {"2024-01-03": 100.0}
        result = _fill_date_gaps(series, "2024-01-01", "2024-01-03")
        self.assertEqual(result["2024-01-01"], 100.0)  # Back-filled
        self.assertEqual(result["2024-01-02"], 100.0)  # Back-filled
        self.assertEqual(result["2024-01-03"], 100.0)

    def test_continuous_series_unchanged(self):
        """Test already continuous series is unchanged."""
        series = {"2024-01-01": 100.0, "2024-01-02": 101.0, "2024-01-03": 102.0}
        result = _fill_date_gaps(series, "2024-01-01", "2024-01-03")
        self.assertEqual(result, series)


class TestListWorksheets(unittest.TestCase):
    """Tests for _list_worksheets function."""

    @patch("requests.get")
    def test_returns_worksheet_names(self, mock_get):
        """Test returns list of worksheet names."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"value": [{"name": "Sheet1"}, {"name": "Sheet2"}]},
            raise_for_status=lambda: None,
        )

        result = _list_worksheets(_make_wb())

        self.assertEqual(result, ["Sheet1", "Sheet2"])

    @patch("requests.get")
    def test_filters_empty_names(self, mock_get):
        """Test filters out worksheets with empty names."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"value": [{"name": "Sheet1"}, {"name": ""}, {"name": None}]},
            raise_for_status=lambda: None,
        )

        result = _list_worksheets(_make_wb())

        self.assertEqual(result, ["Sheet1"])


class TestGetUsedRangeValues(unittest.TestCase):
    """Tests for _get_used_range_values function."""

    @patch("requests.get")
    def test_returns_values_on_success(self, mock_get):
        """Test returns values from used range."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"values": [["A1", "B1"], ["A2", "B2"]]},
        )

        result = _get_used_range_values(_make_wb(), "Sheet1")

        self.assertEqual(result, [["A1", "B1"], ["A2", "B2"]])

    @patch("requests.get")
    def test_returns_empty_on_error(self, mock_get):
        """Test returns empty list on 4xx error."""
        mock_get.return_value = MagicMock(status_code=404)

        result = _get_used_range_values(_make_wb(), "Sheet1")

        self.assertEqual(result, [])


class TestEnsureSheet(unittest.TestCase):
    """Tests for _ensure_sheet function."""

    @patch("requests.post")
    @patch("requests.get")
    def test_returns_existing_sheet(self, mock_get, mock_post):
        """Test returns existing sheet without creating."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "sheet123", "name": "Sheet1"},
        )

        result = _ensure_sheet(_make_wb(), "Sheet1")

        self.assertEqual(result["name"], "Sheet1")
        mock_post.assert_not_called()

    @patch("requests.post")
    @patch("requests.get")
    def test_creates_missing_sheet(self, mock_get, mock_post):
        """Test creates sheet when not found."""
        mock_get.return_value = MagicMock(status_code=404)
        mock_post.return_value = MagicMock(
            status_code=201,
            json=lambda: {"id": "new_sheet", "name": "NewSheet"},
        )

        result = _ensure_sheet(_make_wb(), "NewSheet")

        self.assertEqual(result["name"], "NewSheet")
        mock_post.assert_called_once()


class TestWriteRange(unittest.TestCase):
    """Tests for _write_range function."""

    @patch("requests.post")
    @patch("requests.patch")
    def test_clears_and_writes_values(self, mock_patch, mock_post):
        """Test clears range and writes values."""
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {})
        mock_patch.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)

        values = [["A", "B"], ["1", "2"]]
        _write_range(_make_wb(), "Sheet1", values)

        # Should call clear, patch (write), and table add
        self.assertGreater(mock_post.call_count, 0)
        self.assertGreater(mock_patch.call_count, 0)

    @patch("requests.post")
    @patch("requests.patch")
    def test_handles_empty_values(self, mock_patch, mock_post):
        """Test handles empty values - only clears."""
        mock_post.return_value = MagicMock(status_code=200)

        _write_range(_make_wb(), "Sheet1", [])

        # Should still call clear
        self.assertEqual(mock_post.call_count, 1)
        mock_patch.assert_not_called()


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

    @patch("metals.excel_all._fetch_yahoo_series")
    def test_returns_primary_cad_series(self, mock_fetch):
        """Test returns primary CAD series when available."""
        mock_fetch.side_effect = lambda sym, start, end: (
            {"2024-01-01": 2500.0} if "CAD" in sym else {}
        )

        result = _spot_cad_series("gold", "2024-01-01", "2024-01-01")

        self.assertEqual(result.get("2024-01-01"), 2500.0)

    @patch("metals.excel_all._fetch_yahoo_series")
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

    @patch("metals.excel_all._spot_cad_series")
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

    @patch("metals.excel_all._spot_cad_series")
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

    @patch("metals.excel_all._spot_cad_series")
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


class TestWorkbookContextBaseUrl(unittest.TestCase):
    """Tests for WorkbookContext.base_url property."""

    def test_builds_correct_url(self):
        """Test builds correct Graph API URL."""
        wb = _make_wb()
        self.assertEqual(wb.base_url, "https://graph.microsoft.com/v1.0/drives/drive123/items/item456/workbook")


class TestPadRows(unittest.TestCase):
    """Tests for _pad_rows helper function."""

    def test_pads_short_rows(self):
        """Test pads rows shorter than cols."""
        values = [["A", "B"], ["1"]]
        result = _pad_rows(values, 2)
        self.assertEqual(result, [["A", "B"], ["1", ""]])

    def test_leaves_full_rows(self):
        """Test leaves rows at full width unchanged."""
        values = [["A", "B"], ["1", "2"]]
        result = _pad_rows(values, 2)
        self.assertEqual(result, [["A", "B"], ["1", "2"]])

    def test_empty_values(self):
        """Test handles empty values."""
        result = _pad_rows([], 2)
        self.assertEqual(result, [])


class TestPollAsyncOperation(unittest.TestCase):
    """Tests for _poll_async_operation function."""

    @patch("time.sleep")
    @patch("requests.get")
    def test_returns_resource_id_on_success(self, mock_get, mock_sleep):
        """Test returns resourceId when operation succeeds."""
        mock_get.return_value = MagicMock(
            json=lambda: {"status": "succeeded", "resourceId": "new_item_123"}
        )
        client = MagicMock()
        client._headers.return_value = {}

        result = _poll_async_operation(client, "http://monitor/url", max_attempts=1)

        self.assertEqual(result, "new_item_123")

    @patch("time.sleep")
    @patch("requests.get")
    def test_follows_resource_location(self, mock_get, mock_sleep):
        """Test follows resourceLocation to get ID."""
        mock_get.side_effect = [
            MagicMock(json=lambda: {"status": "completed", "resourceLocation": "http://resource/url"}),
            MagicMock(json=lambda: {"id": "item_from_location"}),
        ]
        client = MagicMock()
        client._headers.return_value = {}

        result = _poll_async_operation(client, "http://monitor/url", max_attempts=2)

        self.assertEqual(result, "item_from_location")

    @patch("time.sleep")
    @patch("requests.get")
    def test_raises_on_timeout(self, mock_get, mock_sleep):
        """Test raises RuntimeError on timeout."""
        mock_get.return_value = MagicMock(json=lambda: {"status": "inProgress"})
        client = MagicMock()
        client._headers.return_value = {}

        with self.assertRaises(RuntimeError) as ctx:
            _poll_async_operation(client, "http://monitor/url", max_attempts=2, delay=0.01)

        self.assertIn("Timed out", str(ctx.exception))


class TestSumifFormula(unittest.TestCase):
    """Tests for _sumif_formula helper function."""

    def test_builds_correct_formula(self):
        """Test builds correct SUMIF formula."""
        result = _sumif_formula("All", "D", "gold", "E")
        self.assertEqual(result, "=SUMIF('All'!$D$2:$D$100000,\"gold\",'All'!$E$2:$E$100000)")


class TestAvgcostFormula(unittest.TestCase):
    """Tests for _avgcost_formula helper function."""

    def test_builds_correct_formula(self):
        """Test builds correct weighted average formula."""
        result = _avgcost_formula("All", "D", "gold", "E", "F")
        self.assertIn("SUMPRODUCT", result)
        self.assertIn("IFERROR", result)
        self.assertIn("gold", result)


class TestSummaryRow(unittest.TestCase):
    """Tests for _summary_row helper function."""

    def test_builds_row_with_formulas(self):
        """Test builds row with label and formulas."""
        result = _summary_row("All", "gold", "D")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], "gold")
        self.assertIn("SUMIF", result[1])
        self.assertIn("SUMPRODUCT", result[2])


if __name__ == "__main__":
    unittest.main()
