"""Tests for metals spot price module."""
from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

from metals.spot import (
    _auto_start_date,
    _today_iso,
    run,
    main,
)


class TestTodayIso(unittest.TestCase):
    """Tests for _today_iso helper."""

    def test_returns_iso_format(self):
        """Test returns valid ISO date format."""
        result = _today_iso()
        # Should match YYYY-MM-DD format
        self.assertRegex(result, r"^\d{4}-\d{2}-\d{2}$")

    def test_returns_today(self):
        """Test returns today's date."""
        result = _today_iso()
        expected = datetime.now().date().isoformat()
        self.assertEqual(result, expected)


class TestAutoStartDate(unittest.TestCase):
    """Tests for _auto_start_date helper."""

    def test_returns_none_when_no_files(self):
        """Test returns None when no cost files exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("metals.spot.Path") as mock_path:
                # Make paths not exist
                mock_path.return_value.exists.return_value = False
                result = _auto_start_date("silver")
                # Should return None when files don't exist
                self.assertIsNone(result)

    def test_parses_date_from_summary_csv(self):
        """Test parses earliest date from summary CSV."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a mock summary CSV
            summary_path = Path(tmpdir) / "out" / "metals" / "silver_summary.csv"
            summary_path.parent.mkdir(parents=True)
            with summary_path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "order_id", "vendor", "total_oz", "cost_per_oz"])
                w.writerow(["2024-06-15", "123", "TD", "1.0", "30.00"])
                w.writerow(["2024-03-10", "124", "Costco", "2.0", "28.00"])
                w.writerow(["2024-09-20", "125", "RCM", "0.5", "32.00"])

            # Patch Path to point to our temp directory
            with patch("metals.spot.Path") as mock_path_cls:
                def path_factory(p):
                    if "silver_summary" in p:
                        return summary_path
                    mock_p = MagicMock()
                    mock_p.exists.return_value = False
                    return mock_p
                mock_path_cls.side_effect = path_factory

                result = _auto_start_date("silver")
                self.assertEqual(result, "2024-03-10")

    def test_handles_invalid_metal(self):
        """Test handles invalid metal type."""
        result = _auto_start_date("platinum")
        # Should still try costs.csv but return None if not found
        self.assertIsNone(result)


class TestRun(unittest.TestCase):
    """Tests for run function."""

    @patch("metals.spot._fetch_stooq_series")
    @patch("metals.spot._fetch_yahoo_series")
    def test_run_creates_csv(self, mock_yahoo, mock_stooq):
        """Test run creates output CSV."""
        mock_stooq.return_value = {
            "2024-01-01": 25.0,
            "2024-01-02": 25.5,
        }
        # FX rate
        mock_stooq.side_effect = [
            {"2024-01-01": 25.0, "2024-01-02": 25.5},  # metal
            {"2024-01-01": 1.35, "2024-01-02": 1.36},  # fx
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "silver_spot.csv"
            result = run(
                metal="silver",
                start_date="2024-01-01",
                end_date="2024-01-02",
                out_path=str(out_path),
            )
            self.assertEqual(result, 0)
            self.assertTrue(out_path.exists())

            # Verify CSV content
            with out_path.open() as f:
                reader = csv.reader(f)
                rows = list(reader)
                self.assertEqual(len(rows), 3)  # header + 2 data rows
                self.assertEqual(rows[0][0], "date")

    def test_run_invalid_metal(self):
        """Test run raises error for invalid metal."""
        with self.assertRaises(SystemExit):
            run(
                metal="platinum",
                start_date="2024-01-01",
                end_date="2024-01-02",
                out_path="/tmp/test.csv",
            )

    @patch("metals.spot._fetch_stooq_series")
    def test_run_falls_back_to_yahoo(self, mock_stooq):
        """Test run falls back to Yahoo when Stooq fails."""
        mock_stooq.return_value = {}  # Empty = failure

        with patch("metals.spot._fetch_yahoo_series") as mock_yahoo:
            mock_yahoo.return_value = {"2024-01-01": 25.0}

            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = Path(tmpdir) / "gold_spot.csv"
                result = run(
                    metal="gold",
                    start_date="2024-01-01",
                    end_date="2024-01-01",
                    out_path=str(out_path),
                )
                self.assertEqual(result, 0)
                # Yahoo should have been called as fallback
                self.assertTrue(mock_yahoo.called)


class TestMain(unittest.TestCase):
    """Tests for main function."""

    @patch("metals.spot.run")
    def test_main_with_defaults(self, mock_run):
        """Test main with default arguments."""
        mock_run.return_value = 0
        result = main(["--metal", "silver"])
        self.assertEqual(result, 0)
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        self.assertEqual(call_args.kwargs["metal"], "silver")

    @patch("metals.spot.run")
    def test_main_with_all_args(self, mock_run):
        """Test main with all arguments."""
        mock_run.return_value = 0
        result = main([
            "--metal", "gold",
            "--start-date", "2024-01-01",
            "--end-date", "2024-12-31",
            "--out", "/tmp/test.csv",
        ])
        self.assertEqual(result, 0)
        call_args = mock_run.call_args
        self.assertEqual(call_args.kwargs["metal"], "gold")
        self.assertEqual(call_args.kwargs["start_date"], "2024-01-01")
        self.assertEqual(call_args.kwargs["end_date"], "2024-12-31")


if __name__ == "__main__":
    unittest.main()
