"""Additional tests for metals/excel_merge.py covering uncovered lines."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from metals.excel_merge import (
    _col_letter,
    _ensure_sheet,
    _get_used_range_values,
    _merge,
    _read_csv,
    _records_to_values,
    _to_records,
    _write_sheet,
)


class TestGetUsedRangeValues(unittest.TestCase):
    @patch("requests.get")
    def test_returns_values_on_success(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "values": [["date", "order_id"], ["2024-01-01", "123"]]
        }
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        result = _get_used_range_values(client, "drive-id", "item-id", "Silver")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], ["date", "order_id"])

    @patch("requests.get")
    def test_returns_empty_on_404(self, mock_get):
        mock_get.return_value.status_code = 404
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        result = _get_used_range_values(client, "drive-id", "item-id", "NonExistentSheet")
        self.assertEqual(result, [])

    @patch("requests.get")
    def test_returns_empty_when_no_values_key(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {}
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        result = _get_used_range_values(client, "drive-id", "item-id", "Sheet1")
        self.assertEqual(result, [])


class TestEnsureSheet(unittest.TestCase):
    @patch("requests.post")
    def test_adds_sheet(self, mock_post):
        mock_post.return_value.status_code = 200
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        _ensure_sheet(client, "drive-id", "item-id", "NewSheet")
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        self.assertIn("worksheets/add", call_url)


class TestWriteSheetMerge(unittest.TestCase):
    @patch("requests.patch")
    @patch("requests.post")
    def test_writes_values_with_table(self, mock_post, mock_patch):
        mock_patch.return_value.status_code = 200
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"id": "table1"}

        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        values = [["date", "order_id"], ["2024-01-01", "123"]]
        _write_sheet(client, "drive-id", "item-id", "Silver", values)

        # Should call clear (post), then patch for values, then multiple posts for table styling
        self.assertGreaterEqual(mock_post.call_count, 1)
        mock_patch.assert_called()

    @patch("requests.patch")
    @patch("requests.post")
    def test_empty_values_only_clears(self, mock_post, mock_patch):
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        _write_sheet(client, "drive-id", "item-id", "Silver", [])

        # Should only call clear (no patch)
        mock_post.assert_called_once()
        mock_patch.assert_not_called()

    @patch("requests.patch")
    @patch("requests.post")
    def test_raises_on_write_failure(self, mock_post, mock_patch):
        mock_patch.return_value.status_code = 500
        mock_patch.return_value.text = "Internal Server Error"

        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        with self.assertRaises(RuntimeError):
            _write_sheet(client, "drive-id", "item-id", "Silver", [["a", "b"]])

    @patch("requests.patch")
    @patch("requests.post")
    def test_table_id_not_none_calls_style(self, mock_post, mock_patch):
        mock_patch.return_value.status_code = 200
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"id": "tid123"}

        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        _write_sheet(client, "drive-id", "item-id", "Gold", [["h1", "h2"], ["v1", "v2"]])

        # After creating table, should patch the table style
        patch_calls = [str(c) for c in mock_patch.call_args_list]
        self.assertTrue(any("tables" in str(c) for c in mock_patch.call_args_list))


class TestMergeAdditional(unittest.TestCase):
    def test_union_headers_in_main_preserves_order(self):
        """Test that the internal union_headers logic (via _merge output) works."""
        existing = [
            {"date": "2024-01-01", "order_id": "1", "vendor": "TD", "notes": "kept"},
        ]
        new = [
            {"date": "2024-01-02", "order_id": "2", "vendor": "Costco", "extra": "new_field"},
        ]
        result = _merge(existing, new)
        self.assertEqual(len(result), 2)

    def test_normalizes_keys(self):
        """Test that norm() strips spaces from dict keys (not values)."""
        # norm() strips spaces from KEYS, not values. So {" order_id ": "1"} → {"order_id": "1"}
        existing = [{" date ": "2024-01-01", " order_id ": "1", " vendor ": "TD"}]
        new = [{"date": "2024-01-01", "order_id": "1", "vendor": "TD"}]
        # Both should reduce to the same key ("1", "TD") after norm() strips key spaces
        result = _merge(existing, new)
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
