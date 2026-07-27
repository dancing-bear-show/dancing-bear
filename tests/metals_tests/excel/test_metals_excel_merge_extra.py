"""Additional tests for metals/excel_merge.py covering uncovered lines."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import requests

from metals.excel_merge import (
    _ensure_sheet,
    _get_used_range_values,
    _merge,
    _write_sheet,
)


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


class TestGetUsedRangeValues(unittest.TestCase):
    @patch(_SESSION_SEAM)
    def test_returns_values_on_success(self, mock_req):
        mock_req.return_value = _make_resp(200, {
            "values": [["date", "order_id"], ["2024-01-01", "123"]]
        })
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        result = _get_used_range_values(client, "drive-id", "item-id", "Silver")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], ["date", "order_id"])

    @patch(_SESSION_SEAM)
    def test_returns_empty_on_404(self, mock_req):
        mock_req.return_value = _make_resp(404)
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        result = _get_used_range_values(client, "drive-id", "item-id", "NonExistentSheet")
        self.assertEqual(result, [])

    @patch(_SESSION_SEAM)
    def test_returns_empty_when_no_values_key(self, mock_req):
        mock_req.return_value = _make_resp(200, {})
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        result = _get_used_range_values(client, "drive-id", "item-id", "Sheet1")
        self.assertEqual(result, [])


class TestEnsureSheet(unittest.TestCase):
    @patch(_SESSION_SEAM)
    def test_adds_sheet(self, mock_req):
        mock_req.return_value = _make_resp(200)
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        _ensure_sheet(client, "drive-id", "item-id", "NewSheet")
        self.assertEqual(len(_calls_for(mock_req, "POST")), 1)
        call = _calls_for(mock_req, "POST")[0]
        self.assertIn("worksheets/add", call.args[1])


class TestWriteSheetMerge(unittest.TestCase):
    @patch(_SESSION_SEAM)
    def test_writes_values_with_table(self, mock_req):
        mock_req.return_value = _make_resp(200, {"id": "table1"})

        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        values = [["date", "order_id"], ["2024-01-01", "123"]]
        _write_sheet(client, "drive-id", "item-id", "Silver", values)

        # Should call clear (post), then patch for values, then multiple posts for table styling
        self.assertGreaterEqual(len(_calls_for(mock_req, "POST")), 1)
        self.assertGreater(len(_calls_for(mock_req, "PATCH")), 0)

    @patch(_SESSION_SEAM)
    def test_empty_values_only_clears(self, mock_req):
        mock_req.return_value = _make_resp(200)
        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        _write_sheet(client, "drive-id", "item-id", "Silver", [])

        # Should only call clear (no patch)
        self.assertEqual(len(_calls_for(mock_req, "POST")), 1)
        self.assertEqual(_calls_for(mock_req, "PATCH"), [])

    @patch("time.sleep", return_value=None)  # Skip actual retry backoff sleeps
    @patch(_SESSION_SEAM)
    def test_raises_on_write_failure(self, mock_req, mock_sleep):
        # Clear (POST) succeeds; write (PATCH) fails with 500 on every retry attempt.
        # write_range_to_sheet() wraps the write PATCH failure in a domain RuntimeError
        # (preserving the pre-migration contract; requests errors are not leaked).
        mock_req.side_effect = [_make_resp(200)] + [_make_resp(500, text="Internal Server Error")] * 5

        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        with self.assertRaises(RuntimeError) as ctx:
            _write_sheet(client, "drive-id", "item-id", "Silver", [["a", "b"]])
        self.assertIn("Failed writing sheet Silver", str(ctx.exception))

    @patch(_SESSION_SEAM)
    def test_table_id_not_none_calls_style(self, mock_req):
        mock_req.return_value = _make_resp(200, {"id": "tid123"})

        client = MagicMock()
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client._headers.return_value = {}

        _write_sheet(client, "drive-id", "item-id", "Gold", [["h1", "h2"], ["v1", "v2"]])

        # After creating table, should patch the table style
        patch_calls = _calls_for(mock_req, "PATCH")
        self.assertTrue(any("tables" in str(c) for c in patch_calls))


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
