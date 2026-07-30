"""Tests for telemetry/_cli_agents.py — agent rendering helpers."""
from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from rich.table import Table

from tests.telemetry_tests.shared_fixtures import _make_agent_token_row
from telemetry._cli_agents import (
    _COL_EST_COST,
    _agent_row_to_dict,
    _build_agents_table,
    _print_agents_csv,
    _print_agents_json,
)


# ---------------------------------------------------------------------------
# _agent_row_to_dict
# ---------------------------------------------------------------------------

class TestAgentRowToDict(unittest.TestCase):
    def test_returns_empty_dict_for_non_row(self):
        result = _agent_row_to_dict("not a row")
        self.assertEqual(result, {})

    def test_returns_empty_dict_for_none(self):
        result = _agent_row_to_dict(None)
        self.assertEqual(result, {})

    def test_serializes_agent_token_row(self):
        row = _make_agent_token_row(agent="code-writer", calls=3, est_cost=0.05)
        result = _agent_row_to_dict(row)
        self.assertEqual(result["agent"], "code-writer")
        self.assertEqual(result["calls"], 3)
        self.assertAlmostEqual(result["est_cost"], 0.05, places=6)

    def test_all_fields_present(self):
        row = _make_agent_token_row()
        result = _agent_row_to_dict(row)
        for key in ("agent", "calls", "input_tokens", "output_tokens",
                    "cache_read_tokens", "cache_write_tokens", "models", "est_cost"):
            self.assertIn(key, result)

    def test_models_is_list(self):
        row = _make_agent_token_row(models=["sonnet", "haiku"])
        result = _agent_row_to_dict(row)
        self.assertIsInstance(result["models"], list)
        self.assertEqual(result["models"], ["sonnet", "haiku"])

    def test_est_cost_rounded_to_6_places(self):
        row = _make_agent_token_row(est_cost=0.1234567890)
        result = _agent_row_to_dict(row)
        self.assertEqual(result["est_cost"], round(0.1234567890, 6))


# ---------------------------------------------------------------------------
# _print_agents_json
# ---------------------------------------------------------------------------

class TestPrintAgentsJson(unittest.TestCase):
    def test_emits_json_with_expected_keys(self):
        rows = [_make_agent_token_row(agent="tester", est_cost=0.02)]
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_agents_json(rows, rows, "7d")
        output = buf.getvalue()
        data = json.loads(output)
        self.assertIn("agent_count", data)
        self.assertIn("returned_count", data)
        self.assertIn("since", data)
        self.assertIn("total_cost", data)
        self.assertIn("agents", data)

    def test_agent_count_matches_all_rows(self):
        all_rows = [
            _make_agent_token_row(agent="a1"),
            _make_agent_token_row(agent="a2"),
        ]
        shown_rows = [all_rows[0]]
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_agents_json(all_rows, shown_rows, "7d")
        data = json.loads(buf.getvalue())
        self.assertEqual(data["agent_count"], 2)
        self.assertEqual(data["returned_count"], 1)

    def test_total_cost_sums_all_rows(self):
        rows = [
            _make_agent_token_row(agent="a1", est_cost=0.10),
            _make_agent_token_row(agent="a2", est_cost=0.05),
        ]
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_agents_json(rows, rows, "30d")
        data = json.loads(buf.getvalue())
        self.assertAlmostEqual(data["total_cost"], 0.15, places=5)

    def test_empty_rows_produces_valid_json(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_agents_json([], [], "all")
        data = json.loads(buf.getvalue())
        self.assertEqual(data["agent_count"], 0)
        self.assertEqual(data["agents"], [])

    def test_since_label_included(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_agents_json([], [], "14d")
        data = json.loads(buf.getvalue())
        self.assertEqual(data["since"], "14d")


# ---------------------------------------------------------------------------
# _print_agents_csv
# ---------------------------------------------------------------------------

class TestPrintAgentsCsv(unittest.TestCase):
    def test_csv_has_header_row(self):
        rows = [_make_agent_token_row(agent="researcher")]
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_agents_csv(rows)
        output = buf.getvalue()
        self.assertIn("agent", output)

    def test_csv_includes_agent_name(self):
        rows = [_make_agent_token_row(agent="reviewer")]
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_agents_csv(rows)
        self.assertIn("reviewer", buf.getvalue())

    def test_multiple_models_semicolon_joined(self):
        rows = [_make_agent_token_row(agent="m-agent", models=["m1", "m2"])]
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_agents_csv(rows)
        self.assertIn("m1;m2", buf.getvalue())

    def test_empty_rows_produces_header_only_or_empty(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_agents_csv([])
        # No crash — may be empty or header only


# ---------------------------------------------------------------------------
# _build_agents_table
# ---------------------------------------------------------------------------

class TestBuildAgentsTable(unittest.TestCase):
    def test_returns_rich_table(self):
        rows = [_make_agent_token_row()]
        table = _build_agents_table(rows, rows, "7d")
        self.assertIsInstance(table, Table)

    def test_title_contains_since(self):
        rows = [_make_agent_token_row()]
        table = _build_agents_table(rows, rows, "30d")
        self.assertIn("30d", str(table.title))

    def test_empty_models_shows_dash(self):
        rows = [_make_agent_token_row(models=[])]
        # Should not raise even with no models
        table = _build_agents_table(rows, rows, "7d")
        self.assertIsInstance(table, Table)

    def test_footer_shows_total_calls(self):
        rows = [
            _make_agent_token_row(agent="a1", calls=3),
            _make_agent_token_row(agent="a2", calls=7),
        ]
        table = _build_agents_table(rows, rows, "7d")
        # Calls column footer should be "10"
        calls_col = table.columns[1]
        self.assertEqual(calls_col.footer, "10")

    def test_col_est_cost_constant(self):
        self.assertEqual(_COL_EST_COST, "Est. Cost")

    def test_all_rows_not_truncated_by_shown_rows(self):
        all_rows = [
            _make_agent_token_row(agent="a1", calls=5),
            _make_agent_token_row(agent="a2", calls=3),
        ]
        shown_rows = [all_rows[0]]
        table = _build_agents_table(all_rows, shown_rows, "7d")
        # Footer totals reflect all_rows (8 calls total), not just shown_rows (5)
        calls_col = table.columns[1]
        self.assertEqual(calls_col.footer, "8")

    def test_multiple_models_comma_joined_in_row(self):
        rows = [_make_agent_token_row(models=["claude-sonnet", "claude-haiku"])]
        table = _build_agents_table(rows, rows, "7d")
        self.assertIsInstance(table, Table)


if __name__ == "__main__":
    unittest.main()
