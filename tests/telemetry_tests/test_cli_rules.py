"""Tests for CLI rules/command wiring and top-level CLI commands."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

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


def _run_main(argv: list[str]) -> tuple[int, str]:
    """Invoke main(argv) and return (rc, stdout). Catches SystemExit(0) from --help."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = main(argv)
    except SystemExit as e:  # NOSONAR - argparse --help exits by design; re-raising would defeat the helper
        rc = e.code if isinstance(e.code, int) else 0
    return rc, buf.getvalue()


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
        with patch("telemetry.rules.load_rules", return_value=rules_no_hints):
            rc, out = _run_main(["rules", "--explain", "bash-as-grep"])
        self.assertEqual(rc, 0)
        self.assertIn("bash-as-grep", out)

    def test_found_rule_with_fix_hints(self):
        from telemetry.rules import DEFAULT_RULES
        with patch("telemetry.rules.load_rules", return_value=DEFAULT_RULES):
            rc, out = _run_main(["rules", "--explain", "bash-as-grep"])
        self.assertEqual(rc, 0)
        self.assertIn("bash-as-grep", out)
        self.assertIn("Fix hints", out)

    def test_not_found_rule(self):
        from telemetry.rules import DEFAULT_RULES
        with patch("telemetry.rules.load_rules", return_value=DEFAULT_RULES):
            rc, out = _run_main(["rules", "--explain", "nonexistent-rule"])
        self.assertEqual(rc, 0)
        self.assertIn("Rule not found", out)
        self.assertIn("nonexistent-rule", out)


# ---------------------------------------------------------------------------
# _rules_list
# ---------------------------------------------------------------------------

class TestRulesList(unittest.TestCase):
    def test_lists_avoidable_and_review_rules(self):
        from telemetry.rules import DEFAULT_RULES
        with patch("telemetry.rules.load_rules", return_value=DEFAULT_RULES):
            rc, out = _run_main(["rules"])
        self.assertEqual(rc, 0)
        self.assertIn("bash-as-grep", out)
        self.assertIn("abandoned-search", out)

    def test_lists_custom_rules(self):
        import copy
        from telemetry.rules import DEFAULT_RULES
        rules_with_custom = copy.deepcopy(DEFAULT_RULES)
        rules_with_custom["custom_rules"] = [{"reason": "my-custom-rule", "tool": "Bash"}]
        with patch("telemetry.rules.load_rules", return_value=rules_with_custom):
            rc, out = _run_main(["rules"])
        self.assertEqual(rc, 0)
        self.assertIn("my-custom-rule", out)

    def test_custom_rule_without_reason_uses_index(self):
        import copy
        from telemetry.rules import DEFAULT_RULES
        rules_with_custom = copy.deepcopy(DEFAULT_RULES)
        rules_with_custom["custom_rules"] = [{"tool": "Bash"}]
        with patch("telemetry.rules.load_rules", return_value=rules_with_custom):
            rc, out = _run_main(["rules"])
        self.assertEqual(rc, 0)
        self.assertIn("custom-0", out)

    def test_skips_non_dict_rule_cfg(self):
        import copy
        from telemetry.rules import DEFAULT_RULES
        rules_bad_cfg = copy.deepcopy(DEFAULT_RULES)
        rules_bad_cfg["avoidable"]["broken-rule"] = "not-a-dict"
        with patch("telemetry.rules.load_rules", return_value=rules_bad_cfg):
            rc, out = _run_main(["rules"])
        self.assertEqual(rc, 0)
        self.assertNotIn("broken-rule", out)


# ---------------------------------------------------------------------------
# rules command wiring
# ---------------------------------------------------------------------------

class TestRulesCommand(unittest.TestCase):
    def test_init_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("telemetry.cli_sessions.Path.home", return_value=Path(tmpdir)):
                rc, out = _run_main(["rules", "--init"])
            self.assertEqual(rc, 0)
            self.assertIn("Created", out)

    def test_init_flag_already_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = Path(tmpdir) / ".telemetry-transcripts"
            nested.mkdir()
            config_path = nested / "rules.yaml"
            config_path.write_text("existing: true\n")
            with patch("telemetry.cli_sessions.Path.home", return_value=Path(tmpdir)):
                rc, out = _run_main(["rules", "--init"])
            self.assertEqual(rc, 0)
            self.assertIn("Already exists", out)

    def test_validate_flag_success(self):
        from telemetry.rules import DEFAULT_RULES
        with patch("telemetry.rules.load_rules", return_value=DEFAULT_RULES):
            with patch("telemetry.rules.validate_rules", return_value=[]):
                rc, out = _run_main(["rules", "--validate"])
        self.assertEqual(rc, 0)
        self.assertIn("valid", out)

    def test_validate_flag_with_errors(self):
        from telemetry.rules import DEFAULT_RULES
        errors = ["avoidable.bash-as-grep: enabled must be boolean"]
        with patch("telemetry.rules.load_rules", return_value=DEFAULT_RULES):
            with patch("telemetry.rules.validate_rules", return_value=errors):
                rc, _ = _run_main(["rules", "--validate"])
        self.assertNotEqual(rc, 0)


# ---------------------------------------------------------------------------
# history command
# ---------------------------------------------------------------------------

class TestHistoryCommand(unittest.TestCase):
    def test_no_sessions_message(self):
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = []
            rc, out = _run_main(["history", "--days", "7"])
        self.assertEqual(rc, 0)
        self.assertIn("No sessions found", out)
        MockProvider.return_value.get_sessions.assert_called_once()

    def test_with_sessions_shows_table(self):
        s = _make_session_summary()
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s]
            rc, _ = _run_main(["history", "--days", "3"])
        self.assertEqual(rc, 0)

    def test_model_split_on_slash(self):
        s = _make_session_summary(model="anthropic/claude-sonnet-4-6")
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s]
            rc, out = _run_main(["history"])
        self.assertEqual(rc, 0)
        self.assertIn("claude-sonnet-4-6", out)


# ---------------------------------------------------------------------------
# sessions command
# ---------------------------------------------------------------------------

class TestSessionsCommand(unittest.TestCase):
    def test_no_sessions_message(self):
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = []
            rc, out = _run_main(["sessions", "--since", "7d"])
        self.assertEqual(rc, 0)
        self.assertIn("No sessions found", out)

    def test_json_format(self):
        sessions = [_make_session_summary()]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = sessions
            rc, out = _run_main(["sessions", "--since", "7d", "--format", "json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["session_count"], 1)

    def test_limit_applied(self):
        sessions = [
            _make_session_summary(session_id="a", total_cost=0.10),
            _make_session_summary(session_id="b", total_cost=0.20),
            _make_session_summary(session_id="c", total_cost=0.05),
        ]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = sessions
            rc, out = _run_main(["sessions", "--since", "7d", "--limit", "1", "--format", "json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["session_count"], 1)

    def test_errors_only_filter(self):
        agent = _make_agent_summary()
        s_with_agents = _make_session_summary(session_id="s1", agents=[agent])
        s_no_agents = _make_session_summary(session_id="s2", agents=[])
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s_with_agents, s_no_agents]
            rc, out = _run_main(["sessions", "--since", "7d", "--errors-only", "--format", "json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["session_count"], 1)

    def test_filters_zero_event_zero_cost_sessions(self):
        s_empty = _make_session_summary(total_events=0, total_cost=0.0)
        s_ok = _make_session_summary(session_id="ok", total_events=5, total_cost=0.01)
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s_empty, s_ok]
            rc, out = _run_main(["sessions", "--since", "7d", "--format", "json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["session_count"], 1)

    def test_table_format_with_sessions(self):
        s = _make_session_summary()
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s]
            rc, _ = _run_main(["sessions", "--since", "7d", "--format", "table"])
        self.assertEqual(rc, 0)

    def test_projects_dir_passed_to_provider(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
                MockProvider.return_value.get_sessions.return_value = []
                rc, _ = _run_main(["sessions", "--since", "7d", "--projects-dir", tmpdir])
            self.assertEqual(rc, 0)
            self.assertIsNotNone(MockProvider.call_args)


# ---------------------------------------------------------------------------
# agents command
# ---------------------------------------------------------------------------

class TestAgentsCommand(unittest.TestCase):
    def test_no_data_message(self):
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = []
            rc, out = _run_main(["agents", "--since", "7d"])
        self.assertEqual(rc, 0)
        self.assertIn("No agent data found", out)

    def test_json_format(self):
        rows = [_make_agent_token_row()]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            rc, out = _run_main(["agents", "--since", "7d", "--format", "json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["agent_count"], 1)
        self.assertIn("agents", data)

    def test_csv_format(self):
        rows = [_make_agent_token_row(agent="doc-writer")]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            rc, out = _run_main(["agents", "--since", "7d", "--format", "csv"])
        self.assertEqual(rc, 0)
        self.assertIn("doc-writer", out)

    def test_table_format_with_data(self):
        rows = [_make_agent_token_row()]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            rc, _ = _run_main(["agents", "--since", "7d", "--format", "table"])
        self.assertEqual(rc, 0)

    def test_model_filter(self):
        rows = [
            _make_agent_token_row(agent="a1", models=["claude-sonnet-4-6"]),
            _make_agent_token_row(agent="a2", models=["claude-haiku-3-5"]),
        ]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            rc, out = _run_main(["agents", "--since", "7d", "--model", "haiku", "--format", "json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["returned_count"], 1)

    def test_limit_applied(self):
        rows = [
            _make_agent_token_row(agent="expensive", est_cost=1.0),
            _make_agent_token_row(agent="cheap", est_cost=0.01),
        ]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            rc, out = _run_main(["agents", "--since", "7d", "--limit", "1", "--format", "json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["returned_count"], 1)

    def test_sort_by_output(self):
        rows = [
            _make_agent_token_row(agent="low", output_tokens=100),
            _make_agent_token_row(agent="high", output_tokens=9000),
        ]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            rc, out = _run_main(["agents", "--since", "7d", "--sort", "output", "--format", "json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["agents"][0]["agent"], "high")

    def test_sort_by_calls(self):
        rows = [
            _make_agent_token_row(agent="few", calls=1),
            _make_agent_token_row(agent="many", calls=50),
        ]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            rc, out = _run_main(["agents", "--since", "7d", "--sort", "calls", "--format", "json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["agents"][0]["agent"], "many")

    def test_sort_by_input(self):
        rows = [
            _make_agent_token_row(agent="small-in", input_tokens=100),
            _make_agent_token_row(agent="large-in", input_tokens=99000),
        ]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            rc, out = _run_main(["agents", "--since", "7d", "--sort", "input", "--format", "json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["agents"][0]["agent"], "large-in")

    def test_sort_by_cache_read(self):
        rows = [
            _make_agent_token_row(agent="low-cache", cache_read_tokens=10),
            _make_agent_token_row(agent="high-cache", cache_read_tokens=50000),
        ]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            rc, out = _run_main(["agents", "--since", "7d", "--sort", "cache-read", "--format", "json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["agents"][0]["agent"], "high-cache")


# ---------------------------------------------------------------------------
# cost-breakdown command
# ---------------------------------------------------------------------------

class TestCostBreakdownCommand(unittest.TestCase):
    def test_no_data_message(self):
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = []
            rc, out = _run_main(["cost-breakdown", "--since", "7d"])
        self.assertEqual(rc, 0)
        self.assertIn("No cost data found", out)

    def test_group_by_agent_json(self):
        rows = [_make_agent_token_row(agent="myagent", est_cost=0.10)]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            rc, out = _run_main(["cost-breakdown", "--since", "7d", "--format", "json", "--group-by", "agent"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["group_by"], "agent")
        self.assertIn("rows", data)

    def test_group_by_day_json(self):
        now = datetime.now(tz=timezone.utc)
        s = _make_session_summary(total_cost=0.15)
        s.start_time = now
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s]
            rc, out = _run_main(["cost-breakdown", "--since", "7d", "--format", "json", "--group-by", "day"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["group_by"], "day")
        self.assertEqual(len(data["rows"]), 1)

    def test_group_by_agent_csv(self):
        rows = [_make_agent_token_row(agent="csvagent", est_cost=0.07)]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            rc, out = _run_main(["cost-breakdown", "--since", "7d", "--format", "csv", "--group-by", "agent"])
        self.assertEqual(rc, 0)
        self.assertIn("agent", out)

    def test_group_by_day_csv(self):
        now = datetime.now(tz=timezone.utc)
        s = _make_session_summary(total_cost=0.05)
        s.start_time = now
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s]
            rc, out = _run_main(["cost-breakdown", "--since", "7d", "--format", "csv", "--group-by", "day"])
        self.assertEqual(rc, 0)
        self.assertIn("day", out)

    def test_group_by_agent_table(self):
        rows = [_make_agent_token_row()]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            rc, _ = _run_main(["cost-breakdown", "--since", "7d", "--format", "table", "--group-by", "agent"])
        self.assertEqual(rc, 0)

    def test_group_by_day_table(self):
        now = datetime.now(tz=timezone.utc)
        s = _make_session_summary(total_cost=0.20)
        s.start_time = now
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s]
            rc, _ = _run_main(["cost-breakdown", "--since", "7d", "--format", "table", "--group-by", "day"])
        self.assertEqual(rc, 0)

    def test_limit_applied(self):
        rows = [
            _make_agent_token_row(agent="a1", est_cost=0.50),
            _make_agent_token_row(agent="a2", est_cost=0.10),
        ]
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = rows
            rc, out = _run_main(["cost-breakdown", "--since", "7d", "--limit", "1", "--format", "json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(len(data["rows"]), 1)

    def test_cost_alias_command(self):
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.aggregate_agents.return_value = []
            rc, out = _run_main(["cost", "--since", "7d"])
        self.assertEqual(rc, 0)
        self.assertIn("No cost data found", out)

    def test_breakdown_by_day_warning_path(self):
        s = _make_session_summary()
        s.start_time = None
        with patch("telemetry.providers.transcript.TranscriptProvider") as MockProvider:
            MockProvider.return_value.get_sessions.return_value = [s]
            rc, _ = _run_main(["cost-breakdown", "--since", "7d", "--group-by", "day"])
        self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# main help
# ---------------------------------------------------------------------------

class TestMainCLI(unittest.TestCase):
    def test_main_shows_help(self):
        rc, out = _run_main(["--help"])
        self.assertEqual(rc, 0)
        self.assertIn("telemetry", out.lower())

    def test_sessions_command_no_sessions(self):
        with patch("telemetry.providers.transcript.TranscriptProvider.get_sessions", return_value=[]):
            rc, out = _run_main(["sessions", "--since", "7d"])
        self.assertEqual(rc, 0)
        self.assertIn("No sessions found", out)

    def test_sessions_command_json_format(self):
        sessions = [_make_session_summary()]
        with patch("telemetry.providers.transcript.TranscriptProvider.get_sessions", return_value=sessions):
            rc, out = _run_main(["sessions", "--since", "7d", "--format", "json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertIn("session_count", data)
        self.assertEqual(data["session_count"], 1)

    def test_history_command_no_sessions(self):
        with patch("telemetry.providers.transcript.TranscriptProvider.get_sessions", return_value=[]):
            rc, out = _run_main(["history", "--days", "7"])
        self.assertEqual(rc, 0)
        self.assertIn("No sessions found", out)

    def test_agents_command_no_data(self):
        with patch("telemetry.providers.transcript.TranscriptProvider.aggregate_agents", return_value=[]):
            rc, out = _run_main(["agents", "--since", "7d"])
        self.assertEqual(rc, 0)
        self.assertIn("No agent data found", out)

    def test_rules_list_command(self):
        rc, out = _run_main(["rules"])
        self.assertEqual(rc, 0)
        self.assertIn("bash-as-grep", out)

    def test_cost_breakdown_no_data(self):
        with patch("telemetry.providers.transcript.TranscriptProvider.aggregate_agents", return_value=[]):
            rc, out = _run_main(["cost-breakdown", "--since", "7d"])
        self.assertEqual(rc, 0)
        self.assertIn("No cost data found", out)


# ---------------------------------------------------------------------------
# otel command
# ---------------------------------------------------------------------------

class TestOtelCommand(unittest.TestCase):
    def test_otel_delegates_to_otel_main(self):
        with patch("telemetry.otel.cli.main", return_value=0) as mock_otel_main:
            rc, _ = _run_main(["otel", "help"])
        self.assertEqual(rc, 0)
        mock_otel_main.assert_called_once_with(["help"])


if __name__ == "__main__":
    unittest.main()
