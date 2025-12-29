"""Tests for metals build_summaries module."""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.metals_tests.fixtures import make_summary_row, write_summary_csv

from metals.build_summaries import run, main


class TestRun(unittest.TestCase):
    """Tests for run function."""

    def test_builds_gold_and_silver_summaries(self):
        """Test builds both gold and silver summary CSVs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            costs_path = Path(tmpdir) / "costs.csv"
            out_dir = Path(tmpdir) / "out"

            write_summary_csv(str(costs_path), [
                make_summary_row(date="2024-01-15", order_id="12345", vendor="TD", metal="gold"),
                make_summary_row(date="2024-01-16", order_id="12346", vendor="Costco", metal="silver", total_oz=10.0, cost_per_oz=35.0),
                make_summary_row(date="2024-01-17", order_id="12347", vendor="RCM", metal="silver", total_oz=5.0, cost_per_oz=38.0),
                make_summary_row(date="2024-01-18", order_id="12348", vendor="TD", metal="gold", total_oz=0.5, cost_per_oz=2600.0),
            ])

            result = run(str(costs_path), str(out_dir))
            self.assertEqual(result, 0)

            # Verify gold summary
            gold_path = out_dir / "gold_summary.csv"
            self.assertTrue(gold_path.exists())
            with gold_path.open() as f:
                rows = list(csv.reader(f))
                self.assertEqual(len(rows), 3)  # header + 2 gold rows
                self.assertEqual(rows[0], ["date", "order_id", "vendor", "total_oz", "cost_per_oz"])
                self.assertEqual(rows[1][0], "2024-01-15")  # first gold row
                self.assertEqual(rows[2][0], "2024-01-18")  # second gold row

            # Verify silver summary
            silver_path = out_dir / "silver_summary.csv"
            self.assertTrue(silver_path.exists())
            with silver_path.open() as f:
                rows = list(csv.reader(f))
                self.assertEqual(len(rows), 3)  # header + 2 silver rows

    def test_creates_output_directory(self):
        """Test creates output directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            costs_path = Path(tmpdir) / "costs.csv"
            out_dir = Path(tmpdir) / "nested" / "output" / "dir"

            write_summary_csv(str(costs_path), [make_summary_row()])

            result = run(str(costs_path), str(out_dir))
            self.assertEqual(result, 0)
            self.assertTrue(out_dir.exists())

    def test_handles_empty_csv(self):
        """Test handles empty costs CSV (header only)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            costs_path = Path(tmpdir) / "costs.csv"
            out_dir = Path(tmpdir) / "out"

            write_summary_csv(str(costs_path), [])

            result = run(str(costs_path), str(out_dir))
            self.assertEqual(result, 0)

            # Both files should exist with only headers
            self.assertTrue((out_dir / "gold_summary.csv").exists())
            self.assertTrue((out_dir / "silver_summary.csv").exists())

    def test_filters_unknown_metals(self):
        """Test filters out unknown metal types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            costs_path = Path(tmpdir) / "costs.csv"
            out_dir = Path(tmpdir) / "out"

            write_summary_csv(str(costs_path), [
                make_summary_row(date="2024-01-15", order_id="12345", metal="gold"),
                make_summary_row(date="2024-01-16", order_id="12346", metal="platinum", cost_per_oz=1000.0),
                make_summary_row(date="2024-01-17", order_id="12347", metal="silver", total_oz=5.0, cost_per_oz=35.0),
            ])

            result = run(str(costs_path), str(out_dir))
            self.assertEqual(result, 0)

            with (out_dir / "gold_summary.csv").open() as f:
                self.assertEqual(len(list(csv.reader(f))), 2)  # header + 1 gold row

            with (out_dir / "silver_summary.csv").open() as f:
                self.assertEqual(len(list(csv.reader(f))), 2)  # header + 1 silver row

    def test_raises_error_for_missing_file(self):
        """Test raises error when costs file doesn't exist."""
        with self.assertRaises(SystemExit):
            run("/nonexistent/costs.csv", "/tmp/out")  # noqa: S108

    def test_handles_case_insensitive_metal(self):
        """Test handles case-insensitive metal names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            costs_path = Path(tmpdir) / "costs.csv"
            out_dir = Path(tmpdir) / "out"

            write_summary_csv(str(costs_path), [
                make_summary_row(date="2024-01-15", order_id="12345", metal="GOLD"),
                make_summary_row(date="2024-01-16", order_id="12346", metal="Silver", total_oz=5.0, cost_per_oz=35.0),
                make_summary_row(date="2024-01-17", order_id="12347", metal="  silver  ", total_oz=5.0, cost_per_oz=35.0),
            ])

            result = run(str(costs_path), str(out_dir))
            self.assertEqual(result, 0)

            with (out_dir / "gold_summary.csv").open() as f:
                self.assertEqual(len(list(csv.reader(f))), 2)  # header + 1 gold row

            with (out_dir / "silver_summary.csv").open() as f:
                self.assertEqual(len(list(csv.reader(f))), 3)  # header + 2 silver rows


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
