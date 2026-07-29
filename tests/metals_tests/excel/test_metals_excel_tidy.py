"""Tests for metals excel_tidy module."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from metals.excel_tidy import (
    _list_sheets,
    _delete_sheet,
    _list_charts,
    _used_rows,
    _set_chart_title,
    _set_axis_titles,
    _set_chart_data,
)
from metals.workbook import WorkbookContext


def _make_wb(client=None):
    """Helper to create a mock WorkbookContext."""
    if client is None:
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}
    return WorkbookContext(client, "drive-id", "item-id")


class TestListSheets(unittest.TestCase):
    """Tests for _list_sheets function."""

    @patch("requests.get")
    def test_lists_sheets(self, mock_get):
        """Test lists worksheets."""
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.return_value = {
            "value": [
                {"id": "1", "name": "Sheet1"},
                {"id": "2", "name": "Sheet2"},
            ]
        }

        result = _list_sheets(_make_wb())
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Sheet1")


class TestDeleteSheet(unittest.TestCase):
    """Tests for _delete_sheet function."""

    @patch("requests.delete")
    def test_deletes_sheet(self, mock_delete):
        """Test deletes worksheet."""
        _delete_sheet(_make_wb(), "Sheet1")
        mock_delete.assert_called_once()
        call_url = mock_delete.call_args[0][0]
        self.assertIn("Sheet1", call_url)


class TestListCharts(unittest.TestCase):
    """Tests for _list_charts function."""

    @patch("requests.get")
    def test_lists_charts(self, mock_get):
        """Test lists charts in worksheet."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "value": [
                {"id": "chart1", "name": "Chart 1"},
            ]
        }

        result = _list_charts(_make_wb(), "Sheet1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "chart1")

    @patch("requests.get")
    def test_returns_empty_on_error(self, mock_get):
        """Test returns empty list on error."""
        mock_get.return_value.status_code = 404

        result = _list_charts(_make_wb(), "Sheet1")
        self.assertEqual(result, [])


class TestUsedRows(unittest.TestCase):
    """Tests for _used_rows function."""

    @patch("requests.get")
    def test_returns_row_count(self, mock_get):
        """Test returns row count."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "values": [
                ["Header1", "Header2"],
                ["Data1", "Data2"],
                ["Data3", "Data4"],
            ]
        }

        result = _used_rows(_make_wb(), "Sheet1")
        self.assertEqual(result, 3)

    @patch("requests.get")
    def test_returns_zero_on_error(self, mock_get):
        """Test returns 0 on error."""
        mock_get.return_value.status_code = 404

        result = _used_rows(_make_wb(), "Sheet1")
        self.assertEqual(result, 0)


class TestSetChartTitle(unittest.TestCase):
    """Tests for _set_chart_title function."""

    @patch("requests.patch")
    def test_sets_chart_title(self, mock_patch):
        """Test sets chart title."""
        _set_chart_title(_make_wb(), "Summary", "chart1", "My Chart")

        mock_patch.assert_called_once()
        call_args = mock_patch.call_args
        self.assertIn("charts('chart1')/title", call_args[0][0])
        self.assertIn('"text": "My Chart"', call_args[1]["data"])
        self.assertIn('"visible": true', call_args[1]["data"])


class TestSetAxisTitles(unittest.TestCase):
    """Tests for _set_axis_titles function."""

    @patch("requests.patch")
    def test_sets_category_axis(self, mock_patch):
        """Test sets category axis title."""
        _set_axis_titles(_make_wb(), "Sheet1", "chart1", category="Date", value=None)

        mock_patch.assert_called_once()
        call_args = mock_patch.call_args
        self.assertIn("categoryAxis/title", call_args[0][0])
        self.assertIn('"text": "Date"', call_args[1]["data"])

    @patch("requests.patch")
    def test_sets_value_axis(self, mock_patch):
        """Test sets value axis title."""
        _set_axis_titles(_make_wb(), "Sheet1", "chart1", category=None, value="Price")

        mock_patch.assert_called_once()
        call_args = mock_patch.call_args
        self.assertIn("valueAxis/title", call_args[0][0])
        self.assertIn('"text": "Price"', call_args[1]["data"])

    @patch("requests.patch")
    def test_sets_both_axes(self, mock_patch):
        """Test sets both axis titles."""
        _set_axis_titles(_make_wb(), "Sheet1", "chart1", category="Date", value="C$")

        self.assertEqual(mock_patch.call_count, 2)

    @patch("requests.patch")
    def test_no_call_when_both_none(self, mock_patch):
        """Test no API call when both are None."""
        _set_axis_titles(_make_wb(), "Sheet1", "chart1", category=None, value=None)

        mock_patch.assert_not_called()


class TestSetChartData(unittest.TestCase):
    """Tests for _set_chart_data function."""

    @patch("requests.post")
    def test_sets_chart_data_range(self, mock_post):
        """Test sets chart data source range."""
        _set_chart_data(_make_wb(), "Profit", "chart1", "A1:B10")

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn("charts('chart1')/setData", call_args[0][0])
        self.assertIn("'Profit'!A1:B10", call_args[1]["data"])
        self.assertIn('"seriesBy": "Auto"', call_args[1]["data"])


class TestTidyDefaultSheets(unittest.TestCase):
    """Tests for _tidy_default_sheets function."""

    @patch("requests.delete")
    @patch("requests.get")
    def test_deletes_unnamed_sheet_starting_with_sheet(self, mock_get, mock_delete):
        """Test removes default Sheet* sheets not in allowed set."""
        from metals.excel_tidy import _tidy_default_sheets
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.return_value = {
            "value": [
                {"id": "1", "name": "Sheet1"},
                {"id": "2", "name": "Gold"},
                {"id": "3", "name": "Silver"},
            ]
        }
        _tidy_default_sheets(_make_wb(), allowed={"Gold", "Silver"})
        # Sheet1 should be deleted (starts with 'sheet', not in allowed)
        self.assertEqual(mock_delete.call_count, 1)
        call_url = mock_delete.call_args[0][0]
        self.assertIn("Sheet1", call_url)

    @patch("requests.delete")
    @patch("requests.get")
    def test_does_not_delete_allowed_sheets(self, mock_get, mock_delete):
        """Test keeps sheets that are in the allowed set."""
        from metals.excel_tidy import _tidy_default_sheets
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.return_value = {
            "value": [
                {"id": "1", "name": "Summary"},
                {"id": "2", "name": "Gold"},
            ]
        }
        _tidy_default_sheets(_make_wb(), allowed={"Summary", "Gold"})
        mock_delete.assert_not_called()

    @patch("requests.delete")
    @patch("requests.get")
    def test_deletes_blank_name_sheet(self, mock_get, mock_delete):
        """Test removes sheets with blank names."""
        from metals.excel_tidy import _tidy_default_sheets
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.return_value = {
            "value": [
                {"id": "1", "name": ""},
                {"id": "2", "name": "Summary"},
            ]
        }
        _tidy_default_sheets(_make_wb(), allowed={"Summary"})
        # Blank name sheet should be deleted
        self.assertEqual(mock_delete.call_count, 1)


class TestTidyProfitCharts(unittest.TestCase):
    """Tests for _tidy_profit_charts function."""

    @patch("requests.post")
    @patch("requests.patch")
    @patch("requests.get")
    def test_sets_chart_titles_and_data_for_profit_sheet(self, mock_get, mock_patch, mock_post):
        """Test sets three chart titles and data ranges when charts exist."""
        from metals.excel_tidy import _tidy_profit_charts

        # First GET: list charts
        charts_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"value": [
                {"id": "c1", "name": "Chart1"},
                {"id": "c2", "name": "Chart2"},
                {"id": "c3", "name": "Chart3"},
            ]}),
        )
        # Second GET: _used_rows (returns 3x rows)
        used_range_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"values": [["h"], ["d1"], ["d2"]]}),
        )
        mock_get.side_effect = [charts_response, used_range_response]

        _tidy_profit_charts(_make_wb(), "Profit")

        # Should set title and axis for each chart, plus data range
        self.assertGreater(mock_patch.call_count, 0)
        self.assertGreater(mock_post.call_count, 0)

    @patch("requests.get")
    def test_noop_when_no_charts(self, mock_get):
        """Test no API calls when profit sheet has no charts."""
        from metals.excel_tidy import _tidy_profit_charts

        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"value": []}

        with patch("requests.patch") as mock_patch, patch("requests.post") as mock_post:
            _tidy_profit_charts(_make_wb(), "Profit")
            mock_patch.assert_not_called()
            mock_post.assert_not_called()

    @patch("requests.post")
    @patch("requests.patch")
    @patch("requests.get")
    def test_handles_fewer_than_three_charts(self, mock_get, mock_patch, mock_post):
        """Test handles fewer charts than config entries without IndexError."""
        from metals.excel_tidy import _tidy_profit_charts

        charts_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"value": [{"id": "c1", "name": "Chart1"}]}),
        )
        used_range_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"values": [["h"], ["d1"]]}),
        )
        mock_get.side_effect = [charts_response, used_range_response]

        # Should not raise even though there's only 1 chart for 3 config entries
        _tidy_profit_charts(_make_wb(), "Profit")
        self.assertTrue(True)

    @patch("requests.post")
    @patch("requests.patch")
    @patch("requests.get")
    def test_used_rows_defaults_to_at_least_2(self, mock_get, mock_patch, mock_post):
        """Test _used_rows result is clamped to at least 2."""
        from metals.excel_tidy import _tidy_profit_charts

        charts_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"value": [{"id": "c1", "name": "C1"}]}),
        )
        # Empty sheet returns 0 rows
        used_range_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"values": []}),
        )
        mock_get.side_effect = [charts_response, used_range_response]

        # max(_used_rows, 2) ensures we always have at least row 2
        _tidy_profit_charts(_make_wb(), "Profit")
        # Data range in POST call should reference row 2 minimum (J2:J2)
        post_call_data = " ".join(str(c) for c in mock_post.call_args_list)
        self.assertIn("J2:J2", post_call_data)

    @patch("metals.excel_tidy._set_chart_data")
    @patch("metals.excel_tidy._set_axis_titles")
    @patch("metals.excel_tidy._set_chart_title")
    @patch("requests.get")
    def test_exception_in_chart_update_is_swallowed(
        self, mock_get, mock_set_title, mock_set_axes, mock_set_data
    ):
        """Test that exceptions in the chart update loop are swallowed (lines 94-95)."""
        from metals.excel_tidy import _tidy_profit_charts

        charts_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"value": [
                {"id": "c1", "name": "Chart1"},
                {"id": "c2", "name": "Chart2"},
                {"id": "c3", "name": "Chart3"},
            ]}),
        )
        used_range_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"values": [["h"], ["d1"]]}),
        )
        mock_get.side_effect = [charts_response, used_range_response]
        # Make _set_chart_title raise so the except branch (lines 94-95) is hit
        mock_set_title.side_effect = RuntimeError("Chart API unavailable")

        # Should not propagate the exception
        _tidy_profit_charts(_make_wb(), "Profit")
        self.assertTrue(True)  # Reached without exception


class TestMainExcelTidy(unittest.TestCase):
    """Tests for the main() entry point in excel_tidy.py."""

    @patch("metals.excel_tidy._tidy_profit_charts")
    @patch("metals.excel_tidy._list_charts")
    @patch("metals.excel_tidy._tidy_default_sheets")
    @patch("metals.excel_tidy.OutlookClient")
    @patch("metals.excel_tidy.resolve_outlook_credentials")
    def test_main_happy_path(
        self,
        mock_creds,
        mock_client_cls,
        mock_tidy_sheets,
        mock_list_charts,
        mock_tidy_profit,
    ):
        """Test main() runs with mocked dependencies and no charts on summary."""
        mock_creds.return_value = ("client-id", "consumers", "/tmp/tok")
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_list_charts.return_value = []  # No charts on summary sheet

        from metals.excel_tidy import main
        rc = main([
            "--drive-id", "drive-id",
            "--item-id", "item-id",
        ])
        self.assertEqual(rc, 0)
        mock_client.authenticate.assert_called_once()
        mock_tidy_sheets.assert_called_once()
        mock_tidy_profit.assert_called_once()

    @patch("metals.excel_tidy._set_axis_titles")
    @patch("metals.excel_tidy._set_chart_title")
    @patch("metals.excel_tidy._tidy_profit_charts")
    @patch("metals.excel_tidy._list_charts")
    @patch("metals.excel_tidy._tidy_default_sheets")
    @patch("metals.excel_tidy.OutlookClient")
    @patch("metals.excel_tidy.resolve_outlook_credentials")
    def test_main_with_summary_chart(
        self,
        mock_creds,
        mock_client_cls,
        mock_tidy_sheets,
        mock_list_charts,
        mock_tidy_profit,
        mock_set_title,
        mock_set_axes,
    ):
        """Test main() sets title on Summary chart when charts exist."""
        mock_creds.return_value = ("client-id", "consumers", "/tmp/tok")
        mock_client_cls.return_value = MagicMock()
        mock_list_charts.return_value = [{"id": "chart-sum-1", "name": "Summary Chart"}]

        from metals.excel_tidy import main
        rc = main([
            "--drive-id", "drive-id",
            "--item-id", "item-id",
            "--summary-sheet", "MySummary",
        ])
        self.assertEqual(rc, 0)
        mock_set_title.assert_called_once()
        # Title should be 'Totals by Metal'
        title_arg = mock_set_title.call_args[0][3]
        self.assertEqual(title_arg, "Totals by Metal")

    @patch("metals.excel_tidy.resolve_outlook_credentials")
    def test_main_exits_without_client_id(self, mock_creds):
        """Test main() exits when no client_id configured."""
        mock_creds.return_value = (None, None, None)

        from metals.excel_tidy import main
        with self.assertRaises(SystemExit):
            main(["--drive-id", "x", "--item-id", "y"])

    @patch("metals.excel_tidy._tidy_profit_charts")
    @patch("metals.excel_tidy._list_charts")
    @patch("metals.excel_tidy._tidy_default_sheets")
    @patch("metals.excel_tidy.OutlookClient")
    @patch("metals.excel_tidy.resolve_outlook_credentials")
    def test_main_uses_custom_sheet_names(
        self,
        mock_creds,
        mock_client_cls,
        mock_tidy_sheets,
        mock_list_charts,
        mock_tidy_profit,
    ):
        """Test main() passes custom sheet names to helper functions."""
        mock_creds.return_value = ("client-id", "consumers", "/tmp/tok")
        mock_client_cls.return_value = MagicMock()
        mock_list_charts.return_value = []

        from metals.excel_tidy import main
        rc = main([
            "--drive-id", "did",
            "--item-id", "iid",
            "--summary-sheet", "MySummary",
            "--gold-sheet", "MyGold",
            "--silver-sheet", "MySilver",
            "--all-sheet", "MyAll",
            "--profit-sheet", "MyProfit",
        ])
        self.assertEqual(rc, 0)

        # Check that allowed set was correctly populated
        call_args = mock_tidy_sheets.call_args
        allowed = call_args[0][1]
        self.assertIn("MySummary", allowed)
        self.assertIn("MyGold", allowed)
        self.assertIn("MySilver", allowed)
        self.assertIn("MyAll", allowed)
        self.assertIn("MyProfit", allowed)


if __name__ == "__main__":
    unittest.main()
