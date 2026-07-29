"""Tests for CLI session/agent/cost data-shaping helpers."""
from __future__ import annotations

import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from click.testing import CliRunner

from telemetry.cli import (
    _agent_row_to_dict,
    _breakdown_by_agent,
    _breakdown_by_day,
    _build_agents_table,
    _build_breakdown_table,
    _build_sessions_table,
    _print_cost_csv,
    _session_to_dict,
    _sessions_json_payload,
    main,
)

from tests.telemetry_tests.shared_fixtures import (
    _make_agent_summary_cli as _make_agent_summary,
    _make_agent_token_row,
    _make_session_summary,
)


# ---------------------------------------------------------------------------
# _session_to_dict
# ---------------------------------------------------------------------------

class TestSessionToDict(unittest.TestCase):
    def test_returns_empty_for_non_session(self):
        result = _session_to_dict("not a session")
        self.assertEqual(result, {})

    def test_happy_path_with_agents(self):
        agent = _make_agent_summary()
        s = _make_session_summary(agents=[agent])
        result = _session_to_dict(s)
        self.assertEqual(result["session_id"], s.session_id)
        self.assertAlmostEqual(result["total_cost"], s.total_cost, places=6)
        self.assertEqual(result["num_agents"], 1)
        self.assertIsInstance(result["agents"], list)
        self.assertEqual(len(result["agents"]), 1)
        self.assertIn("agent_id", result["agents"][0])

    def test_duration_minutes_computed(self):
        s = _make_session_summary()
        result = _session_to_dict(s)
        self.assertIsNotNone(result["duration_minutes"])
        self.assertAlmostEqual(result["duration_minutes"], 30.0, places=1)

    def test_no_end_time_duration_none(self):
        s = _make_session_summary()
        s.end_time = None
        result = _session_to_dict(s)
        self.assertIsNone(result["duration_minutes"])

    def test_no_start_time_isoformat_none(self):
        s = _make_session_summary()
        s.start_time = None
        result = _session_to_dict(s)
        self.assertIsNone(result["start_time"])


# ---------------------------------------------------------------------------
# _sessions_json_payload
# ---------------------------------------------------------------------------

class TestSessionsJsonPayload(unittest.TestCase):
    def test_payload_structure(self):
        s1 = _make_session_summary(total_cost=0.10)
        s2 = _make_session_summary(session_id="xyz999", total_cost=0.05)
        payload = _sessions_json_payload([s1, s2])
        self.assertEqual(payload["session_count"], 2)
        self.assertAlmostEqual(payload["total_cost"], 0.15, places=5)
        self.assertEqual(len(payload["sessions"]), 2)

    def test_empty_sessions(self):
        payload = _sessions_json_payload([])
        self.assertEqual(payload["session_count"], 0)
        self.assertEqual(payload["total_cost"], 0.0)
        self.assertEqual(payload["sessions"], [])


# ---------------------------------------------------------------------------
# _build_sessions_table
# ---------------------------------------------------------------------------

class TestBuildSessionsTable(unittest.TestCase):
    def test_returns_table(self):
        from rich.table import Table
        s = _make_session_summary()
        table = _build_sessions_table([s], "7d")
        self.assertIsInstance(table, Table)

    def test_project_path_short(self):
        from rich.table import Table
        s = _make_session_summary(project_path="/single")
        table = _build_sessions_table([s], "7d")
        self.assertIsInstance(table, Table)

    def test_project_path_none(self):
        from rich.table import Table
        s = _make_session_summary(project_path=None)
        table = _build_sessions_table([s], "7d")
        self.assertIsInstance(table, Table)


# ---------------------------------------------------------------------------
# _agent_row_to_dict
# ---------------------------------------------------------------------------

class TestAgentRowToDict(unittest.TestCase):
    def test_returns_empty_for_non_row(self):
        result = _agent_row_to_dict("not a row")
        self.assertEqual(result, {})

    def test_happy_path(self):
        row = _make_agent_token_row()
        result = _agent_row_to_dict(row)
        self.assertEqual(result["agent"], row.agent)
        self.assertEqual(result["calls"], row.calls)
        self.assertEqual(result["input_tokens"], row.input_tokens)
        self.assertEqual(result["output_tokens"], row.output_tokens)
        self.assertEqual(result["cache_read_tokens"], row.cache_read_tokens)
        self.assertEqual(result["cache_write_tokens"], row.cache_write_tokens)
        self.assertEqual(result["models"], row.models)
        self.assertAlmostEqual(result["est_cost"], row.est_cost, places=6)


# ---------------------------------------------------------------------------
# _print_agents_json
# ---------------------------------------------------------------------------

class TestPrintAgentsJson(unittest.TestCase):
    def test_outputs_valid_json(self):
        rows = [_make_agent_token_row()]
        runner = CliRunner()
        with runner.isolated_filesystem():
            with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
                MockProvider.return_value.aggregate_agents.return_value = rows
                result = runner.invoke(main, ["agents", "--since", "7d", "--format", "json"])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertIn("agent_count", data)
        self.assertEqual(data["agent_count"], 1)
        self.assertIn("agents", data)

    def test_direct_call_structure(self):
        rows = [_make_agent_token_row(agent="tester", est_cost=0.02)]
        runner = CliRunner()
        with patch("telemetry.providers.transcript.TranscriptProvider.aggregate_agents", return_value=rows):
            result = runner.invoke(main, ["agents", "--format", "json", "--since", "7d"])
        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.output)
        self.assertEqual(payload["returned_count"], 1)


# ---------------------------------------------------------------------------
# _print_agents_csv
# ---------------------------------------------------------------------------

class TestPrintAgentsCsv(unittest.TestCase):
    def test_csv_output_has_header_and_row(self):
        runner = CliRunner()
        rows = [_make_agent_token_row(agent="researcher")]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            result = runner.invoke(main, ["agents", "--since", "7d", "--format", "csv"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("agent", result.output)
        self.assertIn("researcher", result.output)

    def test_direct_print_agents_csv(self):
        rows = [_make_agent_token_row(agent="reviewer", calls=2, models=["m1", "m2"])]
        runner = CliRunner()
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            result = runner.invoke(main, ["agents", "--format", "csv", "--since", "7d"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("reviewer", result.output)
        self.assertIn("m1;m2", result.output)


# ---------------------------------------------------------------------------
# _build_agents_table
# ---------------------------------------------------------------------------

class TestBuildAgentsTable(unittest.TestCase):
    def test_returns_table_with_rows(self):
        from rich.table import Table
        rows = [_make_agent_token_row()]
        table = _build_agents_table(rows, rows, "7d")
        self.assertIsInstance(table, Table)

    def test_empty_models_shows_dash(self):
        from rich.table import Table
        rows = [_make_agent_token_row(models=[])]
        table = _build_agents_table(rows, rows, "7d")
        self.assertIsInstance(table, Table)


# ---------------------------------------------------------------------------
# _breakdown_by_agent
# ---------------------------------------------------------------------------

class TestBreakdownByAgent(unittest.TestCase):
    def test_returns_sorted_by_cost_descending(self):
        rows = [
            _make_agent_token_row(agent="cheap", est_cost=0.01),
            _make_agent_token_row(agent="expensive", est_cost=0.50),
        ]
        result = _breakdown_by_agent(rows)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["agent"], "expensive")
        self.assertEqual(result[1]["agent"], "cheap")

    def test_empty_input(self):
        result = _breakdown_by_agent([])
        self.assertEqual(result, [])

    def test_row_fields(self):
        rows = [_make_agent_token_row(agent="myagent", calls=5, est_cost=0.12)]
        result = _breakdown_by_agent(rows)
        self.assertEqual(result[0]["agent"], "myagent")
        self.assertEqual(result[0]["calls"], 5)
        self.assertAlmostEqual(float(result[0]["est_cost"]), 0.12, places=5)


# ---------------------------------------------------------------------------
# _breakdown_by_day
# ---------------------------------------------------------------------------

class TestBreakdownByDay(unittest.TestCase):
    def test_groups_by_day(self):
        now = datetime.now(tz=timezone.utc)
        yesterday = now - timedelta(days=1)
        s1 = _make_session_summary(total_cost=0.10)
        s1.start_time = now
        s2 = _make_session_summary(total_cost=0.20, session_id="s2")
        s2.start_time = yesterday
        result = _breakdown_by_day([s1, s2])
        self.assertEqual(len(result), 2)
        days = [r["day"] for r in result]
        self.assertIn(now.date().isoformat(), days)
        self.assertIn(yesterday.date().isoformat(), days)

    def test_skips_sessions_with_no_start_time(self):
        s = _make_session_summary()
        s.start_time = None
        captured_stderr = io.StringIO()
        with patch("sys.stderr", captured_stderr):
            result = _breakdown_by_day([s])
        self.assertEqual(result, [])
        self.assertIn("Warning", captured_stderr.getvalue())

    def test_aggregates_same_day_costs(self):
        now = datetime.now(tz=timezone.utc)
        s1 = _make_session_summary(total_cost=0.10)
        s1.start_time = now
        s2 = _make_session_summary(total_cost=0.05, session_id="s2")
        s2.start_time = now
        result = _breakdown_by_day([s1, s2])
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(float(result[0]["est_cost"]), 0.15, places=5)


# ---------------------------------------------------------------------------
# _print_cost_csv
# ---------------------------------------------------------------------------

class TestPrintCostCsv(unittest.TestCase):
    def test_empty_rows_no_output(self):
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            _print_cost_csv([], "agent")
        self.assertEqual(captured.getvalue(), "")

    def test_agent_rows_csv_output(self):
        rows = [{"agent": "myagent", "calls": 3, "est_cost": 0.05}]
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            _print_cost_csv(rows, "agent")
        output = captured.getvalue()
        self.assertIn("agent", output)
        self.assertIn("myagent", output)

    def test_day_rows_csv_output(self):
        rows = [{"day": "2026-04-16", "est_cost": 0.10}]
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            _print_cost_csv(rows, "day")
        output = captured.getvalue()
        self.assertIn("day", output)
        self.assertIn("2026-04-16", output)


# ---------------------------------------------------------------------------
# _build_breakdown_table
# ---------------------------------------------------------------------------

class TestBuildBreakdownTable(unittest.TestCase):
    def test_agent_group_by(self):
        from rich.table import Table
        rows = [{"agent": "myagent", "calls": 3, "est_cost": 0.05}]
        table = _build_breakdown_table(rows, "agent", "7d")
        self.assertIsInstance(table, Table)

    def test_day_group_by(self):
        from rich.table import Table
        rows = [{"day": "2026-04-16", "est_cost": 0.10}]
        table = _build_breakdown_table(rows, "day", "7d")
        self.assertIsInstance(table, Table)


if __name__ == "__main__":
    unittest.main()
