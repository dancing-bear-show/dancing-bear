"""Tests for telemetry/otel/cli/otel_summary.py."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from telemetry.otel.cli.otel_summary import (
    _get_workflow_runs_cost_24h,
    _parse_since,
    _stage_cost_if_recent,
    main,
)


# ---------------------------------------------------------------------------
# _parse_since
# ---------------------------------------------------------------------------


class TestParseSince(unittest.TestCase):
    def test_relative_minutes(self):
        result = _parse_since("30m")
        self.assertIsInstance(result, float)

    def test_relative_hours(self):
        result = _parse_since("6h")
        self.assertIsInstance(result, float)

    def test_relative_days(self):
        result = _parse_since("2d")
        self.assertIsInstance(result, float)

    def test_relative_weeks(self):
        result = _parse_since("1w")
        self.assertIsInstance(result, float)

    def test_absolute_date(self):
        result = _parse_since("2026-04-16")
        self.assertIsInstance(result, float)

    def test_absolute_datetime(self):
        result = _parse_since("2026-04-16T10:30")
        self.assertIsInstance(result, float)

    def test_invalid_raises_argument_type_error(self):
        import argparse
        with self.assertRaises(argparse.ArgumentTypeError):
            _parse_since("bad-value")


# ---------------------------------------------------------------------------
# _stage_cost_if_recent
# ---------------------------------------------------------------------------


class TestStageCostIfRecent(unittest.TestCase):
    def test_recent_stage_returns_cost(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "stage.json"
            cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
            p.write_text(json.dumps({
                "finished_at": "2026-04-16T10:00:00Z",
                "metadata": {"subagent_cost_usd": "0.05"},
            }))
            result = _stage_cost_if_recent(p, cutoff)
        self.assertAlmostEqual(result, 0.05)

    def test_old_stage_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "stage.json"
            cutoff = datetime(2026, 6, 1, tzinfo=timezone.utc)
            p.write_text(json.dumps({
                "finished_at": "2026-04-16T10:00:00Z",
                "metadata": {"subagent_cost_usd": "0.05"},
            }))
            result = _stage_cost_if_recent(p, cutoff)
        self.assertIsNone(result)

    def test_missing_cost_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "stage.json"
            cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
            p.write_text(json.dumps({
                "finished_at": "2026-04-16T10:00:00Z",
                "metadata": {},
            }))
            result = _stage_cost_if_recent(p, cutoff)
        self.assertIsNone(result)

    def test_missing_finished_at_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "stage.json"
            cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
            p.write_text(json.dumps({"metadata": {"subagent_cost_usd": "0.05"}}))
            result = _stage_cost_if_recent(p, cutoff)
        self.assertIsNone(result)

    def test_bad_json_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "stage.json"
            p.write_text("not json!")
            result = _stage_cost_if_recent(p, datetime.now(timezone.utc))
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# _get_workflow_runs_cost_24h
# ---------------------------------------------------------------------------


class TestGetWorkflowRunsCost24h(unittest.TestCase):
    def test_no_work_dir_returns_none(self):
        with patch("telemetry.otel.cli.otel_summary.get_work_dir") as mock_wd:
            mock_wd.return_value = Path("/nonexistent/path/xyz")
            result = _get_workflow_runs_cost_24h()
        self.assertIsNone(result)

    def test_work_dir_with_no_stages_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("telemetry.otel.cli.otel_summary.get_work_dir", return_value=Path(td)):
                result = _get_workflow_runs_cost_24h()
        self.assertIsNone(result)

    def test_recent_stage_cost_summed(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            stages = p / "run-001" / "stages"
            stages.mkdir(parents=True)
            (stages / "stage1.json").write_text(json.dumps({
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {"subagent_cost_usd": "0.05"},
            }))
            with patch("telemetry.otel.cli.otel_summary.get_work_dir", return_value=p):
                result = _get_workflow_runs_cost_24h()
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.05, places=4)


# ---------------------------------------------------------------------------
# Helpers to build OtelDisplayData mock
# ---------------------------------------------------------------------------


def _make_display_data(*, available: bool = True) -> MagicMock:
    """Build a minimal OtelDisplayData mock."""
    data = MagicMock()
    data.available = available

    ou = MagicMock()
    ou.cost_24h = 1.23
    ou.total_tokens_24h = 10000
    ou.input_tokens_24h = 5000
    ou.output_tokens_24h = 3000
    ou.cache_read_tokens_24h = 1500
    ou.cache_creation_tokens_24h = 500
    ou.active_hours_24h = 3.5
    ou.model_cost_breakdown = [("claude-sonnet-4-6", 1.0)]
    data.otel_usage = ou

    om = MagicMock()
    om.model_rows = [("claude-sonnet-4-6", 1.0, 8000)]
    data.otel_models = om

    ms = MagicMock()
    ms.cost_per_active_hour = 0.35
    ms.cost_per_loc_added = 0.001
    ms.cost_per_commit = 0.50
    ms.cache_hit_rate_pct = 60.0
    ms.total_tokens_24h = 10000
    data.meta_stats = ms

    hk = MagicMock()
    hk.hooks_fired_today = 10
    hk.avg_hook_latency_ms = 50.0
    hk.blocking_count = 1
    hk.error_count = 0
    hk.hook_names = ["PreToolUse"]
    data.hook_health = hk

    ta = MagicMock()
    ta.tool_calls_today = 100
    ta.accept_rate_pct = 95.0
    ta.top_tools = [("Bash", 60), ("Read", 30)]
    ta.tool_error_count = 2
    ta.bash_error_rate_pct = 3.3
    ta.avg_input_bytes = 512.0
    ta.avg_output_bytes = 1024.0
    data.tool_activity = ta

    ci = MagicMock()
    ci.lines_added_today = 200
    ci.lines_removed_today = 50
    ci.commits_today = 3
    ci.compaction_count = 1
    ci.tokens_saved_by_compaction = 5000
    ci.top_languages = [("python", 10)]
    data.code_impact = ci

    sk = MagicMock()
    sk.skills_invoked_today = 5
    sk.top_skills = [("open-pr", 3)]
    data.skills = sk

    sp = MagicMock()
    sp.prompts_today = 20
    sp.agent_call_pct = 80.0
    sp.effort_mix = {}
    sp.model_mix = [("sonnet", 15)]
    data.session_patterns = sp

    return data


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestOtelSummaryMain(unittest.TestCase):
    def test_unavailable_data_returns_1(self):
        mock_data = _make_display_data(available=False)
        with patch("telemetry.otel.cli.otel_summary.OtelMenubarProvider") as mock_cls:
            with patch("telemetry.otel.cli.otel_summary._get_workflow_runs_cost_24h", return_value=None):
                mock_cls.return_value.get_display_data.return_value = mock_data
                result = main([])
        self.assertEqual(result, 1)

    def test_table_format_returns_0(self):
        mock_data = _make_display_data(available=True)
        with patch("telemetry.otel.cli.otel_summary.OtelMenubarProvider") as mock_cls:
            with patch("telemetry.otel.cli.otel_summary._get_workflow_runs_cost_24h", return_value=None):
                mock_cls.return_value.get_display_data.return_value = mock_data
                result = main([])
        self.assertEqual(result, 0)

    def test_json_format_produces_valid_json(self):
        mock_data = _make_display_data(available=True)
        with patch("telemetry.otel.cli.otel_summary.OtelMenubarProvider") as mock_cls:
            with patch("telemetry.otel.cli.otel_summary._get_workflow_runs_cost_24h", return_value=None):
                mock_cls.return_value.get_display_data.return_value = mock_data
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    main(["--format", "json"])
        data = json.loads(buf.getvalue())
        self.assertIn("usage", data)
        self.assertIn("source", data)

    def test_json_format_includes_source_otel(self):
        mock_data = _make_display_data(available=True)
        with patch("telemetry.otel.cli.otel_summary.OtelMenubarProvider") as mock_cls:
            with patch("telemetry.otel.cli.otel_summary._get_workflow_runs_cost_24h", return_value=None):
                mock_cls.return_value.get_display_data.return_value = mock_data
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    main(["--format", "json"])
        data = json.loads(buf.getvalue())
        self.assertEqual(data["source"], "otel")

    def test_since_flag_mutually_exclusive_with_window(self):
        # Both --since and --window should cause argparse error
        with self.assertRaises(SystemExit):
            main(["--since", "2h", "--window", "24h"])

    def test_window_flag(self):
        mock_data = _make_display_data(available=True)
        with patch("telemetry.otel.cli.otel_summary.OtelMenubarProvider") as mock_cls:
            with patch("telemetry.otel.cli.otel_summary._get_workflow_runs_cost_24h", return_value=None):
                mock_cls.return_value.get_display_data.return_value = mock_data
                result = main(["--window", "7d"])
        self.assertEqual(result, 0)

    def test_since_flag(self):
        mock_data = _make_display_data(available=True)
        with patch("telemetry.otel.cli.otel_summary.OtelMenubarProvider") as mock_cls:
            with patch("telemetry.otel.cli.otel_summary._get_workflow_runs_cost_24h", return_value=None):
                mock_cls.return_value.get_display_data.return_value = mock_data
                result = main(["--since", "6h"])
        self.assertEqual(result, 0)

    def test_workflow_runs_cost_included_in_json(self):
        mock_data = _make_display_data(available=True)
        with patch("telemetry.otel.cli.otel_summary.OtelMenubarProvider") as mock_cls:
            with patch("telemetry.otel.cli.otel_summary._get_workflow_runs_cost_24h", return_value=0.25):
                mock_cls.return_value.get_display_data.return_value = mock_data
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    main(["--format", "json"])
        data = json.loads(buf.getvalue())
        self.assertIn("workflow_runs_cost_24h", data)

    def test_date_flag_shows_warning_to_stderr(self):
        mock_data = _make_display_data(available=True)
        with patch("telemetry.otel.cli.otel_summary.OtelMenubarProvider") as mock_cls:
            with patch("telemetry.otel.cli.otel_summary._get_workflow_runs_cost_24h", return_value=None):
                mock_cls.return_value.get_display_data.return_value = mock_data
                buf = io.StringIO()
                with patch("sys.stderr", buf):
                    main(["--date", "2026-04-16"])
        self.assertIn("not yet implemented", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
