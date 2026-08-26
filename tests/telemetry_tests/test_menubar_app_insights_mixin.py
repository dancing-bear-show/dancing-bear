"""Tests for InsightsMixin in telemetry/_menubar_app_insights.py.

All assertions pin formatted output strings on SimpleNamespace row objects.
No mock call counts; no network access.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from telemetry._menubar_app_insights import InsightsMixin
from telemetry._menubar_config import _MAX_TIPS_LIMIT

_NUM_TIPS = _MAX_TIPS_LIMIT


def _make_host() -> InsightsMixin:
    class _Host(InsightsMixin):
        def _copy_to_clipboard(self, text: str) -> None:  # noqa: ARG002
            pass

        def _notify(self, title: str, msg: str) -> None:  # noqa: ARG002
            pass

    host = _Host()
    host._hdr_insights = NS(title="SENTINEL")
    host._info_insights_summary = NS(title="")
    host._insights_tip_rows = [NS(title="", hidden=False) for _ in range(_NUM_TIPS)]
    host._insights_tip_hints = [{} for _ in range(_NUM_TIPS)]
    return host


class TestProjectLabelFromPath(unittest.TestCase):
    """_project_label_from_path extracts the last dash-segment, truncated to 32 chars."""

    def test_returns_last_segment(self):
        result = InsightsMixin._project_label_from_path("/Users/foo/-Users-foo-code-myproject")
        self.assertEqual(result, "myproject")

    def test_none_returns_empty_string(self):
        self.assertEqual(InsightsMixin._project_label_from_path(None), "")

    def test_empty_string_returns_empty_string(self):
        self.assertEqual(InsightsMixin._project_label_from_path(""), "")

    def test_single_segment_no_dash(self):
        self.assertEqual(InsightsMixin._project_label_from_path("/a/b/c/nondashed"), "nondashed")

    def test_truncates_at_32_chars(self):
        long_name = "a" * 50
        result = InsightsMixin._project_label_from_path(f"/path/{long_name}")
        self.assertEqual(len(result), 32)
        self.assertEqual(result, "a" * 32)


class TestRenderInsightsPayloadNone(unittest.TestCase):
    """When payload=None the section shows a 'data not available' placeholder."""

    def setUp(self):
        self.host = _make_host()
        self.host._render_insights(None)

    def test_header_set_to_insights(self):
        self.assertEqual(self.host._hdr_insights.title, "-- Insights --")

    def test_summary_shows_unavailable_message(self):
        self.assertEqual(
            self.host._info_insights_summary.title,
            "  ccpulse data not available",
        )

    def test_all_tip_rows_hidden(self):
        for i, row in enumerate(self.host._insights_tip_rows):
            with self.subTest(row=i):
                self.assertTrue(row.hidden)

    def test_all_tip_hints_cleared(self):
        for i, hint in enumerate(self.host._insights_tip_hints):
            with self.subTest(hint=i):
                self.assertEqual(hint, {})


class TestRenderInsightsWithProjectPath(unittest.TestCase):
    """Header includes the project short-name when project_path is present."""

    def test_header_includes_project_label(self):
        host = _make_host()
        host._render_insights({
            "project_path": "/Users/user/projects/my-project",
            "efficiency_score": 78.5,
            "waste_summary": {"avoidable": 3, "review": 5},
            "cost_usd": 1.234,
            "cost_is_estimated": False,
            "tips": [],
        })
        self.assertEqual(host._hdr_insights.title, "-- Insights (project) --")

    def test_summary_line_format(self):
        host = _make_host()
        host._render_insights({
            "project_path": "/Users/user/projects/my-project",
            "efficiency_score": 78.5,
            "waste_summary": {"avoidable": 3, "review": 5},
            "cost_usd": 1.234,
            "cost_is_estimated": False,
            "tips": [],
        })
        self.assertEqual(
            host._info_insights_summary.title,
            "  Eff 78%  |  3 avoid / 5 review  |  $1.23",
        )


class TestRenderInsightsNoProjectPath(unittest.TestCase):
    """Header falls back to 'current session' when project_path is absent."""

    def test_header_shows_current_session(self):
        host = _make_host()
        host._render_insights({
            "project_path": None,
            "efficiency_score": 50.0,
            "waste_summary": {"avoidable": 1, "review": 2},
            "cost_usd": 0.5,
            "cost_is_estimated": True,
            "tips": [],
        })
        self.assertEqual(host._hdr_insights.title, "-- Insights (current session) --")

    def test_summary_estimated_cost_prefix(self):
        host = _make_host()
        host._render_insights({
            "project_path": None,
            "efficiency_score": 50.0,
            "waste_summary": {"avoidable": 1, "review": 2},
            "cost_usd": 0.5,
            "cost_is_estimated": True,
            "tips": [],
        })
        # _format_cost prepends '~' for estimated costs
        self.assertIn("~$0.50", host._info_insights_summary.title)


class TestRenderInsightsTips(unittest.TestCase):
    """_render_tip_row formats rows correctly and toggles hidden."""

    def _host_with_tips(self, tips, max_tips=_NUM_TIPS):
        host = _make_host()
        host._render_insights(
            {
                "project_path": None,
                "efficiency_score": 60.0,
                "waste_summary": {},
                "cost_usd": 0.0,
                "cost_is_estimated": False,
                "tips": tips,
            },
            max_tips=max_tips,
        )
        return host

    def test_avoidable_severity_uses_x_icon(self):
        host = self._host_with_tips([
            {"severity": "avoidable", "count": 5, "waste_reason": "re-reads",
             "cost_impact": 0.12, "claude_rule": "", "fix_hint": ""},
        ])
        self.assertIn("✗", host._insights_tip_rows[0].title)

    def test_non_avoidable_severity_uses_warning_icon(self):
        host = self._host_with_tips([
            {"severity": "warning", "count": 3, "waste_reason": "long chains",
             "cost_impact": 0.05, "claude_rule": "", "fix_hint": ""},
        ])
        self.assertIn("⚠", host._insights_tip_rows[0].title)

    def test_tip_row_title_format(self):
        host = self._host_with_tips([
            {"severity": "avoidable", "count": 5, "waste_reason": "redundant re-reads",
             "cost_impact": 0.12, "claude_rule": "Always read before write", "fix_hint": ""},
        ])
        self.assertEqual(
            host._insights_tip_rows[0].title,
            "  ✗ 5× redundant re-reads  ·  saves ~$0.12",
        )

    def test_tip_row_not_hidden_when_data_present(self):
        host = self._host_with_tips([
            {"severity": "avoidable", "count": 1, "waste_reason": "x", "cost_impact": 0.0,
             "claude_rule": "", "fix_hint": ""},
        ])
        self.assertFalse(host._insights_tip_rows[0].hidden)

    def test_extra_tip_rows_hidden(self):
        host = self._host_with_tips([
            {"severity": "avoidable", "count": 1, "waste_reason": "x", "cost_impact": 0.0,
             "claude_rule": "", "fix_hint": ""},
        ])
        # Rows beyond the single tip should be hidden
        for i in range(1, _NUM_TIPS):
            with self.subTest(row=i):
                self.assertTrue(host._insights_tip_rows[i].hidden)

    def test_tip_hints_populated_for_present_rows(self):
        host = self._host_with_tips([
            {"severity": "avoidable", "count": 5, "waste_reason": "re-reads",
             "cost_impact": 0.12, "claude_rule": "Read rule", "fix_hint": "hint text"},
        ])
        hint = host._insights_tip_hints[0]
        self.assertEqual(hint["waste_reason"], "re-reads")
        self.assertEqual(hint["claude_rule"], "Read rule")
        self.assertEqual(hint["fix_hint"], "hint text")

    def test_tip_hints_empty_for_absent_rows(self):
        host = self._host_with_tips([
            {"severity": "avoidable", "count": 1, "waste_reason": "x",
             "cost_impact": 0.0, "claude_rule": "", "fix_hint": ""},
        ])
        self.assertEqual(host._insights_tip_hints[1], {})

    def test_max_tips_limits_rendered_count(self):
        tips = [
            {"severity": "warning", "count": i, "waste_reason": f"reason{i}",
             "cost_impact": 0.01, "claude_rule": "", "fix_hint": ""}
            for i in range(_NUM_TIPS)
        ]
        host = self._host_with_tips(tips, max_tips=3)
        # Only first 3 rows shown
        for i in range(3):
            self.assertFalse(host._insights_tip_rows[i].hidden)
        for i in range(3, _NUM_TIPS):
            with self.subTest(row=i):
                self.assertTrue(host._insights_tip_rows[i].hidden)

    def test_non_dict_tips_filtered_out(self):
        """Tips that are not dicts are silently ignored."""
        host = self._host_with_tips(["not a dict", 42, None])
        # All rows should be hidden (no valid tips)
        self.assertTrue(host._insights_tip_rows[0].hidden)


class TestRenderInsightsWasteSummaryNotDict(unittest.TestCase):
    """Non-dict waste_summary is treated as empty."""

    def test_non_dict_waste_summary_defaults_to_zero_counts(self):
        host = _make_host()
        host._render_insights({
            "project_path": None,
            "efficiency_score": 40.0,
            "waste_summary": "invalid",
            "cost_usd": 0.0,
            "cost_is_estimated": False,
            "tips": [],
        })
        self.assertIn("0 avoid / 0 review", host._info_insights_summary.title)


class TestMakeTipClickHandler(unittest.TestCase):
    """_make_tip_click_handler: copy-to-clipboard path when no claude_rule."""

    def setUp(self):
        # _handler imports rumps unconditionally at its top, before any branch
        # runs — so every test here needs the module present, not just the ones
        # reaching rumps.alert(). rumps is macOS-only (the [menubar] extra is
        # marked sys_platform == 'darwin'), so on Linux CI the bare import
        # raises ModuleNotFoundError. Stub it for the whole class to keep these
        # tests platform-independent.
        self.mock_rumps = MagicMock()
        patcher = patch.dict("sys.modules", {"rumps": self.mock_rumps})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fix_hint_copies_and_notifies_when_no_rule(self):
        host = _make_host()
        host._insights_tip_hints = [
            {"waste_reason": "reason", "claude_rule": "", "fix_hint": "do this instead"},
        ]
        copied = []
        notified = []

        def fake_copy(text):
            copied.append(text)

        def fake_notify(title, msg):
            notified.append((title, msg))

        host._copy_to_clipboard = fake_copy
        host._notify = fake_notify

        handler = host._make_tip_click_handler(0)
        handler(None)

        self.assertEqual(copied, ["do this instead"])
        self.assertEqual(notified, [("Fix copied", "do this instead")])

    def test_no_fix_hint_no_copy_when_no_rule(self):
        host = _make_host()
        host._insights_tip_hints = [
            {"waste_reason": "reason", "claude_rule": "", "fix_hint": ""},
        ]
        copied = []
        host._copy_to_clipboard = lambda t: copied.append(t)

        handler = host._make_tip_click_handler(0)
        handler(None)

        self.assertEqual(copied, [])

    def test_out_of_bounds_idx_uses_empty_dict(self):
        """An idx beyond the hints list uses an empty dict (no rule, no hint)."""
        host = _make_host()
        host._insights_tip_hints = []  # empty
        copied = []
        notified = []
        host._copy_to_clipboard = lambda t: copied.append(t)
        host._notify = lambda title, msg: notified.append((title, msg))

        handler = host._make_tip_click_handler(99)
        handler(None)

        # With no rule and no fix_hint the handler must be a no-op, not merely
        # non-raising: nothing is copied and the user is not notified.
        self.assertEqual(copied, [])
        self.assertEqual(notified, [])

    def test_rule_present_shows_alert_and_copies_on_confirm(self):
        """When claude_rule is set, handler shows a rumps alert; user clicks Copy."""
        from unittest.mock import MagicMock
        host = _make_host()
        host._insights_tip_hints = [
            {"waste_reason": "re-reads", "claude_rule": "Always read once", "fix_hint": ""},
        ]
        copied = []
        notified = []
        host._copy_to_clipboard = lambda t: copied.append(t)
        host._notify = lambda title, msg: notified.append((title, msg))

        mock_rumps = MagicMock()
        mock_rumps.alert.return_value = 1  # user clicked "Copy"

        handler = host._make_tip_click_handler(0)
        # Patch rumps where it's imported inside the handler's closure
        with patch.dict("sys.modules", {"rumps": mock_rumps}):
            handler(None)

        self.assertEqual(copied, ["Always read once"])
        self.assertEqual(notified, [("Rule copied", "Always read once")])

    def test_rule_present_no_copy_on_cancel(self):
        """When the user dismisses the alert (response != 1), nothing is copied."""
        from unittest.mock import MagicMock
        host = _make_host()
        host._insights_tip_hints = [
            {"waste_reason": "re-reads", "claude_rule": "Always read once", "fix_hint": ""},
        ]
        copied = []
        host._copy_to_clipboard = lambda t: copied.append(t)

        mock_rumps = MagicMock()
        mock_rumps.alert.return_value = 0  # user clicked "Close"

        handler = host._make_tip_click_handler(0)
        with patch.dict("sys.modules", {"rumps": mock_rumps}):
            handler(None)

        self.assertEqual(copied, [])


if __name__ == "__main__":
    unittest.main()
