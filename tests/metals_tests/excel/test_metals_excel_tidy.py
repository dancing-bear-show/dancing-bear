"""Tests for metals excel_tidy module."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

import requests

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


# HTTP requests are routed through HttpClient -> requests.Session.request, so tests
# patch that single seam. A >=400 status must raise via raise_for_status so the
# migrated try/except error paths fire the way the old status_code checks did.
_SESSION_SEAM = "requests.sessions.Session.request"


def _make_resp(status=200, json_data=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_data if json_data is not None else {}
    r.text = text
    r.headers = {}
    if status >= 400:
        r.raise_for_status.side_effect = requests.exceptions.HTTPError(str(status))
    else:
        r.raise_for_status.return_value = None
    return r


def _calls_for(mock_req, method):
    """Filter Session.request call_args_list to calls for a specific HTTP method."""
    return [c for c in mock_req.call_args_list if c.args and c.args[0] == method]


def _make_wb(client=None):
    """Helper to create a mock WorkbookContext."""
    if client is None:
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}
    return WorkbookContext(client, "drive-id", "item-id")


class TestListSheets(unittest.TestCase):
    """Tests for _list_sheets function."""

    @patch(_SESSION_SEAM)
    def test_lists_sheets(self, mock_req):
        """Test lists worksheets."""
        mock_req.return_value = _make_resp(200, {
            "value": [
                {"id": "1", "name": "Sheet1"},
                {"id": "2", "name": "Sheet2"},
            ]
        })

        result = _list_sheets(_make_wb())
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Sheet1")


class TestDeleteSheet(unittest.TestCase):
    """Tests for _delete_sheet function."""

    @patch(_SESSION_SEAM)
    def test_deletes_sheet(self, mock_req):
        """Test deletes worksheet."""
        mock_req.return_value = _make_resp(200)

        _delete_sheet(_make_wb(), "Sheet1")
        self.assertEqual(len(_calls_for(mock_req, "DELETE")), 1)
        call = _calls_for(mock_req, "DELETE")[0]
        self.assertIn("Sheet1", call.args[1])


class TestListCharts(unittest.TestCase):
    """Tests for _list_charts function."""

    @patch(_SESSION_SEAM)
    def test_lists_charts(self, mock_req):
        """Test lists charts in worksheet."""
        mock_req.return_value = _make_resp(200, {
            "value": [
                {"id": "chart1", "name": "Chart 1"},
            ]
        })

        result = _list_charts(_make_wb(), "Sheet1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "chart1")

    @patch(_SESSION_SEAM)
    def test_returns_empty_on_error(self, mock_req):
        """Test returns empty list on error."""
        mock_req.return_value = _make_resp(404)

        result = _list_charts(_make_wb(), "Sheet1")
        self.assertEqual(result, [])


class TestUsedRows(unittest.TestCase):
    """Tests for _used_rows function."""

    @patch(_SESSION_SEAM)
    def test_returns_row_count(self, mock_req):
        """Test returns row count."""
        mock_req.return_value = _make_resp(200, {
            "values": [
                ["Header1", "Header2"],
                ["Data1", "Data2"],
                ["Data3", "Data4"],
            ]
        })

        result = _used_rows(_make_wb(), "Sheet1")
        self.assertEqual(result, 3)

    @patch(_SESSION_SEAM)
    def test_returns_zero_on_error(self, mock_req):
        """Test returns 0 on error."""
        mock_req.return_value = _make_resp(404)

        result = _used_rows(_make_wb(), "Sheet1")
        self.assertEqual(result, 0)


class TestSetChartTitle(unittest.TestCase):
    """Tests for _set_chart_title function."""

    @patch(_SESSION_SEAM)
    def test_sets_chart_title(self, mock_req):
        """Test sets chart title."""
        mock_req.return_value = _make_resp(200)

        _set_chart_title(_make_wb(), "Summary", "chart1", "My Chart")

        self.assertEqual(len(_calls_for(mock_req, "PATCH")), 1)
        call = _calls_for(mock_req, "PATCH")[0]
        self.assertIn("charts('chart1')/title", call.args[1])
        self.assertIn('"text": "My Chart"', call.kwargs["data"])
        self.assertIn('"visible": true', call.kwargs["data"])


class TestSetAxisTitles(unittest.TestCase):
    """Tests for _set_axis_titles function."""

    @patch(_SESSION_SEAM)
    def test_sets_category_axis(self, mock_req):
        """Test sets category axis title."""
        mock_req.return_value = _make_resp(200)

        _set_axis_titles(_make_wb(), "Sheet1", "chart1", category="Date", value=None)

        self.assertEqual(len(_calls_for(mock_req, "PATCH")), 1)
        call = _calls_for(mock_req, "PATCH")[0]
        self.assertIn("categoryAxis/title", call.args[1])
        self.assertIn('"text": "Date"', call.kwargs["data"])

    @patch(_SESSION_SEAM)
    def test_sets_value_axis(self, mock_req):
        """Test sets value axis title."""
        mock_req.return_value = _make_resp(200)

        _set_axis_titles(_make_wb(), "Sheet1", "chart1", category=None, value="Price")

        self.assertEqual(len(_calls_for(mock_req, "PATCH")), 1)
        call = _calls_for(mock_req, "PATCH")[0]
        self.assertIn("valueAxis/title", call.args[1])
        self.assertIn('"text": "Price"', call.kwargs["data"])

    @patch(_SESSION_SEAM)
    def test_sets_both_axes(self, mock_req):
        """Test sets both axis titles."""
        mock_req.return_value = _make_resp(200)

        _set_axis_titles(_make_wb(), "Sheet1", "chart1", category="Date", value="C$")

        self.assertEqual(len(_calls_for(mock_req, "PATCH")), 2)

    @patch(_SESSION_SEAM)
    def test_no_call_when_both_none(self, mock_req):
        """Test no API call when both are None."""
        _set_axis_titles(_make_wb(), "Sheet1", "chart1", category=None, value=None)

        self.assertEqual(_calls_for(mock_req, "PATCH"), [])


class TestSetChartData(unittest.TestCase):
    """Tests for _set_chart_data function."""

    @patch(_SESSION_SEAM)
    def test_sets_chart_data_range(self, mock_req):
        """Test sets chart data source range."""
        mock_req.return_value = _make_resp(200)

        _set_chart_data(_make_wb(), "Profit", "chart1", "A1:B10")

        self.assertEqual(len(_calls_for(mock_req, "POST")), 1)
        call = _calls_for(mock_req, "POST")[0]
        self.assertIn("charts('chart1')/setData", call.args[1])
        self.assertIn("'Profit'!A1:B10", call.kwargs["data"])
        self.assertIn('"seriesBy": "Auto"', call.kwargs["data"])


if __name__ == "__main__":
    unittest.main()
