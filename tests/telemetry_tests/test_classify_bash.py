"""Tests for classify.py — first-pass bash/tool rules (TestFirstPassFailedTool, TestClassifyBash,
TestRedundantRead, TestRapidReEdit, TestApplyCustomRules, TestDefaultClassification)."""
from __future__ import annotations

import unittest

from telemetry.classify import ClassifyEngine

from tests.telemetry_tests.shared_fixtures import (
    BASH_RULES,
    EMPTY_RULES,
    _evt,
    reset_seq,
)


# ===========================================================================
# First pass — failure short-circuit
# ===========================================================================

class TestFirstPassFailedTool(unittest.TestCase):
    def setUp(self):
        reset_seq()
        self.engine = ClassifyEngine(EMPTY_RULES)

    def test_failed_tool_use_classified_avoidable(self):
        evt = _evt(tool_name="Read", success=False)
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "avoidable")
        self.assertEqual(evt.waste_reason, "failed-tool")

    def test_failed_tool_use_short_circuits_bash_rules(self):
        """Even if bash rules would otherwise fire, failure takes priority."""
        rules = dict(BASH_RULES)
        engine = ClassifyEngine(rules)
        evt = _evt(
            tool_name="Bash",
            tool_input={"command": "cat foo.txt"},
            success=False,
        )
        engine.classify([evt])
        self.assertEqual(evt.classification, "avoidable")
        self.assertEqual(evt.waste_reason, "failed-tool")

    def test_success_none_does_not_short_circuit(self):
        """success=None should not trigger failed-tool."""
        evt = _evt(tool_name="Read", success=None)
        self.engine.classify([evt])
        self.assertNotEqual(evt.waste_reason, "failed-tool")

    def test_non_tool_use_event_skipped(self):
        evt = _evt(tool_name="Read", event_type="api_request", success=False)
        self.engine.classify([evt])
        self.assertIsNone(evt.classification)

    def test_already_classified_event_skipped(self):
        evt = _evt(tool_name="Read", classification="productive")
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "productive")


# ===========================================================================
# First pass — _classify_bash
# ===========================================================================

class TestClassifyBash(unittest.TestCase):
    def setUp(self):
        reset_seq()
        self.engine = ClassifyEngine(BASH_RULES)

    def test_cat_command_classified_avoidable(self):
        evt = _evt(tool_name="Bash", tool_input={"command": "cat foo.txt"})
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "avoidable")
        self.assertEqual(evt.waste_reason, "bash-as-cat")

    def test_grep_without_exclude_classified_avoidable(self):
        evt = _evt(tool_name="Bash", tool_input={"command": "grep foo bar.txt"})
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "avoidable")
        self.assertEqual(evt.waste_reason, "bash-as-grep")

    def test_grep_with_exclude_pattern_not_classified_avoidable(self):
        evt = _evt(tool_name="Bash", tool_input={"command": "grep --include='*.py' foo ."})
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "productive")

    def test_disabled_rule_skipped(self):
        evt = _evt(tool_name="Bash", tool_input={"command": "ls -la"})
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "productive")

    def test_first_segment_before_pipe_extracted(self):
        """Command with pipe — only first segment is checked."""
        evt = _evt(tool_name="Bash", tool_input={"command": "cat foo.txt | wc -l"})
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "avoidable")
        self.assertEqual(evt.waste_reason, "bash-as-cat")

    def test_no_command_key_does_not_crash(self):
        evt = _evt(tool_name="Bash", tool_input={})
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "productive")

    def test_no_tool_input_does_not_crash(self):
        evt = _evt(tool_name="Bash", tool_input=None)
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "productive")

    def test_no_bash_rules_falls_through(self):
        engine = ClassifyEngine(EMPTY_RULES)
        evt = _evt(tool_name="Bash", tool_input={"command": "cat foo.txt"})
        engine.classify([evt])
        self.assertEqual(evt.classification, "productive")


# ===========================================================================
# First pass — _is_redundant_read
# ===========================================================================

class TestRedundantRead(unittest.TestCase):
    def setUp(self):
        reset_seq()
        self.rule = {
            "enabled": True,
            "window_seconds": 60,
            "lookback_events": 10,
        }
        self.rules = {"avoidable": {"redundant-read": self.rule}}
        self.engine = ClassifyEngine(self.rules)

    def test_no_file_path_not_redundant(self):
        evt = _evt(tool_name="Read", tool_input={})
        self.engine.classify([evt])
        self.assertNotEqual(evt.classification, "avoidable")

    def test_no_prior_read_not_redundant(self):
        evt = _evt(tool_name="Read", tool_input={"file_path": "/foo/bar.py"})
        self.engine.classify([evt])
        self.assertNotEqual(evt.waste_reason, "redundant-read")

    def test_prior_read_different_file_not_redundant(self):
        e1 = _evt(tool_name="Read", tool_input={"file_path": "/other.py"}, offset_seconds=0)
        e2 = _evt(tool_name="Read", tool_input={"file_path": "/foo/bar.py"}, offset_seconds=10)
        self.engine.classify([e1, e2])
        self.assertNotEqual(e2.waste_reason, "redundant-read")

    def test_prior_read_same_file_within_window_is_redundant(self):
        e1 = _evt(tool_name="Read", tool_input={"file_path": "/foo/bar.py"}, offset_seconds=0)
        e2 = _evt(tool_name="Read", tool_input={"file_path": "/foo/bar.py"}, offset_seconds=30)
        self.engine.classify([e1, e2])
        self.assertEqual(e2.classification, "avoidable")
        self.assertEqual(e2.waste_reason, "redundant-read")

    def test_prior_read_outside_time_window_not_redundant(self):
        e1 = _evt(tool_name="Read", tool_input={"file_path": "/foo/bar.py"}, offset_seconds=0)
        e2 = _evt(tool_name="Read", tool_input={"file_path": "/foo/bar.py"}, offset_seconds=120)
        self.engine.classify([e1, e2])
        self.assertNotEqual(e2.waste_reason, "redundant-read")

    def test_prior_read_outside_lookback_count_not_redundant(self):
        """If the prior read falls outside lookback_events, it's not considered."""
        rules = {"avoidable": {"redundant-read": {
            "enabled": True,
            "window_seconds": 3600,
            "lookback_events": 1,
        }}}
        engine = ClassifyEngine(rules)
        e1 = _evt(tool_name="Read", tool_input={"file_path": "/foo/bar.py"}, offset_seconds=0)
        e_mid = _evt(tool_name="Bash", tool_input={"command": "echo hi"}, offset_seconds=5)
        e2 = _evt(tool_name="Read", tool_input={"file_path": "/foo/bar.py"}, offset_seconds=10)
        engine.classify([e1, e_mid, e2])
        self.assertNotEqual(e2.waste_reason, "redundant-read")

    def test_rule_disabled_skips_check(self):
        rules = {"avoidable": {"redundant-read": {"enabled": False}}}
        engine = ClassifyEngine(rules)
        e1 = _evt(tool_name="Read", tool_input={"file_path": "/foo/bar.py"}, offset_seconds=0)
        e2 = _evt(tool_name="Read", tool_input={"file_path": "/foo/bar.py"}, offset_seconds=5)
        engine.classify([e1, e2])
        self.assertNotEqual(e2.waste_reason, "redundant-read")

    def test_rule_missing_from_config_defaults_enabled(self):
        """When 'redundant-read' key is absent entirely, defaults to enabled."""
        engine = ClassifyEngine({"avoidable": {}})
        e1 = _evt(tool_name="Read", tool_input={"file_path": "/foo/bar.py"}, offset_seconds=0)
        e2 = _evt(tool_name="Read", tool_input={"file_path": "/foo/bar.py"}, offset_seconds=5)
        engine.classify([e1, e2])
        self.assertEqual(e2.waste_reason, "redundant-read")

    def test_non_tool_use_prior_event_skipped_in_lookback(self):
        """A non-tool_use event in the lookback window is skipped."""
        e_api = _evt(event_type="api_request", tool_name=None, offset_seconds=0)
        e_read = _evt(tool_name="Read", tool_input={"file_path": "/foo/bar.py"}, offset_seconds=5)
        engine = ClassifyEngine({"avoidable": {"redundant-read": {
            "enabled": True, "window_seconds": 60, "lookback_events": 10,
        }}})
        engine.classify([e_api, e_read])
        self.assertNotEqual(e_read.waste_reason, "redundant-read")


# ===========================================================================
# First pass — _is_rapid_re_edit
# ===========================================================================

class TestRapidReEdit(unittest.TestCase):
    def setUp(self):
        reset_seq()
        self.rule = {
            "enabled": True,
            "window_seconds": 30,
            "lookback_events": 5,
            "min_gap_seconds": 0,
        }
        self.rules = {"avoidable": {"rapid-re-edit": self.rule}}
        self.engine = ClassifyEngine(self.rules)

    def test_rapid_re_edit_same_file_within_window(self):
        e1 = _evt(tool_name="Edit", tool_input={"file_path": "/foo.py"}, offset_seconds=0)
        e2 = _evt(tool_name="Edit", tool_input={"file_path": "/foo.py"}, offset_seconds=10)
        self.engine.classify([e1, e2])
        self.assertEqual(e2.classification, "avoidable")
        self.assertEqual(e2.waste_reason, "rapid-re-edit")

    def test_multiedit_and_notebookedit_trigger(self):
        for tool in ("MultiEdit", "NotebookEdit"):
            reset_seq()
            e1 = _evt(tool_name=tool, tool_input={"file_path": "/foo.py"}, offset_seconds=0)
            e2 = _evt(tool_name=tool, tool_input={"file_path": "/foo.py"}, offset_seconds=5)
            engine = ClassifyEngine(self.rules)
            engine.classify([e1, e2])
            self.assertEqual(e2.waste_reason, "rapid-re-edit", f"Expected rapid-re-edit for {tool}")

    def test_different_file_not_rapid_re_edit(self):
        e1 = _evt(tool_name="Edit", tool_input={"file_path": "/foo.py"}, offset_seconds=0)
        e2 = _evt(tool_name="Edit", tool_input={"file_path": "/bar.py"}, offset_seconds=5)
        self.engine.classify([e1, e2])
        self.assertNotEqual(e2.waste_reason, "rapid-re-edit")

    def test_outside_window_not_rapid_re_edit(self):
        e1 = _evt(tool_name="Edit", tool_input={"file_path": "/foo.py"}, offset_seconds=0)
        e2 = _evt(tool_name="Edit", tool_input={"file_path": "/foo.py"}, offset_seconds=60)
        self.engine.classify([e1, e2])
        self.assertNotEqual(e2.waste_reason, "rapid-re-edit")

    def test_min_gap_seconds_excludes_too_fast_edits(self):
        """Delta < min_gap_seconds should NOT count as rapid re-edit."""
        rules = {"avoidable": {"rapid-re-edit": {
            "enabled": True,
            "window_seconds": 30,
            "lookback_events": 5,
            "min_gap_seconds": 10,
        }}}
        engine = ClassifyEngine(rules)
        e1 = _evt(tool_name="Edit", tool_input={"file_path": "/foo.py"}, offset_seconds=0)
        e2 = _evt(tool_name="Edit", tool_input={"file_path": "/foo.py"}, offset_seconds=5)
        engine.classify([e1, e2])
        self.assertNotEqual(e2.waste_reason, "rapid-re-edit")

    def test_no_file_path_not_rapid_re_edit(self):
        e1 = _evt(tool_name="Edit", tool_input={}, offset_seconds=0)
        e2 = _evt(tool_name="Edit", tool_input={}, offset_seconds=5)
        self.engine.classify([e1, e2])
        self.assertNotEqual(e2.waste_reason, "rapid-re-edit")

    def test_rule_disabled_skips_check(self):
        rules = {"avoidable": {"rapid-re-edit": {"enabled": False}}}
        engine = ClassifyEngine(rules)
        e1 = _evt(tool_name="Edit", tool_input={"file_path": "/foo.py"}, offset_seconds=0)
        e2 = _evt(tool_name="Edit", tool_input={"file_path": "/foo.py"}, offset_seconds=5)
        engine.classify([e1, e2])
        self.assertNotEqual(e2.waste_reason, "rapid-re-edit")

    def test_non_tool_use_prior_event_skipped_in_rapid_re_edit_lookback(self):
        """A non-tool_use event in the lookback window is skipped."""
        e_api = _evt(event_type="api_request", tool_name=None, offset_seconds=0)
        e_edit = _evt(tool_name="Edit", tool_input={"file_path": "/foo.py"}, offset_seconds=5)
        engine = ClassifyEngine({"avoidable": {"rapid-re-edit": {
            "enabled": True, "window_seconds": 30, "lookback_events": 5, "min_gap_seconds": 0,
        }}})
        engine.classify([e_api, e_edit])
        self.assertNotEqual(e_edit.waste_reason, "rapid-re-edit")

    def test_non_edit_tool_prior_event_skipped_in_lookback(self):
        """A prior tool_use with a non-edit tool_name is skipped in lookback."""
        e_read = _evt(tool_name="Read", tool_input={"file_path": "/foo.py"}, offset_seconds=0)
        e_edit = _evt(tool_name="Edit", tool_input={"file_path": "/foo.py"}, offset_seconds=5)
        engine = ClassifyEngine({"avoidable": {"rapid-re-edit": {
            "enabled": True, "window_seconds": 30, "lookback_events": 5, "min_gap_seconds": 0,
        }}})
        engine.classify([e_read, e_edit])
        self.assertNotEqual(e_edit.waste_reason, "rapid-re-edit")


# ===========================================================================
# First pass — _apply_custom_rules
# ===========================================================================

class TestApplyCustomRules(unittest.TestCase):
    def setUp(self):
        reset_seq()

    def test_match_by_tool_name(self):
        rules = {"custom_rules": [
            {"tool": "Read", "classification": "review", "reason": "custom-read"},
        ]}
        engine = ClassifyEngine(rules)
        evt = _evt(tool_name="Read")
        engine.classify([evt])
        self.assertEqual(evt.classification, "review")
        self.assertEqual(evt.waste_reason, "custom-read")

    def test_match_by_pattern(self):
        rules = {"custom_rules": [
            {"pattern": r"pytest", "classification": "productive", "reason": "pytest-run"},
        ]}
        engine = ClassifyEngine(rules)
        evt = _evt(tool_name="Bash", tool_input={"command": "pytest tests/"})
        engine.classify([evt])
        self.assertEqual(evt.classification, "productive")
        self.assertEqual(evt.waste_reason, "pytest-run")

    def test_match_by_tool_and_pattern_both_must_match(self):
        rules = {"custom_rules": [
            {"tool": "Bash", "pattern": r"make test", "classification": "productive", "reason": "make-test"},
        ]}
        engine = ClassifyEngine(rules)
        evt_wrong_tool = _evt(tool_name="Read", tool_input={"command": "make test"})
        evt_wrong_cmd = _evt(tool_name="Bash", tool_input={"command": "make lint"})
        evt_ok = _evt(tool_name="Bash", tool_input={"command": "make test"})
        engine.classify([evt_wrong_tool, evt_wrong_cmd, evt_ok])
        self.assertNotEqual(evt_wrong_tool.waste_reason, "make-test")
        self.assertNotEqual(evt_wrong_cmd.waste_reason, "make-test")
        self.assertEqual(evt_ok.waste_reason, "make-test")

    def test_rule_with_neither_tool_nor_pattern_matches_all(self):
        """A rule with no tool or pattern constraint matches every tool_use event."""
        rules = {"custom_rules": [
            {"classification": "neutral", "reason": "catch-all"},
        ]}
        engine = ClassifyEngine(rules)
        evt = _evt(tool_name="Write")
        engine.classify([evt])
        self.assertEqual(evt.waste_reason, "catch-all")

    def test_first_matching_rule_wins(self):
        rules = {"custom_rules": [
            {"tool": "Read", "classification": "avoidable", "reason": "first-rule"},
            {"tool": "Read", "classification": "review", "reason": "second-rule"},
        ]}
        engine = ClassifyEngine(rules)
        evt = _evt(tool_name="Read")
        engine.classify([evt])
        self.assertEqual(evt.waste_reason, "first-rule")

    def test_no_match_returns_none_falls_to_default(self):
        rules = {"custom_rules": [
            {"tool": "Bash", "classification": "review", "reason": "bash-custom"},
        ]}
        engine = ClassifyEngine(rules)
        evt = _evt(tool_name="Write")
        engine.classify([evt])
        self.assertEqual(evt.classification, "productive")
        self.assertIsNone(evt.waste_reason)

    def test_default_reason_is_custom(self):
        rules = {"custom_rules": [
            {"tool": "Read"},
        ]}
        engine = ClassifyEngine(rules)
        evt = _evt(tool_name="Read")
        engine.classify([evt])
        self.assertEqual(evt.waste_reason, "custom")

    def test_no_custom_rules_key(self):
        engine = ClassifyEngine(EMPTY_RULES)
        evt = _evt(tool_name="Write")
        engine.classify([evt])
        self.assertEqual(evt.classification, "productive")


# ===========================================================================
# First pass — _default_classification
# ===========================================================================

class TestDefaultClassification(unittest.TestCase):
    def setUp(self):
        reset_seq()
        self.engine = ClassifyEngine(EMPTY_RULES)

    def test_edit_is_productive(self):
        evt = _evt(tool_name="Edit")
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "productive")

    def test_write_is_productive(self):
        evt = _evt(tool_name="Write")
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "productive")

    def test_multiedit_is_productive(self):
        evt = _evt(tool_name="MultiEdit")
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "productive")

    def test_notebookedit_is_productive(self):
        evt = _evt(tool_name="NotebookEdit")
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "productive")

    def test_bash_defaults_productive(self):
        evt = _evt(tool_name="Bash")
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "productive")

    def test_agent_defaults_productive(self):
        """Agent defaults to productive in first pass (fruitless-agent disabled so second pass doesn't override)."""
        rules = {"review": {"fruitless-agent": {"enabled": False}}}
        engine = ClassifyEngine(rules)
        evt = _evt(tool_name="Agent", tool_input={"subagent_type": "code-writer"})
        engine.classify([evt])
        self.assertEqual(evt.classification, "productive")

    def test_read_defaults_neutral(self):
        evt = _evt(tool_name="Read")
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "neutral")

    def test_unknown_tool_defaults_neutral(self):
        evt = _evt(tool_name="UnknownTool")
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "neutral")

    def test_configured_neutral_tool_list(self):
        rules = {"tools": {"neutral": ["WebSearch"]}}
        engine = ClassifyEngine(rules)
        evt = _evt(tool_name="WebSearch")
        engine.classify([evt])
        self.assertEqual(evt.classification, "neutral")

    def test_configured_productive_tool_list_overrides_default(self):
        rules = {"tools": {"productive": ["Read"]}}
        engine = ClassifyEngine(rules)
        evt = _evt(tool_name="Read")
        engine.classify([evt])
        self.assertEqual(evt.classification, "productive")


if __name__ == "__main__":
    unittest.main()


# ===========================================================================
# Null-valued tool_input keys
# ===========================================================================

class TestNullCommandIsNotTheStringNone(unittest.TestCase):
    """A present-but-null `command` must read as empty, not the literal "None".

    `.get("command", "")` returns the default only when the key is ABSENT. A key
    present with a null value returns None, and `str(None)` is "None" — a
    four-character string that matches rules and reads as a real command
    everywhere downstream.
    """

    def setUp(self):
        reset_seq()

    def test_null_command_does_not_match_a_rule_on_the_word_none(self):
        """The literal string "None" must never be what a rule matches against.

        This is the failure the fix prevents: `.get("command", "")` returns None
        for a key present with a null value, and `str(None)` is "None" — which a
        pattern containing "none" then matches, classifying a command that was
        never issued.
        """
        rules = {
            "avoidable": {
                "bash-as-none": {"enabled": True, "patterns": ["None"]},
            }
        }
        evt = _evt(tool_name="Bash", tool_input={"command": None})
        events = [evt]
        ClassifyEngine(rules).classify(events)
        self.assertNotEqual(
            evt.waste_reason,
            "bash-as-none",
            "null command leaked to the matcher as the literal string 'None'",
        )

    def test_null_command_matches_a_missing_command(self):
        """A null command and an absent key must classify identically."""
        rules = {
            "avoidable": {
                "bash-as-none": {"enabled": True, "patterns": ["None"]},
            }
        }
        missing = _evt(tool_name="Bash", tool_input={})
        null_valued = _evt(tool_name="Bash", tool_input={"command": None})
        events = [missing, null_valued]
        ClassifyEngine(rules).classify(events)
        self.assertEqual(
            (missing.classification, missing.waste_reason),
            (null_valued.classification, null_valued.waste_reason),
        )
