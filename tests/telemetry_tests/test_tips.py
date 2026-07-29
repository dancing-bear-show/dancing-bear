"""Tests for telemetry/tips.py — TipsEngine."""
from __future__ import annotations

import unittest

from tests.telemetry_tests.shared_fixtures import _evt, _make_blame, _make_tip, reset_seq
from telemetry.models import BlameTarget, SessionEvent, Tip
from telemetry.tips import TipsEngine


def _avoidable_evt(waste_reason: str = "bash-as-grep", cost: float = 0.05) -> SessionEvent:
    """Build an avoidable event with a blame_target set."""
    evt = _evt(classification="avoidable", waste_reason=waste_reason)
    evt.blame_target = BlameTarget(level="session", name="session", fix_hint="use Grep")
    evt.cost_usd = cost
    return evt


def _review_evt(waste_reason: str = "abandoned-search", cost: float = 0.02) -> SessionEvent:
    """Build a review event with a blame_target set."""
    evt = _evt(classification="review", waste_reason=waste_reason)
    evt.blame_target = BlameTarget(level="session", name="session", fix_hint="reconsider approach")
    evt.cost_usd = cost
    return evt


class TestTipsEngineGenerate(unittest.TestCase):
    def setUp(self):
        reset_seq()
        self.engine = TipsEngine()

    # --- happy paths ---

    def test_single_avoidable_event_produces_tip(self):
        evt = _avoidable_evt()
        tips = self.engine.generate([evt])
        self.assertEqual(len(tips), 1)
        self.assertEqual(tips[0].waste_reason, "bash-as-grep")
        self.assertEqual(tips[0].count, 1)

    def test_single_review_event_produces_tip(self):
        evt = _review_evt()
        tips = self.engine.generate([evt])
        self.assertEqual(len(tips), 1)
        self.assertEqual(tips[0].waste_reason, "abandoned-search")

    def test_empty_events_returns_no_tips(self):
        tips = self.engine.generate([])
        self.assertEqual(tips, [])

    def test_productive_event_excluded(self):
        evt = _evt(classification="productive", tool_name="Edit")
        tips = self.engine.generate([evt])
        self.assertEqual(tips, [])

    def test_neutral_event_excluded(self):
        evt = _evt(classification="neutral", tool_name="Read")
        tips = self.engine.generate([evt])
        self.assertEqual(tips, [])

    def test_event_without_blame_target_excluded(self):
        evt = _evt(classification="avoidable", waste_reason="bash-as-grep")
        evt.blame_target = None
        tips = self.engine.generate([evt])
        self.assertEqual(tips, [])

    def test_event_without_waste_reason_excluded(self):
        evt = _evt(classification="avoidable", waste_reason=None)
        evt.blame_target = BlameTarget(level="session", name="session", fix_hint="x")
        tips = self.engine.generate([evt])
        self.assertEqual(tips, [])

    # --- grouping ---

    def test_same_reason_level_name_grouped(self):
        e1 = _avoidable_evt(waste_reason="bash-as-grep", cost=0.05)
        e2 = _avoidable_evt(waste_reason="bash-as-grep", cost=0.03)
        tips = self.engine.generate([e1, e2])
        self.assertEqual(len(tips), 1)
        self.assertEqual(tips[0].count, 2)
        self.assertAlmostEqual(tips[0].cost_impact, 0.08, places=5)

    def test_different_reasons_produce_separate_tips(self):
        e1 = _avoidable_evt(waste_reason="bash-as-grep")
        e2 = _avoidable_evt(waste_reason="redundant-read")
        tips = self.engine.generate([e1, e2])
        self.assertEqual(len(tips), 2)
        reasons = {t.waste_reason for t in tips}
        self.assertIn("bash-as-grep", reasons)
        self.assertIn("redundant-read", reasons)

    def test_different_levels_produce_separate_tips(self):
        e1 = _avoidable_evt(waste_reason="bash-as-grep")
        e1.blame_target = BlameTarget(level="skill", name="my-skill", fix_hint="use Grep")

        e2 = _avoidable_evt(waste_reason="bash-as-grep")
        e2.blame_target = BlameTarget(level="session", name="session", fix_hint="use Grep")

        tips = self.engine.generate([e1, e2])
        self.assertEqual(len(tips), 2)

    # --- sorting ---

    def test_sorted_by_cost_descending(self):
        e1 = _avoidable_evt(waste_reason="bash-as-grep", cost=0.01)
        e2 = _avoidable_evt(waste_reason="redundant-read", cost=0.10)
        tips = self.engine.generate([e1, e2])
        self.assertEqual(tips[0].waste_reason, "redundant-read")
        self.assertEqual(tips[1].waste_reason, "bash-as-grep")

    # --- max_tips ---

    def test_max_tips_limits_output(self):
        events = [_avoidable_evt(f"reason-{i}") for i in range(10)]
        for e in events:
            e.blame_target = BlameTarget(level="session", name="session", fix_hint="fix")
        tips = self.engine.generate(events, max_tips=3)
        self.assertLessEqual(len(tips), 3)

    def test_max_tips_zero_returns_empty(self):
        evt = _avoidable_evt()
        tips = self.engine.generate([evt], max_tips=0)
        self.assertEqual(tips, [])

    # --- message format ---

    def test_session_level_message_format(self):
        evt = _avoidable_evt(waste_reason="bash-as-grep")
        evt.blame_target = BlameTarget(level="session", name="session", fix_hint="x")
        tips = self.engine.generate([evt])
        self.assertIn("bash-as-grep", tips[0].message)
        self.assertIn("avoidable", tips[0].message)
        self.assertIn("✗", tips[0].message)

    def test_non_session_level_message_includes_name(self):
        evt = _avoidable_evt(waste_reason="bash-as-cat")
        evt.blame_target = BlameTarget(level="skill", name="my-flow", fix_hint="x")
        tips = self.engine.generate([evt])
        self.assertIn("my-flow", tips[0].message)

    def test_review_tip_uses_warning_icon(self):
        evt = _review_evt()
        tips = self.engine.generate([evt])
        self.assertIn("⚠", tips[0].message)

    # --- cost and tip fields ---

    def test_tip_cost_impact_sums_event_costs(self):
        e1 = _avoidable_evt(cost=0.05)
        e2 = _avoidable_evt(cost=0.07)
        tips = self.engine.generate([e1, e2])
        self.assertAlmostEqual(tips[0].cost_impact, 0.12, places=5)

    def test_event_with_none_cost_skipped_in_sum(self):
        e1 = _avoidable_evt(cost=0.05)
        e2 = _avoidable_evt(cost=0.03)
        e2.cost_usd = None  # Override to None
        tips = self.engine.generate([e1, e2])
        self.assertAlmostEqual(tips[0].cost_impact, 0.05, places=5)

    def test_tip_has_fix_hint(self):
        evt = _avoidable_evt()
        tips = self.engine.generate([evt])
        self.assertIsNotNone(tips[0].fix_hint)
        self.assertEqual(tips[0].fix_hint, "use Grep")

    def test_tip_blame_target_set(self):
        evt = _avoidable_evt()
        tips = self.engine.generate([evt])
        self.assertIsInstance(tips[0].blame_target, BlameTarget)

    def test_tip_is_tip_instance(self):
        evt = _avoidable_evt()
        tips = self.engine.generate([evt])
        self.assertIsInstance(tips[0], Tip)


class TestTipsEngineFilters(unittest.TestCase):
    def setUp(self):
        reset_seq()

    def test_exclude_blame_pattern_filters_tip(self):
        engine = TipsEngine(rules={
            "tip_filters": {
                "exclude_blame_patterns": ["superpowers:*"],
                "min_cost_impact": 0.0,
            }
        })
        evt = _avoidable_evt(waste_reason="bash-as-grep", cost=0.10)
        evt.blame_target = BlameTarget(level="skill", name="superpowers:onboarding", fix_hint="x")
        tips = engine.generate([evt])
        self.assertEqual(tips, [])

    def test_exclude_pattern_does_not_filter_non_matching(self):
        engine = TipsEngine(rules={
            "tip_filters": {
                "exclude_blame_patterns": ["superpowers:*"],
                "min_cost_impact": 0.0,
            }
        })
        evt = _avoidable_evt(waste_reason="bash-as-grep", cost=0.10)
        tips = engine.generate([evt])
        self.assertEqual(len(tips), 1)

    def test_min_cost_impact_filters_low_cost_tips(self):
        engine = TipsEngine(rules={
            "tip_filters": {
                "exclude_blame_patterns": [],
                "min_cost_impact": 0.05,
            }
        })
        evt = _avoidable_evt(waste_reason="bash-as-grep", cost=0.01)
        tips = engine.generate([evt])
        self.assertEqual(tips, [])

    def test_min_cost_impact_passes_above_threshold(self):
        engine = TipsEngine(rules={
            "tip_filters": {
                "exclude_blame_patterns": [],
                "min_cost_impact": 0.05,
            }
        })
        evt = _avoidable_evt(waste_reason="bash-as-grep", cost=0.10)
        tips = engine.generate([evt])
        self.assertEqual(len(tips), 1)

    def test_none_rules_uses_defaults(self):
        engine = TipsEngine(rules=None)
        evt = _avoidable_evt()
        # Should not crash with None rules
        tips = engine.generate([evt])
        self.assertIsInstance(tips, list)

    def test_empty_rules_uses_defaults(self):
        engine = TipsEngine(rules={})
        evt = _avoidable_evt()
        tips = engine.generate([evt])
        self.assertIsInstance(tips, list)

    def test_multiple_exclude_patterns(self):
        engine = TipsEngine(rules={
            "tip_filters": {
                "exclude_blame_patterns": ["superpowers:*", "internal:*"],
                "min_cost_impact": 0.0,
            }
        })
        e1 = _avoidable_evt(waste_reason="bash-as-grep", cost=0.10)
        e1.blame_target = BlameTarget(level="skill", name="internal:flow", fix_hint="x")
        e2 = _avoidable_evt(waste_reason="redundant-read", cost=0.10)
        e2.blame_target = BlameTarget(level="skill", name="user:flow", fix_hint="x")
        tips = engine.generate([e1, e2])
        # Only e2 should pass the filter
        self.assertEqual(len(tips), 1)
        self.assertEqual(tips[0].waste_reason, "redundant-read")


if __name__ == "__main__":
    unittest.main()
