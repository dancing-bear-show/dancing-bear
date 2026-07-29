"""Tests for tui/_renderers.py — panel-level renderers and compound UI helpers."""
from __future__ import annotations

import io
import unittest

from rich.console import Console
from rich.panel import Panel

from telemetry.models import AgentSummary, ToolStats
from telemetry.tui._renderers import (
    _agent_detail,
    _efficiency_color,
    _print_agents_panel,
    _print_tool_stats_panel,
    _render_stats_compact,
    _render_stats_panel,
    _render_timeline_line,
    _stats_duration_str,
    _stats_session_label,
    _tip_detail,
    _tool_stat_detail,
)

from tests.telemetry_tests.shared_fixtures import (
    _make_agent_summary_tui as _make_agent_summary,
    _make_event,
    _make_summary,
    _make_tip,
    _make_tool_stats,
    _render_panel_text,
)


# ---------------------------------------------------------------------------
# _tool_stat_detail
# ---------------------------------------------------------------------------

class TestToolStatDetail(unittest.TestCase):
    def test_header_includes_tool_name_and_count(self):
        stat = _make_tool_stats("Bash")
        result = _tool_stat_detail(stat, [])
        self.assertIn("Bash", result)
        self.assertIn("5 calls", result)

    def test_avoidable_and_review_counts(self):
        stat = _make_tool_stats("Bash")
        result = _tool_stat_detail(stat, [])
        self.assertIn("Avoidable: 2", result)
        self.assertIn("Review: 1", result)

    def test_multiple_classifications_all_rendered(self):
        stat = _make_tool_stats("Bash")
        events = [
            _make_event(event_type="tool_use", tool_name="Bash", classification="avoidable"),
            _make_event(event_type="tool_use", tool_name="Bash", classification="productive"),
            _make_event(event_type="tool_use", tool_name="Bash", classification="neutral"),
        ]
        result = _tool_stat_detail(stat, events)
        self.assertIn("avoidable", result)
        self.assertIn("productive", result)
        self.assertIn("neutral", result)

    def test_empty_classification_group_skipped(self):
        stat = _make_tool_stats("Bash")
        events = [
            _make_event(event_type="tool_use", tool_name="Bash", classification="avoidable"),
        ]
        result = _tool_stat_detail(stat, events)
        self.assertIn("avoidable", result)
        self.assertNotIn("⚠ review", result)

    def test_filters_to_matching_tool_name(self):
        stat = _make_tool_stats("Bash")
        events = [
            _make_event(event_type="tool_use", tool_name="Bash", classification="productive"),
            _make_event(event_type="tool_use", tool_name="Read", classification="avoidable"),
        ]
        result = _tool_stat_detail(stat, events)
        self.assertIn("productive", result)

    def test_non_tool_use_events_excluded(self):
        stat = _make_tool_stats("Bash")
        events = [
            _make_event(event_type="api_request", tool_name="Bash", classification="avoidable"),
        ]
        result = _tool_stat_detail(stat, events)
        self.assertNotIn("avoidable", result)


# ---------------------------------------------------------------------------
# _tip_detail
# ---------------------------------------------------------------------------

class TestTipDetail(unittest.TestCase):
    def test_avoidable_uses_red_cross(self):
        tip = _make_tip(severity="avoidable")
        result = _tip_detail(tip)
        self.assertIn("[red]✗[/]", result)

    def test_non_avoidable_uses_yellow_warning(self):
        tip = _make_tip(severity="review")
        result = _tip_detail(tip)
        self.assertIn("[yellow]⚠[/]", result)

    def test_includes_count_and_cost(self):
        tip = _make_tip()
        result = _tip_detail(tip)
        self.assertIn("Occurrences:", result)
        self.assertIn("3", result)
        self.assertIn("Cost impact:", result)
        self.assertIn("0.0120", result)

    def test_includes_blame_info(self):
        tip = _make_tip()
        result = _tip_detail(tip)
        self.assertIn("Blame:", result)
        self.assertIn("s2s:onboarding", result)

    def test_includes_fix_hint(self):
        tip = _make_tip()
        result = _tip_detail(tip)
        self.assertIn("Fix:", result)
        self.assertIn(tip.fix_hint, result)

    def test_includes_waste_reason(self):
        tip = _make_tip()
        result = _tip_detail(tip)
        self.assertIn("redundant-read", result)


# ---------------------------------------------------------------------------
# _agent_detail
# ---------------------------------------------------------------------------

class TestAgentDetail(unittest.TestCase):
    def test_basic_fields_present(self):
        agent = _make_agent_summary()
        result = _agent_detail(agent)
        self.assertIn(agent.description, result)
        self.assertIn(agent.agent_id, result)
        self.assertIn(agent.agent_type, result)

    def test_model_short_name(self):
        agent = _make_agent_summary()
        result = _agent_detail(agent)
        self.assertIn("claude-sonnet-4-6", result)

    def test_duration_in_seconds(self):
        agent = _make_agent_summary()
        result = _agent_detail(agent)
        self.assertIn("5.0s", result)

    def test_tool_use_count(self):
        agent = _make_agent_summary()
        result = _agent_detail(agent)
        self.assertIn("Tool calls:", result)
        self.assertIn("8", result)

    def test_cost_shown(self):
        agent = _make_agent_summary()
        result = _agent_detail(agent)
        self.assertIn("Cost:", result)

    def test_total_tokens_shown(self):
        agent = _make_agent_summary()
        result = _agent_detail(agent)
        self.assertIn("Total tokens:", result)


# ---------------------------------------------------------------------------
# _render_timeline_line
# ---------------------------------------------------------------------------

class TestRenderTimelineLine(unittest.TestCase):
    def test_basic_fields_present(self):
        evt = _make_event(tool_name="Bash", classification="productive")
        result = _render_timeline_line(evt)
        self.assertIn("Bash", result)

    def test_with_waste_reason(self):
        evt = _make_event(waste_reason="bash-as-grep")
        result = _render_timeline_line(evt)
        self.assertIn("GREP", result)

    def test_without_waste_reason(self):
        evt = _make_event(waste_reason=None)
        result = _render_timeline_line(evt)
        self.assertNotIn("GREP", result)

    def test_with_cost_usd(self):
        evt = _make_event(cost_usd=0.0042)
        result = _render_timeline_line(evt)
        self.assertIn("0.0042", result)

    def test_without_cost_usd(self):
        evt = _make_event(cost_usd=None)
        result = _render_timeline_line(evt)
        self.assertNotIn("$0.", result)

    def test_timestamp_format_hhmmss(self):
        import re
        evt = _make_event()
        result = _render_timeline_line(evt)
        self.assertIsNotNone(re.search(r"\d{2}:\d{2}:\d{2}", result))

    def test_classification_none_defaults_to_neutral(self):
        evt = _make_event(classification=None)
        result = _render_timeline_line(evt)
        self.assertIsInstance(result, str)

    def test_tool_name_none_handled(self):
        evt = _make_event(tool_name=None)
        result = _render_timeline_line(evt)
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# _stats_duration_str
# ---------------------------------------------------------------------------

class TestStatsDurationStr(unittest.TestCase):
    def test_with_end_time(self):
        summary = _make_summary(end_time_offset_secs=3661)
        result = _stats_duration_str(summary)
        self.assertEqual(result, "01:01:01")

    def test_exact_zero(self):
        summary = _make_summary(end_time_offset_secs=0)
        result = _stats_duration_str(summary)
        self.assertEqual(result, "00:00:00")

    def test_live_mode_returns_elapsed_string(self):
        import re
        summary = _make_summary(end_time_offset_secs=None)
        result = _stats_duration_str(summary)
        self.assertIsNotNone(re.match(r"^\d{2}:\d{2}:\d{2}$", result))

    def test_format_is_two_digit_padded(self):
        summary = _make_summary(end_time_offset_secs=5)
        result = _stats_duration_str(summary)
        self.assertEqual(result, "00:00:05")


# ---------------------------------------------------------------------------
# _stats_session_label
# ---------------------------------------------------------------------------

class TestStatsSessionLabel(unittest.TestCase):
    def test_returns_last_path_segment(self):
        summary = _make_summary(project_path="/home/user/myproject")
        result = _stats_session_label(summary)
        self.assertEqual(result, "myproject")

    def test_multi_segment_path(self):
        summary = _make_summary(project_path="/a/b/c/dancing-bear")
        result = _stats_session_label(summary)
        self.assertEqual(result, "dancing-bear")

    def test_project_path_none_falls_back_to_session_id(self):
        summary = _make_summary(project_path=None, session_id="abc123def4560000")
        result = _stats_session_label(summary)
        self.assertEqual(result, "abc123def4560000")

    def test_long_segment_truncated_to_24(self):
        long_name = "a" * 30
        summary = _make_summary(project_path=f"/home/user/{long_name}")
        result = _stats_session_label(summary)
        self.assertLessEqual(len(result), 24)

    def test_trailing_slash_handled(self):
        summary = _make_summary(project_path="/home/user/myproject/")
        result = _stats_session_label(summary)
        self.assertEqual(result, "myproject")

    def test_root_path_falls_back_to_session_id(self):
        summary = _make_summary(project_path="/", session_id="abc123def4560000")
        result = _stats_session_label(summary)
        self.assertEqual(result, "abc123def4560000")


# ---------------------------------------------------------------------------
# _efficiency_color
# ---------------------------------------------------------------------------

class TestEfficiencyColor(unittest.TestCase):
    def test_above_75_returns_green(self):
        self.assertEqual(_efficiency_color(100.0), "green")
        self.assertEqual(_efficiency_color(76.0), "green")

    def test_exactly_75_returns_green(self):
        self.assertEqual(_efficiency_color(75.0), "green")

    def test_between_50_and_75_returns_yellow(self):
        self.assertEqual(_efficiency_color(74.9), "yellow")
        self.assertEqual(_efficiency_color(60.0), "yellow")

    def test_exactly_50_returns_yellow(self):
        self.assertEqual(_efficiency_color(50.0), "yellow")

    def test_below_50_returns_red(self):
        self.assertEqual(_efficiency_color(49.9), "red")
        self.assertEqual(_efficiency_color(0.0), "red")

    def test_clearly_above_75(self):
        self.assertEqual(_efficiency_color(90.0), "green")

    def test_clearly_below_50(self):
        self.assertEqual(_efficiency_color(10.0), "red")


# ---------------------------------------------------------------------------
# _render_stats_panel
# ---------------------------------------------------------------------------

class TestRenderStatsPanel(unittest.TestCase):
    def test_returns_panel_instance(self):
        summary = _make_summary()
        result = _render_stats_panel(summary)
        self.assertIsInstance(result, Panel)

    def test_rendered_output_contains_model(self):
        summary = _make_summary(model="anthropic/claude-sonnet-4-6")
        panel = _render_stats_panel(summary)
        text = _render_panel_text(panel)
        self.assertIn("claude-sonnet-4-6", text)

    def test_rendered_output_contains_cost(self):
        summary = _make_summary(total_cost=0.05)
        panel = _render_stats_panel(summary)
        text = _render_panel_text(panel)
        self.assertIn("0.05", text)

    def test_rendered_output_contains_duration(self):
        summary = _make_summary(end_time_offset_secs=3661)
        panel = _render_stats_panel(summary)
        text = _render_panel_text(panel)
        self.assertIn("01:01:01", text)

    def test_rendered_output_contains_session_label(self):
        summary = _make_summary(project_path="/home/user/dancing-bear")
        panel = _render_stats_panel(summary)
        text = _render_panel_text(panel)
        self.assertIn("dancing-bear", text)

    def test_rendered_output_contains_productive_count(self):
        summary = _make_summary(productive_count=10, avoidable_count=3)
        panel = _render_stats_panel(summary)
        text = _render_panel_text(panel)
        self.assertIn("10", text)
        self.assertIn("3", text)

    def test_cache_hit_rate_shown(self):
        summary = _make_summary(cache_hit_rate=0.6)
        panel = _render_stats_panel(summary)
        text = _render_panel_text(panel)
        self.assertIn("60%", text)

    def test_cache_na_when_none(self):
        summary = _make_summary(cache_hit_rate=None)
        panel = _render_stats_panel(summary)
        text = _render_panel_text(panel)
        self.assertIn("n/a", text)


# ---------------------------------------------------------------------------
# _render_stats_compact
# ---------------------------------------------------------------------------

class TestRenderStatsCompact(unittest.TestCase):
    def test_with_cache_hit_rate(self):
        summary = _make_summary(cache_hit_rate=0.8)
        result = _render_stats_compact(summary)
        self.assertIn("80%↑", result)

    def test_without_cache_hit_rate(self):
        summary = _make_summary(cache_hit_rate=None)
        result = _render_stats_compact(summary)
        self.assertIn("n/a", result)

    def test_model_short_name(self):
        summary = _make_summary(model="anthropic/claude-sonnet-4-6")
        result = _render_stats_compact(summary)
        self.assertIn("claude-sonnet-4-6", result)

    def test_efficiency_score_in_output(self):
        summary = _make_summary(efficiency_score=80.0)
        result = _render_stats_compact(summary)
        self.assertIn("80%", result)

    def test_counts_present(self):
        summary = _make_summary(productive_count=10, avoidable_count=2)
        result = _render_stats_compact(summary)
        self.assertIn("10", result)
        self.assertIn("2", result)

    def test_duration_present(self):
        summary = _make_summary(end_time_offset_secs=3661)
        result = _render_stats_compact(summary)
        self.assertIn("01:01:01", result)


# ---------------------------------------------------------------------------
# _print_tool_stats_panel
# ---------------------------------------------------------------------------

class TestPrintToolStatsPanel(unittest.TestCase):
    def _make_console(self) -> tuple[Console, io.StringIO]:
        buf = io.StringIO()
        console = Console(file=buf, width=100, highlight=False, markup=True)
        return console, buf

    def test_empty_tool_stats_produces_no_output(self):
        console, buf = self._make_console()
        summary = _make_summary(tool_stats={})
        _print_tool_stats_panel(console, summary)
        self.assertEqual(buf.getvalue(), "")

    def test_non_empty_tool_stats_produces_output(self):
        console, buf = self._make_console()
        stat = _make_tool_stats("Bash")
        summary = _make_summary(tool_stats={"Bash": stat})
        _print_tool_stats_panel(console, summary)
        output = buf.getvalue()
        self.assertIn("Bash", output)

    def test_panel_title_in_output(self):
        console, buf = self._make_console()
        stat = _make_tool_stats("Read")
        summary = _make_summary(tool_stats={"Read": stat})
        _print_tool_stats_panel(console, summary)
        output = buf.getvalue()
        self.assertIn("Tool Breakdown", output)

    def test_multiple_tools_rendered(self):
        console, buf = self._make_console()
        stats = {
            "Bash": _make_tool_stats("Bash"),
            "Read": _make_tool_stats("Read"),
        }
        summary = _make_summary(tool_stats=stats)
        _print_tool_stats_panel(console, summary)
        output = buf.getvalue()
        self.assertIn("Bash", output)
        self.assertIn("Read", output)

    def test_avoidable_count_zero_shows_dash(self):
        console, buf = self._make_console()
        stat = ToolStats(tool_name="Grep", count=3, cost=0.01, avoidable_count=0, review_count=0)
        summary = _make_summary(tool_stats={"Grep": stat})
        _print_tool_stats_panel(console, summary)
        output = buf.getvalue()
        self.assertIn("—", output)


# ---------------------------------------------------------------------------
# _print_agents_panel
# ---------------------------------------------------------------------------

class TestPrintAgentsPanel(unittest.TestCase):
    def _make_console(self) -> tuple[Console, io.StringIO]:
        buf = io.StringIO()
        console = Console(file=buf, width=100, highlight=False, markup=True)
        return console, buf

    def test_empty_agents_produces_no_output(self):
        console, buf = self._make_console()
        _print_agents_panel(console, [])
        self.assertEqual(buf.getvalue(), "")

    def test_non_empty_agents_produces_output(self):
        console, buf = self._make_console()
        agent = _make_agent_summary()
        _print_agents_panel(console, [agent])
        output = buf.getvalue()
        self.assertIn("Fix authentication bug", output)

    def test_panel_title_in_output(self):
        console, buf = self._make_console()
        agent = _make_agent_summary()
        _print_agents_panel(console, [agent])
        output = buf.getvalue()
        self.assertIn("Agents", output)

    def test_model_short_name_in_output(self):
        console, buf = self._make_console()
        agent = _make_agent_summary()
        _print_agents_panel(console, [agent])
        output = buf.getvalue()
        self.assertIn("claude-sonnet-4-6", output)

    def test_duration_in_output(self):
        console, buf = self._make_console()
        agent = _make_agent_summary()
        _print_agents_panel(console, [agent])
        output = buf.getvalue()
        self.assertIn("5.0s", output)

    def test_description_truncated_at_25(self):
        console, buf = self._make_console()
        agent = AgentSummary(
            agent_id="a-001",
            agent_type="code-writer",
            description="x" * 30,
            model="claude-sonnet",
            duration_ms=1000,
            total_tokens=100,
            total_tool_uses=2,
            cost_usd=0.001,
        )
        _print_agents_panel(console, [agent])
        output = buf.getvalue()
        self.assertNotIn("x" * 30, output)


if __name__ == "__main__":
    unittest.main()
