"""Tests for CLI rules/command wiring and top-level CLI commands."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from telemetry.cli import (
    _rules_init,
    _rules_validate,
    main,
)

from tests.telemetry_tests.shared_fixtures import (
    _make_agent_summary_cli as _make_agent_summary,
    _make_agent_token_row,
    _make_session_summary,
)


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
        import copy
        from telemetry.rules import DEFAULT_RULES
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
        import copy
        from telemetry.rules import DEFAULT_RULES
        rules_with_custom = copy.deepcopy(DEFAULT_RULES)
        rules_with_custom["custom_rules"] = [{"reason": "my-custom-rule", "tool": "Bash"}]
        runner = CliRunner()
        with patch("telemetry.rules.load_rules", return_value=rules_with_custom):
            result = runner.invoke(main, ["rules"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("my-custom-rule", result.output)

    def test_custom_rule_without_reason_uses_index(self):
        import copy
        from telemetry.rules import DEFAULT_RULES
        rules_with_custom = copy.deepcopy(DEFAULT_RULES)
        rules_with_custom["custom_rules"] = [{"tool": "Bash"}]
        runner = CliRunner()
        with patch("telemetry.rules.load_rules", return_value=rules_with_custom):
            result = runner.invoke(main, ["rules"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("custom-0", result.output)

    def test_skips_non_dict_rule_cfg(self):
        import copy
        from telemetry.rules import DEFAULT_RULES
        rules_bad_cfg = copy.deepcopy(DEFAULT_RULES)
        rules_bad_cfg["avoidable"]["broken-rule"] = "not-a-dict"
        runner = CliRunner()
        with patch("telemetry.rules.load_rules", return_value=rules_bad_cfg):
            result = runner.invoke(main, ["rules"])
        self.assertEqual(result.exit_code, 0)
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
