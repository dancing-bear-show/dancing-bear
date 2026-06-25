"""Tests for telemetry CLI commands."""

import unittest
from unittest.mock import MagicMock, patch
from click.testing import CliRunner

from telemetry.cli import (
    _fmt_tokens,
    _fmt_duration,
    _truncate_id,
    main,
)
from telemetry.models import SessionSummary
from datetime import datetime


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


class TestFmtTokens(unittest.TestCase):
    def test_small(self):
        self.assertEqual(_fmt_tokens(500), "500")

    def test_thousands(self):
        self.assertEqual(_fmt_tokens(1500), "2K")

    def test_millions(self):
        self.assertEqual(_fmt_tokens(2_500_000), "2.5M")

    def test_exactly_one_thousand(self):
        self.assertEqual(_fmt_tokens(1000), "1K")


class TestFmtDuration(unittest.TestCase):
    def test_hours_and_minutes(self):
        s = _make_session_summary()
        result = _fmt_duration(s)
        self.assertEqual(result, "30m")

    def test_none_end_time(self):
        s = _make_session_summary()
        s.end_time = None
        result = _fmt_duration(s)
        self.assertEqual(result, "—")


class TestTruncateId(unittest.TestCase):
    def test_short_id_unchanged(self):
        self.assertEqual(_truncate_id("abc"), "abc")

    def test_long_id_truncated(self):
        result = _truncate_id("a" * 20)
        self.assertLessEqual(len(result), 16)
        self.assertIn("…", result)


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
        import json
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


if __name__ == "__main__":
    unittest.main()
