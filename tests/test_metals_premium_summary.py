"""Tests for metals premium_summary module."""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from metals.premium_summary import (
    PremRow,
    _read_premium_csv,
    _summarize,
    _monthly,
    run,
    main,
)


class TestPremRow(unittest.TestCase):
    """Tests for PremRow dataclass."""

    def test_creation(self):
        """Test PremRow creation."""
        row = PremRow(
            date="2024-01-15",
            vendor="TD",
            order_id="12345",
            metal="silver",
            cost_per_oz=35.00,
            spot_cad=30.00,
            total_oz=10.0,
        )
        self.assertEqual(row.date, "2024-01-15")
        self.assertEqual(row.metal, "silver")
        self.assertEqual(row.cost_per_oz, 35.00)
        self.assertEqual(row.spot_cad, 30.00)


class TestReadPremiumCsv(unittest.TestCase):
    """Tests for _read_premium_csv function."""

    def test_reads_valid_csv(self):
        """Test reading valid premium CSV."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            w = csv.writer(f)
            w.writerow(["date", "vendor", "order_id", "metal", "cost_per_oz_cad", "spot_cad", "total_oz"])
            w.writerow(["2024-01-15", "TD", "12345", "silver", "35.00", "30.00", "10.0"])
            w.writerow(["2024-01-16", "Costco", "12346", "silver", "36.00", "31.00", "5.0"])
            f.flush()

            rows = _read_premium_csv(f.name, "silver")
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].vendor, "TD")
            self.assertEqual(rows[0].cost_per_oz, 35.00)

    def test_filters_by_metal(self):
        """Test filters rows by metal."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            w = csv.writer(f)
            w.writerow(["date", "vendor", "order_id", "metal", "cost_per_oz_cad", "spot_cad", "total_oz"])
            w.writerow(["2024-01-15", "TD", "12345", "silver", "35.00", "30.00", "10.0"])
            w.writerow(["2024-01-16", "TD", "12346", "gold", "2500.00", "2400.00", "1.0"])
            f.flush()

            silver = _read_premium_csv(f.name, "silver")
            gold = _read_premium_csv(f.name, "gold")
            self.assertEqual(len(silver), 1)
            self.assertEqual(len(gold), 1)

    def test_returns_empty_for_nonexistent_file(self):
        """Test returns empty list for nonexistent file."""
        rows = _read_premium_csv("/nonexistent/path.csv", "silver")
        self.assertEqual(rows, [])

    def test_returns_empty_for_none_path(self):
        """Test returns empty list for None path."""
        rows = _read_premium_csv(None, "silver")
        self.assertEqual(rows, [])


class TestSummarize(unittest.TestCase):
    """Tests for _summarize function."""

    def test_summarizes_rows(self):
        """Test summarizing rows."""
        rows = [
            PremRow(date="2024-01-15", vendor="TD", order_id="1", metal="silver",
                    cost_per_oz=35.00, spot_cad=30.00, total_oz=10.0),
            PremRow(date="2024-01-16", vendor="Costco", order_id="2", metal="silver",
                    cost_per_oz=36.00, spot_cad=31.00, total_oz=5.0),
        ]
        result = _summarize(rows)

        self.assertEqual(result["total_oz"], 15.0)
        # Total spent: 35*10 + 36*5 = 350 + 180 = 530
        self.assertEqual(result["total_spent_cad"], 530.0)
        # Spot value: 30*10 + 31*5 = 300 + 155 = 455
        self.assertEqual(result["spot_value_cad"], 455.0)
        # Premium: 530 - 455 = 75
        self.assertEqual(result["total_premium_cad"], 75.0)

    def test_handles_empty_rows(self):
        """Test handles empty rows."""
        result = _summarize([])
        self.assertEqual(result["total_oz"], 0.0)
        self.assertEqual(result["total_spent_cad"], 0.0)

    def test_skips_invalid_rows(self):
        """Test skips rows with zero/negative values."""
        rows = [
            PremRow(date="2024-01-15", vendor="TD", order_id="1", metal="silver",
                    cost_per_oz=35.00, spot_cad=30.00, total_oz=10.0),
            PremRow(date="2024-01-16", vendor="TD", order_id="2", metal="silver",
                    cost_per_oz=0, spot_cad=30.00, total_oz=5.0),  # invalid
            PremRow(date="2024-01-17", vendor="TD", order_id="3", metal="silver",
                    cost_per_oz=35.00, spot_cad=0, total_oz=5.0),  # invalid
        ]
        result = _summarize(rows)
        self.assertEqual(result["total_oz"], 10.0)  # Only first row


class TestMonthly(unittest.TestCase):
    """Tests for _monthly function."""

    def test_groups_by_month(self):
        """Test groups rows by month."""
        rows = [
            PremRow(date="2024-01-15", vendor="TD", order_id="1", metal="silver",
                    cost_per_oz=35.00, spot_cad=30.00, total_oz=10.0),
            PremRow(date="2024-01-20", vendor="TD", order_id="2", metal="silver",
                    cost_per_oz=36.00, spot_cad=31.00, total_oz=5.0),
            PremRow(date="2024-02-10", vendor="TD", order_id="3", metal="silver",
                    cost_per_oz=34.00, spot_cad=29.00, total_oz=8.0),
        ]
        result = _monthly(rows)

        self.assertIn("2024-01", result)
        self.assertIn("2024-02", result)
        self.assertEqual(result["2024-01"]["orders"], 2)
        self.assertEqual(result["2024-01"]["total_oz"], 15.0)
        self.assertEqual(result["2024-02"]["orders"], 1)

    def test_handles_empty_rows(self):
        """Test handles empty rows."""
        result = _monthly([])
        self.assertEqual(len(result), 0)


class TestRun(unittest.TestCase):
    """Tests for run function."""

    def test_run_creates_output_files(self):
        """Test run creates summary and monthly CSV files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create silver premium CSV
            silver_path = Path(tmpdir) / "premium_silver.csv"
            with silver_path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "vendor", "order_id", "metal", "cost_per_oz_cad", "spot_cad", "total_oz"])
                w.writerow(["2024-01-15", "TD", "12345", "silver", "35.00", "30.00", "10.0"])

            # Create gold premium CSV
            gold_path = Path(tmpdir) / "premium_gold.csv"
            with gold_path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "vendor", "order_id", "metal", "cost_per_oz_cad", "spot_cad", "total_oz"])
                w.writerow(["2024-01-16", "TD", "12346", "gold", "2500.00", "2400.00", "1.0"])

            out_summary = Path(tmpdir) / "summary.csv"
            out_monthly = Path(tmpdir) / "monthly.csv"

            result = run(
                str(silver_path),
                str(gold_path),
                str(out_summary),
                str(out_monthly),
            )
            self.assertEqual(result, 0)
            self.assertTrue(out_summary.exists())
            self.assertTrue(out_monthly.exists())

    def test_run_handles_missing_files(self):
        """Test run handles missing input files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_summary = Path(tmpdir) / "summary.csv"
            out_monthly = Path(tmpdir) / "monthly.csv"

            result = run(
                "/nonexistent/silver.csv",
                "/nonexistent/gold.csv",
                str(out_summary),
                str(out_monthly),
            )
            self.assertEqual(result, 0)


class TestMain(unittest.TestCase):
    """Tests for main function."""

    @patch("metals.premium_summary.run")
    def test_main_with_defaults(self, mock_run):
        """Test main with default arguments."""
        mock_run.return_value = 0
        result = main([])
        self.assertEqual(result, 0)
        mock_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
