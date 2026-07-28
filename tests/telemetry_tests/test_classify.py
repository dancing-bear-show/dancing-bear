"""Tests for telemetry/classify.py — ClassifyEngine."""

import unittest
from datetime import datetime, timedelta, timezone

from telemetry.classify import ClassifyEngine
from telemetry.models import SessionEvent


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_seq = [0]


def _evt(
    tool_name: str | None = None,
    event_type: str = "tool_use",
    tool_input: dict | None = None,
    success: bool | None = None,
    classification: str | None = None,
    waste_reason: str | None = None,
    offset_seconds: float = 0.0,
) -> SessionEvent:
    """Build a SessionEvent with sensible defaults, auto-incrementing sequence."""
    _seq[0] += 1
    return SessionEvent(
        timestamp=_BASE_TS + timedelta(seconds=offset_seconds),
        event_type=event_type,
        sequence=_seq[0],
        session_id="test-session",
        tool_name=tool_name,
        tool_input=tool_input,
        success=success,
        classification=classification,
        waste_reason=waste_reason,
    )


def reset_seq():
    """Reset the auto-incrementing sequence counter before each test class."""
    _seq[0] = 0


# ---------------------------------------------------------------------------
# Minimal rule configs for reuse
# ---------------------------------------------------------------------------

EMPTY_RULES: dict = {}

BASH_RULES = {
    "avoidable": {
        "bash-as-cat": {
            "enabled": True,
            "patterns": [r"\bcat\b"],
            "exclude": [],
        },
        "bash-as-grep": {
            "enabled": True,
            "patterns": [r"\bgrep\b"],
            "exclude": [r"--include"],
        },
        "bash-as-disabled": {
            "enabled": False,
            "patterns": [r"\bls\b"],
            "exclude": [],
        },
    }
}


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
        # Should NOT be avoidable/failed-tool — default classification applies
        self.assertNotEqual(evt.waste_reason, "failed-tool")

    def test_non_tool_use_event_skipped(self):
        evt = _evt(tool_name="Read", event_type="api_request", success=False)
        self.engine.classify([evt])
        # first pass skips non-tool_use events; classification stays None
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
        # exclude fires — should fall through to default (productive for Bash)
        self.assertEqual(evt.classification, "productive")

    def test_disabled_rule_skipped(self):
        evt = _evt(tool_name="Bash", tool_input={"command": "ls -la"})
        self.engine.classify([evt])
        # bash-as-disabled is disabled; ls should fall through to default
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
        # No command → no match → default productive
        self.assertEqual(evt.classification, "productive")

    def test_no_tool_input_does_not_crash(self):
        evt = _evt(tool_name="Bash", tool_input=None)
        self.engine.classify([evt])
        self.assertEqual(evt.classification, "productive")

    def test_no_bash_rules_falls_through(self):
        engine = ClassifyEngine(EMPTY_RULES)
        evt = _evt(tool_name="Bash", tool_input={"command": "cat foo.txt"})
        engine.classify([evt])
        # No rules defined — default productive
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
        # One non-read event in between pushes e1 outside lookback_events=1
        e_mid = _evt(tool_name="Bash", tool_input={"command": "echo hi"}, offset_seconds=5)
        e2 = _evt(tool_name="Read", tool_input={"file_path": "/foo/bar.py"}, offset_seconds=10)
        engine.classify([e1, e_mid, e2])
        # e1 is at position idx-2; lookback_events=1 means start=idx-1=1 (e_mid), so e1 is excluded
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
        # Rule missing → rule={} → enabled defaults True → redundant-read fires
        self.assertEqual(e2.waste_reason, "redundant-read")

    def test_non_tool_use_prior_event_skipped_in_lookback(self):
        """A non-tool_use event in the lookback window is skipped (not treated as a prior read)."""
        e_api = _evt(event_type="api_request", tool_name=None, offset_seconds=0)
        e_read = _evt(tool_name="Read", tool_input={"file_path": "/foo/bar.py"}, offset_seconds=5)
        engine = ClassifyEngine({"avoidable": {"redundant-read": {
            "enabled": True, "window_seconds": 60, "lookback_events": 10,
        }}})
        engine.classify([e_api, e_read])
        # e_api is not tool_use, so it's skipped; no prior Read → not redundant
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
        # delta=5 < min_gap_seconds=10 → not rapid-re-edit
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
        # e_api is not tool_use → skipped; no prior Edit → not rapid-re-edit
        self.assertNotEqual(e_edit.waste_reason, "rapid-re-edit")

    def test_non_edit_tool_prior_event_skipped_in_lookback(self):
        """A prior tool_use with a non-edit tool_name is skipped in lookback."""
        e_read = _evt(tool_name="Read", tool_input={"file_path": "/foo.py"}, offset_seconds=0)
        e_edit = _evt(tool_name="Edit", tool_input={"file_path": "/foo.py"}, offset_seconds=5)
        engine = ClassifyEngine({"avoidable": {"rapid-re-edit": {
            "enabled": True, "window_seconds": 30, "lookback_events": 5, "min_gap_seconds": 0,
        }}})
        engine.classify([e_read, e_edit])
        # e_read is not an edit tool → skipped; no prior Edit → not rapid-re-edit
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
        # Wrong tool → no match
        evt_wrong_tool = _evt(tool_name="Read", tool_input={"command": "make test"})
        # Right tool, wrong command → no match
        evt_wrong_cmd = _evt(tool_name="Bash", tool_input={"command": "make lint"})
        # Both right → match
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
        # No custom match → _default_classification → Write is productive
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
        # With fruitless-agent disabled, first-pass default of "productive" is preserved
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


# ===========================================================================
# Second pass — _classify_abandoned_search
# ===========================================================================

class TestClassifyAbandonedSearch(unittest.TestCase):
    def setUp(self):
        reset_seq()

    def _make_rules(self, consecutive_reads=3, enabled=True):
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
            _evt(tool_name="Read", tool_input={"file_path": "/foo.py"},
                 offset_seconds=0),
            _evt(tool_name="Read", tool_input={"file_path": "/foo.py"},
                 offset_seconds=5),
            _evt(tool_name="Read", tool_input={"file_path": "/foo.py"},
                 offset_seconds=10),
        ]
        # First event gets redundant-read applied to the second; third also redundant
        redundant_rules = {
            "avoidable": {"redundant-read": {"enabled": True, "window_seconds": 60, "lookback_events": 10}},
            "review": {"abandoned-search": {"enabled": True, "consecutive_reads": 3}},
        }
        engine = ClassifyEngine(redundant_rules)
        engine.classify(evts)
        # evts[1] and evts[2] are avoidable/redundant-read — must not be changed to review
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
        # Pre-set to neutral (matches _default_classification behavior for Read)
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
        window_seconds=300,
        lookforward_events=10,
        exempt_agent_types=None,
        enabled=True,
    ):
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
            # This Edit is at position 3 (past lookforward_events=2 counting from after Agent)
            _evt(tool_name="Edit", offset_seconds=30),
        ]
        engine.classify(evts)
        # Edit is beyond event-count limit → fruitless
        self.assertEqual(evts[0].waste_reason, "fruitless-agent")

    def test_write_outside_time_window_not_counted(self):
        """Write within event count but past time window should NOT count."""
        rules = self._make_rules(window_seconds=5, lookforward_events=100)
        engine = ClassifyEngine(rules)
        evts = [
            _evt(tool_name="Agent", tool_input={"subagent_type": "code-writer"}, offset_seconds=0),
            _evt(tool_name="Edit", offset_seconds=10),  # delta=10 > window_seconds=5
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
        # First pass sets Agent to productive (default); second pass should override
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
            # api_request is not tool_use → skipped, not counted
            _evt(event_type="api_request", tool_name=None, offset_seconds=10),
            # Edit within window and within event count (since api_request was skipped)
            _evt(tool_name="Edit", offset_seconds=20),
        ]
        engine.classify(evts)
        # Edit is found → not fruitless
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
        engine.classify([])  # must not raise

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
        # An avoidable Bash event followed by no writes
        evts = [
            _evt(tool_name="Bash", tool_input={"command": "cat foo.txt"}, offset_seconds=0),
        ]
        engine.classify(evts)
        self.assertEqual(evts[0].classification, "avoidable")


if __name__ == "__main__":
    unittest.main()
