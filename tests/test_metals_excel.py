"""Tests for metals excel module."""
from __future__ import annotations

import csv
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from metals.excel import (
    _col_letter,
    _read_csv,
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


if __name__ == "__main__":
    unittest.main()
