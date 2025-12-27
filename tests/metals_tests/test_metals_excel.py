"""Tests for metals excel module."""
from __future__ import annotations

import csv
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
        # BA = 53
        self.assertEqual(_col_letter(53), "BA")
        # ZZ = 702
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


if __name__ == "__main__":
    unittest.main()
