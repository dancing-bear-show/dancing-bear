"""Tests for metals excel module."""
from __future__ import annotations

import csv
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from metals.excel import (
    _col_letter,
    _read_csv,
    _write_sheet,
)


class TestColLetter(unittest.TestCase):
    """Tests for _col_letter function."""

    def test_single_letters(self):
        """Test single letter columns."""
        self.assertEqual(_col_letter(1), "A")
        self.assertEqual(_col_letter(2), "B")
        self.assertEqual(_col_letter(26), "Z")

    def test_double_letters(self):
        """Test double letter columns."""
        self.assertEqual(_col_letter(27), "AA")
        self.assertEqual(_col_letter(28), "AB")
        self.assertEqual(_col_letter(52), "AZ")
        self.assertEqual(_col_letter(53), "BA")

    def test_triple_letters(self):
        """Test triple letter columns."""
        # 26 + 26*26 = 702 is ZZ, so 703 is AAA
        self.assertEqual(_col_letter(703), "AAA")


class TestReadCsv(unittest.TestCase):
    """Tests for _read_csv function."""

    def test_reads_csv(self):
        """Test reading CSV file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            w = csv.writer(f)
            w.writerow(["col1", "col2", "col3"])
            w.writerow(["a", "b", "c"])
            w.writerow(["d", "e", "f"])
            f.flush()

            rows = _read_csv(f.name)
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0], ["col1", "col2", "col3"])
            self.assertEqual(rows[1], ["a", "b", "c"])

    def test_reads_empty_csv(self):
        """Test reading empty CSV file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.flush()
            rows = _read_csv(f.name)
            self.assertEqual(rows, [])

    def test_reads_csv_with_quotes(self):
        """Test reading CSV with quoted fields."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            w = csv.writer(f)
            w.writerow(["name", "description"])
            w.writerow(["item", "has, comma"])
            f.flush()
            rows = _read_csv(f.name)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1][1], "has, comma")


class TestColLetterAdvanced(unittest.TestCase):
    """Advanced tests for _col_letter function."""

    def test_middle_letters(self):
        """Test middle alphabet letters."""
        self.assertEqual(_col_letter(13), "M")
        self.assertEqual(_col_letter(14), "N")

    def test_boundary_values(self):
        """Test boundary values between single and double letters."""
        self.assertEqual(_col_letter(25), "Y")
        self.assertEqual(_col_letter(26), "Z")
        self.assertEqual(_col_letter(27), "AA")

    def test_large_columns(self):
        """Test large column numbers."""
        self.assertEqual(_col_letter(53), "BA")
        self.assertEqual(_col_letter(702), "ZZ")


class TestWriteSheet(unittest.TestCase):
    """Tests for _write_sheet function."""

    @patch("requests.patch")
    @patch("requests.post")
    def test_writes_values_to_sheet(self, mock_post, mock_patch):
        """Test writes values to worksheet."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {"Authorization": "Bearer token"}
        mock_patch.return_value.raise_for_status = MagicMock()

        values = [
            ["Header1", "Header2"],
            ["A", "B"],
            ["C", "D"],
        ]
        _write_sheet(mock_client, "drive-id", "item-id", "Sheet1", values)

        # Should clear first, then patch
        mock_post.assert_called_once()
        mock_patch.assert_called_once()
        # Check the range address
        call_args = mock_patch.call_args
        self.assertIn("A1:B3", call_args[0][0])

    @patch("requests.patch")
    @patch("requests.post")
    def test_handles_empty_values(self, mock_post, mock_patch):
        """Test handles empty values list."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}

        _write_sheet(mock_client, "drive-id", "item-id", "Sheet1", [])

        # Should clear but not patch when empty
        mock_post.assert_called_once()
        mock_patch.assert_not_called()

    @patch("requests.patch")
    @patch("requests.post")
    def test_raises_on_error(self, mock_post, mock_patch):
        """Test raises RuntimeError on API error."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}
        mock_patch.return_value.status_code = 400
        mock_patch.return_value.text = "Bad Request"
        mock_patch.return_value.raise_for_status.side_effect = Exception("HTTP Error")

        with self.assertRaises(RuntimeError) as ctx:
            _write_sheet(mock_client, "drive-id", "item-id", "Sheet1", [["A", "B"]])
        self.assertIn("Failed to write sheet", str(ctx.exception))

    @patch("requests.patch")
    @patch("requests.post")
    def test_calculates_correct_range(self, mock_post, mock_patch):
        """Test calculates correct range for varying column counts."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}
        mock_patch.return_value.raise_for_status = MagicMock()

        # 5 columns, 2 rows
        values = [
            ["A", "B", "C", "D", "E"],
            ["1", "2", "3", "4", "5"],
        ]
        _write_sheet(mock_client, "drive-id", "item-id", "Sheet1", values)

        call_args = mock_patch.call_args
        self.assertIn("A1:E2", call_args[0][0])


class TestMainExcel(unittest.TestCase):
    """Tests for the main() entry point in metals/excel.py (lines 51-85)."""

    @patch("metals.excel._write_sheet")
    @patch("metals.excel._read_csv")
    @patch("metals.excel.OutlookClient")
    @patch("metals.excel.resolve_outlook_credentials")
    def test_main_writes_both_sheets(
        self, mock_creds, mock_client_cls, mock_read_csv, mock_write_sheet
    ):
        """Test main() reads both CSVs and writes both sheets."""
        mock_creds.return_value = ("client-id", "consumers", "/tmp/tok")  # nosec B108 - mock credential path, not a real file op
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_read_csv.return_value = [["date", "order_id"], ["2024-01-01", "1"]]

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as sf, \
             tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as gf:
            self.addCleanup(os.unlink, sf.name)
            self.addCleanup(os.unlink, gf.name)
            from metals.excel import main
            rc = main([
                "--drive-id", "drive-id",
                "--item-id", "item-id",
                "--silver-csv", sf.name,
                "--silver-sheet", "Silver",
                "--gold-csv", gf.name,
                "--gold-sheet", "Gold",
            ])

        self.assertEqual(rc, 0)
        mock_client.authenticate.assert_called_once()
        self.assertEqual(mock_write_sheet.call_count, 2)

    @patch("metals.excel._write_sheet")
    @patch("metals.excel._read_csv")
    @patch("metals.excel.OutlookClient")
    @patch("metals.excel.resolve_outlook_credentials")
    def test_main_skips_missing_csv_args(
        self, mock_creds, mock_client_cls, mock_read_csv, mock_write_sheet
    ):
        """Test main() skips writing a sheet when CSV/sheet args not provided."""
        mock_creds.return_value = ("client-id", "consumers", "/tmp/tok")  # nosec B108 - mock credential path, not a real file op
        mock_client_cls.return_value = MagicMock()

        from metals.excel import main
        rc = main([
            "--drive-id", "drive-id",
            "--item-id", "item-id",
            # No --silver-csv / --silver-sheet / --gold-csv / --gold-sheet
        ])
        self.assertEqual(rc, 0)
        # Neither CSV provided → neither sheet written
        mock_write_sheet.assert_not_called()
        mock_read_csv.assert_not_called()

    @patch("metals.excel._write_sheet")
    @patch("metals.excel._read_csv")
    @patch("metals.excel.OutlookClient")
    @patch("metals.excel.resolve_outlook_credentials")
    def test_main_writes_only_silver_when_gold_missing(
        self, mock_creds, mock_client_cls, mock_read_csv, mock_write_sheet
    ):
        """Test main() writes only the silver sheet when gold args are absent."""
        mock_creds.return_value = ("client-id", "consumers", "/tmp/tok")  # nosec B108 - mock credential path, not a real file op
        mock_client_cls.return_value = MagicMock()
        mock_read_csv.return_value = [["date"], ["2024-01-01"]]

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as sf:
            self.addCleanup(os.unlink, sf.name)
            from metals.excel import main
            rc = main([
                "--drive-id", "drive-id",
                "--item-id", "item-id",
                "--silver-csv", sf.name,
                "--silver-sheet", "Silver",
            ])

        self.assertEqual(rc, 0)
        # Only one write (Silver)
        self.assertEqual(mock_write_sheet.call_count, 1)
        call_sheet = mock_write_sheet.call_args[0][3]
        self.assertEqual(call_sheet, "Silver")

    @patch("metals.excel.resolve_outlook_credentials")
    def test_main_exits_without_client_id(self, mock_creds):
        """Test main() raises SystemExit when no client_id is configured."""
        mock_creds.return_value = (None, None, None)

        from metals.excel import main
        with self.assertRaises(SystemExit):
            main([
                "--drive-id", "x",
                "--item-id", "y",
            ])


if __name__ == "__main__":
    unittest.main()
