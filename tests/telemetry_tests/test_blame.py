"""Tests for telemetry/blame.py — BlameEngine."""
from __future__ import annotations

import unittest

from tests.telemetry_tests.shared_fixtures import _evt, _make_blame, reset_seq
from telemetry.blame import BlameEngine
from telemetry.models import BlameTarget


class TestBlameEngineAttribute(unittest.TestCase):
    def setUp(self):
        reset_seq()
        self.engine = BlameEngine(rules={})

    # --- happy paths ---

    def test_avoidable_event_gets_session_blame(self):
        evt = _evt(classification="avoidable", waste_reason="bash-as-grep")
        self.engine.attribute([evt])
        self.assertIsNotNone(evt.blame_target)
        self.assertEqual(evt.blame_target.level, "session")
        self.assertEqual(evt.blame_target.name, "session")

    def test_review_event_gets_session_blame(self):
        evt = _evt(classification="review", waste_reason="abandoned-search")
        self.engine.attribute([evt])
        self.assertIsNotNone(evt.blame_target)
        self.assertEqual(evt.blame_target.level, "session")

    def test_productive_event_blame_cleared(self):
        evt = _evt(classification="productive", tool_name="Edit")
        # Pre-set blame to verify it's cleared
        evt.blame_target = _make_blame()
        self.engine.attribute([evt])
        self.assertIsNone(evt.blame_target)

    def test_neutral_event_blame_cleared(self):
        evt = _evt(classification="neutral", tool_name="Read")
        evt.blame_target = _make_blame()
        self.engine.attribute([evt])
        self.assertIsNone(evt.blame_target)

    def test_none_classification_blame_cleared(self):
        evt = _evt(classification=None, tool_name="Read")
        self.engine.attribute([evt])
        self.assertIsNone(evt.blame_target)

    # --- skill context ---

    def test_skill_event_updates_active_skill(self):
        skill_evt = _evt(
            tool_name="Skill",
            event_type="tool_use",
            tool_input={"skill": "onboarding"},
        )
        avoidable_evt = _evt(classification="avoidable", waste_reason="redundant-read")
        self.engine.attribute([skill_evt, avoidable_evt])
        self.assertEqual(avoidable_evt.blame_target.level, "skill")
        self.assertEqual(avoidable_evt.blame_target.name, "onboarding")

    def test_skill_context_persists_across_subsequent_events(self):
        skill_evt = _evt(
            tool_name="Skill",
            event_type="tool_use",
            tool_input={"skill": "deploy"},
        )
        evt1 = _evt(classification="avoidable", waste_reason="bash-as-grep")
        evt2 = _evt(classification="avoidable", waste_reason="redundant-read")
        self.engine.attribute([skill_evt, evt1, evt2])
        self.assertEqual(evt1.blame_target.name, "deploy")
        self.assertEqual(evt2.blame_target.name, "deploy")

    def test_skill_tool_without_skill_key_does_not_update(self):
        skill_evt = _evt(tool_name="Skill", tool_input={})
        avoidable_evt = _evt(classification="avoidable", waste_reason="bash-as-cat")
        self.engine.attribute([skill_evt, avoidable_evt])
        # No skill name extracted — falls through to session
        self.assertEqual(avoidable_evt.blame_target.level, "session")

    # --- agent context ---

    def test_agent_context_overrides_skill(self):
        skill_evt = _evt(
            tool_name="Skill",
            event_type="tool_use",
            tool_input={"skill": "my-skill"},
        )
        avoidable_evt = _evt(classification="avoidable", waste_reason="bash-as-grep")
        self.engine.attribute([skill_evt, avoidable_evt], agent_context="code-writer")
        self.assertEqual(avoidable_evt.blame_target.level, "agent")
        self.assertEqual(avoidable_evt.blame_target.name, "code-writer")

    def test_agent_context_no_skill(self):
        evt = _evt(classification="review", waste_reason="fruitless-agent")
        self.engine.attribute([evt], agent_context="tester")
        self.assertEqual(evt.blame_target.level, "agent")
        self.assertEqual(evt.blame_target.name, "tester")

    # --- fix hints ---

    def test_fix_hint_from_rules(self):
        engine = BlameEngine(rules={
            "fix_hints": {
                "bash-as-grep": {
                    "session": "Session: use Grep tool instead.",
                    "skill": "Skill {name}: use Grep tool.",
                }
            }
        })
        evt = _evt(classification="avoidable", waste_reason="bash-as-grep")
        engine.attribute([evt])
        self.assertIn("Grep", evt.blame_target.fix_hint)

    def test_fix_hint_skill_level_uses_name_format(self):
        engine = BlameEngine(rules={
            "fix_hints": {
                "redundant-read": {
                    "skill": "Skill {name} read the same file multiple times.",
                }
            }
        })
        skill_evt = _evt(tool_name="Skill", tool_input={"skill": "my-skill"})
        evt = _evt(classification="avoidable", waste_reason="redundant-read")
        engine.attribute([skill_evt, evt])
        self.assertIn("my-skill", evt.blame_target.fix_hint)

    def test_fix_hint_fallback_when_no_waste_reason(self):
        evt = _evt(classification="avoidable", waste_reason=None)
        self.engine.attribute([evt])
        # Default hint includes level-based text
        self.assertIn("waste", evt.blame_target.fix_hint.lower())

    def test_fix_hint_fallback_when_reason_not_in_rules(self):
        evt = _evt(classification="avoidable", waste_reason="unknown-reason")
        self.engine.attribute([evt])
        # Default template includes the waste reason
        self.assertIn("unknown-reason", evt.blame_target.fix_hint)

    def test_fix_hint_format_error_returns_template(self):
        # Template with a bad format spec — should not raise
        engine = BlameEngine(rules={
            "fix_hints": {
                "bash-as-cat": {
                    "session": "Bad format {missing_key}.",
                }
            }
        })
        evt = _evt(classification="avoidable", waste_reason="bash-as-cat")
        engine.attribute([evt])
        # Should not raise; returns raw template
        self.assertIsInstance(evt.blame_target.fix_hint, str)

    # --- edge cases ---

    def test_empty_events_list_no_error(self):
        self.engine.attribute([])  # Should not raise

    def test_blame_target_is_blame_target_instance(self):
        evt = _evt(classification="avoidable", waste_reason="bash-as-grep")
        self.engine.attribute([evt])
        self.assertIsInstance(evt.blame_target, BlameTarget)

    def test_skill_none_tool_input_does_not_crash(self):
        skill_evt = _evt(tool_name="Skill", tool_input=None)
        evt = _evt(classification="avoidable", waste_reason="bash-as-grep")
        self.engine.attribute([skill_evt, evt])
        # Should not crash — active_skill stays None, falls to session
        self.assertEqual(evt.blame_target.level, "session")


class TestGetFixHint(unittest.TestCase):
    def test_no_waste_reason_returns_generic(self):
        engine = BlameEngine(rules={})
        hint = engine._get_fix_hint(None, "session", "session")
        self.assertIn("waste", hint.lower())

    def test_waste_reason_no_matching_rules_uses_default_template(self):
        engine = BlameEngine(rules={"fix_hints": {}})
        hint = engine._get_fix_hint("some-reason", "session", "my-session")
        self.assertIn("some-reason", hint)

    def test_waste_reason_with_matching_hint(self):
        engine = BlameEngine(rules={
            "fix_hints": {
                "bash-as-grep": {
                    "agent": "Agent {name}: use Grep.",
                }
            }
        })
        hint = engine._get_fix_hint("bash-as-grep", "agent", "code-writer")
        self.assertIn("code-writer", hint)
        self.assertIn("Grep", hint)


if __name__ == "__main__":
    unittest.main()
