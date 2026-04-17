"""Tests for diagrams CLI renderers."""

import unittest
from datetime import datetime, timezone

from diagrams.cli import _render_cost_pie, _render_token_pie, _render_timeline
from diagrams.mermaid import GanttBuilder, PieBuilder, SequenceDiagramBuilder
from telemetry.parser import SessionStats
from telemetry.pricing import compute_cost, model_tier


def _make_session(session_id="abc123", model="claude-sonnet-4-6",
                  input_tok=1000, output_tok=500,
                  start="2026-04-16T10:00:00Z", end="2026-04-16T10:30:00Z"):
    from pathlib import Path
    s = SessionStats(session_id=session_id, path=Path(f"/fake/{session_id}.jsonl"))
    s.model = model
    s.input_tokens = input_tok
    s.output_tokens = output_tok
    s.events = 1
    s.start_time = datetime.fromisoformat(start.replace("Z", "+00:00"))
    s.end_time = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return s


class TestRenderCostPie(unittest.TestCase):
    def test_renders_pie_with_session(self):
        sessions = [_make_session(model="claude-opus-4-6", input_tok=1_000_000, output_tok=0)]
        result = _render_cost_pie(sessions, 7, compute_cost, model_tier)
        self.assertIn("pie title", result)
        self.assertIn("Opus", result)

    def test_empty_sessions_renders_empty_pie(self):
        result = _render_cost_pie([], 7, compute_cost, model_tier)
        self.assertIn("pie title", result)
        # No slices for zero-cost tiers
        self.assertNotIn('"Opus"', result)

    def test_unknown_model_excluded(self):
        sessions = [_make_session(model="future-model-xyz")]
        result = _render_cost_pie(sessions, 7, compute_cost, model_tier)
        # Unknown model has 0 cost, so no slice should appear
        self.assertNotIn("future-model-xyz", result)


class TestRenderTokenPie(unittest.TestCase):
    def test_renders_pie_with_tokens(self):
        sessions = [_make_session(model="claude-haiku-4-5", input_tok=500, output_tok=200)]
        result = _render_token_pie(sessions, 7, model_tier)
        self.assertIn("pie title", result)
        self.assertIn("Haiku", result)

    def test_multiple_tiers(self):
        sessions = [
            _make_session(session_id="s1", model="claude-opus-4-6", input_tok=1000),
            _make_session(session_id="s2", model="claude-sonnet-4-6", input_tok=2000),
        ]
        result = _render_token_pie(sessions, 7, model_tier)
        self.assertIn("Opus", result)
        self.assertIn("Sonnet", result)


class TestRenderTimeline(unittest.TestCase):
    def test_renders_gantt(self):
        sessions = [_make_session()]
        result = _render_timeline(sessions, 7, compute_cost, model_tier)
        self.assertIn("gantt", result)
        self.assertIn("dateFormat YYYY-MM-DD", result)
        self.assertIn("2026-04-16", result)

    def test_duration_in_days(self):
        sessions = [_make_session()]
        result = _render_timeline(sessions, 7, compute_cost, model_tier)
        # Duration must use 'd' suffix, not 'm'
        self.assertRegex(result, r"\d+d")
        self.assertNotIn("m\n", result)

    def test_task_id_sanitized(self):
        # Session ID with hyphens should produce valid Mermaid task IDs
        sessions = [_make_session(session_id="abc-def-ghi-123")]
        result = _render_timeline(sessions, 7, compute_cost, model_tier)
        # ID should not contain hyphens
        import re
        ids = re.findall(r":t(\w+),", result)
        for tid in ids:
            self.assertRegex(tid, r"^[A-Za-z0-9_]+$")

    def test_no_sessions_renders_empty_gantt(self):
        result = _render_timeline([], 7, compute_cost, model_tier)
        self.assertIn("gantt", result)


class TestSequenceDiagramBuilder(unittest.TestCase):
    def test_note_raises_without_over(self):
        builder = SequenceDiagramBuilder()
        with self.assertRaises(ValueError):
            builder.note("hello")

    def test_note_renders_correctly(self):
        builder = SequenceDiagramBuilder()
        builder.participant("A").note("hello", over=["A"])
        result = builder.render()
        self.assertIn("Note over A: hello", result)

    def test_alt_custom_else_label(self):
        builder = SequenceDiagramBuilder()
        builder.alt("success", ["A->>B: ok"], else_body=["A->>B: fail"], else_label="timeout")
        result = builder.render()
        self.assertIn("else timeout", result)
        self.assertNotIn("else failure", result)

    def test_alt_default_else_label(self):
        builder = SequenceDiagramBuilder()
        builder.alt("success", ["A->>B: ok"], else_body=["A->>B: fail"])
        result = builder.render()
        self.assertIn("else else", result)


if __name__ == "__main__":
    unittest.main()
