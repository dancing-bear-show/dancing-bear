"""Tests for metals excel_tidy module."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from metals.excel_tidy import (
    _headers,
    _list_sheets,
    _delete_sheet,
    _list_charts,
    _used_rows,
    _set_chart_title,
    _set_axis_titles,
    _set_chart_data,
)


class TestHeaders(unittest.TestCase):
    """Tests for _headers function."""

    def test_returns_client_headers(self):
        """Test returns client headers."""
        mock_client = MagicMock()
        mock_client._headers.return_value = {"Authorization": "Bearer token"}
        result = _headers(mock_client)
        self.assertEqual(result, {"Authorization": "Bearer token"})


class TestListSheets(unittest.TestCase):
    """Tests for _list_sheets function."""

    @patch("requests.get")
    def test_lists_sheets(self, mock_get):
        """Test lists worksheets."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.return_value = {
            "value": [
                {"id": "1", "name": "Sheet1"},
                {"id": "2", "name": "Sheet2"},
            ]
        }

        result = _list_sheets(mock_client, "drive-id", "item-id")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Sheet1")


class TestDeleteSheet(unittest.TestCase):
    """Tests for _delete_sheet function."""

    @patch("requests.delete")
    def test_deletes_sheet(self, mock_delete):
        """Test deletes worksheet."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}

        _delete_sheet(mock_client, "drive-id", "item-id", "Sheet1")
        mock_delete.assert_called_once()
        call_url = mock_delete.call_args[0][0]
        self.assertIn("Sheet1", call_url)


class TestListCharts(unittest.TestCase):
    """Tests for _list_charts function."""

    @patch("requests.get")
    def test_lists_charts(self, mock_get):
        """Test lists charts in worksheet."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "value": [
                {"id": "chart1", "name": "Chart 1"},
            ]
        }

        result = _list_charts(mock_client, "drive-id", "item-id", "Sheet1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "chart1")

    @patch("requests.get")
    def test_returns_empty_on_error(self, mock_get):
        """Test returns empty list on error."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}
        mock_get.return_value.status_code = 404

        result = _list_charts(mock_client, "drive-id", "item-id", "Sheet1")
        self.assertEqual(result, [])


class TestUsedRows(unittest.TestCase):
    """Tests for _used_rows function."""

    @patch("requests.get")
    def test_returns_row_count(self, mock_get):
        """Test returns row count."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "values": [
                ["Header1", "Header2"],
                ["Data1", "Data2"],
                ["Data3", "Data4"],
            ]
        }

        result = _used_rows(mock_client, "drive-id", "item-id", "Sheet1")
        self.assertEqual(result, 3)

    @patch("requests.get")
    def test_returns_zero_on_error(self, mock_get):
        """Test returns 0 on error."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}
        mock_get.return_value.status_code = 404

        result = _used_rows(mock_client, "drive-id", "item-id", "Sheet1")
        self.assertEqual(result, 0)


class TestSetChartTitle(unittest.TestCase):
    """Tests for _set_chart_title function."""

    @patch("requests.patch")
    def test_sets_chart_title(self, mock_patch):
        """Test sets chart title."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {"Authorization": "Bearer token"}

        _set_chart_title(mock_client, "drive-id", "item-id", "Summary", "chart1", "My Chart")

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
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}

        _set_axis_titles(mock_client, "drive-id", "item-id", "Sheet1", "chart1", category="Date", value=None)

        mock_patch.assert_called_once()
        call_args = mock_patch.call_args
        self.assertIn("categoryAxis/title", call_args[0][0])
        self.assertIn('"text": "Date"', call_args[1]["data"])

    @patch("requests.patch")
    def test_sets_value_axis(self, mock_patch):
        """Test sets value axis title."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}

        _set_axis_titles(mock_client, "drive-id", "item-id", "Sheet1", "chart1", category=None, value="Price")

        mock_patch.assert_called_once()
        call_args = mock_patch.call_args
        self.assertIn("valueAxis/title", call_args[0][0])
        self.assertIn('"text": "Price"', call_args[1]["data"])

    @patch("requests.patch")
    def test_sets_both_axes(self, mock_patch):
        """Test sets both axis titles."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}

        _set_axis_titles(mock_client, "drive-id", "item-id", "Sheet1", "chart1", category="Date", value="C$")

        self.assertEqual(mock_patch.call_count, 2)

    @patch("requests.patch")
    def test_no_call_when_both_none(self, mock_patch):
        """Test no API call when both are None."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}

        _set_axis_titles(mock_client, "drive-id", "item-id", "Sheet1", "chart1", category=None, value=None)

        mock_patch.assert_not_called()


class TestSetChartData(unittest.TestCase):
    """Tests for _set_chart_data function."""

    @patch("requests.post")
    def test_sets_chart_data_range(self, mock_post):
        """Test sets chart data source range."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}

        _set_chart_data(mock_client, "drive-id", "item-id", "Profit", "chart1", "A1:B10")

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn("charts('chart1')/setData", call_args[0][0])
        self.assertIn("'Profit'!A1:B10", call_args[1]["data"])
        self.assertIn('"seriesBy": "Auto"', call_args[1]["data"])


if __name__ == "__main__":
    unittest.main()
