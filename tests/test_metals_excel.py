"""Tests for metals excel module."""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
