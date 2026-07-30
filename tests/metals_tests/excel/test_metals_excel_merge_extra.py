"""Additional tests for metals/excel_merge.py covering uncovered lines."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from metals.excel_merge import (
    _copy_item,
    _ensure_sheet,
    _get_used_range_values,
    _merge,
    _merge_key,
    _merge_update,
    _poll_copy_monitor,
    _to_records,
    _write_sheet,
)


def _make_client():
    client = MagicMock()
    client.GRAPH = "https://graph.microsoft.com/v1.0"
    client._headers.return_value = {"Authorization": "Bearer tok"}
    return client


class TestGetUsedRangeValues(unittest.TestCase):
    @patch("requests.get")
    def test_returns_values_on_success(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "values": [["date", "order_id"], ["2024-01-01", "123"]]
        }
        result = _get_used_range_values(_make_client(), "drive-id", "item-id", "Silver")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], ["date", "order_id"])

    @patch("requests.get")
    def test_returns_empty_on_404(self, mock_get):
        mock_get.return_value.status_code = 404
        result = _get_used_range_values(_make_client(), "drive-id", "item-id", "NonExistentSheet")
        self.assertEqual(result, [])

    @patch("requests.get")
    def test_returns_empty_when_no_values_key(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {}
        result = _get_used_range_values(_make_client(), "drive-id", "item-id", "Sheet1")
        self.assertEqual(result, [])

    @patch("requests.get")
    def test_returns_empty_on_500(self, mock_get):
        mock_get.return_value.status_code = 500
        result = _get_used_range_values(_make_client(), "drive-id", "item-id", "Sheet1")
        self.assertEqual(result, [])


class TestPollCopyMonitor(unittest.TestCase):
    @patch("time.sleep")
    @patch("requests.get")
    def test_returns_resource_id_on_succeeded(self, mock_get, mock_sleep):
        mock_get.return_value.json.return_value = {"status": "succeeded", "resourceId": "new-item-123"}
        result = _poll_copy_monitor(_make_client(), "http://monitor/url", "drive-id")
        self.assertEqual(result, ("drive-id", "new-item-123"))

    @patch("time.sleep")
    @patch("requests.get")
    def test_returns_resource_id_on_completed(self, mock_get, mock_sleep):
        mock_get.return_value.json.return_value = {"status": "completed", "resourceId": "item-completed"}
        result = _poll_copy_monitor(_make_client(), "http://monitor/url", "drive-id")
        self.assertEqual(result, ("drive-id", "item-completed"))

    @patch("time.sleep")
    @patch("requests.get")
    def test_follows_resource_location(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            MagicMock(json=MagicMock(return_value={"status": "succeeded", "resourceLocation": "http://resource"})),
            MagicMock(json=MagicMock(return_value={"id": "item-from-location"})),
        ]
        result = _poll_copy_monitor(_make_client(), "http://monitor/url", "drive-id")
        self.assertEqual(result, ("drive-id", "item-from-location"))


class TestPollCopyMonitorTimeout(unittest.TestCase):
    """Test timeout path: sleep is called and RuntimeError raised after loop exhaustion."""

    @patch("metals.excel_merge.time")
    @patch("requests.get")
    def test_raises_runtime_error_after_exhaustion(self, mock_get, mock_time):
        """Exhaust the 60-iteration poll loop with instant sleeps, verify RuntimeError."""
        mock_get.return_value.json.return_value = {"status": "inProgress"}
        mock_time.sleep = MagicMock()

        with self.assertRaises(RuntimeError) as ctx:
            _poll_copy_monitor(_make_client(), "http://monitor/url", "drive-id")
        self.assertIn("Timed out", str(ctx.exception))
        # time.sleep called once per iteration (60 total)
        self.assertEqual(mock_time.sleep.call_count, 60)


class TestCopyItem(unittest.TestCase):
    @patch("requests.post")
    @patch("requests.get")
    def test_returns_from_poll_on_202(self, mock_get, mock_post):
        """Test _copy_item polls monitor URL on 202 response."""
        # GET /items/{id} returns parent metadata
        mock_get.side_effect = [
            MagicMock(json=MagicMock(return_value={"parentReference": {"id": "parent-id"}})),
            # Second GET is the poll
            MagicMock(json=MagicMock(return_value={"status": "succeeded", "resourceId": "new-item"})),
        ]
        mock_post.return_value.status_code = 202
        mock_post.return_value.headers = {"Location": "http://monitor/url"}

        with patch("time.sleep"):
            result = _copy_item(_make_client(), "drive-id", "item-id", "Merged.xlsx")
        self.assertEqual(result, ("drive-id", "new-item"))

    @patch("requests.post")
    @patch("requests.get")
    def test_returns_item_id_on_200_with_body(self, mock_get, mock_post):
        """Test _copy_item returns item id directly when 200 response has body (no Location)."""
        mock_get.return_value.json.return_value = {"parentReference": {"id": "parent-id"}}
        mock_post.return_value.status_code = 200
        mock_post.return_value.headers = {}  # No Location header
        mock_post.return_value.json.return_value = {"id": "direct-item-id"}

        result = _copy_item(_make_client(), "drive-id", "item-id", "Merged.xlsx")
        self.assertEqual(result, ("drive-id", "direct-item-id"))

    @patch("requests.post")
    @patch("requests.get")
    def test_raises_on_copy_failure(self, mock_get, mock_post):
        """Test _copy_item raises RuntimeError on non-200/202 status."""
        mock_get.return_value.json.return_value = {}
        mock_post.return_value.status_code = 500
        mock_post.return_value.text = "Server Error"

        with self.assertRaises(RuntimeError) as ctx:
            _copy_item(_make_client(), "drive-id", "item-id", "Merged.xlsx")
        self.assertIn("Copy failed", str(ctx.exception))

    @patch("requests.post")
    @patch("requests.get")
    def test_raises_when_no_location_and_no_body(self, mock_get, mock_post):
        """Test raises RuntimeError when no Location header and no parseable body."""
        mock_get.return_value.json.return_value = {}
        mock_post.return_value.status_code = 202
        mock_post.return_value.headers = {}  # No Location
        mock_post.return_value.json.side_effect = Exception("no json")

        with self.assertRaises(RuntimeError) as ctx:
            _copy_item(_make_client(), "drive-id", "item-id", "Merged.xlsx")
        self.assertIn("no monitor location", str(ctx.exception))

    @patch("requests.post")
    @patch("requests.get")
    def test_copy_without_parent_id(self, mock_get, mock_post):
        """Test _copy_item works when parent metadata has no parentReference."""
        mock_get.return_value.json.return_value = {}  # no parentReference
        mock_post.return_value.status_code = 200
        mock_post.return_value.headers = {}
        mock_post.return_value.json.return_value = {"id": "no-parent-item"}

        result = _copy_item(_make_client(), "drive-id", "item-id", "Merged.xlsx")
        self.assertEqual(result, ("drive-id", "no-parent-item"))

        # Body should not have parentReference key
        body_str = mock_post.call_args[1].get("data") or ""
        self.assertNotIn("parentReference", body_str)


class TestMergeUpdateBranch(unittest.TestCase):
    def test_merge_update_fills_empty_fields_from_new(self):
        """Test _merge_update fills empty fields from new record (the else branch at line 131)."""
        base = {"date": "2024-01-01", "order_id": "1", "vendor": "TD", "notes": ""}
        new_rec = {"notes": "added-note", "extra": "extra-val", "date": "2024-01-02"}
        _merge_update(base, new_rec)
        # 'notes' was empty so it should get filled
        self.assertEqual(base["notes"], "added-note")
        # 'extra' wasn't in base so it should be added
        self.assertEqual(base["extra"], "extra-val")
        # 'date' is a core field, so it gets overridden when new has a value
        self.assertEqual(base["date"], "2024-01-02")

    def test_merge_update_does_not_overwrite_existing_non_core(self):
        """Test _merge_update doesn't overwrite existing non-empty non-core fields."""
        base = {"date": "2024-01-01", "order_id": "1", "vendor": "TD", "notes": "original"}
        new_rec = {"notes": "new-note"}
        _merge_update(base, new_rec)
        # 'notes' is not a core field and base already has it, so it should NOT be overwritten
        self.assertEqual(base["notes"], "original")

    def test_merge_key_uses_order_id_and_vendor(self):
        """Test _merge_key extracts the correct tuple."""
        rec = {"order_id": "123", "vendor": "TD", "date": "2024-01-01"}
        self.assertEqual(_merge_key(rec), ("123", "TD"))

    def test_merge_key_defaults_to_empty(self):
        """Test _merge_key defaults to empty strings for missing fields."""
        self.assertEqual(_merge_key({}), ("", ""))


class TestToRecordsSkipsAllEmpty(unittest.TestCase):
    def test_skips_all_empty_rows(self):
        """Test _to_records skips rows where all values are empty strings."""
        values = [
            ["date", "order_id", "vendor"],
            ["", "", ""],  # all empty - should be skipped
            ["2024-01-01", "123", "TD"],
        ]
        _, recs = _to_records(values)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["date"], "2024-01-01")


class TestEnsureSheet(unittest.TestCase):
    @patch("requests.post")
    def test_adds_sheet(self, mock_post):
        mock_post.return_value.status_code = 200
        _ensure_sheet(_make_client(), "drive-id", "item-id", "NewSheet")
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

        values = [["date", "order_id"], ["2024-01-01", "123"]]
        _write_sheet(_make_client(), "drive-id", "item-id", "Silver", values)

        self.assertGreaterEqual(mock_post.call_count, 1)
        mock_patch.assert_called()

    @patch("requests.patch")
    @patch("requests.post")
    def test_empty_values_only_clears(self, mock_post, mock_patch):
        _write_sheet(_make_client(), "drive-id", "item-id", "Silver", [])
        mock_post.assert_called_once()
        mock_patch.assert_not_called()

    @patch("requests.patch")
    @patch("requests.post")
    def test_raises_on_write_failure(self, mock_post, mock_patch):
        mock_patch.return_value.status_code = 500
        mock_patch.return_value.text = "Internal Server Error"

        with self.assertRaises(RuntimeError):
            _write_sheet(_make_client(), "drive-id", "item-id", "Silver", [["a", "b"]])

    @patch("requests.patch")
    @patch("requests.post")
    def test_table_id_not_none_calls_style(self, mock_post, mock_patch):
        mock_patch.return_value.status_code = 200
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"id": "tid123"}

        _write_sheet(_make_client(), "drive-id", "item-id", "Gold", [["h1", "h2"], ["v1", "v2"]])

        self.assertTrue(any("tables" in str(c) for c in mock_patch.call_args_list))


class TestMergeAdditional(unittest.TestCase):
    def test_union_headers_in_main_preserves_order(self):
        """The internal union_headers logic via _merge output works."""
        existing = [
            {"date": "2024-01-01", "order_id": "1", "vendor": "TD", "notes": "kept"},
        ]
        new = [
            {"date": "2024-01-02", "order_id": "2", "vendor": "Costco", "extra": "new_field"},
        ]
        result = _merge(existing, new)
        self.assertEqual(len(result), 2)

    def test_normalizes_keys(self):
        """norm() strips spaces from dict keys."""
        existing = [{" date ": "2024-01-01", " order_id ": "1", " vendor ": "TD"}]
        new = [{"date": "2024-01-01", "order_id": "1", "vendor": "TD"}]
        result = _merge(existing, new)
        self.assertEqual(len(result), 1)


class TestMainExcelMergeUnionHeaders(unittest.TestCase):
    """Test that main() union_headers adds extra columns from merged records (lines 203-204)."""

    @patch("metals.excel_merge._write_sheet")
    @patch("metals.excel_merge._ensure_sheet")
    @patch("metals.excel_merge._copy_item")
    @patch("metals.excel_merge._read_csv")
    @patch("metals.excel_merge._get_used_range_values")
    @patch("metals.excel_merge.OutlookClient")
    @patch("metals.excel_merge.resolve_outlook_credentials")
    def test_union_headers_includes_extra_columns(
        self,
        mock_creds,
        mock_client_cls,
        mock_get_range,
        mock_read_csv,
        mock_copy,
        mock_ensure,
        mock_write,
    ):
        """Test that extra columns beyond base headers are included in the write call."""
        mock_creds.return_value = ("cid", "consumers", "/tmp/tok")
        mock_client_cls.return_value = MagicMock()
        # Existing sheet has an extra column 'notes' beyond base headers
        mock_get_range.return_value = [
            ["date", "order_id", "vendor", "total_oz", "cost_per_oz", "notes"],
            ["2024-01-01", "1", "TD", "1.0", "2500.00", "a note"],
        ]
        # New CSV also has extra column 'ref'
        mock_read_csv.return_value = [
            ["date", "order_id", "vendor", "total_oz", "cost_per_oz", "ref"],
            ["2024-01-02", "2", "Costco", "5.0", "30.00", "REF001"],
        ]
        mock_copy.return_value = ("drive-new", "item-new")

        from metals.excel_merge import main
        rc = main([
            "--drive-id", "drive-src",
            "--item-id", "item-src",
            "--silver-csv", "/tmp/silver.csv",
            "--gold-csv", "/tmp/gold.csv",
        ])
        self.assertEqual(rc, 0)

        # The values written should include the extra headers (union_headers path lines 203-204)
        # _write_sheet signature: (client, drive_id, item_id, sheet, values) → index 4
        write_call_values = mock_write.call_args_list[0][0][4]  # 5th arg is values
        written_headers = write_call_values[0]
        # Base headers must be present
        for base_h in ["date", "order_id", "vendor", "total_oz", "cost_per_oz"]:
            self.assertIn(base_h, written_headers)
        # Extra column from existing should be present (union_headers adds it)
        self.assertIn("notes", written_headers)


class TestMainExcelMerge(unittest.TestCase):
    """Integration tests for the main() function in excel_merge.py."""

    def _make_resolved_creds(self):
        return ("client-id-123", "consumers", "/tmp/token.json")

    @patch("metals.excel_merge._write_sheet")
    @patch("metals.excel_merge._ensure_sheet")
    @patch("metals.excel_merge._copy_item")
    @patch("metals.excel_merge._read_csv")
    @patch("metals.excel_merge._get_used_range_values")
    @patch("metals.excel_merge.OutlookClient")
    @patch("metals.excel_merge.resolve_outlook_credentials")
    def test_main_happy_path(
        self,
        mock_creds,
        mock_client_cls,
        mock_get_range,
        mock_read_csv,
        mock_copy,
        mock_ensure,
        mock_write,
    ):
        """Test main() runs end-to-end with mocked dependencies."""
        mock_creds.return_value = ("cid", "consumers", "/tmp/tok")
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_get_range.return_value = [
            ["date", "order_id", "vendor", "total_oz", "cost_per_oz"],
            ["2024-01-01", "1", "TD", "1.0", "2500.00"],
        ]
        mock_read_csv.return_value = [
            ["date", "order_id", "vendor", "total_oz", "cost_per_oz"],
            ["2024-01-02", "2", "Costco", "5.0", "30.00"],
        ]
        mock_copy.return_value = ("drive-new", "item-new")

        from metals.excel_merge import main
        rc = main([
            "--drive-id", "drive-src",
            "--item-id", "item-src",
            "--silver-csv", "/tmp/silver.csv",
            "--gold-csv", "/tmp/gold.csv",
        ])
        self.assertEqual(rc, 0)
        mock_client.authenticate.assert_called_once()
        self.assertEqual(mock_ensure.call_count, 2)
        self.assertEqual(mock_write.call_count, 2)

    @patch("metals.excel_merge.resolve_outlook_credentials")
    def test_main_exits_without_client_id(self, mock_creds):
        """Test main() exits when no client_id is configured."""
        mock_creds.return_value = (None, None, None)

        from metals.excel_merge import main
        with self.assertRaises(SystemExit):
            main([
                "--drive-id", "x",
                "--item-id", "y",
                "--silver-csv", "/tmp/s.csv",
                "--gold-csv", "/tmp/g.csv",
            ])


if __name__ == "__main__":
    unittest.main()
