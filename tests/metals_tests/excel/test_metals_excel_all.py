"""Tests for metals/excel_all.py - re-imports plus targeted coverage for _copy_item and main()."""
from __future__ import annotations

import csv
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tests.metals_tests.excel.test_excel_io import (  # noqa: F401
    TestColLetter,
    TestReadCsv,
    TestToRecords,
    TestMergeAll,
    TestToValuesAll,
    TestSetSheetPosition,
    TestSetSheetVisibility,
    TestFillDateGaps,
    TestListWorksheets,
    TestGetUsedRangeValues,
    TestEnsureSheet,
    TestWriteRange,
    TestWorkbookContextBaseUrl,
    TestPadRows,
    TestPollAsyncOperation,
    TestSumifFormula,
    TestAvgcostFormula,
    TestSummaryRow,
)
from tests.metals_tests.excel.test_excel_chart import (  # noqa: F401
    TestBuildSummaryValues,
    TestAddChart,
    TestWriteFilterView,
    TestSpotCadSeries,
    TestBuildProfitSeries,
)

from metals.workbook import WorkbookContext


def _make_wb(drive_id="drive123", item_id="item456"):
    client = MagicMock()
    client.GRAPH = "https://graph.microsoft.com/v1.0"
    client._headers.return_value = {"Authorization": "Bearer tok"}
    return WorkbookContext(client, drive_id, item_id)


class TestCopyItemExcelAll(unittest.TestCase):
    """Tests for _copy_item in excel_all.py (lines 76-104)."""

    @patch("requests.get")
    @patch("requests.post")
    def test_returns_new_wb_via_poll(self, mock_post, mock_get):
        """Test _copy_item polls async operation and returns new WorkbookContext."""
        from metals.excel_all import _copy_item, _poll_async_operation

        # GET /items/{id} → parent metadata
        mock_get.side_effect = [
            MagicMock(json=MagicMock(return_value={"parentReference": {"id": "parent-id"}})),
            # Second GET is the poll (status succeeded)
            MagicMock(json=MagicMock(return_value={"status": "succeeded", "resourceId": "new-item"})),
        ]
        mock_post.return_value.status_code = 202
        mock_post.return_value.headers = {"Location": "http://monitor/url"}

        wb = _make_wb()
        with patch("time.sleep"):
            new_wb = _copy_item(wb, "Merged.xlsx")

        self.assertIsInstance(new_wb, WorkbookContext)
        self.assertEqual(new_wb.item_id, "new-item")
        self.assertEqual(new_wb.drive_id, "drive123")

    @patch("requests.get")
    @patch("requests.post")
    def test_returns_new_wb_from_body_on_200(self, mock_post, mock_get):
        """Test _copy_item returns WorkbookContext from body when 200 response has no Location."""
        from metals.excel_all import _copy_item

        mock_get.return_value.json.return_value = {}  # no parentReference
        mock_post.return_value.status_code = 200
        mock_post.return_value.headers = {}  # no Location
        mock_post.return_value.json.return_value = {"id": "direct-new-id"}

        wb = _make_wb()
        new_wb = _copy_item(wb, "Merged.xlsx")

        self.assertIsInstance(new_wb, WorkbookContext)
        self.assertEqual(new_wb.item_id, "direct-new-id")

    @patch("requests.get")
    @patch("requests.post")
    def test_raises_on_copy_failure(self, mock_post, mock_get):
        """Test _copy_item raises RuntimeError when copy returns non-200/202."""
        from metals.excel_all import _copy_item

        mock_get.return_value.json.return_value = {}
        mock_post.return_value.status_code = 500
        mock_post.return_value.text = "Server Error"

        wb = _make_wb()
        with self.assertRaises(RuntimeError) as ctx:
            _copy_item(wb, "Merged.xlsx")
        self.assertIn("Copy failed", str(ctx.exception))

    @patch("requests.get")
    @patch("requests.post")
    def test_raises_when_no_location_and_no_body(self, mock_post, mock_get):
        """Test raises RuntimeError when no Location and no parseable body."""
        from metals.excel_all import _copy_item

        mock_get.return_value.json.return_value = {}
        mock_post.return_value.status_code = 202
        mock_post.return_value.headers = {}  # no Location
        mock_post.return_value.json.side_effect = Exception("no json")

        wb = _make_wb()
        with self.assertRaises(RuntimeError) as ctx:
            _copy_item(wb, "Merged.xlsx")
        self.assertIn("no body", str(ctx.exception))

    @patch("requests.get")
    @patch("requests.post")
    def test_includes_parent_reference_in_body(self, mock_post, mock_get):
        """Test _copy_item includes parentReference in request body when parent_id available."""
        from metals.excel_all import _copy_item
        import json

        mock_get.return_value.json.return_value = {"parentReference": {"id": "parent-xyz"}}
        mock_post.return_value.status_code = 200
        mock_post.return_value.headers = {}
        mock_post.return_value.json.return_value = {"id": "item-with-parent"}

        wb = _make_wb()
        _copy_item(wb, "Copy.xlsx")

        body = json.loads(mock_post.call_args[1]["data"])
        self.assertIn("parentReference", body)
        self.assertEqual(body["parentReference"]["id"], "parent-xyz")


class TestMainExcelAll(unittest.TestCase):
    """Integration tests for the main() entry point in excel_all.py."""

    def _make_csv(self, rows):
        """Helper: write rows to a temp CSV and return its path."""
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        self.addCleanup(os.unlink, f.name)
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
        f.flush()
        f.close()
        return f.name

    @patch("metals.excel_all._build_profit_series")
    @patch("metals.excel_all._write_range")
    @patch("metals.excel_all._write_filter_view")
    @patch("metals.excel_all._add_chart")
    @patch("metals.excel_all._set_sheet_visibility")
    @patch("metals.excel_all._set_sheet_position")
    @patch("metals.excel_all._ensure_sheet")
    @patch("metals.excel_all._copy_item")
    @patch("metals.excel_all._read_existing_workbook_recs")
    @patch("metals.excel_all.OutlookClient")
    @patch("metals.excel_all.resolve_outlook_credentials")
    def test_main_happy_path(
        self,
        mock_creds,
        mock_client_cls,
        mock_read_existing,
        mock_copy,
        mock_ensure,
        mock_set_pos,
        mock_set_vis,
        mock_add_chart,
        mock_write_filter,
        mock_write_range,
        mock_profit,
    ):
        """Test main() runs end-to-end with all I/O mocked."""
        mock_creds.return_value = ("client-id", "consumers", "/tmp/tok")
        mock_client_cls.return_value = MagicMock()
        mock_read_existing.return_value = []
        mock_copy.return_value = _make_wb("drive-new", "item-new")
        mock_ensure.return_value = {"name": "Sheet"}
        mock_profit.return_value = []  # No profit data → no profit sheet

        silver_csv = self._make_csv([
            {"date": "2024-01-01", "order_id": "1", "vendor": "TD", "total_oz": "1.0", "cost_per_oz": "30.00"},
        ])
        gold_csv = self._make_csv([
            {"date": "2024-01-02", "order_id": "2", "vendor": "Costco", "total_oz": "0.5", "cost_per_oz": "2500.00"},
        ])

        from metals.excel_all import main
        rc = main([
            "--drive-id", "drive-src",
            "--item-id", "item-src",
            "--silver-csv", silver_csv,
            "--gold-csv", gold_csv,
        ])
        self.assertEqual(rc, 0)

    @patch("metals.excel_all._build_profit_series")
    @patch("metals.excel_all._write_range")
    @patch("metals.excel_all._write_filter_view")
    @patch("metals.excel_all._add_chart")
    @patch("metals.excel_all._set_sheet_visibility")
    @patch("metals.excel_all._set_sheet_position")
    @patch("metals.excel_all._ensure_sheet")
    @patch("metals.excel_all._copy_item")
    @patch("metals.excel_all._read_existing_workbook_recs")
    @patch("metals.excel_all.OutlookClient")
    @patch("metals.excel_all.resolve_outlook_credentials")
    def test_main_with_profit_data_creates_profit_sheet(
        self,
        mock_creds,
        mock_client_cls,
        mock_read_existing,
        mock_copy,
        mock_ensure,
        mock_set_pos,
        mock_set_vis,
        mock_add_chart,
        mock_write_filter,
        mock_write_range,
        mock_profit,
    ):
        """Test main() creates Profit sheet when profit series data is present."""
        mock_creds.return_value = ("client-id", "consumers", "/tmp/tok")
        mock_client_cls.return_value = MagicMock()
        mock_read_existing.return_value = []
        mock_copy.return_value = _make_wb("drive-new", "item-new")
        mock_ensure.return_value = {"name": "Sheet"}
        # Return non-empty profit data → triggers Profit sheet creation
        mock_profit.return_value = [
            ["date", "gold_spot", "gold_avg", "gold_pnl", "gold_oz", "silver_spot",
             "silver_avg", "silver_pnl", "silver_oz", "portfolio_pnl"],
            ["2024-01-01", "2500.0", "2400.0", "100.0", "1.0",
             "30.0", "28.0", "2.0", "10.0", "102.0"],
        ]

        silver_csv = self._make_csv([
            {"date": "2024-01-01", "order_id": "1", "vendor": "TD", "total_oz": "10.0", "cost_per_oz": "28.0"},
        ])
        gold_csv = self._make_csv([
            {"date": "2024-01-01", "order_id": "2", "vendor": "Costco", "total_oz": "1.0", "cost_per_oz": "2400.0"},
        ])

        from metals.excel_all import main
        rc = main([
            "--drive-id", "drive-src",
            "--item-id", "item-src",
            "--silver-csv", silver_csv,
            "--gold-csv", gold_csv,
        ])
        self.assertEqual(rc, 0)
        # Profit sheet should be created (5 base sheets + 1 profit)
        self.assertGreaterEqual(mock_ensure.call_count, 5)

    @patch("metals.excel_all.resolve_outlook_credentials")
    def test_main_exits_without_client_id(self, mock_creds):
        """Test main() raises SystemExit when no client_id configured."""
        mock_creds.return_value = (None, None, None)

        from metals.excel_all import main
        with self.assertRaises(SystemExit):
            main([
                "--drive-id", "x",
                "--item-id", "y",
                "--silver-csv", "/tmp/s.csv",
                "--gold-csv", "/tmp/g.csv",
            ])

    @patch("metals.excel_all._build_profit_series")
    @patch("metals.excel_all._write_range")
    @patch("metals.excel_all._write_filter_view")
    @patch("metals.excel_all._add_chart")
    @patch("metals.excel_all._set_sheet_visibility")
    @patch("metals.excel_all._set_sheet_position")
    @patch("metals.excel_all._ensure_sheet")
    @patch("metals.excel_all._copy_item")
    @patch("metals.excel_all._read_existing_workbook_recs")
    @patch("metals.excel_all.OutlookClient")
    @patch("metals.excel_all.resolve_outlook_credentials")
    def test_main_sheet_position_exception_is_swallowed(
        self,
        mock_creds,
        mock_client_cls,
        mock_read_existing,
        mock_copy,
        mock_ensure,
        mock_set_pos,
        mock_set_vis,
        mock_add_chart,
        mock_write_filter,
        mock_write_range,
        mock_profit,
    ):
        """Test main() swallows sheet positioning exceptions (nosec B110 paths)."""
        mock_creds.return_value = ("client-id", "consumers", "/tmp/tok")
        mock_client_cls.return_value = MagicMock()
        mock_read_existing.return_value = []
        mock_copy.return_value = _make_wb("drive-new", "item-new")
        mock_ensure.return_value = {"name": "Sheet"}
        mock_profit.return_value = []
        # Force sheet positioning to throw
        mock_set_pos.side_effect = RuntimeError("Position API not supported")

        silver_csv = self._make_csv([
            {"date": "2024-01-01", "order_id": "1", "vendor": "TD", "total_oz": "1.0", "cost_per_oz": "30.00"},
        ])
        gold_csv = self._make_csv([
            {"date": "2024-01-01", "order_id": "2", "vendor": "Costco", "total_oz": "0.5", "cost_per_oz": "2500.00"},
        ])

        from metals.excel_all import main
        # Should NOT raise - the exception is swallowed
        rc = main([
            "--drive-id", "drive-src",
            "--item-id", "item-src",
            "--silver-csv", silver_csv,
            "--gold-csv", gold_csv,
        ])
        self.assertEqual(rc, 0)

    @patch("metals.excel_all._build_profit_series")
    @patch("metals.excel_all._write_range")
    @patch("metals.excel_all._write_filter_view")
    @patch("metals.excel_all._add_chart")
    @patch("metals.excel_all._set_sheet_visibility")
    @patch("metals.excel_all._set_sheet_position")
    @patch("metals.excel_all._ensure_sheet")
    @patch("metals.excel_all._copy_item")
    @patch("metals.excel_all._read_existing_workbook_recs")
    @patch("metals.excel_all.OutlookClient")
    @patch("metals.excel_all.resolve_outlook_credentials")
    def test_main_visibility_exception_is_swallowed(
        self,
        mock_creds,
        mock_client_cls,
        mock_read_existing,
        mock_copy,
        mock_ensure,
        mock_set_pos,
        mock_set_vis,
        mock_add_chart,
        mock_write_filter,
        mock_write_range,
        mock_profit,
    ):
        """Test main() swallows sheet visibility exceptions (nosec B110 path)."""
        mock_creds.return_value = ("client-id", "consumers", "/tmp/tok")
        mock_client_cls.return_value = MagicMock()
        mock_read_existing.return_value = []
        mock_copy.return_value = _make_wb("drive-new", "item-new")
        mock_ensure.return_value = {"name": "Sheet"}
        mock_profit.return_value = []
        mock_set_vis.side_effect = RuntimeError("Visibility API not supported")

        silver_csv = self._make_csv([
            {"date": "2024-01-01", "order_id": "1", "vendor": "TD", "total_oz": "1.0", "cost_per_oz": "30.00"},
        ])
        gold_csv = self._make_csv([
            {"date": "2024-01-01", "order_id": "2", "vendor": "Costco", "total_oz": "0.5", "cost_per_oz": "2500.00"},
        ])

        from metals.excel_all import main
        rc = main([
            "--drive-id", "drive-src",
            "--item-id", "item-src",
            "--silver-csv", silver_csv,
            "--gold-csv", gold_csv,
        ])
        self.assertEqual(rc, 0)


if __name__ == '__main__':
    unittest.main()
