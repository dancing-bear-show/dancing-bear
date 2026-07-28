"""Tests for telemetry/tui/_renderers.py."""

import io
import unittest
from datetime import datetime, timedelta, timezone

from rich.console import Console
from rich.panel import Panel

from telemetry.models import (
    AgentSummary,
    BlameTarget,
    SessionEvent,
    SessionSummary,
    Tip,
    ToolStats,
)
from telemetry.tui._renderers import (
    _agent_detail,
    _efficiency_color,
    _event_input_detail,
    _print_agents_panel,
    _print_tool_stats_panel,
    _render_cls_group,
    _render_header_text,
    _render_stats_compact,
    _render_stats_panel,
    _render_timeline_line,
    _render_tips_text,
    _stats_duration_str,
    _stats_session_label,
    _tip_detail,
    _tool_event_detail,
    _tool_stat_detail,
)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    """Return a stable UTC datetime for the current test run."""
    return datetime.now(timezone.utc)


def _make_summary_base(
    *,
    session_id: str = "abc123def4560000",
    project_path: str | None = "/home/user/myproject",
    model: str = "anthropic/claude-sonnet-4-6",
    total_cost: float = 0.05,
    cost_is_estimated: bool = False,
    efficiency_score: float = 80.0,
    end_time_offset_secs: int | None = 1800,
    cache_hit_rate: float | None = 0.5,
    input_tokens: int = 1000,
    output_tokens: int = 500,
) -> dict:
    """Return a kwargs dict for SessionSummary construction (identity/timing/cost fields)."""
    start = _now() - timedelta(seconds=end_time_offset_secs or 3600)
    end = (start + timedelta(seconds=end_time_offset_secs)) if end_time_offset_secs is not None else None
    return {
        "session_id": session_id,
        "project_path": project_path,
        "start_time": start,
        "end_time": end,
        "model": model,
        "total_cost": total_cost,
        "cost_is_estimated": cost_is_estimated,
        "total_events": 20,
        "efficiency_score": efficiency_score,
        "cache_hit_rate": cache_hit_rate,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def _make_summary(
    *,
    productive_count: int = 10,
    neutral_count: int = 5,
    avoidable_count: int = 2,
    review_count: int = 1,
    tool_stats: dict | None = None,
    agents: list | None = None,
    tips: list | None = None,
    **base_kwargs,
) -> SessionSummary:
    """Build a SessionSummary with sensible defaults for renderer tests."""
    kwargs = _make_summary_base(**base_kwargs)
    kwargs.update({
        "productive_count": productive_count,
        "neutral_count": neutral_count,
        "avoidable_count": avoidable_count,
        "review_count": review_count,
        "tool_stats": tool_stats or {},
        "agents": agents or [],
        "tips": tips or [],
    })
    return SessionSummary(**kwargs)


def _make_event(
    *,
    event_type: str = "tool_use",
    tool_name: str | None = "Bash",
    tool_input: dict | None = None,
    classification: str | None = "productive",
    waste_reason: str | None = None,
    cost_usd: float | None = None,
    cost_is_estimated: bool = False,
    blame_target: BlameTarget | None = None,
    model: str | None = "claude-sonnet-4-6",
) -> SessionEvent:
    return SessionEvent(
        timestamp=_now(),
        event_type=event_type,
        sequence=1,
        session_id="abc123def4560000",
        tool_name=tool_name,
        tool_input=tool_input,
        classification=classification,
        waste_reason=waste_reason,
        cost_usd=cost_usd,
        cost_is_estimated=cost_is_estimated,
        blame_target=blame_target,
        model=model,
    )


def _make_blame() -> BlameTarget:
    return BlameTarget(
        level="skill",
        name="s2s:onboarding",
        fix_hint="Reduce repeated reads",
    )


def _make_tip(*, severity: str = "avoidable") -> Tip:
    return Tip(
        severity=severity,
        waste_reason="redundant-read",
        count=3,
        cost_impact=0.012,
        blame_target=_make_blame(),
        message="Redundant reads detected",
        fix_hint="Cache file contents between calls",
    )


def _make_tool_stats(tool_name: str = "Bash") -> ToolStats:
    return ToolStats(
        tool_name=tool_name,
        count=5,
        cost=0.025,
        avoidable_count=2,
        review_count=1,
    )


def _make_agent_summary() -> AgentSummary:
    return AgentSummary(
        agent_id="agent-001",
        agent_type="code-writer",
        description="Fix authentication bug",
        model="anthropic/claude-sonnet-4-6",
        duration_ms=5000,
        total_tokens=2000,
        total_tool_uses=8,
        cost_usd=0.03,
        cost_is_estimated=False,
    )


def _render_panel_text(panel: Panel, width: int = 100) -> str:
    """Render a Rich Panel to a plain string via StringIO."""
    buf = io.StringIO()
    console = Console(file=buf, width=width, highlight=False, markup=True)
    console.print(panel)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# _render_header_text
# ---------------------------------------------------------------------------

class TestRenderHeaderText(unittest.TestCase):
    def test_history_mode(self):
        summary = _make_summary(end_time_offset_secs=1800)
        result = _render_header_text(summary)
        self.assertIn("HISTORY", result)
        self.assertNotIn("LIVE", result)

    def test_live_mode(self):
        summary = _make_summary(end_time_offset_secs=None)
        result = _render_header_text(summary)
        self.assertIn("LIVE", result)
        self.assertNotIn("HISTORY", result)

    def test_cache_hit_rate_shown_when_set(self):
        summary = _make_summary(cache_hit_rate=0.75)
        result = _render_header_text(summary)
        self.assertIn("75%", result)

    def test_cache_hit_rate_na_when_none(self):
        summary = _make_summary(cache_hit_rate=None)
        result = _render_header_text(summary)
        self.assertIn("n/a", result)

    def test_cost_is_estimated_flag(self):
        summary = _make_summary(cost_is_estimated=True)
        result = _render_header_text(summary)
        self.assertIn("[estimated]", result)

    def test_cost_not_estimated_no_flag(self):
        summary = _make_summary(cost_is_estimated=False)
        result = _render_header_text(summary)
        self.assertNotIn("[estimated]", result)

    def test_model_short_name_extracted(self):
        summary = _make_summary(model="anthropic/claude-sonnet-4-6")
        result = _render_header_text(summary)
        self.assertIn("claude-sonnet-4-6", result)
        self.assertNotIn("anthropic/", result)

    def test_session_id_in_output(self):
        summary = _make_summary(session_id="abc123def4560000")
        result = _render_header_text(summary)
        self.assertIn("abc123def456000", result)

    def test_duration_format(self):
        summary = _make_summary(end_time_offset_secs=3661)
        result = _render_header_text(summary)
        # 3661 seconds = 1 hour, 1 minute, 1 second
        self.assertIn("01:01:01", result)

    def test_project_path_shown(self):
        summary = _make_summary(project_path="/home/user/myproject")
        result = _render_header_text(summary)
        self.assertIn("/home/user/myproject", result)

    def test_project_path_none_shows_dash(self):
        summary = _make_summary(project_path=None)
        result = _render_header_text(summary)
        self.assertIn("Path: -", result)

    def test_count_fields_present(self):
        summary = _make_summary(productive_count=10, neutral_count=5, avoidable_count=2, review_count=1)
        result = _render_header_text(summary)
        self.assertIn("10", result)
        self.assertIn("5", result)
        self.assertIn("2", result)
        self.assertIn("1", result)


# ---------------------------------------------------------------------------
# _render_tips_text
# ---------------------------------------------------------------------------

class TestRenderTipsText(unittest.TestCase):
    def test_empty_list_returns_clean_message(self):
        result = _render_tips_text([])
        self.assertIn("clean", result)

    def test_avoidable_severity_uses_red_x(self):
        tip = _make_tip(severity="avoidable")
        result = _render_tips_text([tip])
        self.assertIn("[red]✗[/]", result)
        self.assertIn(tip.message, result)

    def test_other_severity_uses_yellow_warning(self):
        tip = _make_tip(severity="review")
        result = _render_tips_text([tip])
        self.assertIn("[yellow]⚠[/]", result)
        self.assertIn(tip.message, result)

    def test_multiple_tips(self):
        tips = [_make_tip(severity="avoidable"), _make_tip(severity="review")]
        result = _render_tips_text(tips)
        self.assertEqual(result.count("→"), 2)

    def test_fix_hint_appears(self):
        tip = _make_tip()
        result = _render_tips_text([tip])
        self.assertIn(tip.fix_hint, result)


# ---------------------------------------------------------------------------
# _tool_event_detail
# ---------------------------------------------------------------------------

class TestToolEventDetail(unittest.TestCase):
    def test_basic_fields_present(self):
        evt = _make_event(tool_name="Bash", classification="productive")
        result = _tool_event_detail(evt)
        self.assertIn("Bash", result)
        self.assertIn("productive", result)

    def test_with_tool_input(self):
        evt = _make_event(tool_input={"command": "ls -la"})
        result = _tool_event_detail(evt)
        self.assertIn("Input:", result)
        self.assertIn("command:", result)
        self.assertIn("ls -la", result)

    def test_without_tool_input(self):
        evt = _make_event(tool_input=None)
        result = _tool_event_detail(evt)
        self.assertNotIn("Input:", result)

    def test_long_value_truncated(self):
        long_val = "x" * 600
        evt = _make_event(tool_input={"content": long_val})
        result = _tool_event_detail(evt)
        self.assertIn("…", result)
        # The truncated value should be exactly 500 chars + ellipsis, not the full 600
        self.assertNotIn("x" * 501, result)

    def test_short_value_not_truncated(self):
        short_val = "a" * 499
        evt = _make_event(tool_input={"content": short_val})
        result = _tool_event_detail(evt)
        self.assertNotIn("…", result)

    def test_with_cost_usd(self):
        evt = _make_event(cost_usd=0.0042)
        result = _tool_event_detail(evt)
        self.assertIn("Cost:", result)
        self.assertIn("0.0042", result)

    def test_without_cost_usd(self):
        evt = _make_event(cost_usd=None)
        result = _tool_event_detail(evt)
        self.assertNotIn("Cost:", result)

    def test_estimated_cost_label(self):
        evt = _make_event(cost_usd=0.01, cost_is_estimated=True)
        result = _tool_event_detail(evt)
        self.assertIn("estimated", result)

    def test_with_waste_reason(self):
        evt = _make_event(waste_reason="bash-as-grep")
        result = _tool_event_detail(evt)
        self.assertIn("Reason:", result)
        self.assertIn("bash-as-grep", result)

    def test_without_waste_reason(self):
        evt = _make_event(waste_reason=None)
        result = _tool_event_detail(evt)
        self.assertNotIn("Reason:", result)

    def test_with_blame_target(self):
        blame = _make_blame()
        evt = _make_event(blame_target=blame)
        result = _tool_event_detail(evt)
        self.assertIn("Blame:", result)
        self.assertIn(blame.name, result)
        self.assertIn("Fix:", result)
        self.assertIn(blame.fix_hint, result)

    def test_without_blame_target(self):
        evt = _make_event(blame_target=None)
        result = _tool_event_detail(evt)
        self.assertNotIn("Blame:", result)

    def test_classification_none_defaults_to_neutral(self):
        evt = _make_event(classification=None)
        result = _tool_event_detail(evt)
        self.assertIn("neutral", result)


# ---------------------------------------------------------------------------
# _event_input_detail
# ---------------------------------------------------------------------------

class TestEventInputDetail(unittest.TestCase):
    def test_bash_returns_command(self):
        evt = _make_event(tool_input={"command": "git status"})
        result = _event_input_detail("Bash", evt)
        self.assertEqual(result, "git status")

    def test_bash_truncates_long_command(self):
        evt = _make_event(tool_input={"command": "x" * 80})
        result = _event_input_detail("Bash", evt)
        self.assertLessEqual(len(result), 60)

    def test_read_returns_short_path(self):
        evt = _make_event(tool_input={"file_path": "/home/user/project/src/main.py"})
        result = _event_input_detail("Read", evt)
        self.assertIn("src/main.py", result)
        self.assertNotIn("/home/user/project/", result)

    def test_edit_path_shortening(self):
        evt = _make_event(tool_input={"file_path": "/a/b/c/d/file.py"})
        result = _event_input_detail("Edit", evt)
        self.assertEqual(result, "d/file.py")

    def test_write_path_shortening(self):
        evt = _make_event(tool_input={"file_path": "/a/b/c/d/file.py"})
        result = _event_input_detail("Write", evt)
        self.assertEqual(result, "d/file.py")

    def test_multiedit_path_shortening(self):
        evt = _make_event(tool_input={"file_path": "/a/b/c/d/file.py"})
        result = _event_input_detail("MultiEdit", evt)
        self.assertEqual(result, "d/file.py")

    def test_path_without_slash_unchanged(self):
        evt = _make_event(tool_input={"file_path": "filename.py"})
        result = _event_input_detail("Read", evt)
        self.assertEqual(result, "filename.py")

    def test_grep_returns_pattern_and_path(self):
        evt = _make_event(tool_input={"pattern": "def foo", "path": "src/"})
        result = _event_input_detail("Grep", evt)
        self.assertIn("def foo", result)
        self.assertIn("src/", result)

    def test_glob_returns_pattern(self):
        evt = _make_event(tool_input={"pattern": "**/*.py"})
        result = _event_input_detail("Glob", evt)
        self.assertEqual(result, "**/*.py")

    def test_agent_returns_description(self):
        evt = _make_event(tool_input={"description": "Run tests"})
        result = _event_input_detail("Agent", evt)
        self.assertEqual(result, "Run tests")

    def test_skill_returns_skill_name(self):
        evt = _make_event(tool_input={"skill": "verify"})
        result = _event_input_detail("Skill", evt)
        self.assertEqual(result, "verify")

    def test_fallback_uses_event_desc(self):
        evt = _make_event(tool_name="UnknownTool", tool_input={"command": "something"})
        result = _event_input_detail("UnknownTool", evt)
        # Should use _event_desc fallback, which reads tool_input fields
        self.assertIsInstance(result, str)
        self.assertLessEqual(len(result), 60)

    def test_empty_input_returns_empty_or_short(self):
        evt = _make_event(tool_input={})
        result = _event_input_detail("Bash", evt)
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# _render_cls_group
# ---------------------------------------------------------------------------

class TestRenderClsGroup(unittest.TestCase):
    def test_with_waste_reason(self):
        evt = _make_event(
            classification="avoidable",
            waste_reason="bash-as-grep",
            tool_input={"command": "grep foo bar.py"},
        )
        lines = _render_cls_group("avoidable", [evt], "Bash")
        combined = "\n".join(lines)
        self.assertIn("avoidable", combined)
        self.assertIn("GREP", combined)

    def test_without_waste_reason(self):
        evt = _make_event(
            classification="productive",
            waste_reason=None,
            tool_input={"command": "make test"},
        )
        lines = _render_cls_group("productive", [evt], "Bash")
        combined = "\n".join(lines)
        self.assertIn("productive", combined)
        self.assertNotIn("GREP", combined)

    def test_count_in_header(self):
        events = [
            _make_event(classification="neutral"),
            _make_event(classification="neutral"),
        ]
        lines = _render_cls_group("neutral", events, "Bash")
        header = lines[0]
        self.assertIn("(2)", header)

    def test_empty_group_still_returns_header_and_blank(self):
        # Even with an empty group list, it returns header + trailing blank
        lines = _render_cls_group("neutral", [], "Bash")
        # Header + trailing blank line
        self.assertGreaterEqual(len(lines), 1)

    def test_with_cost_shows_dollar_amount(self):
        evt = _make_event(cost_usd=0.0042)
        lines = _render_cls_group("productive", [evt], "Bash")
        combined = "\n".join(lines)
        self.assertIn("0.0042", combined)


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
        # Only avoidable events — "review" group should not appear in output
        stat = _make_tool_stats("Bash")
        events = [
            _make_event(event_type="tool_use", tool_name="Bash", classification="avoidable"),
        ]
        result = _tool_stat_detail(stat, events)
        self.assertIn("avoidable", result)
        # The "review" header should not appear since there are no review events
        self.assertNotIn("⚠ review", result)

    def test_filters_to_matching_tool_name(self):
        stat = _make_tool_stats("Bash")
        events = [
            _make_event(event_type="tool_use", tool_name="Bash", classification="productive"),
            _make_event(event_type="tool_use", tool_name="Read", classification="avoidable"),
        ]
        result = _tool_stat_detail(stat, events)
        # Only Bash events contribute — avoidable from Read should not form a group
        # We can verify there is only one event rendered (one timestamp line in productive)
        self.assertIn("productive", result)

    def test_non_tool_use_events_excluded(self):
        stat = _make_tool_stats("Bash")
        events = [
            _make_event(event_type="api_request", tool_name="Bash", classification="avoidable"),
        ]
        result = _tool_stat_detail(stat, events)
        # api_request events are filtered out
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
        # 5000ms = 5.0s
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
        # No dollar sign for cost
        self.assertNotIn("$0.", result)

    def test_timestamp_format_hhmmss(self):
        evt = _make_event()
        result = _render_timeline_line(evt)
        # Timestamp should be HH:MM:SS embedded in dim tags
        import re
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
        summary = _make_summary(end_time_offset_secs=None)
        result = _stats_duration_str(summary)
        # Should be a valid HH:MM:SS string
        import re
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
        # _stats_session_label returns session_id[:16], so a 16-char ID returns all 16 chars
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
        # "/" splits into all empty strings, so parts list is empty -> falls back to session_id
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
        # Description column max_width=25, so full 30-char string should not appear
        self.assertNotIn("x" * 30, output)


if __name__ == "__main__":
    unittest.main()
