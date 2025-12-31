"""Tests for metals spot price module."""

from __future__ import annotations

from tests.fixtures import test_path
import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

from metals.spot import (
    _auto_start_date,
    _fetch_stooq_series,
    _fetch_yahoo_series,
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


class TestFetchYahooSeries(unittest.TestCase):
    """Tests for _fetch_yahoo_series function."""

    @patch("requests.get")
    def test_parses_valid_response(self, mock_get):
        """Test parsing a valid Yahoo Finance response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "chart": {
                "result": [{
                    "timestamp": [1704067200, 1704153600],  # 2024-01-01, 2024-01-02 UTC
                    "indicators": {
                        "quote": [{
                            "close": [25.0, 25.5]
                        }]
                    }
                }]
            }
        }
        mock_get.return_value = mock_response

        result = _fetch_yahoo_series("XAGUSD=X", "2024-01-01", "2024-01-02")
        self.assertIn("2024-01-01", result)
        self.assertIn("2024-01-02", result)
        self.assertEqual(result["2024-01-01"], 25.0)
        self.assertEqual(result["2024-01-02"], 25.5)

    @patch("requests.get")
    def test_forward_fills_gaps(self, mock_get):
        """Test forward-fill behavior for missing days."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        # Only return data for first day, skip second
        mock_response.json.return_value = {
            "chart": {
                "result": [{
                    "timestamp": [1704067200],  # 2024-01-01 only
                    "indicators": {
                        "quote": [{
                            "close": [25.0]
                        }]
                    }
                }]
            }
        }
        mock_get.return_value = mock_response

        result = _fetch_yahoo_series("XAGUSD=X", "2024-01-01", "2024-01-03")
        self.assertEqual(result["2024-01-01"], 25.0)
        self.assertEqual(result["2024-01-02"], 25.0)  # forward-filled
        self.assertEqual(result["2024-01-03"], 25.0)  # forward-filled

    @patch("requests.get")
    def test_back_fills_initial_gap(self, mock_get):
        """Test back-fill behavior for initial missing days."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        # Data starts on 2024-01-03, but window starts on 2024-01-01
        mock_response.json.return_value = {
            "chart": {
                "result": [{
                    "timestamp": [1704240000],  # 2024-01-03
                    "indicators": {
                        "quote": [{
                            "close": [26.0]
                        }]
                    }
                }]
            }
        }
        mock_get.return_value = mock_response

        result = _fetch_yahoo_series("XAGUSD=X", "2024-01-01", "2024-01-03")
        self.assertEqual(result["2024-01-01"], 26.0)  # back-filled
        self.assertEqual(result["2024-01-02"], 26.0)  # back-filled
        self.assertEqual(result["2024-01-03"], 26.0)

    @patch("requests.get")
    def test_handles_empty_response(self, mock_get):
        """Test handling of empty response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_get.return_value = mock_response

        result = _fetch_yahoo_series("XAGUSD=X", "2024-01-01", "2024-01-02")
        self.assertEqual(result, {})

    @patch("requests.get")
    def test_handles_malformed_json(self, mock_get):
        """Test handling of malformed JSON structure."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"chart": {"result": []}}
        mock_get.return_value = mock_response

        result = _fetch_yahoo_series("XAGUSD=X", "2024-01-01", "2024-01-02")
        self.assertEqual(result, {})

    @patch("requests.get")
    def test_handles_none_close_values(self, mock_get):
        """Test handling of None values in close prices."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "chart": {
                "result": [{
                    "timestamp": [1704067200, 1704153600],
                    "indicators": {
                        "quote": [{
                            "close": [25.0, None]  # second value is None
                        }]
                    }
                }]
            }
        }
        mock_get.return_value = mock_response

        result = _fetch_yahoo_series("XAGUSD=X", "2024-01-01", "2024-01-02")
        self.assertEqual(result["2024-01-01"], 25.0)
        self.assertEqual(result["2024-01-02"], 25.0)  # forward-filled from 01

    @patch("requests.get")
    @patch("time.sleep", return_value=None)  # Skip actual sleep
    def test_retries_on_429(self, mock_sleep, mock_get):
        """Test retry behavior on HTTP 429."""
        fail_response = MagicMock()
        fail_response.status_code = 429

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "chart": {
                "result": [{
                    "timestamp": [1704067200],
                    "indicators": {"quote": [{"close": [25.0]}]}
                }]
            }
        }
        mock_get.side_effect = [fail_response, success_response]

        result = _fetch_yahoo_series("XAGUSD=X", "2024-01-01", "2024-01-01")
        self.assertEqual(result["2024-01-01"], 25.0)
        self.assertEqual(mock_get.call_count, 2)

    @patch("requests.get")
    @patch("time.sleep", return_value=None)
    def test_retries_on_5xx(self, mock_sleep, mock_get):
        """Test retry behavior on HTTP 5xx errors."""
        fail_response = MagicMock()
        fail_response.status_code = 503

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "chart": {
                "result": [{
                    "timestamp": [1704067200],
                    "indicators": {"quote": [{"close": [25.0]}]}
                }]
            }
        }
        mock_get.side_effect = [fail_response, success_response]

        result = _fetch_yahoo_series("XAGUSD=X", "2024-01-01", "2024-01-01")
        self.assertEqual(result["2024-01-01"], 25.0)

    @patch("requests.get")
    @patch("time.sleep", return_value=None)
    def test_handles_request_exception(self, mock_sleep, mock_get):
        """Test handling of request exceptions."""
        mock_get.side_effect = Exception("Network error")

        result = _fetch_yahoo_series("XAGUSD=X", "2024-01-01", "2024-01-01")
        self.assertEqual(result, {})


class TestFetchStooqSeries(unittest.TestCase):
    """Tests for _fetch_stooq_series function."""

    @patch("requests.get")
    def test_parses_valid_csv(self, mock_get):
        """Test parsing a valid Stooq CSV response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = (
            "Date,Open,High,Low,Close\n"
            "2024-01-01,24.5,25.5,24.0,25.0\n"
            "2024-01-02,25.0,26.0,24.8,25.5\n"
        )
        mock_get.return_value = mock_response

        result = _fetch_stooq_series("xagusd", "2024-01-01", "2024-01-02")
        self.assertEqual(result["2024-01-01"], 25.0)
        self.assertEqual(result["2024-01-02"], 25.5)

    @patch("requests.get")
    def test_forward_fills_gaps(self, mock_get):
        """Test forward-fill for missing days."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = (
            "Date,Open,High,Low,Close\n"
            "2024-01-01,24.5,25.5,24.0,25.0\n"
            # 2024-01-02 is missing (weekend or holiday)
            "2024-01-03,25.2,26.0,25.0,25.8\n"
        )
        mock_get.return_value = mock_response

        result = _fetch_stooq_series("xagusd", "2024-01-01", "2024-01-03")
        self.assertEqual(result["2024-01-01"], 25.0)
        self.assertEqual(result["2024-01-02"], 25.0)  # forward-filled
        self.assertEqual(result["2024-01-03"], 25.8)

    @patch("requests.get")
    def test_back_fills_initial_gap(self, mock_get):
        """Test back-fill for initial missing days."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        # Data starts on 2024-01-03, but window starts on 2024-01-01
        mock_response.text = (
            "Date,Open,High,Low,Close\n"
            "2024-01-03,25.2,26.0,25.0,25.8\n"
        )
        mock_get.return_value = mock_response

        result = _fetch_stooq_series("xagusd", "2024-01-01", "2024-01-03")
        self.assertEqual(result["2024-01-01"], 25.8)  # back-filled
        self.assertEqual(result["2024-01-02"], 25.8)  # back-filled
        self.assertEqual(result["2024-01-03"], 25.8)

    @patch("requests.get")
    def test_handles_http_error(self, mock_get):
        """Test handling of HTTP errors."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result = _fetch_stooq_series("xagusd", "2024-01-01", "2024-01-02")
        self.assertEqual(result, {})

    @patch("requests.get")
    def test_handles_empty_response(self, mock_get):
        """Test handling of empty response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = ""
        mock_get.return_value = mock_response

        result = _fetch_stooq_series("xagusd", "2024-01-01", "2024-01-02")
        self.assertEqual(result, {})

    @patch("requests.get")
    def test_handles_malformed_csv(self, mock_get):
        """Test handling of malformed CSV."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Not a valid CSV response"
        mock_get.return_value = mock_response

        result = _fetch_stooq_series("xagusd", "2024-01-01", "2024-01-02")
        self.assertEqual(result, {})

    @patch("requests.get")
    def test_handles_incomplete_rows(self, mock_get):
        """Test handling of CSV with incomplete rows."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = (
            "Date,Open,High,Low,Close\n"
            "2024-01-01,24.5,25.5,24.0,25.0\n"
            "2024-01-02,25.0\n"  # incomplete row
            "2024-01-03,25.2,26.0,25.0,25.8\n"
        )
        mock_get.return_value = mock_response

        result = _fetch_stooq_series("xagusd", "2024-01-01", "2024-01-03")
        self.assertEqual(result["2024-01-01"], 25.0)
        self.assertEqual(result["2024-01-02"], 25.0)  # forward-filled (row skipped)
        self.assertEqual(result["2024-01-03"], 25.8)

    @patch("requests.get")
    def test_handles_invalid_close_value(self, mock_get):
        """Test handling of non-numeric close values."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = (
            "Date,Open,High,Low,Close\n"
            "2024-01-01,24.5,25.5,24.0,25.0\n"
            "2024-01-02,25.0,26.0,24.8,N/A\n"  # invalid close
            "2024-01-03,25.2,26.0,25.0,25.8\n"
        )
        mock_get.return_value = mock_response

        result = _fetch_stooq_series("xagusd", "2024-01-01", "2024-01-03")
        self.assertEqual(result["2024-01-01"], 25.0)
        self.assertEqual(result["2024-01-02"], 25.0)  # forward-filled
        self.assertEqual(result["2024-01-03"], 25.8)

    @patch("requests.get")
    def test_handles_request_exception(self, mock_get):
        """Test handling of request exceptions."""
        mock_get.side_effect = Exception("Network error")

        result = _fetch_stooq_series("xagusd", "2024-01-01", "2024-01-02")
        self.assertEqual(result, {})

    @patch("requests.get")
    def test_slices_to_window(self, mock_get):
        """Test that only data within the window is returned."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        # Response includes data outside the requested window
        mock_response.text = (
            "Date,Open,High,Low,Close\n"
            "2023-12-31,24.0,24.5,23.5,24.2\n"
            "2024-01-01,24.5,25.5,24.0,25.0\n"
            "2024-01-02,25.0,26.0,24.8,25.5\n"
            "2024-01-03,25.5,26.5,25.0,26.0\n"
        )
        mock_get.return_value = mock_response

        result = _fetch_stooq_series("xagusd", "2024-01-01", "2024-01-02")
        self.assertNotIn("2023-12-31", result)
        self.assertIn("2024-01-01", result)
        self.assertIn("2024-01-02", result)
        self.assertNotIn("2024-01-03", result)


class TestAutoStartDate(unittest.TestCase):
    """Tests for _auto_start_date helper."""

    def test_returns_none_when_no_files(self):
        """Test returns None when no cost files exist."""
        with tempfile.TemporaryDirectory():
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
                out_path=test_path("test.csv"),  # noqa: S108
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
            "--out", test_path("test.csv"),  # noqa: S108
        ])
        self.assertEqual(result, 0)
        call_args = mock_run.call_args
        self.assertEqual(call_args.kwargs["metal"], "gold")
        self.assertEqual(call_args.kwargs["start_date"], "2024-01-01")
        self.assertEqual(call_args.kwargs["end_date"], "2024-12-31")


if __name__ == "__main__":
    unittest.main()
