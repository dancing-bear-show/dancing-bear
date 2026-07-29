"""Tests for tui/_renderers.py — core rendering helpers (header, tips, tool event detail,
event input detail, cls group)."""
from __future__ import annotations

import unittest

from telemetry.tui._renderers import (
    _event_input_detail,
    _render_cls_group,
    _render_header_text,
    _render_tips_text,
    _tool_event_detail,
)

from tests.telemetry_tests.shared_fixtures import (
    _make_blame,
    _make_event,
    _make_summary,
    _make_tip,
)


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
        lines = _render_cls_group("neutral", [], "Bash")
        self.assertGreaterEqual(len(lines), 1)

    def test_with_cost_shows_dollar_amount(self):
        evt = _make_event(cost_usd=0.0042)
        lines = _render_cls_group("productive", [evt], "Bash")
        combined = "\n".join(lines)
        self.assertIn("0.0042", combined)


if __name__ == "__main__":
    unittest.main()
