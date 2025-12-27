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


if __name__ == "__main__":
    unittest.main()
