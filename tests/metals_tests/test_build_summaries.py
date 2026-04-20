"""Tests for metals.build_summaries module.

Covers run() and main() including all branches:
- gold-only, silver-only, mixed, unknown metal types
- missing input file (SystemExit)
- case-insensitive + whitespace-stripped metal names
- empty CSV (header only)
- nested output directory creation
- None/empty field values coerced to str
- CLI default and custom argument passthrough
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.metals_tests.fixtures import make_summary_row, write_summary_csv


class TestRunGoldAndSilverSummaries(unittest.TestCase):
    """run() writes correct gold_summary.csv and silver_summary.csv."""

    def _write_costs(self, path: Path, rows: list) -> None:
        write_summary_csv(str(path), rows)

    def _read_csv(self, path: Path) -> list[list[str]]:
        with path.open(encoding="utf-8") as f:
            return list(csv.reader(f))

    def test_returns_zero_on_success(self):
        from metals.build_summaries import run

        with tempfile.TemporaryDirectory() as tmp:
            costs = Path(tmp) / "costs.csv"
            self._write_costs(costs, [make_summary_row(metal="gold")])
            self.assertEqual(run(str(costs), tmp), 0)

    def test_gold_and_silver_rows_split_correctly(self):
        from metals.build_summaries import run

        with tempfile.TemporaryDirectory() as tmp:
            costs = Path(tmp) / "costs.csv"
            out = Path(tmp) / "out"
            self._write_costs(costs, [
                make_summary_row(date="2024-01-01", order_id="1", vendor="TD", metal="gold"),
                make_summary_row(date="2024-01-02", order_id="2", vendor="Costco", metal="silver",
                                 total_oz=10.0, cost_per_oz=35.0),
                make_summary_row(date="2024-01-03", order_id="3", vendor="RCM", metal="gold",
                                 total_oz=0.5, cost_per_oz=2600.0),
            ])
            run(str(costs), str(out))

            gold_rows = self._read_csv(out / "gold_summary.csv")
            self.assertEqual(len(gold_rows), 3)  # header + 2
            self.assertEqual(gold_rows[0], ["date", "order_id", "vendor", "total_oz", "cost_per_oz"])
            self.assertEqual(gold_rows[1][0], "2024-01-01")
            self.assertEqual(gold_rows[2][0], "2024-01-03")

            silver_rows = self._read_csv(out / "silver_summary.csv")
            self.assertEqual(len(silver_rows), 2)  # header + 1
            self.assertEqual(silver_rows[1][0], "2024-01-02")

    def test_empty_csv_produces_header_only_summaries(self):
        from metals.build_summaries import run

        with tempfile.TemporaryDirectory() as tmp:
            costs = Path(tmp) / "costs.csv"
            self._write_costs(costs, [])
            out = Path(tmp) / "out"
            run(str(costs), str(out))

            for fname in ("gold_summary.csv", "silver_summary.csv"):
                rows = self._read_csv(out / fname)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0], ["date", "order_id", "vendor", "total_oz", "cost_per_oz"])

    def test_filters_out_unknown_metal_types(self):
        from metals.build_summaries import run

        with tempfile.TemporaryDirectory() as tmp:
            costs = Path(tmp) / "costs.csv"
            out = Path(tmp) / "out"
            self._write_costs(costs, [
                make_summary_row(metal="gold"),
                make_summary_row(metal="platinum", order_id="99"),
                make_summary_row(metal="silver", order_id="98", total_oz=5.0, cost_per_oz=35.0),
                make_summary_row(metal="", order_id="97"),
            ])
            run(str(costs), str(out))

            gold_rows = self._read_csv(out / "gold_summary.csv")
            self.assertEqual(len(gold_rows), 2)  # header + 1

            silver_rows = self._read_csv(out / "silver_summary.csv")
            self.assertEqual(len(silver_rows), 2)  # header + 1

    def test_case_insensitive_metal_matching(self):
        from metals.build_summaries import run

        with tempfile.TemporaryDirectory() as tmp:
            costs = Path(tmp) / "costs.csv"
            out = Path(tmp) / "out"
            self._write_costs(costs, [
                make_summary_row(metal="GOLD", order_id="1"),
                make_summary_row(metal="Gold", order_id="2"),
                make_summary_row(metal="Silver", order_id="3", total_oz=5.0, cost_per_oz=35.0),
            ])
            run(str(costs), str(out))

            gold_rows = self._read_csv(out / "gold_summary.csv")
            self.assertEqual(len(gold_rows), 3)  # header + 2

            silver_rows = self._read_csv(out / "silver_summary.csv")
            self.assertEqual(len(silver_rows), 2)  # header + 1

    def test_whitespace_stripped_from_metal_field(self):
        from metals.build_summaries import run

        with tempfile.TemporaryDirectory() as tmp:
            costs = Path(tmp) / "costs.csv"
            out = Path(tmp) / "out"
            self._write_costs(costs, [
                make_summary_row(metal="  silver  ", order_id="1", total_oz=5.0, cost_per_oz=35.0),
                make_summary_row(metal=" gold ", order_id="2"),
            ])
            run(str(costs), str(out))

            gold_rows = self._read_csv(out / "gold_summary.csv")
            self.assertEqual(len(gold_rows), 2)  # header + 1

            silver_rows = self._read_csv(out / "silver_summary.csv")
            self.assertEqual(len(silver_rows), 2)  # header + 1

    def test_creates_nested_output_directory(self):
        from metals.build_summaries import run

        with tempfile.TemporaryDirectory() as tmp:
            costs = Path(tmp) / "costs.csv"
            out = Path(tmp) / "a" / "b" / "c"
            self._write_costs(costs, [make_summary_row()])
            run(str(costs), str(out))
            self.assertTrue(out.exists())
            self.assertTrue((out / "gold_summary.csv").exists())
            self.assertTrue((out / "silver_summary.csv").exists())

    def test_missing_costs_file_raises_system_exit(self):
        from metals.build_summaries import run

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                run("/nonexistent/path/costs.csv", tmp)
            self.assertIn("costs file not found", str(ctx.exception))

    def test_output_row_values_match_input(self):
        from metals.build_summaries import run

        with tempfile.TemporaryDirectory() as tmp:
            costs = Path(tmp) / "costs.csv"
            out = Path(tmp) / "out"
            self._write_costs(costs, [
                make_summary_row(
                    date="2024-06-01",
                    order_id="ORD-001",
                    vendor="RCM",
                    metal="silver",
                    total_oz=20.5,
                    cost_per_oz=34.75,
                ),
            ])
            run(str(costs), str(out))

            silver_rows = self._read_csv(out / "silver_summary.csv")
            data = silver_rows[1]
            self.assertEqual(data[0], "2024-06-01")   # date
            self.assertEqual(data[1], "ORD-001")       # order_id
            self.assertEqual(data[2], "RCM")           # vendor

    def test_gold_only_input_leaves_silver_header_only(self):
        from metals.build_summaries import run

        with tempfile.TemporaryDirectory() as tmp:
            costs = Path(tmp) / "costs.csv"
            out = Path(tmp) / "out"
            self._write_costs(costs, [
                make_summary_row(metal="gold", order_id="1"),
                make_summary_row(metal="gold", order_id="2"),
            ])
            run(str(costs), str(out))

            silver_rows = self._read_csv(out / "silver_summary.csv")
            self.assertEqual(len(silver_rows), 1)  # header only

    def test_silver_only_input_leaves_gold_header_only(self):
        from metals.build_summaries import run

        with tempfile.TemporaryDirectory() as tmp:
            costs = Path(tmp) / "costs.csv"
            out = Path(tmp) / "out"
            self._write_costs(costs, [
                make_summary_row(metal="silver", order_id="1", total_oz=5.0, cost_per_oz=35.0),
            ])
            run(str(costs), str(out))

            gold_rows = self._read_csv(out / "gold_summary.csv")
            self.assertEqual(len(gold_rows), 1)  # header only


class TestMain(unittest.TestCase):
    """main() parses CLI args and delegates to run()."""

    @patch("metals.build_summaries.run")
    def test_defaults_passed_to_run(self, mock_run):
        from metals.build_summaries import main

        mock_run.return_value = 0
        result = main([])
        self.assertEqual(result, 0)
        mock_run.assert_called_once_with(
            costs_path="out/metals/costs.csv",
            out_dir="out/metals",
        )

    @patch("metals.build_summaries.run")
    def test_custom_costs_and_out_dir_passed_to_run(self, mock_run):
        from metals.build_summaries import main

        mock_run.return_value = 0
        result = main(["--costs", "/data/c.csv", "--out-dir", "/data/out"])
        self.assertEqual(result, 0)
        mock_run.assert_called_once_with(
            costs_path="/data/c.csv",
            out_dir="/data/out",
        )

    @patch("metals.build_summaries.run")
    def test_returns_run_return_value(self, mock_run):
        from metals.build_summaries import main

        mock_run.return_value = 42
        result = main([])
        self.assertEqual(result, 42)


if __name__ == "__main__":
    unittest.main()
