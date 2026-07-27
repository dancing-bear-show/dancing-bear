"""Tests for metals excel module."""
from __future__ import annotations

import csv
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import requests

from metals.excel import (
    _col_letter,
    _read_csv,
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

    @patch(_SESSION_SEAM)
    def test_writes_values_to_sheet(self, mock_req):
        """Test writes values to worksheet."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {"Authorization": "Bearer token"}
        mock_req.return_value = _make_resp(200)

        values = [
            ["Header1", "Header2"],
            ["A", "B"],
            ["C", "D"],
        ]
        _write_sheet(mock_client, "drive-id", "item-id", "Sheet1", values)

        # Should clear first (POST), then patch (PATCH)
        self.assertEqual(len(_calls_for(mock_req, "POST")), 1)
        self.assertEqual(len(_calls_for(mock_req, "PATCH")), 1)
        # Check the range address (URL is the 2nd positional arg under the seam)
        call = _calls_for(mock_req, "PATCH")[0]
        self.assertIn("A1:B3", call.args[1])

    @patch(_SESSION_SEAM)
    def test_handles_empty_values(self, mock_req):
        """Test handles empty values list."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}
        mock_req.return_value = _make_resp(200)

        _write_sheet(mock_client, "drive-id", "item-id", "Sheet1", [])

        # Should clear but not patch when empty
        self.assertEqual(len(_calls_for(mock_req, "POST")), 1)
        self.assertEqual(_calls_for(mock_req, "PATCH"), [])

    @patch(_SESSION_SEAM)
    def test_raises_on_error(self, mock_req):
        """Test raises RuntimeError on API error."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}
        # Clear (POST) succeeds; write (PATCH) fails with 400
        mock_req.side_effect = [_make_resp(200), _make_resp(400, text="Bad Request")]

        with self.assertRaises(RuntimeError) as ctx:
            _write_sheet(mock_client, "drive-id", "item-id", "Sheet1", [["A", "B"]])
        self.assertIn("Failed to write sheet", str(ctx.exception))

    @patch(_SESSION_SEAM)
    def test_calculates_correct_range(self, mock_req):
        """Test calculates correct range for varying column counts."""
        mock_client = MagicMock()
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_client._headers.return_value = {}
        mock_req.return_value = _make_resp(200)

        # 5 columns, 2 rows
        values = [
            ["A", "B", "C", "D", "E"],
            ["1", "2", "3", "4", "5"],
        ]
        _write_sheet(mock_client, "drive-id", "item-id", "Sheet1", values)

        call = _calls_for(mock_req, "PATCH")[0]
        self.assertIn("A1:E2", call.args[1])


if __name__ == "__main__":
    unittest.main()
