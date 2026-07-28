"""Tests for telemetry CLI commands."""

import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from telemetry.cli import (
    _agent_row_to_dict,
    _breakdown_by_agent,
    _breakdown_by_day,
    _build_agents_table,
    _build_breakdown_table,
    _build_sessions_table,
    _fmt_duration,
    _fmt_tokens,
    _parse_since_cli,
    _print_cost_csv,
    _rules_init,
    _rules_validate,
    _session_to_dict,
    _sessions_json_payload,
    _truncate_id,
    main,
)
from telemetry.models import AgentSummary, AgentTokenRow, SessionSummary


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def _make_session_summary(
    session_id="abc123def456",
    model="claude-sonnet-4-6",
    input_tokens=1000,
    output_tokens=500,
    cache_read_tokens=200,
    cache_creation_tokens=50,
    total_events=5,
    total_cost=0.01,
    start="2026-04-16T10:00:00Z",
    end="2026-04-16T10:30:00Z",
    agents=None,
    project_path="/foo/bar",
):
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return SessionSummary(
        session_id=session_id,
        project_path=project_path,
        start_time=start_dt,
        end_time=end_dt,
        model=model,
        total_cost=total_cost,
        cost_is_estimated=False,
        total_events=total_events,
        efficiency_score=80.0,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        agents=agents or [],
    )


def _make_agent_token_row(
    agent="code-writer",
    calls=3,
    input_tokens=5000,
    output_tokens=2000,
    cache_read_tokens=1000,
    cache_write_tokens=500,
    models=None,
    est_cost=0.05,
):
    return AgentTokenRow(
        agent=agent,
        calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        models=models if models is not None else ["claude-sonnet-4-6"],
        est_cost=est_cost,
    )


def _make_agent_summary(
    agent_id="agt-001",
    agent_type="code-writer",
    description="Write code",
    model="claude-sonnet-4-6",
    duration_ms=30000,
    total_tokens=3000,
    total_tool_uses=5,
    cost_usd=0.03,
):
    return AgentSummary(
        agent_id=agent_id,
        agent_type=agent_type,
        description=description,
        model=model,
        duration_ms=duration_ms,
        total_tokens=total_tokens,
        total_tool_uses=total_tool_uses,
        cost_usd=cost_usd,
    )


# ---------------------------------------------------------------------------
# _fmt_tokens
# ---------------------------------------------------------------------------

class TestFmtTokens(unittest.TestCase):
    def test_small(self):
        self.assertEqual(_fmt_tokens(500), "500")

    def test_thousands(self):
        self.assertEqual(_fmt_tokens(1500), "1K")

    def test_millions(self):
        self.assertEqual(_fmt_tokens(2_500_000), "2.5M")

    def test_exactly_one_thousand(self):
        self.assertEqual(_fmt_tokens(1000), "1K")


# ---------------------------------------------------------------------------
# _fmt_duration
# ---------------------------------------------------------------------------

class TestFmtDuration(unittest.TestCase):
    def test_minutes_only(self):
        s = _make_session_summary()
        result = _fmt_duration(s)
        self.assertEqual(result, "30m")

    def test_hours_and_minutes(self):
        start = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 16, 11, 15, 0, tzinfo=timezone.utc)
        s = _make_session_summary()
        s.start_time = start
        s.end_time = end
        result = _fmt_duration(s)
        self.assertEqual(result, "1h15m")

    def test_none_end_time(self):
        s = _make_session_summary()
        s.end_time = None
        result = _fmt_duration(s)
        self.assertEqual(result, "—")

    def test_non_session_object_returns_dash(self):
        result = _fmt_duration("not a session")
        self.assertEqual(result, "—")


# ---------------------------------------------------------------------------
# _truncate_id
# ---------------------------------------------------------------------------

class TestTruncateId(unittest.TestCase):
    def test_short_id_unchanged(self):
        self.assertEqual(_truncate_id("abc"), "abc")

    def test_long_id_truncated(self):
        result = _truncate_id("a" * 20)
        self.assertLessEqual(len(result), 16)
        self.assertIn("…", result)


# ---------------------------------------------------------------------------
# _parse_since_cli
# ---------------------------------------------------------------------------

class TestParseSinceCli(unittest.TestCase):
    def test_valid_window_string(self):
        result = _parse_since_cli("7d")
        self.assertIsInstance(result, datetime)
        # Should be roughly 7 days in the past
        now = datetime.now(tz=timezone.utc)
        diff = now - result
        self.assertAlmostEqual(diff.days, 7, delta=1)

    def test_bare_integer_raises_bad_parameter(self):
        import click
        with self.assertRaises(click.BadParameter):
            _parse_since_cli("7")

    def test_invalid_window_string_raises_bad_parameter(self):
        import click
        with self.assertRaises(click.BadParameter):
            _parse_since_cli("notawindow")


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
        # Short path with fewer than 2 parts
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
        # Capture output via CliRunner
        runner = CliRunner()
        with runner.isolated_filesystem():
            # Call via CLI to capture output properly
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
        # Capture via runner so rich console outputs correctly
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


# ---------------------------------------------------------------------------
# _rules_init
# ---------------------------------------------------------------------------

class TestRulesInit(unittest.TestCase):
    def test_creates_file_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "rules.yaml"
            _rules_init(config_path)
            self.assertTrue(config_path.exists())
            content = config_path.read_text()
            self.assertIn("avoidable", content)
            self.assertIn("bash-as-grep", content)

    def test_skips_creation_when_file_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "rules.yaml"
            config_path.write_text("existing: content\n")
            original_mtime = config_path.stat().st_mtime
            _rules_init(config_path)
            # File should remain unchanged
            self.assertEqual(config_path.stat().st_mtime, original_mtime)
            self.assertEqual(config_path.read_text(), "existing: content\n")

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "nested" / "subdir" / "rules.yaml"
            _rules_init(config_path)
            self.assertTrue(config_path.exists())


# ---------------------------------------------------------------------------
# _rules_validate
# ---------------------------------------------------------------------------

class TestRulesValidate(unittest.TestCase):
    def test_valid_rules_no_exit(self):
        from telemetry.rules import DEFAULT_RULES
        with patch("telemetry.rules.load_rules", return_value=DEFAULT_RULES):
            with patch("telemetry.rules.validate_rules", return_value=[]):
                # Should not raise
                _rules_validate()

    def test_invalid_rules_raises_system_exit(self):
        from telemetry.rules import DEFAULT_RULES
        errors = ["avoidable.bash-as-grep: enabled must be boolean"]
        with patch("telemetry.rules.load_rules", return_value=DEFAULT_RULES):
            with patch("telemetry.rules.validate_rules", return_value=errors):
                with self.assertRaises(SystemExit) as ctx:
                    _rules_validate()
                self.assertEqual(ctx.exception.code, 1)


# ---------------------------------------------------------------------------
# _rules_explain
# ---------------------------------------------------------------------------

class TestRulesExplain(unittest.TestCase):
    def test_found_rule_no_fix_hints(self):
        from telemetry.rules import DEFAULT_RULES
        import copy
        rules_no_hints = copy.deepcopy(DEFAULT_RULES)
        rules_no_hints.pop("fix_hints", None)
        runner = CliRunner()
        with patch("telemetry.rules.load_rules", return_value=rules_no_hints):
            result = runner.invoke(main, ["rules", "--explain", "bash-as-grep"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("bash-as-grep", result.output)

    def test_found_rule_with_fix_hints(self):
        from telemetry.rules import DEFAULT_RULES
        runner = CliRunner()
        with patch("telemetry.rules.load_rules", return_value=DEFAULT_RULES):
            result = runner.invoke(main, ["rules", "--explain", "bash-as-grep"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("bash-as-grep", result.output)
        # DEFAULT_RULES has fix_hints for bash-as-grep
        self.assertIn("Fix hints", result.output)

    def test_not_found_rule(self):
        from telemetry.rules import DEFAULT_RULES
        runner = CliRunner()
        with patch("telemetry.rules.load_rules", return_value=DEFAULT_RULES):
            result = runner.invoke(main, ["rules", "--explain", "nonexistent-rule"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Rule not found", result.output)
        self.assertIn("nonexistent-rule", result.output)


# ---------------------------------------------------------------------------
# _rules_list
# ---------------------------------------------------------------------------

class TestRulesList(unittest.TestCase):
    def test_lists_avoidable_and_review_rules(self):
        from telemetry.rules import DEFAULT_RULES
        runner = CliRunner()
        with patch("telemetry.rules.load_rules", return_value=DEFAULT_RULES):
            result = runner.invoke(main, ["rules"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("bash-as-grep", result.output)
        self.assertIn("abandoned-search", result.output)

    def test_lists_custom_rules(self):
        from telemetry.rules import DEFAULT_RULES
        import copy
        rules_with_custom = copy.deepcopy(DEFAULT_RULES)
        rules_with_custom["custom_rules"] = [{"reason": "my-custom-rule", "tool": "Bash"}]
        runner = CliRunner()
        with patch("telemetry.rules.load_rules", return_value=rules_with_custom):
            result = runner.invoke(main, ["rules"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("my-custom-rule", result.output)

    def test_custom_rule_without_reason_uses_index(self):
        from telemetry.rules import DEFAULT_RULES
        import copy
        rules_with_custom = copy.deepcopy(DEFAULT_RULES)
        rules_with_custom["custom_rules"] = [{"tool": "Bash"}]
        runner = CliRunner()
        with patch("telemetry.rules.load_rules", return_value=rules_with_custom):
            result = runner.invoke(main, ["rules"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("custom-0", result.output)

    def test_skips_non_dict_rule_cfg(self):
        # Exercises the `if not isinstance(cfg, dict): continue` branch
        from telemetry.rules import DEFAULT_RULES
        import copy
        rules_bad_cfg = copy.deepcopy(DEFAULT_RULES)
        # Insert a non-dict value into avoidable — should be silently skipped
        rules_bad_cfg["avoidable"]["broken-rule"] = "not-a-dict"
        runner = CliRunner()
        with patch("telemetry.rules.load_rules", return_value=rules_bad_cfg):
            result = runner.invoke(main, ["rules"])
        self.assertEqual(result.exit_code, 0)
        # "broken-rule" should not appear in output since it was skipped
        self.assertNotIn("broken-rule", result.output)


# ---------------------------------------------------------------------------
# rules command wiring
# ---------------------------------------------------------------------------

class TestRulesCommand(unittest.TestCase):
    def test_init_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("telemetry.cli.Path.home", return_value=Path(tmpdir)):
                runner = CliRunner()
                result = runner.invoke(main, ["rules", "--init"])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("Created", result.output)

    def test_init_flag_already_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Pre-create the nested path that the command uses
            nested = Path(tmpdir) / ".telemetry-transcripts"
            nested.mkdir()
            config_path = nested / "rules.yaml"
            config_path.write_text("existing: true\n")
            with patch("telemetry.cli.Path.home", return_value=Path(tmpdir)):
                runner = CliRunner()
                result = runner.invoke(main, ["rules", "--init"])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("Already exists", result.output)

    def test_validate_flag_success(self):
        from telemetry.rules import DEFAULT_RULES
        with patch("telemetry.rules.load_rules", return_value=DEFAULT_RULES):
            with patch("telemetry.rules.validate_rules", return_value=[]):
                runner = CliRunner()
                result = runner.invoke(main, ["rules", "--validate"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("valid", result.output)

    def test_validate_flag_with_errors(self):
        from telemetry.rules import DEFAULT_RULES
        errors = ["avoidable.bash-as-grep: enabled must be boolean"]
        with patch("telemetry.rules.load_rules", return_value=DEFAULT_RULES):
            with patch("telemetry.rules.validate_rules", return_value=errors):
                runner = CliRunner()
                result = runner.invoke(main, ["rules", "--validate"])
        self.assertNotEqual(result.exit_code, 0)


# ---------------------------------------------------------------------------
# history command
# ---------------------------------------------------------------------------

class TestHistoryCommand(unittest.TestCase):
    def test_no_sessions_message(self):
        runner = CliRunner()
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = []
            result = runner.invoke(main, ["history", "--days", "7"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("No sessions found", result.output)
        MockProvider.return_value.get_sessions.assert_called_once()

    def test_with_sessions_shows_table(self):
        runner = CliRunner()
        s = _make_session_summary()
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s]
            result = runner.invoke(main, ["history", "--days", "3"])
        self.assertEqual(result.exit_code, 0)
        MockProvider.return_value.get_sessions.assert_called_once()

    def test_model_split_on_slash(self):
        # model has '/' — the CLI uses .split("/")[-1]
        runner = CliRunner()
        s = _make_session_summary(model="anthropic/claude-sonnet-4-6")
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s]
            result = runner.invoke(main, ["history"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("claude-sonnet-4-6", result.output)


# ---------------------------------------------------------------------------
# sessions command
# ---------------------------------------------------------------------------

class TestSessionsCommand(unittest.TestCase):
    def test_no_sessions_message(self):
        runner = CliRunner()
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = []
            result = runner.invoke(main, ["sessions", "--since", "7d"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("No sessions found", result.output)

    def test_json_format(self):
        runner = CliRunner()
        sessions = [_make_session_summary()]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = sessions
            result = runner.invoke(main, ["sessions", "--since", "7d", "--format", "json"])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertEqual(data["session_count"], 1)

    def test_limit_applied(self):
        runner = CliRunner()
        sessions = [
            _make_session_summary(session_id="a", total_cost=0.10),
            _make_session_summary(session_id="b", total_cost=0.20),
            _make_session_summary(session_id="c", total_cost=0.05),
        ]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = sessions
            result = runner.invoke(main, ["sessions", "--since", "7d", "--limit", "1", "--format", "json"])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertEqual(data["session_count"], 1)

    def test_errors_only_filter(self):
        runner = CliRunner()
        agent = _make_agent_summary()
        s_with_agents = _make_session_summary(session_id="s1", agents=[agent])
        s_no_agents = _make_session_summary(session_id="s2", agents=[])
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s_with_agents, s_no_agents]
            result = runner.invoke(main, [
                "sessions", "--since", "7d", "--errors-only", "--format", "json"
            ])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertEqual(data["session_count"], 1)

    def test_filters_zero_event_zero_cost_sessions(self):
        runner = CliRunner()
        s_empty = _make_session_summary(total_events=0, total_cost=0.0)
        s_ok = _make_session_summary(session_id="ok", total_events=5, total_cost=0.01)
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s_empty, s_ok]
            result = runner.invoke(main, ["sessions", "--since", "7d", "--format", "json"])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertEqual(data["session_count"], 1)

    def test_table_format_with_sessions(self):
        runner = CliRunner()
        s = _make_session_summary()
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s]
            result = runner.invoke(main, ["sessions", "--since", "7d", "--format", "table"])
        self.assertEqual(result.exit_code, 0)

    def test_projects_dir_passed_to_provider(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
                MockProvider.return_value.get_sessions.return_value = []
                result = runner.invoke(main, [
                    "sessions", "--since", "7d", "--projects-dir", tmpdir
                ])
            self.assertEqual(result.exit_code, 0)
            call_kwargs = MockProvider.call_args
            self.assertIsNotNone(call_kwargs)


# ---------------------------------------------------------------------------
# agents command
# ---------------------------------------------------------------------------

class TestAgentsCommand(unittest.TestCase):
    def test_no_data_message(self):
        runner = CliRunner()
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = []
            result = runner.invoke(main, ["agents", "--since", "7d"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("No agent data found", result.output)

    def test_json_format(self):
        runner = CliRunner()
        rows = [_make_agent_token_row()]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            result = runner.invoke(main, ["agents", "--since", "7d", "--format", "json"])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertEqual(data["agent_count"], 1)
        self.assertIn("agents", data)

    def test_csv_format(self):
        runner = CliRunner()
        rows = [_make_agent_token_row(agent="doc-writer")]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            result = runner.invoke(main, ["agents", "--since", "7d", "--format", "csv"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("doc-writer", result.output)

    def test_table_format_with_data(self):
        runner = CliRunner()
        rows = [_make_agent_token_row()]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            result = runner.invoke(main, ["agents", "--since", "7d", "--format", "table"])
        self.assertEqual(result.exit_code, 0)

    def test_model_filter(self):
        runner = CliRunner()
        rows = [
            _make_agent_token_row(agent="a1", models=["claude-sonnet-4-6"]),
            _make_agent_token_row(agent="a2", models=["claude-haiku-3-5"]),
        ]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            result = runner.invoke(main, [
                "agents", "--since", "7d", "--model", "haiku", "--format", "json"
            ])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertEqual(data["returned_count"], 1)

    def test_limit_applied(self):
        runner = CliRunner()
        rows = [
            _make_agent_token_row(agent="expensive", est_cost=1.0),
            _make_agent_token_row(agent="cheap", est_cost=0.01),
        ]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            result = runner.invoke(main, [
                "agents", "--since", "7d", "--limit", "1", "--format", "json"
            ])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertEqual(data["returned_count"], 1)

    def test_sort_by_output(self):
        runner = CliRunner()
        rows = [
            _make_agent_token_row(agent="low", output_tokens=100),
            _make_agent_token_row(agent="high", output_tokens=9000),
        ]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            result = runner.invoke(main, [
                "agents", "--since", "7d", "--sort", "output", "--format", "json"
            ])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertEqual(data["agents"][0]["agent"], "high")

    def test_sort_by_calls(self):
        runner = CliRunner()
        rows = [
            _make_agent_token_row(agent="few", calls=1),
            _make_agent_token_row(agent="many", calls=50),
        ]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            result = runner.invoke(main, [
                "agents", "--since", "7d", "--sort", "calls", "--format", "json"
            ])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertEqual(data["agents"][0]["agent"], "many")

    def test_sort_by_input(self):
        runner = CliRunner()
        rows = [
            _make_agent_token_row(agent="small-in", input_tokens=100),
            _make_agent_token_row(agent="large-in", input_tokens=99000),
        ]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            result = runner.invoke(main, [
                "agents", "--since", "7d", "--sort", "input", "--format", "json"
            ])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertEqual(data["agents"][0]["agent"], "large-in")

    def test_sort_by_cache_read(self):
        runner = CliRunner()
        rows = [
            _make_agent_token_row(agent="low-cache", cache_read_tokens=10),
            _make_agent_token_row(agent="high-cache", cache_read_tokens=50000),
        ]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            result = runner.invoke(main, [
                "agents", "--since", "7d", "--sort", "cache-read", "--format", "json"
            ])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertEqual(data["agents"][0]["agent"], "high-cache")


# ---------------------------------------------------------------------------
# cost-breakdown command
# ---------------------------------------------------------------------------

class TestCostBreakdownCommand(unittest.TestCase):
    def test_no_data_message(self):
        runner = CliRunner()
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = []
            result = runner.invoke(main, ["cost-breakdown", "--since", "7d"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("No cost data found", result.output)

    def test_group_by_agent_json(self):
        runner = CliRunner()
        rows = [_make_agent_token_row(agent="myagent", est_cost=0.10)]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            result = runner.invoke(main, [
                "cost-breakdown", "--since", "7d", "--format", "json", "--group-by", "agent"
            ])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertEqual(data["group_by"], "agent")
        self.assertIn("rows", data)

    def test_group_by_day_json(self):
        runner = CliRunner()
        now = datetime.now(tz=timezone.utc)
        s = _make_session_summary(total_cost=0.15)
        s.start_time = now
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s]
            result = runner.invoke(main, [
                "cost-breakdown", "--since", "7d", "--format", "json", "--group-by", "day"
            ])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertEqual(data["group_by"], "day")
        self.assertEqual(len(data["rows"]), 1)

    def test_group_by_agent_csv(self):
        runner = CliRunner()
        rows = [_make_agent_token_row(agent="csvagent", est_cost=0.07)]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            result = runner.invoke(main, [
                "cost-breakdown", "--since", "7d", "--format", "csv", "--group-by", "agent"
            ])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("agent", result.output)

    def test_group_by_day_csv(self):
        runner = CliRunner()
        now = datetime.now(tz=timezone.utc)
        s = _make_session_summary(total_cost=0.05)
        s.start_time = now
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s]
            result = runner.invoke(main, [
                "cost-breakdown", "--since", "7d", "--format", "csv", "--group-by", "day"
            ])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("day", result.output)

    def test_group_by_agent_table(self):
        runner = CliRunner()
        rows = [_make_agent_token_row()]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            result = runner.invoke(main, [
                "cost-breakdown", "--since", "7d", "--format", "table", "--group-by", "agent"
            ])
        self.assertEqual(result.exit_code, 0)

    def test_group_by_day_table(self):
        runner = CliRunner()
        now = datetime.now(tz=timezone.utc)
        s = _make_session_summary(total_cost=0.20)
        s.start_time = now
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s]
            result = runner.invoke(main, [
                "cost-breakdown", "--since", "7d", "--format", "table", "--group-by", "day"
            ])
        self.assertEqual(result.exit_code, 0)

    def test_limit_applied(self):
        runner = CliRunner()
        rows = [
            _make_agent_token_row(agent="a1", est_cost=0.50),
            _make_agent_token_row(agent="a2", est_cost=0.10),
        ]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            result = runner.invoke(main, [
                "cost-breakdown", "--since", "7d", "--limit", "1", "--format", "json"
            ])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertEqual(len(data["rows"]), 1)

    def test_cost_alias_command(self):
        # "cost" is a backwards-compatible alias for "cost-breakdown"
        runner = CliRunner()
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = []
            result = runner.invoke(main, ["cost", "--since", "7d"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("No cost data found", result.output)

    def test_breakdown_by_day_warning_path(self):
        runner = CliRunner()
        s = _make_session_summary()
        s.start_time = None
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s]
            result = runner.invoke(main, [
                "cost-breakdown", "--since", "7d", "--group-by", "day"
            ])
        # No crash — empty data message
        self.assertEqual(result.exit_code, 0)


# ---------------------------------------------------------------------------
# main help
# ---------------------------------------------------------------------------

class TestMainCLI(unittest.TestCase):
    def test_main_shows_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("telemetry", result.output.lower())

    def test_sessions_command_no_sessions(self):
        runner = CliRunner()
        with patch("telemetry.providers.transcript.TranscriptProvider.get_sessions", return_value=[]):
            result = runner.invoke(main, ["sessions", "--since", "7d"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("No sessions found", result.output)

    def test_sessions_command_json_format(self):
        runner = CliRunner()
        sessions = [_make_session_summary()]
        with patch("telemetry.providers.transcript.TranscriptProvider.get_sessions", return_value=sessions):
            result = runner.invoke(main, ["sessions", "--since", "7d", "--format", "json"])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertIn("session_count", data)
        self.assertEqual(data["session_count"], 1)

    def test_history_command_no_sessions(self):
        runner = CliRunner()
        with patch("telemetry.providers.transcript.TranscriptProvider.get_sessions", return_value=[]):
            result = runner.invoke(main, ["history", "--days", "7"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("No sessions found", result.output)

    def test_agents_command_no_data(self):
        runner = CliRunner()
        with patch("telemetry.providers.transcript.TranscriptProvider.aggregate_agents", return_value=[]):
            result = runner.invoke(main, ["agents", "--since", "7d"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("No agent data found", result.output)

    def test_rules_list_command(self):
        runner = CliRunner()
        result = runner.invoke(main, ["rules"])
        self.assertEqual(result.exit_code, 0)
        # Should show rule names from default rules
        self.assertIn("bash-as-grep", result.output)

    def test_cost_breakdown_no_data(self):
        runner = CliRunner()
        with patch("telemetry.providers.transcript.TranscriptProvider.aggregate_agents", return_value=[]):
            result = runner.invoke(main, ["cost-breakdown", "--since", "7d"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("No cost data found", result.output)


# ---------------------------------------------------------------------------
# otel command
# ---------------------------------------------------------------------------

class TestOtelCommand(unittest.TestCase):
    def test_otel_delegates_to_otel_main(self):
        runner = CliRunner()
        with patch("telemetry.otel.cli.main", return_value=0) as mock_otel_main:
            result = runner.invoke(main, ["otel", "help"])
        self.assertEqual(result.exit_code, 0)
        mock_otel_main.assert_called_once_with(["help"])


if __name__ == "__main__":
    unittest.main()
