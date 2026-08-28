"""Coverage-filling tests for calendars/outlook_pipelines/settings.py.

Targets the uncovered lines and branches identified in the coverage report:
- _process_single_event: no-eid, no-config, empty-patch early returns
- _evaluate_config: non-dict rule skip, no-match no-defaults, apply_set falsy merge
- _match_rule: subject_contains fail, subject_regex fail, location_contains fail
- _build_patch: categories as list/tuple, categories None/other, rem_min parse error
- _format_patch_log: all five conditional branches
- _apply_event_patch: exception path
- _coerce_bool: None, truthy strings, falsy strings, unknown string
- _to_list: list/tuple input, empty string
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from tests.fixtures import write_yaml
from calendars.outlook_pipelines.settings import (
    OutlookSettingsProcessor,
    OutlookSettingsRequest,
    OutlookSettingsRequestConsumer,
    _SettingsProcessingContext,
)


def _make_request(cfg, svc, dry_run=False, calendar=None):
    """Build a minimal OutlookSettingsRequest from a config dict and a service stub."""
    cfg_path = write_yaml(cfg)
    return OutlookSettingsRequest(
        config_path=Path(cfg_path),
        calendar=calendar,
        from_date=None,
        to_date=None,
        dry_run=dry_run,
        service=svc,
    )


def _make_svc(events=None):
    svc = MagicMock()
    svc.list_events_in_range.return_value = events or []
    return svc


def _proc():
    return OutlookSettingsProcessor()


# ---------------------------------------------------------------------------
# _process_single_event early-exit branches
# ---------------------------------------------------------------------------

class TestProcessSingleEventEarlyExits(unittest.TestCase):
    """Cover the three return-0 branches in _process_single_event."""

    def _ctx(self, defaults=None, rules=None, dry_run=False):
        return _SettingsProcessingContext(
            svc=MagicMock(),
            defaults=defaults or {},
            rules=rules or [],
            calendar=None,
            dry_run=dry_run,
        )

    def test_event_without_id_returns_zero(self):
        """Line 83: event with no 'id' → (0, 0, [])."""
        ctx = self._ctx()
        sel, chg, logs = _proc()._process_single_event(ctx, {"subject": "No ID"})
        self.assertEqual((sel, chg, logs), (0, 0, []))

    def test_event_no_matching_rule_no_defaults_returns_zero(self):
        """Line 86: _evaluate_config returns None → (0, 0, [])."""
        ctx = self._ctx(defaults={}, rules=[])  # no defaults, no rules
        sel, chg, logs = _proc()._process_single_event(ctx, {"id": "E1", "subject": "X"})
        self.assertEqual((sel, chg, logs), (0, 0, []))

    def test_event_matches_and_applies_with_all_none_patch(self):
        """Line 89 (dead code note): _build_patch always returns a 5-key dict so 'if not patch'
        is never True. This test documents the actual behaviour: an event that matches a rule
        with an empty 'set' dict still counts as 'changed' (the API call is made).

        The code at line 89 is unreachable because _build_patch returns a non-empty dict
        regardless of the input config values.
        """
        svc = MagicMock()
        ctx = _SettingsProcessingContext(
            svc=svc,
            defaults={},
            rules=[
                {"match": {}, "set": {}},  # matches everything, no patchable fields
            ],
            calendar=None,
            dry_run=False,
        )
        event = {"id": "E1", "subject": "Something"}
        sel, chg, logs = _proc()._process_single_event(ctx, event)
        # Because _build_patch always returns a non-empty dict, "if not patch" never fires.
        # The patch (all-None values) is applied via update_event_settings.
        self.assertEqual(sel, 1)
        self.assertEqual(chg, 1)
        self.assertEqual(logs, [])


# ---------------------------------------------------------------------------
# _evaluate_config branches
# ---------------------------------------------------------------------------

class TestEvaluateConfig(unittest.TestCase):
    """Cover branch gaps in _evaluate_config."""

    def test_non_dict_rule_is_skipped(self):
        """Lines 132, 133→130: a non-dict entry in rules must be skipped."""
        p = OutlookSettingsProcessor()
        result = p._evaluate_config(
            defaults={"show_as": "busy"},
            rules=["not-a-dict", None, 42],  # all non-dict
            event={"subject": "Meeting"},
        )
        # No rule matched, but defaults exist → returns defaults
        self.assertEqual(result, {"show_as": "busy"})

    def test_no_match_no_defaults_returns_none(self):
        """Line 137: apply_set is None and defaults is empty → return None."""
        p = OutlookSettingsProcessor()
        result = p._evaluate_config(
            defaults={},
            rules=[
                {"match": {"subject_contains": ["Swim"]}, "set": {"categories": ["Kids"]}}
            ],
            event={"subject": "Meeting"},  # doesn't match
        )
        self.assertIsNone(result)

    def test_matching_rule_with_empty_set_key(self):
        """Line 140→142: apply_set is {} (falsy) — defaults still applied, apply_set not merged."""
        p = OutlookSettingsProcessor()
        result = p._evaluate_config(
            defaults={"sensitivity": "normal"},
            rules=[
                {"match": {"subject_contains": ["Meeting"]}, "set": {}}
            ],
            event={"subject": "Team Meeting"},
        )
        self.assertEqual(result, {"sensitivity": "normal"})

    def test_break_after_first_matching_rule(self):
        """Line 133→130: loop breaks after first match; second rule is never evaluated."""
        p = OutlookSettingsProcessor()
        result = p._evaluate_config(
            defaults={},
            rules=[
                {"match": {"subject_contains": ["Meeting"]}, "set": {"show_as": "tentative"}},
                {"match": {"subject_contains": ["Meeting"]}, "set": {"show_as": "busy"}},
            ],
            event={"subject": "Team Meeting"},
        )
        self.assertEqual(result.get("show_as"), "tentative")


# ---------------------------------------------------------------------------
# _match_rule branches
# ---------------------------------------------------------------------------

class TestMatchRule(unittest.TestCase):
    """Cover the three negative branches in _match_rule."""

    def test_subject_contains_miss_returns_false(self):
        """Line 148: subject_contains list has entries but subject doesn't match → False."""
        p = OutlookSettingsProcessor()
        result = p._match_rule(
            {"match": {"subject_contains": ["Swim", "Pool"]}},
            subject="Team Meeting",
            location="",
        )
        self.assertFalse(result)

    def test_subject_regex_miss_returns_false(self):
        """Line 151: subject_regex has entries but subject doesn't match → False."""
        p = OutlookSettingsProcessor()
        result = p._match_rule(
            {"match": {"subject_regex": [r"^Swim\b"]}},
            subject="Meeting",
            location="",
        )
        self.assertFalse(result)

    def test_location_contains_miss_returns_false(self):
        """Line 154: location_contains entries don't match location → False."""
        p = OutlookSettingsProcessor()
        result = p._match_rule(
            {"match": {"location_contains": ["Arena"]}},
            subject="Hockey",
            location="Community Center",
        )
        self.assertFalse(result)

    def test_subject_contains_hit_and_location_hit(self):
        """Happy path: both subject and location match → True."""
        p = OutlookSettingsProcessor()
        result = p._match_rule(
            {"match": {"subject_contains": ["Meet"], "location_contains": ["Arena"]}},
            subject="Team Meeting",
            location="Community Arena",
        )
        self.assertTrue(result)


# ---------------------------------------------------------------------------
# _build_patch branches
# ---------------------------------------------------------------------------

class TestBuildPatch(unittest.TestCase):
    """Cover categories-as-list/tuple, categories=None, and rem_min parse error."""

    def test_categories_as_list(self):
        """Line 160/161: categories given as a list → preserved as list of stripped strings."""
        p = OutlookSettingsProcessor()
        patch = p._build_patch({"categories": ["Work", " Personal "]})
        self.assertEqual(patch["categories"], ["Work", "Personal"])

    def test_categories_as_tuple(self):
        """Line 160/162: categories given as a tuple → converted to list."""
        p = OutlookSettingsProcessor()
        patch = p._build_patch({"categories": ("Alpha", "Beta")})
        self.assertEqual(patch["categories"], ["Alpha", "Beta"])

    def test_categories_none(self):
        """Line 164: categories is None → patch['categories'] is None."""
        p = OutlookSettingsProcessor()
        patch = p._build_patch({"show_as": "busy"})
        self.assertIsNone(patch["categories"])

    def test_categories_int_coerced(self):
        """Line 164 else branch: non-string, non-list, non-None value → [str(cats)]."""
        p = OutlookSettingsProcessor()
        patch = p._build_patch({"categories": 42})
        self.assertEqual(patch["categories"], ["42"])

    def test_reminder_minutes_parse_error_returns_none(self):
        """Lines 171-172: rem_min that can't be int'd → None."""
        p = OutlookSettingsProcessor()
        patch = p._build_patch({"reminder_minutes": "not-a-number"})
        self.assertIsNone(patch["reminder_minutes"])

    def test_reminder_minutes_valid_int_string(self):
        """Happy path: rem_min as numeric string → int."""
        p = OutlookSettingsProcessor()
        patch = p._build_patch({"reminder_minutes": "15"})
        self.assertEqual(patch["reminder_minutes"], 15)


# ---------------------------------------------------------------------------
# _format_patch_log branches
# ---------------------------------------------------------------------------

class TestFormatPatchLog(unittest.TestCase):
    """Cover all five conditional branches in _format_patch_log."""

    def test_all_fields_present(self):
        """Happy path: all five fields → log contains all."""
        p = OutlookSettingsProcessor()
        patch = {
            "categories": ["Work"],
            "show_as": "busy",
            "sensitivity": "private",
            "is_reminder_on": True,
            "reminder_minutes": 15,
        }
        log = p._format_patch_log("E1", "Meeting", patch)
        self.assertIn("categories=", log)
        self.assertIn("showAs=busy", log)
        self.assertIn("sensitivity=private", log)
        self.assertIn("isReminderOn=True", log)
        self.assertIn("reminderMinutes=15", log)

    def test_categories_none_excluded(self):
        """Line 184→186: categories is None → not included in log."""
        p = OutlookSettingsProcessor()
        patch = {
            "categories": None,
            "show_as": "busy",
            "sensitivity": None,
            "is_reminder_on": None,
            "reminder_minutes": None,
        }
        log = p._format_patch_log("E1", "X", patch)
        self.assertNotIn("categories=", log)
        self.assertIn("showAs=busy", log)

    def test_show_as_falsy_excluded(self):
        """Line 186→188: show_as is empty string → not included."""
        p = OutlookSettingsProcessor()
        patch = {"categories": None, "show_as": "", "sensitivity": None, "is_reminder_on": None, "reminder_minutes": None}
        log = p._format_patch_log("E1", "X", patch)
        self.assertNotIn("showAs=", log)

    def test_sensitivity_none_excluded(self):
        """Line 189 conditional: sensitivity is None → not included."""
        p = OutlookSettingsProcessor()
        patch = {"categories": ["A"], "show_as": None, "sensitivity": None, "is_reminder_on": None, "reminder_minutes": None}
        log = p._format_patch_log("E1", "X", patch)
        self.assertNotIn("sensitivity=", log)

    def test_is_reminder_on_none_excluded(self):
        """Line 191 conditional: is_reminder_on is None → not included."""
        p = OutlookSettingsProcessor()
        patch = {"categories": None, "show_as": None, "sensitivity": "normal", "is_reminder_on": None, "reminder_minutes": None}
        log = p._format_patch_log("E1", "X", patch)
        self.assertNotIn("isReminderOn=", log)

    def test_reminder_minutes_none_excluded(self):
        """Line 192→194: reminder_minutes is None → not included."""
        p = OutlookSettingsProcessor()
        patch = {"categories": None, "show_as": None, "sensitivity": None, "is_reminder_on": False, "reminder_minutes": None}
        log = p._format_patch_log("E1", "X", patch)
        self.assertNotIn("reminderMinutes=", log)
        self.assertIn("isReminderOn=False", log)


# ---------------------------------------------------------------------------
# _apply_event_patch exception path
# ---------------------------------------------------------------------------

class TestApplyEventPatch(unittest.TestCase):
    """Cover the exception handler in _apply_event_patch."""

    def test_apply_succeeds(self):
        """Happy path: update_event_settings does not raise → (True, None)."""
        p = OutlookSettingsProcessor()
        svc = MagicMock()
        ok, err = p._apply_event_patch(svc, "E1", None, {
            "categories": ["Work"], "show_as": "busy",
            "sensitivity": None, "is_reminder_on": None, "reminder_minutes": None,
        })
        self.assertTrue(ok)
        self.assertIsNone(err)
        svc.update_event_settings.assert_called_once()

    def test_apply_exception_returns_false_with_message(self):
        """Lines 212-213: update_event_settings raises → (False, error_message)."""
        p = OutlookSettingsProcessor()
        svc = MagicMock()
        svc.update_event_settings.side_effect = RuntimeError("Graph API error")
        ok, err = p._apply_event_patch(svc, "E1", None, {
            "categories": None, "show_as": None,
            "sensitivity": None, "is_reminder_on": None, "reminder_minutes": None,
        })
        self.assertFalse(ok)
        self.assertIsNotNone(err)
        self.assertIn("E1", err)
        self.assertIn("Graph API error", err)


# ---------------------------------------------------------------------------
# _coerce_bool branches
# ---------------------------------------------------------------------------

class TestCoerceBool(unittest.TestCase):
    """Cover all _coerce_bool branches."""

    def test_bool_true_passthrough(self):
        self.assertTrue(OutlookSettingsProcessor()._coerce_bool(True))

    def test_bool_false_passthrough(self):
        self.assertFalse(OutlookSettingsProcessor()._coerce_bool(False))

    def test_none_returns_none(self):
        """Line 217: value is None → None."""
        self.assertIsNone(OutlookSettingsProcessor()._coerce_bool(None))

    def test_truthy_strings(self):
        """Lines 223-225: '1', 'true', 'yes', 'on' → True."""
        p = OutlookSettingsProcessor()
        for s in ("1", "true", "True", "TRUE", "yes", "YES", "on", "ON"):
            with self.subTest(s=s):
                self.assertTrue(p._coerce_bool(s))

    def test_falsy_strings(self):
        """Lines 223-225: '0', 'false', 'no', 'off' → False."""
        p = OutlookSettingsProcessor()
        for s in ("0", "false", "False", "FALSE", "no", "NO", "off", "OFF"):
            with self.subTest(s=s):
                self.assertFalse(p._coerce_bool(s))

    def test_unknown_string_returns_none(self):
        """Line 232: unrecognized string → None."""
        self.assertIsNone(OutlookSettingsProcessor()._coerce_bool("maybe"))

    def test_integer_one_coerced_true(self):
        """Non-bool integer 1 → str '1' → True."""
        self.assertTrue(OutlookSettingsProcessor()._coerce_bool(1))

    def test_integer_zero_coerced_false(self):
        """Non-bool integer 0 → str '0' → False."""
        self.assertFalse(OutlookSettingsProcessor()._coerce_bool(0))


# ---------------------------------------------------------------------------
# _to_list branches
# ---------------------------------------------------------------------------

class TestToList(unittest.TestCase):
    """Cover _to_list branches."""

    def test_none_returns_empty(self):
        self.assertEqual(OutlookSettingsProcessor()._to_list(None), [])

    def test_list_of_strings(self):
        self.assertEqual(OutlookSettingsProcessor()._to_list(["a", "b"]), ["a", "b"])

    def test_tuple_of_strings(self):
        self.assertEqual(OutlookSettingsProcessor()._to_list(("x", "y")), ["x", "y"])

    def test_list_filters_blank_entries(self):
        """Blank strings in list are filtered out."""
        self.assertEqual(OutlookSettingsProcessor()._to_list(["a", "  ", ""]), ["a"])

    def test_plain_string(self):
        self.assertEqual(OutlookSettingsProcessor()._to_list("hello"), ["hello"])

    def test_empty_string_returns_empty(self):
        """Empty/whitespace-only plain string → []."""
        self.assertEqual(OutlookSettingsProcessor()._to_list(""), [])
        self.assertEqual(OutlookSettingsProcessor()._to_list("   "), [])


# ---------------------------------------------------------------------------
# Integration: processor apply with failed patch (error log propagates)
# ---------------------------------------------------------------------------

class TestSettingsProcessorApplyFailed(unittest.TestCase):
    """Cover _process_single_event → _apply_event_patch failure path end-to-end."""

    def test_apply_failure_logged_but_not_counted_as_changed(self):
        cfg = {"defaults": {"show_as": "busy"}, "rules": []}
        cfg_path = write_yaml(cfg)
        svc = _make_svc(events=[{"id": "E1", "subject": "Meeting"}])
        svc.update_event_settings.side_effect = RuntimeError("network error")

        req = OutlookSettingsRequest(
            config_path=Path(cfg_path),
            calendar=None,
            from_date=None,
            to_date=None,
            dry_run=False,
            service=svc,
        )
        env = OutlookSettingsProcessor().process(OutlookSettingsRequestConsumer(req).consume())
        self.assertTrue(env.ok())
        result = env.payload
        self.assertEqual(result.selected, 1)
        self.assertEqual(result.changed, 0)
        self.assertEqual(len(result.logs), 1)
        self.assertIn("E1", result.logs[0])

    def test_apply_success_counts_as_changed(self):
        """Happy path paired with the failure test above."""
        cfg = {"defaults": {"show_as": "busy"}, "rules": []}
        cfg_path = write_yaml(cfg)
        svc = _make_svc(events=[{"id": "E1", "subject": "Meeting"}])

        req = OutlookSettingsRequest(
            config_path=Path(cfg_path),
            calendar=None,
            from_date=None,
            to_date=None,
            dry_run=False,
            service=svc,
        )
        env = OutlookSettingsProcessor().process(OutlookSettingsRequestConsumer(req).consume())
        self.assertTrue(env.ok())
        result = env.payload
        self.assertEqual(result.selected, 1)
        self.assertEqual(result.changed, 1)
        self.assertEqual(result.logs, [])


# ---------------------------------------------------------------------------
# Integration: dry-run path with _format_patch_log
# ---------------------------------------------------------------------------

class TestSettingsProcessorDryRunLogging(unittest.TestCase):
    """Verify dry-run formats log lines from _format_patch_log."""

    def test_dry_run_logs_patch_details(self):
        cfg = {
            "defaults": {
                "show_as": "tentative",
                "sensitivity": "private",
                "is_reminder_on": "yes",
                "reminder_minutes": 5,
            },
            "rules": [],
        }
        cfg_path = write_yaml(cfg)
        svc = _make_svc(events=[{"id": "E1", "subject": "Stand-up"}])

        req = OutlookSettingsRequest(
            config_path=Path(cfg_path),
            calendar=None,
            from_date=None,
            to_date=None,
            dry_run=True,
            service=svc,
        )
        env = OutlookSettingsProcessor().process(OutlookSettingsRequestConsumer(req).consume())
        self.assertTrue(env.ok())
        result = env.payload
        self.assertEqual(result.selected, 1)
        self.assertEqual(result.changed, 0)
        self.assertEqual(len(result.logs), 1)
        log = result.logs[0]
        self.assertIn("[dry-run]", log)
        self.assertIn("showAs=tentative", log)
        self.assertIn("sensitivity=private", log)
        self.assertIn("isReminderOn=True", log)
        self.assertIn("reminderMinutes=5", log)


if __name__ == "__main__":
    unittest.main(verbosity=2)
