"""Tests for metals build_summaries module."""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from metals.build_summaries import run, main


class TestRun(unittest.TestCase):
    """Tests for run function."""

    def test_builds_gold_and_silver_summaries(self):
        """Test builds both gold and silver summary CSVs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            costs_path = Path(tmpdir) / "costs.csv"
            out_dir = Path(tmpdir) / "out"

            # Create costs CSV
            with costs_path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "order_id", "vendor", "metal", "total_oz", "cost_per_oz"])
                w.writerow(["2024-01-15", "12345", "TD", "gold", "1.0", "2500.00"])
                w.writerow(["2024-01-16", "12346", "Costco", "silver", "10.0", "35.00"])
                w.writerow(["2024-01-17", "12347", "RCM", "silver", "5.0", "38.00"])
                w.writerow(["2024-01-18", "12348", "TD", "gold", "0.5", "2600.00"])

            result = run(str(costs_path), str(out_dir))
            self.assertEqual(result, 0)

            # Verify gold summary
            gold_path = out_dir / "gold_summary.csv"
            self.assertTrue(gold_path.exists())
            with gold_path.open() as f:
                reader = csv.reader(f)
                rows = list(reader)
                self.assertEqual(len(rows), 3)  # header + 2 gold rows
                self.assertEqual(rows[0], ["date", "order_id", "vendor", "total_oz", "cost_per_oz"])
                self.assertEqual(rows[1][0], "2024-01-15")  # first gold row
                self.assertEqual(rows[2][0], "2024-01-18")  # second gold row

            # Verify silver summary
            silver_path = out_dir / "silver_summary.csv"
            self.assertTrue(silver_path.exists())
            with silver_path.open() as f:
                reader = csv.reader(f)
                rows = list(reader)
                self.assertEqual(len(rows), 3)  # header + 2 silver rows

    def test_creates_output_directory(self):
        """Test creates output directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            costs_path = Path(tmpdir) / "costs.csv"
            out_dir = Path(tmpdir) / "nested" / "output" / "dir"

            with costs_path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "order_id", "vendor", "metal", "total_oz", "cost_per_oz"])
                w.writerow(["2024-01-15", "12345", "TD", "gold", "1.0", "2500.00"])

            result = run(str(costs_path), str(out_dir))
            self.assertEqual(result, 0)
            self.assertTrue(out_dir.exists())

    def test_handles_empty_csv(self):
        """Test handles empty costs CSV (header only)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            costs_path = Path(tmpdir) / "costs.csv"
            out_dir = Path(tmpdir) / "out"

            with costs_path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "order_id", "vendor", "metal", "total_oz", "cost_per_oz"])

            result = run(str(costs_path), str(out_dir))
            self.assertEqual(result, 0)

            # Both files should exist with only headers
            gold_path = out_dir / "gold_summary.csv"
            silver_path = out_dir / "silver_summary.csv"
            self.assertTrue(gold_path.exists())
            self.assertTrue(silver_path.exists())

    def test_filters_unknown_metals(self):
        """Test filters out unknown metal types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            costs_path = Path(tmpdir) / "costs.csv"
            out_dir = Path(tmpdir) / "out"

            with costs_path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "order_id", "vendor", "metal", "total_oz", "cost_per_oz"])
                w.writerow(["2024-01-15", "12345", "TD", "gold", "1.0", "2500.00"])
                w.writerow(["2024-01-16", "12346", "TD", "platinum", "1.0", "1000.00"])  # Unknown metal
                w.writerow(["2024-01-17", "12347", "TD", "silver", "5.0", "35.00"])

            result = run(str(costs_path), str(out_dir))
            self.assertEqual(result, 0)

            # Gold should have 1 row, silver should have 1 row
            with (out_dir / "gold_summary.csv").open() as f:
                rows = list(csv.reader(f))
                self.assertEqual(len(rows), 2)  # header + 1 gold row

            with (out_dir / "silver_summary.csv").open() as f:
                rows = list(csv.reader(f))
                self.assertEqual(len(rows), 2)  # header + 1 silver row

    def test_raises_error_for_missing_file(self):
        """Test raises error when costs file doesn't exist."""
        with self.assertRaises(SystemExit):
            run("/nonexistent/costs.csv", "/tmp/out")  # noqa: S108

    def test_handles_case_insensitive_metal(self):
        """Test handles case-insensitive metal names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            costs_path = Path(tmpdir) / "costs.csv"
            out_dir = Path(tmpdir) / "out"

            with costs_path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "order_id", "vendor", "metal", "total_oz", "cost_per_oz"])
                w.writerow(["2024-01-15", "12345", "TD", "GOLD", "1.0", "2500.00"])
                w.writerow(["2024-01-16", "12346", "TD", "Silver", "5.0", "35.00"])
                w.writerow(["2024-01-17", "12347", "TD", "  silver  ", "5.0", "35.00"])

            result = run(str(costs_path), str(out_dir))
            self.assertEqual(result, 0)

            with (out_dir / "gold_summary.csv").open() as f:
                rows = list(csv.reader(f))
                self.assertEqual(len(rows), 2)  # header + 1 gold row

            with (out_dir / "silver_summary.csv").open() as f:
                rows = list(csv.reader(f))
                self.assertEqual(len(rows), 3)  # header + 2 silver rows


class TestMain(unittest.TestCase):
    """Tests for main function."""

    @patch("metals.build_summaries.run")
    def test_main_with_defaults(self, mock_run):
        """Test main with default arguments."""
        mock_run.return_value = 0
        result = main([])
        self.assertEqual(result, 0)
        mock_run.assert_called_once_with(
            costs_path="out/metals/costs.csv",
            out_dir="out/metals",
        )

    @patch("metals.build_summaries.run")
    def test_main_with_custom_args(self, mock_run):
        """Test main with custom arguments."""
        mock_run.return_value = 0
        result = main([
            "--costs", "/custom/costs.csv",
            "--out-dir", "/custom/output",
        ])
        self.assertEqual(result, 0)
        mock_run.assert_called_once_with(
            costs_path="/custom/costs.csv",
            out_dir="/custom/output",
        )


if __name__ == "__main__":
    unittest.main()
