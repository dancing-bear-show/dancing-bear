"""Tests for diagrams/cli.py command dispatch and helper functions."""

import unittest
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from diagrams.cli import (
    _format_tokens,
    _render_cost_pie,
    _render_timeline,
    _render_token_pie,
    _session_cost,
    cmd_telemetry,
    main,
)
from telemetry.parser import SessionStats
from telemetry.pricing import compute_cost, model_tier


def _make_session(
    session_id="abc123",
    model="claude-sonnet-4-6",
    input_tok=1000,
    output_tok=500,
    cache_read=0,
    cache_create=0,
    start="2026-04-16T10:00:00Z",
    end="2026-04-16T10:30:00Z",
):
    s = SessionStats(session_id=session_id, path=Path(f"/fake/{session_id}.jsonl"))
    s.model = model
    s.input_tokens = input_tok
    s.output_tokens = output_tok
    s.cache_read_tokens = cache_read
    s.cache_create_tokens = cache_create
    s.events = 1
    s.start_time = datetime.fromisoformat(start.replace("Z", "+00:00"))
    s.end_time = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return s


class TestFormatTokens(unittest.TestCase):
    def test_small(self):
        self.assertEqual(_format_tokens(999), "999")

    def test_thousands(self):
        self.assertEqual(_format_tokens(2500), "2.5K")

    def test_millions(self):
        self.assertEqual(_format_tokens(3_000_000), "3.0M")


class TestSessionCost(unittest.TestCase):
    def test_no_model_returns_zero(self):
        s = _make_session(model="")
        self.assertEqual(_session_cost(s, compute_cost), 0.0)

    def test_known_model_nonzero(self):
        s = _make_session(model="claude-opus-4-6", input_tok=1_000_000)
        cost = _session_cost(s, compute_cost)
        self.assertGreater(cost, 0.0)


class TestRenderCostPie(unittest.TestCase):
    def test_renders_pie(self):
        sessions = [_make_session(model="claude-opus-4-6", input_tok=1_000_000)]
        result = _render_cost_pie(sessions, 7, compute_cost, model_tier)
        self.assertIn("pie title", result)

    def test_empty_sessions(self):
        result = _render_cost_pie([], 7, compute_cost, model_tier)
        self.assertIn("pie title", result)

    def test_unknown_model_excluded(self):
        sessions = [_make_session(model="future-xyz", input_tok=1_000_000)]
        result = _render_cost_pie(sessions, 7, compute_cost, model_tier)
        self.assertNotIn("future-xyz", result)

    def test_session_without_model_skipped(self):
        sessions = [_make_session(model="")]
        result = _render_cost_pie(sessions, 7, compute_cost, model_tier)
        self.assertIn("pie title", result)


class TestRenderTokenPie(unittest.TestCase):
    def test_renders_pie(self):
        sessions = [_make_session(model="claude-haiku-4-5", input_tok=2000)]
        result = _render_token_pie(sessions, 7, model_tier)
        self.assertIn("pie title", result)
        self.assertIn("Haiku", result)

    def test_session_without_model_skipped(self):
        sessions = [_make_session(model="")]
        result = _render_token_pie(sessions, 7, model_tier)
        self.assertIn("pie title", result)

    def test_multiple_tiers(self):
        sessions = [
            _make_session(session_id="s1", model="claude-opus-4-6", input_tok=1000),
            _make_session(session_id="s2", model="claude-haiku-4-5", input_tok=2000),
        ]
        result = _render_token_pie(sessions, 7, model_tier)
        self.assertIn("Opus", result)
        self.assertIn("Haiku", result)


class TestRenderTimeline(unittest.TestCase):
    def test_renders_gantt(self):
        sessions = [_make_session()]
        result = _render_timeline(sessions, 7, compute_cost, model_tier)
        self.assertIn("gantt", result)
        self.assertIn("2026-04-16", result)

    def test_empty_sessions(self):
        result = _render_timeline([], 7, compute_cost, model_tier)
        self.assertIn("gantt", result)
        self.assertNotIn("section", result)

    def test_session_without_start_time_skipped(self):
        s = _make_session()
        s.start_time = None
        result = _render_timeline([s], 7, compute_cost, model_tier)
        self.assertIn("gantt", result)
        self.assertNotIn("section", result)

    def test_session_without_model_renders_question_mark_tier(self):
        s = _make_session(model="")
        result = _render_timeline([s], 7, compute_cost, model_tier)
        self.assertIn("gantt", result)
        self.assertIn("?", result)

    def test_long_session_duration(self):
        # 2-day session should produce 2d
        s = _make_session(
            start="2026-04-14T10:00:00Z",
            end="2026-04-16T10:00:00Z",
        )
        result = _render_timeline([s], 7, compute_cost, model_tier)
        self.assertIn("2d", result)


class TestCmdTelemetry(unittest.TestCase):
    def _make_args(self, diagram_type="cost-pie", days=7):
        args = MagicMock()
        args.type = diagram_type
        args.days = days
        return args

    def test_no_sessions_returns_1(self):
        with patch("diagrams.cli._load_telemetry", return_value=([], compute_cost, model_tier)):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_telemetry(self._make_args())
        self.assertEqual(rc, 1)
        self.assertIn("No sessions found", buf.getvalue())

    def test_cost_pie_returns_0(self):
        sessions = [_make_session(model="claude-opus-4-6", input_tok=1_000_000)]
        with patch("diagrams.cli._load_telemetry", return_value=(sessions, compute_cost, model_tier)):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_telemetry(self._make_args(diagram_type="cost-pie"))
        self.assertEqual(rc, 0)
        self.assertIn("pie", buf.getvalue())

    def test_token_pie_returns_0(self):
        sessions = [_make_session(model="claude-sonnet-4-6")]
        with patch("diagrams.cli._load_telemetry", return_value=(sessions, compute_cost, model_tier)):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_telemetry(self._make_args(diagram_type="token-pie"))
        self.assertEqual(rc, 0)

    def test_timeline_returns_0(self):
        sessions = [_make_session()]
        with patch("diagrams.cli._load_telemetry", return_value=(sessions, compute_cost, model_tier)):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_telemetry(self._make_args(diagram_type="timeline"))
        self.assertEqual(rc, 0)
        self.assertIn("gantt", buf.getvalue())

    def test_unknown_diagram_type_returns_1(self):
        sessions = [_make_session()]
        with patch("diagrams.cli._load_telemetry", return_value=(sessions, compute_cost, model_tier)):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_telemetry(self._make_args(diagram_type="unknown-type"))
        self.assertEqual(rc, 1)
        self.assertIn("Unknown diagram type", buf.getvalue())


class TestDiagramsMain(unittest.TestCase):
    def test_no_command_prints_help(self):
        buf = StringIO()
        with patch("sys.stdout", buf):
            rc = main([])
        self.assertEqual(rc, 0)

    def test_telemetry_cost_pie_dispatched(self):
        sessions = [_make_session(model="claude-opus-4-6", input_tok=500_000)]
        with patch("diagrams.cli._load_telemetry", return_value=(sessions, compute_cost, model_tier)):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = main(["telemetry", "cost-pie", "--days", "14"])
        self.assertEqual(rc, 0)

    def test_telemetry_token_pie_dispatched(self):
        sessions = [_make_session()]
        with patch("diagrams.cli._load_telemetry", return_value=(sessions, compute_cost, model_tier)):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = main(["telemetry", "token-pie"])
        self.assertEqual(rc, 0)

    def test_telemetry_timeline_dispatched(self):
        sessions = [_make_session()]
        with patch("diagrams.cli._load_telemetry", return_value=(sessions, compute_cost, model_tier)):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = main(["telemetry", "timeline"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
