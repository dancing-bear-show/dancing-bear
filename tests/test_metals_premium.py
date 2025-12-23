"""Tests for metals premium calculation module."""
from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

from metals.premium import (
    CostRow,
    _parse_costs,
    _parse_units_breakdown,
    _classify_units,
    _window,
    run,
    main,
)


class TestCostRow(unittest.TestCase):
    """Tests for CostRow dataclass."""

    def test_creation(self):
        """Test CostRow creation."""
        row = CostRow(
            date="2024-01-15",
            vendor="TD",
            metal="silver",
            currency="CAD",
            cost_per_oz=35.00,
            total_oz=10.0,
            order_id="12345",
            units_breakdown="1ozx10",
        )
        self.assertEqual(row.date, "2024-01-15")
        self.assertEqual(row.vendor, "TD")
        self.assertEqual(row.metal, "silver")
        self.assertEqual(row.cost_per_oz, 35.00)
        self.assertEqual(row.total_oz, 10.0)


class TestParseCosts(unittest.TestCase):
    """Tests for _parse_costs function."""

    def test_parses_valid_csv(self):
        """Test parsing valid costs CSV."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            w = csv.writer(f)
            w.writerow(["date", "vendor", "metal", "currency", "cost_per_oz", "total_oz", "order_id", "units_breakdown"])
            w.writerow(["2024-01-15", "TD", "silver", "CAD", "35.00", "10.0", "12345", "1ozx10"])
            w.writerow(["2024-01-16", "Costco", "gold", "CAD", "2500.00", "1.0", "12346", "1ozx1"])
            w.writerow(["2024-01-17", "RCM", "silver", "CAD", "38.00", "5.0", "12347", "0.5ozx10"])
            f.flush()

            rows = _parse_costs(f.name, "silver")
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].vendor, "TD")
            self.assertEqual(rows[1].vendor, "RCM")

    def test_filters_by_metal(self):
        """Test filters rows by metal type."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            w = csv.writer(f)
            w.writerow(["date", "vendor", "metal", "currency", "cost_per_oz", "total_oz", "order_id", "units_breakdown"])
            w.writerow(["2024-01-15", "TD", "silver", "CAD", "35.00", "10.0", "12345", "1ozx10"])
            w.writerow(["2024-01-16", "TD", "gold", "CAD", "2500.00", "1.0", "12346", "1ozx1"])
            f.flush()

            silver_rows = _parse_costs(f.name, "silver")
            gold_rows = _parse_costs(f.name, "gold")
            self.assertEqual(len(silver_rows), 1)
            self.assertEqual(len(gold_rows), 1)

    def test_skips_invalid_rows(self):
        """Test skips rows with invalid cost/oz values."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            w = csv.writer(f)
            w.writerow(["date", "vendor", "metal", "currency", "cost_per_oz", "total_oz", "order_id", "units_breakdown"])
            w.writerow(["2024-01-15", "TD", "silver", "CAD", "35.00", "10.0", "12345", "1ozx10"])
            w.writerow(["2024-01-16", "TD", "silver", "CAD", "-5.00", "10.0", "12346", "1ozx10"])  # negative cost
            w.writerow(["2024-01-17", "TD", "silver", "CAD", "35.00", "0", "12347", "1ozx10"])  # zero oz
            w.writerow(["2024-01-18", "TD", "silver", "CAD", "invalid", "10.0", "12348", "1ozx10"])  # invalid number
            f.flush()

            rows = _parse_costs(f.name, "silver")
            self.assertEqual(len(rows), 1)


class TestParseUnitsBreakdown(unittest.TestCase):
    """Tests for _parse_units_breakdown function."""

    def test_parses_single_unit(self):
        """Test parsing single unit breakdown."""
        result = _parse_units_breakdown("1ozx10")
        self.assertEqual(result, [(1.0, 10.0)])

    def test_parses_multiple_units(self):
        """Test parsing multiple unit breakdown."""
        result = _parse_units_breakdown("0.1ozx2;1ozx3")
        self.assertEqual(result, [(0.1, 2.0), (1.0, 3.0)])

    def test_parses_fractional_oz(self):
        """Test parsing fractional ounce units."""
        result = _parse_units_breakdown("0.5ozx5;0.25ozx4")
        self.assertEqual(result, [(0.5, 5.0), (0.25, 4.0)])

    def test_handles_simple_oz_format(self):
        """Test handling simple oz format without quantity."""
        result = _parse_units_breakdown("1oz")
        self.assertEqual(result, [(1.0, 1.0)])

    def test_returns_empty_for_empty_string(self):
        """Test returns empty list for empty string."""
        result = _parse_units_breakdown("")
        self.assertEqual(result, [])

    def test_handles_whitespace(self):
        """Test handles whitespace in breakdown."""
        result = _parse_units_breakdown("  1ozx5  ;  0.5ozx2  ")
        self.assertEqual(result, [(1.0, 5.0), (0.5, 2.0)])

    def test_handles_invalid_format(self):
        """Test handles invalid format gracefully."""
        result = _parse_units_breakdown("invalid;1ozx5")
        self.assertEqual(result, [(1.0, 5.0)])


class TestClassifyUnits(unittest.TestCase):
    """Tests for _classify_units function."""

    def test_classifies_fractional(self):
        """Test classifies fractional units."""
        units = [(0.1, 5), (0.5, 2)]
        self.assertEqual(_classify_units(units), "fractional")

    def test_classifies_one_oz(self):
        """Test classifies 1 oz units."""
        units = [(1.0, 10)]
        self.assertEqual(_classify_units(units), "one_oz")

    def test_classifies_near_one_oz(self):
        """Test classifies near 1 oz as one_oz (0.98-1.02)."""
        units = [(0.99, 5), (1.01, 3)]
        self.assertEqual(_classify_units(units), "one_oz")

    def test_classifies_bulk(self):
        """Test classifies bulk units (>1 oz)."""
        units = [(5.0, 2), (10.0, 1)]
        self.assertEqual(_classify_units(units), "bulk")

    def test_classifies_mixed(self):
        """Test classifies mixed units."""
        units = [(0.1, 5), (1.0, 3), (5.0, 1)]
        self.assertEqual(_classify_units(units), "mixed")

    def test_classifies_unknown_for_empty(self):
        """Test returns unknown for empty units."""
        self.assertEqual(_classify_units([]), "unknown")


class TestWindow(unittest.TestCase):
    """Tests for _window function."""

    def test_finds_date_range(self):
        """Test finds min/max date range."""
        rows = [
            CostRow(date="2024-03-15", vendor="", metal="", currency="", cost_per_oz=0, total_oz=0, order_id="", units_breakdown=""),
            CostRow(date="2024-01-10", vendor="", metal="", currency="", cost_per_oz=0, total_oz=0, order_id="", units_breakdown=""),
            CostRow(date="2024-06-20", vendor="", metal="", currency="", cost_per_oz=0, total_oz=0, order_id="", units_breakdown=""),
        ]
        start, end = _window(rows)
        self.assertEqual(start, "2024-01-10")
        self.assertEqual(end, "2024-06-20")

    def test_handles_empty_rows(self):
        """Test handles empty rows list."""
        start, end = _window([])
        # Should return today for both
        today = date.today().isoformat()
        self.assertEqual(start, today)
        self.assertEqual(end, today)

    def test_handles_single_row(self):
        """Test handles single row."""
        rows = [
            CostRow(date="2024-05-15", vendor="", metal="", currency="", cost_per_oz=0, total_oz=0, order_id="", units_breakdown=""),
        ]
        start, end = _window(rows)
        self.assertEqual(start, "2024-05-15")
        self.assertEqual(end, "2024-05-15")


class TestRun(unittest.TestCase):
    """Tests for run function."""

    @patch("metals.premium._spot_series_cad")
    def test_run_creates_output(self, mock_spot):
        """Test run creates output CSV."""
        mock_spot.return_value = {
            "2024-01-15": 30.00,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            costs_path = Path(tmpdir) / "costs.csv"
            with costs_path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "vendor", "metal", "currency", "cost_per_oz", "total_oz", "order_id", "units_breakdown"])
                w.writerow(["2024-01-15", "TD", "silver", "CAD", "35.00", "10.0", "12345", "1ozx10"])

            out_path = Path(tmpdir) / "premium.csv"
            result = run(
                metal="silver",
                costs_path=str(costs_path),
                out_path=str(out_path),
            )
            self.assertEqual(result, 0)
            self.assertTrue(out_path.exists())

    def test_run_invalid_metal(self):
        """Test run raises error for invalid metal."""
        with self.assertRaises(SystemExit):
            run(
                metal="platinum",
                costs_path="/tmp/costs.csv",
                out_path="/tmp/premium.csv",
            )

    @patch("metals.premium._spot_series_cad")
    def test_run_handles_no_matching_rows(self, mock_spot):
        """Test run handles no matching rows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            costs_path = Path(tmpdir) / "costs.csv"
            with costs_path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "vendor", "metal", "currency", "cost_per_oz", "total_oz", "order_id", "units_breakdown"])
                w.writerow(["2024-01-15", "TD", "gold", "CAD", "2500.00", "1.0", "12345", "1ozx1"])

            out_path = Path(tmpdir) / "premium.csv"
            result = run(
                metal="silver",  # No silver rows
                costs_path=str(costs_path),
                out_path=str(out_path),
            )
            self.assertEqual(result, 0)


class TestMain(unittest.TestCase):
    """Tests for main function."""

    @patch("metals.premium.run")
    def test_main_with_defaults(self, mock_run):
        """Test main with default arguments."""
        mock_run.return_value = 0
        result = main(["--metal", "silver"])
        self.assertEqual(result, 0)
        mock_run.assert_called_once()

    @patch("metals.premium.run")
    def test_main_with_all_args(self, mock_run):
        """Test main with all arguments."""
        mock_run.return_value = 0
        result = main([
            "--metal", "gold",
            "--costs", "/path/to/costs.csv",
            "--out", "/path/to/premium.csv",
        ])
        self.assertEqual(result, 0)
        call_args = mock_run.call_args
        self.assertEqual(call_args.kwargs["metal"], "gold")
        self.assertEqual(call_args.kwargs["costs_path"], "/path/to/costs.csv")


if __name__ == "__main__":
    unittest.main()
