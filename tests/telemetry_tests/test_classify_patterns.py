"""Tests for classify.py — second-pass pattern rules (TestClassifyAbandonedSearch,
TestClassifyFruitlessAgent, TestClassifyEndToEnd)."""
from __future__ import annotations

import unittest

from telemetry.classify import ClassifyEngine

from tests.telemetry_tests.shared_fixtures import (
    EMPTY_RULES,
    _evt,
    reset_seq,
)


# ===========================================================================
# Second pass — _classify_abandoned_search
# ===========================================================================

class TestClassifyAbandonedSearch(unittest.TestCase):
    def setUp(self):
        reset_seq()

    def _make_rules(self, consecutive_reads: int = 3, enabled: bool = True) -> dict:
        return {
            "review": {
                "abandoned-search": {
                    "enabled": enabled,
                    "consecutive_reads": consecutive_reads,
                }
            }
        }

    def test_three_reads_with_no_write_after_marked_abandoned(self):
        rules = self._make_rules()
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Read", offset_seconds=0),
            _evt(tool_name="Read", offset_seconds=5),
            _evt(tool_name="Read", offset_seconds=10),
        ]
        engine.classify(evts)
        for e in evts:
            self.assertEqual(e.classification, "review")
            self.assertEqual(e.waste_reason, "abandoned-search")

    def test_run_shorter_than_threshold_not_marked(self):
        rules = self._make_rules(consecutive_reads=3)
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Read", offset_seconds=0),
            _evt(tool_name="Read", offset_seconds=5),
        ]
        engine.classify(evts)
        for e in evts:
            self.assertNotEqual(e.waste_reason, "abandoned-search")

    def test_run_followed_by_write_not_marked(self):
        rules = self._make_rules()
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Read", offset_seconds=0),
            _evt(tool_name="Read", offset_seconds=5),
            _evt(tool_name="Read", offset_seconds=10),
            _evt(tool_name="Edit", offset_seconds=15),
        ]
        engine.classify(evts)
        for e in evts[:3]:
            self.assertNotEqual(e.waste_reason, "abandoned-search")

    def test_grep_and_glob_count_as_search_tools(self):
        rules = self._make_rules()
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Grep", offset_seconds=0),
            _evt(tool_name="Glob", offset_seconds=5),
            _evt(tool_name="Read", offset_seconds=10),
        ]
        engine.classify(evts)
        for e in evts:
            self.assertEqual(e.waste_reason, "abandoned-search")

    def test_avoidable_classification_not_overridden(self):
        """Events already classified 'avoidable' must NOT be overridden."""
        evts = [
            _evt(tool_name="Read", tool_input={"file_path": "/foo.py"}, offset_seconds=0),
            _evt(tool_name="Read", tool_input={"file_path": "/foo.py"}, offset_seconds=5),
            _evt(tool_name="Read", tool_input={"file_path": "/foo.py"}, offset_seconds=10),
        ]
        redundant_rules = {
            "avoidable": {"redundant-read": {"enabled": True, "window_seconds": 60, "lookback_events": 10}},
            "review": {"abandoned-search": {"enabled": True, "consecutive_reads": 3}},
        }
        engine = ClassifyEngine(redundant_rules)
        engine.classify(evts)
        self.assertEqual(evts[1].classification, "avoidable")
        self.assertEqual(evts[1].waste_reason, "redundant-read")

    def test_neutral_classification_can_be_overridden(self):
        """Events currently classified 'neutral' should be upgraded to 'review'."""
        rules = self._make_rules()
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Read", offset_seconds=0),
            _evt(tool_name="Read", offset_seconds=5),
            _evt(tool_name="Read", offset_seconds=10),
        ]
        for e in evts:
            e.classification = "neutral"
        engine._second_pass(evts)
        for e in evts:
            self.assertEqual(e.classification, "review")
            self.assertEqual(e.waste_reason, "abandoned-search")

    def test_abandoned_search_rule_disabled(self):
        rules = self._make_rules(enabled=False)
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Read", offset_seconds=0),
            _evt(tool_name="Read", offset_seconds=5),
            _evt(tool_name="Read", offset_seconds=10),
        ]
        engine.classify(evts)
        for e in evts:
            self.assertNotEqual(e.waste_reason, "abandoned-search")

    def test_rule_missing_from_config_defaults_enabled(self):
        """When 'abandoned-search' key absent, enabled defaults True."""
        rules = {"review": {}}
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Read", offset_seconds=0),
            _evt(tool_name="Read", offset_seconds=5),
            _evt(tool_name="Read", offset_seconds=10),
        ]
        engine.classify(evts)
        for e in evts:
            self.assertEqual(e.waste_reason, "abandoned-search")


# ===========================================================================
# Second pass — _classify_fruitless_agent
# ===========================================================================

class TestClassifyFruitlessAgent(unittest.TestCase):
    def setUp(self):
        reset_seq()

    def _make_rules(
        self,
        window_seconds: int = 300,
        lookforward_events: int = 10,
        exempt_agent_types: list | None = None,
        enabled: bool = True,
    ) -> dict:
        rule: dict = {
            "enabled": enabled,
            "window_seconds": window_seconds,
            "lookforward_events": lookforward_events,
        }
        if exempt_agent_types is not None:
            rule["exempt_agent_types"] = exempt_agent_types
        return {"review": {"fruitless-agent": rule}}

    def test_agent_with_no_write_after_marked_fruitless(self):
        rules = self._make_rules()
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Agent", tool_input={"subagent_type": "code-writer"}, offset_seconds=0),
            _evt(tool_name="Read", offset_seconds=10),
        ]
        engine.classify(evts)
        self.assertEqual(evts[0].classification, "review")
        self.assertEqual(evts[0].waste_reason, "fruitless-agent")

    def test_agent_with_write_after_not_marked_fruitless(self):
        rules = self._make_rules()
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Agent", tool_input={"subagent_type": "code-writer"}, offset_seconds=0),
            _evt(tool_name="Edit", offset_seconds=10),
        ]
        engine.classify(evts)
        self.assertNotEqual(evts[0].waste_reason, "fruitless-agent")

    def test_exempt_agent_types_skipped(self):
        for agent_type in ("reviewer", "researcher", "Explore", "fact-checker",
                           "unit-validator", "cross-unit-validator", "claude-code-guide"):
            reset_seq()
            rules = self._make_rules()
            engine = ClassifyEngine(rules)
            evts = [
                _evt(tool_name="Agent", tool_input={"subagent_type": agent_type}, offset_seconds=0),
                _evt(tool_name="Read", offset_seconds=10),
            ]
            engine.classify(evts)
            self.assertNotEqual(
                evts[0].waste_reason, "fruitless-agent",
                f"Expected {agent_type} to be exempt from fruitless-agent"
            )

    def test_custom_exempt_types_honored(self):
        rules = self._make_rules(exempt_agent_types=["my-special-agent"])
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Agent", tool_input={"subagent_type": "my-special-agent"}, offset_seconds=0),
        ]
        engine.classify(evts)
        self.assertNotEqual(evts[0].waste_reason, "fruitless-agent")

    def test_write_outside_event_count_window_not_counted(self):
        """Write just past lookforward_events boundary should NOT count."""
        rules = self._make_rules(window_seconds=3600, lookforward_events=2)
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Agent", tool_input={"subagent_type": "code-writer"}, offset_seconds=0),
            _evt(tool_name="Read", offset_seconds=10),
            _evt(tool_name="Read", offset_seconds=20),
            _evt(tool_name="Edit", offset_seconds=30),
        ]
        engine.classify(evts)
        self.assertEqual(evts[0].waste_reason, "fruitless-agent")

    def test_write_outside_time_window_not_counted(self):
        """Write within event count but past time window should NOT count."""
        rules = self._make_rules(window_seconds=5, lookforward_events=100)
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Agent", tool_input={"subagent_type": "code-writer"}, offset_seconds=0),
            _evt(tool_name="Edit", offset_seconds=10),
        ]
        engine.classify(evts)
        self.assertEqual(evts[0].waste_reason, "fruitless-agent")

    def test_fruitless_agent_does_not_override_avoidable(self):
        """Only overrides None or 'productive'; not 'avoidable'."""
        rules = self._make_rules()
        engine = ClassifyEngine(rules)
        agent_evt = _evt(tool_name="Agent", tool_input={"subagent_type": "code-writer"},
                         offset_seconds=0, classification="avoidable", waste_reason="failed-tool")
        evts = [agent_evt, _evt(tool_name="Read", offset_seconds=10)]
        engine.classify(evts)
        self.assertEqual(agent_evt.classification, "avoidable")
        self.assertEqual(agent_evt.waste_reason, "failed-tool")

    def test_fruitless_agent_overrides_productive(self):
        rules = self._make_rules()
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Agent", tool_input={"subagent_type": "code-writer"}, offset_seconds=0),
        ]
        engine.classify(evts)
        self.assertEqual(evts[0].classification, "review")
        self.assertEqual(evts[0].waste_reason, "fruitless-agent")

    def test_fruitless_agent_rule_disabled(self):
        rules = self._make_rules(enabled=False)
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Agent", tool_input={"subagent_type": "code-writer"}, offset_seconds=0),
        ]
        engine.classify(evts)
        self.assertNotEqual(evts[0].waste_reason, "fruitless-agent")

    def test_non_tool_use_event_skipped_in_lookforward(self):
        """Non-tool_use events after Agent are skipped (not counted toward lookforward_events)."""
        rules = self._make_rules(window_seconds=300, lookforward_events=1)
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Agent", tool_input={"subagent_type": "code-writer"}, offset_seconds=0),
            _evt(event_type="api_request", tool_name=None, offset_seconds=10),
            _evt(tool_name="Edit", offset_seconds=20),
        ]
        engine.classify(evts)
        self.assertNotEqual(evts[0].waste_reason, "fruitless-agent")

    def test_write_tools_multiedit_notebookedit_count(self):
        for write_tool in ("Write", "MultiEdit", "NotebookEdit"):
            reset_seq()
            rules = self._make_rules()
            engine = ClassifyEngine(rules)
            evts = [
                _evt(tool_name="Agent", tool_input={"subagent_type": "code-writer"}, offset_seconds=0),
                _evt(tool_name=write_tool, offset_seconds=10),
            ]
            engine.classify(evts)
            self.assertNotEqual(
                evts[0].waste_reason, "fruitless-agent",
                f"Expected {write_tool} to count as a write tool"
            )


# ===========================================================================
# End-to-end classify() — both passes
# ===========================================================================

class TestClassifyEndToEnd(unittest.TestCase):
    def setUp(self):
        reset_seq()

    def test_classify_mutates_events_in_place(self):
        engine = ClassifyEngine(EMPTY_RULES)
        evts = [_evt(tool_name="Edit"), _evt(tool_name="Read")]
        engine.classify(evts)
        self.assertIsNotNone(evts[0].classification)
        self.assertIsNotNone(evts[1].classification)

    def test_empty_list_does_not_crash(self):
        engine = ClassifyEngine(EMPTY_RULES)
        engine.classify([])

    def test_mixed_event_types_only_tool_use_classified(self):
        engine = ClassifyEngine(EMPTY_RULES)
        api_evt = _evt(event_type="api_request", tool_name=None)
        tool_evt = _evt(tool_name="Edit")
        engine.classify([api_evt, tool_evt])
        self.assertIsNone(api_evt.classification)
        self.assertEqual(tool_evt.classification, "productive")

    def test_full_pipeline_bash_avoidable_and_abandoned_search(self):
        """Integration: bash-as-cat + abandoned-search both fire in one classify() call."""
        rules = {
            "avoidable": {
                "bash-as-cat": {"enabled": True, "patterns": [r"\bcat\b"], "exclude": []},
            },
            "review": {
                "abandoned-search": {"enabled": True, "consecutive_reads": 3},
            },
        }
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Bash", tool_input={"command": "cat foo.txt"}, offset_seconds=0),
            _evt(tool_name="Read", offset_seconds=10),
            _evt(tool_name="Read", offset_seconds=20),
            _evt(tool_name="Read", offset_seconds=30),
        ]
        engine.classify(evts)
        self.assertEqual(evts[0].classification, "avoidable")
        self.assertEqual(evts[0].waste_reason, "bash-as-cat")
        self.assertEqual(evts[1].classification, "review")
        self.assertEqual(evts[1].waste_reason, "abandoned-search")

    def test_second_pass_does_not_override_first_pass_avoidable(self):
        """Avoidable events from first pass survive second pass unchanged."""
        rules = {
            "avoidable": {
                "bash-as-cat": {"enabled": True, "patterns": [r"\bcat\b"], "exclude": []},
            },
            "review": {
                "fruitless-agent": {"enabled": True, "window_seconds": 300, "lookforward_events": 10},
            },
        }
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Bash", tool_input={"command": "cat foo.txt"}, offset_seconds=0),
        ]
        engine.classify(evts)
        self.assertEqual(evts[0].classification, "avoidable")


if __name__ == "__main__":
    unittest.main()
