"""Tests for spot price run and main CLI entrypoints."""

from __future__ import annotations

from tests.fixtures import test_path
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from metals.spot import (
    run,
    main,
)


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
                out_path=test_path("test.csv"),  # noqa: S108 - test fixture path
            )

    @patch("metals.spot._fetch_stooq_series")
    def test_run_falls_back_to_yahoo(self, mock_stooq):
        """Test run falls back to Yahoo when Stooq fails."""
        mock_stooq.return_value = {}

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
            "--out", test_path("test.csv"),  # noqa: S108 - test fixture path
        ])
        self.assertEqual(result, 0)
        call_args = mock_run.call_args
        self.assertEqual(call_args.kwargs["metal"], "gold")
        self.assertEqual(call_args.kwargs["start_date"], "2024-01-01")
        self.assertEqual(call_args.kwargs["end_date"], "2024-12-31")


if __name__ == "__main__":
    unittest.main()

if __name__ == "__main__":
    unittest.main()
