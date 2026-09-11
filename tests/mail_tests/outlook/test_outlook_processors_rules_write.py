"""Tests for missing branches and lines in processors_rules_write.py.

Targets the following uncovered paths (as of 75.2% baseline):
  lines: 121, 126, 129-132, 153, 163-169, 184-185, 242, 293-294, 303-306,
         322, 328, 332, 364-371
  branches: 120->121, 125->126, 128->129, 152->153, 156->150, 163->164,
            163->165, 241->242, 247->237, 302->303, 321->322, 327->328,
            331->332, 361->364, 365->366, 365->371
"""
from __future__ import annotations

import unittest
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

from mail.outlook.processors_rules_write import (
    OutlookRulesSyncProcessor,
    OutlookRulesPlanProcessor,
    OutlookRulesPlanResult,
    OutlookRulesSweepProcessor,
)
from mail.outlook.processors_rules_helpers import (
    RuleContext,
    _build_plan_action,
    _build_rule_action,
    _build_rule_criteria,
    _create_rule_key,
    _format_plan_action,
)
from mail.outlook.consumers import (
    OutlookRulesSyncPayload,
    OutlookRulesPlanPayload,
    OutlookRulesSweepPayload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(**kwargs) -> MagicMock:
    """Return a MagicMock client pre-configured with sensible defaults."""
    client = MagicMock()
    client.list_filters.return_value = kwargs.pop("list_filters", [])
    client.get_label_id_map.return_value = kwargs.pop("name_to_id", {})
    client.get_folder_path_map.return_value = kwargs.pop("folder_path_map", {})
    client.get_folder_id_map.return_value = kwargs.pop("folder_id_map", {})
    for k, v in kwargs.items():
        setattr(client, k, v)
    return client


def _make_ctx(**kwargs) -> RuleContext:
    """Build a minimal RuleContext for unit tests of private helpers."""
    client = kwargs.pop("client", MagicMock())
    return RuleContext(
        client=client,
        name_to_id=kwargs.pop("name_to_id", {}),
        folder_map=kwargs.pop("folder_map", {}),
        move_to_folders=kwargs.pop("move_to_folders", False),
    )


# ---------------------------------------------------------------------------
# OutlookRulesSyncProcessor._create_rule_if_new
# ---------------------------------------------------------------------------

class TestCreateRuleIfNewNoCriteria(unittest.TestCase):
    """Line 121 / branch 120->121: empty criteria returns None."""

    def test_empty_match_returns_none(self):
        """A spec with no recognised match keys yields None (not a tuple)."""
        proc = OutlookRulesSyncProcessor()
        ctx = _make_ctx()
        result = proc._create_rule_if_new(
            spec={"match": {}, "action": {}},
            existing={},
            ctx=ctx,
            dry_run=True,
        )
        self.assertIsNone(result)

    def test_missing_match_key_returns_none(self):
        """A spec with no 'match' key at all also returns None."""
        proc = OutlookRulesSyncProcessor()
        ctx = _make_ctx()
        result = proc._create_rule_if_new(
            spec={"action": {"add": ["Label1"]}},
            existing={},
            ctx=ctx,
            dry_run=True,
        )
        self.assertIsNone(result)


class TestCreateRuleIfNewAlreadyExists(unittest.TestCase):
    """Line 126 / branch 125->126: key already in existing returns (key, False)."""

    def test_existing_key_returns_false_created(self):
        """When the computed key is already in existing, was_created is False."""
        proc = OutlookRulesSyncProcessor()
        ctx = _make_ctx(name_to_id={"Work": "cat-work"})

        spec = {"match": {"from": "boss@example.com"}, "action": {"add": ["Work"]}}

        # First run with empty existing to learn the key
        result_new = proc._create_rule_if_new(spec, {}, ctx, dry_run=True)
        self.assertIsNotNone(result_new)
        key, was_created = result_new
        self.assertTrue(was_created)

        # Now run again with that key pre-populated in existing
        existing = {key: {"id": "rule-existing"}}
        result_dup = proc._create_rule_if_new(spec, existing, ctx, dry_run=True)
        self.assertIsNotNone(result_dup)
        returned_key, was_created_dup = result_dup
        self.assertEqual(returned_key, key)
        self.assertFalse(was_created_dup)


class TestCreateRuleIfNewApplyPath(unittest.TestCase):
    """Lines 129-132 / branch 128->129: dry_run=False calls create_filter."""

    def test_dry_run_false_calls_create_filter(self):
        """When dry_run is False and key is new, create_filter is called."""
        mock_client = MagicMock()
        ctx = _make_ctx(client=mock_client)

        proc = OutlookRulesSyncProcessor()
        result = proc._create_rule_if_new(
            spec={"match": {"from": "news@example.com"}, "action": {}},
            existing={},
            ctx=ctx,
            dry_run=False,
        )
        self.assertIsNotNone(result)
        _key, was_created = result
        self.assertTrue(was_created)
        mock_client.create_filter.assert_called_once()

    def test_create_filter_exception_is_swallowed(self):
        """Exception from create_filter is caught; rule still counts as (key, True)."""
        mock_client = MagicMock()
        mock_client.create_filter.side_effect = Exception("Graph API 429")
        ctx = _make_ctx(client=mock_client)

        proc = OutlookRulesSyncProcessor()
        result = proc._create_rule_if_new(
            spec={"match": {"from": "spam@example.com"}, "action": {}},
            existing={},
            ctx=ctx,
            dry_run=False,
        )
        self.assertIsNotNone(result)
        _key, was_created = result
        self.assertTrue(was_created)
        mock_client.create_filter.assert_called_once()


# ---------------------------------------------------------------------------
# OutlookRulesSyncProcessor._create_desired_rules
# ---------------------------------------------------------------------------

class TestCreateDesiredRulesSkipInvalid(unittest.TestCase):
    """Line 153 / branch 152->153: None result from _create_rule_if_new is skipped."""

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_invalid_spec_not_counted(self, mock_norm, mock_load):
        """A spec with no valid criteria contributes 0 to created count."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {}, "action": {}},                             # invalid — no criteria
            {"match": {"from": "valid@example.com"}, "action": {}},  # valid
        ]

        client = _make_client(list_filters=[])
        payload = OutlookRulesSyncPayload(client=client, config_path="/t.yaml", dry_run=True)
        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        # Only the valid spec was created
        self.assertEqual(envelope.payload.created, 1)

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_two_new_specs_both_counted(self, mock_norm, mock_load):
        """Two valid new specs both count as created; loop iterates twice with was_created=True."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "first@example.com"}, "action": {}},
            {"match": {"from": "second@example.com"}, "action": {}},
        ]

        client = _make_client(list_filters=[])
        payload = OutlookRulesSyncPayload(client=client, config_path="/t.yaml", dry_run=True)
        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.created, 2)

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_existing_spec_not_counted(self, mock_norm, mock_load):
        """Branch 156->150: was_created=False when key already exists does not increment created."""
        mock_load.return_value = {"filters": []}
        # One desired spec
        mock_norm.return_value = [
            {"match": {"from": "repeat@example.com"}, "action": {}}
        ]
        # The same rule exists already; compute canonical key via a quick helper run
        # We pre-seed existing by running process() dry once, then using the rule dict
        existing_rule = {
            "criteria": {"from": "repeat@example.com"},
            "action": {},
        }
        client = _make_client(list_filters=[existing_rule])
        payload = OutlookRulesSyncPayload(client=client, config_path="/t.yaml", dry_run=True)
        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        # Rule already exists, so created == 0
        self.assertEqual(envelope.payload.created, 0)


# ---------------------------------------------------------------------------
# OutlookRulesSyncProcessor._delete_one_rule
# ---------------------------------------------------------------------------

class TestDeleteOneRule(unittest.TestCase):
    """Lines 163-169 / branches 163->164, 163->165."""

    def test_dry_run_returns_true_without_calling_delete(self):
        """dry_run=True: returns True, delete_filter never called."""
        mock_client = MagicMock()
        proc = OutlookRulesSyncProcessor()
        result = proc._delete_one_rule(mock_client, "rule-99", dry_run=True)
        self.assertTrue(result)
        mock_client.delete_filter.assert_not_called()

    def test_no_rid_returns_true_without_calling_delete(self):
        """Empty rid: returns True, delete_filter never called."""
        mock_client = MagicMock()
        proc = OutlookRulesSyncProcessor()
        result = proc._delete_one_rule(mock_client, None, dry_run=False)
        self.assertTrue(result)
        mock_client.delete_filter.assert_not_called()

    def test_apply_path_calls_delete_filter(self):
        """dry_run=False and valid rid: delete_filter called, returns True."""
        mock_client = MagicMock()
        mock_client.delete_filter.return_value = None
        proc = OutlookRulesSyncProcessor()
        result = proc._delete_one_rule(mock_client, "rule-42", dry_run=False)
        self.assertTrue(result)
        mock_client.delete_filter.assert_called_once_with("rule-42")

    def test_delete_filter_exception_returns_false(self):
        """delete_filter raising an exception: returns False."""
        mock_client = MagicMock()
        mock_client.delete_filter.side_effect = Exception("Not found")
        proc = OutlookRulesSyncProcessor()
        result = proc._delete_one_rule(mock_client, "bad-rule", dry_run=False)
        self.assertFalse(result)
        mock_client.delete_filter.assert_called_once_with("bad-rule")


# ---------------------------------------------------------------------------
# OutlookRulesSyncProcessor._delete_missing_rules
# ---------------------------------------------------------------------------

class TestDeleteMissingRules(unittest.TestCase):
    """Lines 184-185: the body of _delete_missing_rules."""

    def test_deletes_rules_not_in_desired_set(self):
        """Rules whose keys are not in desired_keys are deleted."""
        mock_client = MagicMock()
        mock_client.delete_filter.return_value = None

        existing = {
            "key-keep": {"id": "r-keep"},
            "key-remove": {"id": "r-remove"},
        }
        desired_keys = {"key-keep"}

        payload = OutlookRulesSyncPayload(
            client=mock_client, config_path="/t.yaml", dry_run=False
        )
        proc = OutlookRulesSyncProcessor()
        deleted = proc._delete_missing_rules(existing, desired_keys, payload)

        self.assertEqual(deleted, 1)
        mock_client.delete_filter.assert_called_once_with("r-remove")

    def test_dry_run_counts_without_deleting(self):
        """dry_run=True: counts the rules to delete but never calls delete_filter."""
        mock_client = MagicMock()
        existing = {
            "key-a": {"id": "r-a"},
            "key-b": {"id": "r-b"},
        }
        payload = OutlookRulesSyncPayload(
            client=mock_client, config_path="/t.yaml", dry_run=True
        )
        proc = OutlookRulesSyncProcessor()
        deleted = proc._delete_missing_rules(existing, set(), payload)

        self.assertEqual(deleted, 2)
        mock_client.delete_filter.assert_not_called()

    def test_nothing_to_delete_returns_zero(self):
        """When every existing key is desired, nothing is deleted."""
        mock_client = MagicMock()
        existing = {"key-a": {"id": "r-a"}}
        payload = OutlookRulesSyncPayload(
            client=mock_client, config_path="/t.yaml", dry_run=False
        )
        proc = OutlookRulesSyncProcessor()
        deleted = proc._delete_missing_rules(existing, {"key-a"}, payload)

        self.assertEqual(deleted, 0)
        mock_client.delete_filter.assert_not_called()


# ---------------------------------------------------------------------------
# Full sync with delete_missing=True
# ---------------------------------------------------------------------------

class TestSyncWithDeleteMissing(unittest.TestCase):
    """Exercise the delete_missing branch in process()."""

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_delete_missing_removes_stale_rules(self, mock_norm, mock_load):
        """delete_missing=True causes stale rules to be removed."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "keep@example.com"}, "action": {}}
        ]

        # Stale rule has no corresponding desired spec
        stale_rule = {
            "id": "stale-99",
            "criteria": {"from": "stale@example.com"},
            "action": {},
        }
        mock_client = _make_client(list_filters=[stale_rule])
        mock_client.delete_filter.return_value = None

        payload = OutlookRulesSyncPayload(
            client=mock_client,
            config_path="/t.yaml",
            dry_run=False,
            delete_missing=True,
        )
        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.deleted, 1)
        mock_client.delete_filter.assert_called_once_with("stale-99")


# ---------------------------------------------------------------------------
# OutlookRulesPlanProcessor._build_plan_items
# ---------------------------------------------------------------------------

class TestBuildPlanItemsSkipNoCriteria(unittest.TestCase):
    """Line 242 / branch 241->242: continue when criteria is empty."""

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_spec_with_no_criteria_skipped(self, mock_norm, mock_load):
        """A spec with no valid match fields is skipped in plan output."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {}, "action": {}},                              # empty — skipped
            {"match": {"from": "ok@example.com"}, "action": {}},      # valid
        ]

        client = _make_client(list_filters=[])
        payload = OutlookRulesPlanPayload(client=client, config_path="/t.yaml")
        envelope = OutlookRulesPlanProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.would_create, 1)


class TestBuildPlanItemsSkipExisting(unittest.TestCase):
    """Branch 247->237: when computed key is already in existing_keys, skip."""

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_existing_key_not_included_in_plan(self, mock_norm, mock_load):
        """A desired spec whose key matches an existing rule is not in plan items."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "old@example.com"}, "action": {}}
        ]

        # Existing rule with the same from address — keys will collide
        existing_rule = {
            "criteria": {"from": "old@example.com"},
            "action": {},
        }
        client = _make_client(list_filters=[existing_rule])
        payload = OutlookRulesPlanPayload(client=client, config_path="/t.yaml")
        envelope = OutlookRulesPlanProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.would_create, 0)
        self.assertEqual(envelope.payload.plan_items, [])


# ---------------------------------------------------------------------------
# OutlookRulesSweepProcessor.process — exception path
# ---------------------------------------------------------------------------

class TestSweepProcessorException(unittest.TestCase):
    """Lines 293-294: outer exception handler in sweep process()."""

    @patch("core.yamlio.load_config")
    def test_config_error_returns_error_envelope(self, mock_load):
        """If load_config raises, process returns an error envelope."""
        mock_load.side_effect = Exception("YAML parse error")
        client = MagicMock()
        payload = OutlookRulesSweepPayload(client=client, config_path="/bad.yaml")
        envelope = OutlookRulesSweepProcessor().process(payload)

        self.assertEqual(envelope.status, "error")
        self.assertIsNone(envelope.payload)
        self.assertIn("YAML parse error", envelope.diagnostics["error"])
        self.assertEqual(envelope.diagnostics["code"], 1)


# ---------------------------------------------------------------------------
# OutlookRulesSweepProcessor._clear_cache_if_needed
# ---------------------------------------------------------------------------

class TestClearCacheIfNeeded(unittest.TestCase):
    """Lines 303-306 / branch 302->303."""

    def test_clear_cache_true_calls_cfg_clear(self):
        """clear_cache=True calls client.cfg_clear()."""
        mock_client = MagicMock()
        proc = OutlookRulesSweepProcessor()
        proc._clear_cache_if_needed(mock_client, clear_cache=True)
        mock_client.cfg_clear.assert_called_once()

    def test_clear_cache_false_does_not_call_cfg_clear(self):
        """clear_cache=False: cfg_clear never called."""
        mock_client = MagicMock()
        proc = OutlookRulesSweepProcessor()
        proc._clear_cache_if_needed(mock_client, clear_cache=False)
        mock_client.cfg_clear.assert_not_called()

    def test_cfg_clear_exception_is_swallowed(self):
        """If cfg_clear raises, the exception is silently absorbed."""
        mock_client = MagicMock()
        mock_client.cfg_clear.side_effect = Exception("Cache unavailable")
        proc = OutlookRulesSweepProcessor()
        # Should not raise
        proc._clear_cache_if_needed(mock_client, clear_cache=True)
        mock_client.cfg_clear.assert_called_once()


# ---------------------------------------------------------------------------
# OutlookRulesSweepProcessor._process_sweep_rules — skip branches
# ---------------------------------------------------------------------------

class TestProcessSweepRulesSkips(unittest.TestCase):
    """Lines 322, 328, 332 / branches 321->322, 327->328, 331->332."""

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_no_search_query_rule_skipped(self, mock_norm, mock_load):
        """A spec with no matchable search query (srch='') is skipped."""
        mock_load.return_value = {"filters": []}
        # A spec with no 'from' or 'subject' produces empty search query
        mock_norm.return_value = [{"match": {}, "action": {}}]

        client = MagicMock()
        client.get_folder_path_map.return_value = {}
        payload = OutlookRulesSweepPayload(
            client=client, config_path="/t.yaml", dry_run=True, move_to_folders=True
        )
        envelope = OutlookRulesSweepProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.moved, 0)
        client.search_inbox_messages.assert_not_called()

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_no_destination_folder_rule_skipped(self, mock_norm, mock_load):
        """A spec whose action has no valid folder destination is skipped."""
        mock_load.return_value = {"filters": []}
        # Has a search query but no moveToFolder and move_to_folders=False
        mock_norm.return_value = [{"match": {"from": "news@example.com"}, "action": {}}]

        client = MagicMock()
        client.get_folder_path_map.return_value = {}
        payload = OutlookRulesSweepPayload(
            client=client,
            config_path="/t.yaml",
            dry_run=True,
            move_to_folders=False,  # no automatic folder resolution
        )
        envelope = OutlookRulesSweepProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.moved, 0)
        client.search_inbox_messages.assert_not_called()

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_no_messages_found_rule_skipped(self, mock_norm, mock_load):
        """When search returns no messages, no move is attempted."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "news@example.com"}, "action": {"moveToFolder": "Archive"}}
        ]

        client = MagicMock()
        client.get_folder_path_map.return_value = {"Archive": "folder-arch"}
        client.search_inbox_messages.return_value = []  # no messages
        payload = OutlookRulesSweepPayload(
            client=client, config_path="/t.yaml", dry_run=True, move_to_folders=True
        )
        envelope = OutlookRulesSweepProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.moved, 0)
        client.move_message.assert_not_called()


# ---------------------------------------------------------------------------
# OutlookRulesSweepProcessor._move_messages
# ---------------------------------------------------------------------------

class TestMoveMessages(unittest.TestCase):
    """Lines 364-371 / branches 361->364, 365->366, 365->371."""

    def test_dry_run_returns_count_without_moving(self):
        """dry_run=True: count is len(ids), move_message never called."""
        mock_client = MagicMock()
        proc = OutlookRulesSweepProcessor()
        moved = proc._move_messages(mock_client, ["m1", "m2", "m3"], "dest-id", dry_run=True)
        self.assertEqual(moved, 3)
        mock_client.move_message.assert_not_called()

    def test_apply_path_moves_all_messages(self):
        """dry_run=False: each id is moved, total count returned."""
        mock_client = MagicMock()
        mock_client.move_message.return_value = None
        proc = OutlookRulesSweepProcessor()
        moved = proc._move_messages(mock_client, ["m1", "m2"], "dest-id", dry_run=False)
        self.assertEqual(moved, 2)
        self.assertEqual(mock_client.move_message.call_count, 2)
        mock_client.move_message.assert_any_call("m1", "dest-id")
        mock_client.move_message.assert_any_call("m2", "dest-id")

    def test_move_message_exception_skips_message(self):
        """If move_message raises for one message, it is skipped; others still counted."""
        mock_client = MagicMock()
        # First call raises, second succeeds
        mock_client.move_message.side_effect = [Exception("Locked"), None]
        proc = OutlookRulesSweepProcessor()
        moved = proc._move_messages(mock_client, ["m-fail", "m-ok"], "dest-id", dry_run=False)
        self.assertEqual(moved, 1)
        self.assertEqual(mock_client.move_message.call_count, 2)

    def test_empty_message_list_returns_zero(self):
        """Empty ids list: no calls, moved=0."""
        mock_client = MagicMock()
        proc = OutlookRulesSweepProcessor()
        moved = proc._move_messages(mock_client, [], "dest-id", dry_run=False)
        self.assertEqual(moved, 0)
        mock_client.move_message.assert_not_called()


# ---------------------------------------------------------------------------
# Full sweep integration with clear_cache and non-dry-run
# ---------------------------------------------------------------------------

class TestSweepFullIntegration(unittest.TestCase):
    """Exercise clear_cache, actual message move, and count aggregation."""

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_sweep_with_clear_cache_and_real_moves(self, mock_norm, mock_load):
        """Sweep with clear_cache=True and dry_run=False moves messages."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "news@example.com"}, "action": {"moveToFolder": "Archive"}}
        ]

        client = MagicMock()
        client.cfg_clear.return_value = None
        client.get_folder_path_map.return_value = {"Archive": "folder-arch"}
        client.ensure_folder_path.return_value = "folder-arch"
        client.search_inbox_messages.return_value = ["m1", "m2"]
        client.move_message.return_value = None

        payload = OutlookRulesSweepPayload(
            client=client,
            config_path="/t.yaml",
            dry_run=False,
            move_to_folders=True,
            clear_cache=True,
        )
        envelope = OutlookRulesSweepProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.moved, 2)
        client.cfg_clear.assert_called_once()
        self.assertEqual(client.move_message.call_count, 2)

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_sweep_multiple_rules_count_aggregated(self, mock_norm, mock_load):
        """moved count aggregates across multiple rules."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "a@example.com"}, "action": {"moveToFolder": "FolderA"}},
            {"match": {"from": "b@example.com"}, "action": {"moveToFolder": "FolderB"}},
        ]

        client = MagicMock()
        client.get_folder_path_map.return_value = {
            "FolderA": "fid-a",
            "FolderB": "fid-b",
        }
        folder_map = {"FolderA": "fid-a", "FolderB": "fid-b"}
        client.ensure_folder_path.side_effect = lambda p: folder_map[p]
        client.search_inbox_messages.side_effect = [["m1", "m2"], ["m3"]]
        client.move_message.return_value = None

        payload = OutlookRulesSweepPayload(
            client=client,
            config_path="/t.yaml",
            dry_run=False,
            move_to_folders=True,
        )
        envelope = OutlookRulesSweepProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.moved, 3)


class TestPlanProcessorHonoursNoMoveToFolder(unittest.TestCase):
    """The plan processor must not derive a folder for a keepInInbox rule.

    This exercises OutlookRulesPlanProcessor.process end to end (config load ->
    normalize -> _build_plan_action) rather than calling the action builder
    directly. That distinction is the whole point of these tests: the builder
    was already guarded, but `process` re-normalizes the derived config first,
    and normalization dropped the `noMoveToFolder` marker because it builds its
    action dict from an allowlist. The guard then never fired and the rule got
    a folder move anyway -- the exact inbox-move keepInInbox exists to prevent.

    Reproduced against live Outlook before the fix: `rules.plan` emitted
    `action={'moveToFolderId': 'Tech-Grafana', ...}` for the grafana rule.
    """

    def _plan(self, filters: list[dict]) -> list[str]:
        # Path-keyed: that is what the processor loads, and the ids are
        # deliberately unlike the normalized label spellings so an assertion can
        # tell a real resolution from the path-fallback string.
        client = _make_client(
            name_to_id={"Tech/Grafana": "cat-graf", "Lists/Commercial": "cat-comm"},
            folder_path_map={"Tech/Grafana": "folder-graf", "Lists/Commercial": "folder-comm"},
        )
        payload = OutlookRulesPlanPayload(
            client=client,
            config_path="/t.yaml",
            move_to_folders=True,
        )
        with patch(
            "core.yamlio.load_config", return_value={"filters": filters}
        ):
            envelope = OutlookRulesPlanProcessor().process(payload)
        self.assertEqual(envelope.status, "success")
        result = envelope.payload
        self.assertIsNotNone(result)
        # cast rather than `assert` for the Optional narrowing: bandit flags a
        # bare assert (B101) since it vanishes under -O. assertIsNotNone above
        # is the real check.
        return cast(OutlookRulesPlanResult, result).plan_items

    def test_keep_in_inbox_rule_plans_no_folder_move(self):
        """A derived noMoveToFolder rule must plan an action with no moveToFolderId."""
        items = self._plan(
            [{"match": {"from": "grafana.com"}, "action": {"add": ["Tech/Grafana"], "noMoveToFolder": True}}]
        )
        self.assertEqual(1, len(items))
        self.assertNotIn("moveToFolderId", items[0])

    def test_normal_rule_still_plans_a_folder_move(self):
        """Contrast: without the marker the folder derivation must still happen.

        Guards against "fixing" the bug by disabling folder moves for everyone,
        which would stop commercial and newsletter mail being filed.
        """
        items = self._plan(
            [{"match": {"from": "shop.example.com"}, "action": {"add": ["Lists/Commercial"]}}]
        )
        self.assertEqual(1, len(items))
        # The REAL id, not merely "some id". Asserting presence alone passed on
        # the path-fallback string `Lists-Commercial`, which is what made the
        # plan key diverge from apply's for every nested rule.
        self.assertIn("'moveToFolderId': 'folder-comm'", items[0])
        self.assertNotIn("Lists-Commercial", items[0])

    def test_raw_keep_in_inbox_config_plans_no_folder_move(self):
        """The RAW unified config must work too, with no derive step in between.

        Regression: `rules.plan`/`rules.sync`/`rules.sweep` accept the documented
        unified config directly, where the marker is still spelled `keepInInbox`.
        The fix originally keyed only on the derived `noMoveToFolder`, so this
        path kept deriving a folder from add[0] and moving the mail out.

        Verified live before the fix: `rules.plan` on a raw config emitted
        `action={'moveToFolderId': 'Tech-Grafana', ...}`.
        """
        items = self._plan(
            [{"match": {"from": "grafana.com"}, "action": {"add": ["Tech/Grafana"], "keepInInbox": True}}]
        )
        self.assertEqual(1, len(items))
        self.assertNotIn("moveToFolderId", items[0])

    def test_explicit_move_to_folder_wins_over_the_marker(self):
        """An explicit moveToFolder beats noMoveToFolder, and plan must agree with apply.

        The two co-occur in real output: `derive.filters
        --outlook-archive-on-remove-inbox` emits `moveToFolder: Archive`
        alongside the marker for any rule that removes INBOX.

        Regression: `_build_plan_action` did not check `moveToFolder` at all, so
        it reported no move while `_build_rule_action` (sync) and
        `_resolve_destination_folder` (sweep) both moved to Archive. A plan that
        contradicts its own apply is worse than either behaviour alone, because
        the plan is what you read before committing to the change.
        """
        items = self._plan(
            [{
                "match": {"from": "grafana.com"},
                "action": {"moveToFolder": "Archive", "noMoveToFolder": True},
            }]
        )
        self.assertEqual(1, len(items))
        self.assertIn("moveToFolderId", items[0])

    def test_mixed_rules_each_take_their_own_path(self):
        """Both rule kinds in one config: only the marked one skips the move."""
        items = self._plan(
            [
                {"match": {"from": "grafana.com"}, "action": {"add": ["Tech/Grafana"], "noMoveToFolder": True}},
                {"match": {"from": "shop.example.com"}, "action": {"add": ["Lists/Commercial"]}},
            ]
        )
        self.assertEqual(2, len(items))
        graf = next(i for i in items if "grafana.com" in i)
        comm = next(i for i in items if "shop.example.com" in i)
        self.assertNotIn("moveToFolderId", graf)
        self.assertIn("moveToFolderId", comm)


class TestPlanNestedExplicitDestination(unittest.TestCase):
    """A nested explicit `moveToFolder` must key and display the same as sync.

    Regression: `_build_plan_action` normalized the path before looking it up,
    turning `Security/Alerts` into `Security-Alerts`. That matched no key in
    either folder map, so the normalized string was used AS the folder id —
    while sync resolved the real path through `ensure_folder_path()` and got a
    Graph id. The plan's `_create_rule_key` therefore differed from apply's, so
    an existing rule was reported as "Would create" and the destination was
    displayed with the wrong name.

    Two changes are needed together: look the raw path up first, and give plan
    a path-keyed map (`get_folder_path_map`, as sync and sweep already use)
    rather than `get_folder_id_map`, which keys displayName only and can never
    contain a nested path.
    """

    ACTION = {"add": ["Security/Alerts"], "moveToFolder": "Security/Alerts"}
    MATCH = {"from": "sec.example.net"}
    PATH_MAP = {"Security/Alerts": "real-graph-id"}

    def test_plan_key_matches_sync_key(self):
        """The same spec must produce the same rule key in plan and sync."""
        plan_ctx = RuleContext.for_plan(
            name_to_id={"Security/Alerts": "cat-sec"},
            folder_map=self.PATH_MAP,
            move_to_folders=True,
        )
        client = MagicMock()
        client.ensure_folder_path.return_value = "real-graph-id"
        sync_ctx = RuleContext(
            client=client,
            name_to_id={"Security/Alerts": "cat-sec"},
            folder_map=self.PATH_MAP,
            move_to_folders=True,
        )

        plan_action = _build_plan_action(dict(self.ACTION), plan_ctx)
        sync_action = _build_rule_action(dict(self.ACTION), sync_ctx)

        self.assertEqual("real-graph-id", plan_action["moveToFolderId"])
        self.assertEqual(sync_action, plan_action)
        crit = _build_rule_criteria(self.MATCH)
        self.assertEqual(
            _create_rule_key(crit, sync_action),
            _create_rule_key(crit, plan_action),
            "plan key must match sync key or plan reports an existing rule as new",
        )

    def test_plan_displays_the_real_path(self):
        """Display resolves back to `Security/Alerts`, not `Security-Alerts`."""
        plan_ctx = RuleContext.for_plan(
            name_to_id={}, folder_map=self.PATH_MAP, move_to_folders=True
        )
        action = _build_plan_action(dict(self.ACTION), plan_ctx)
        disp = _format_plan_action(action, self.PATH_MAP)
        self.assertEqual("Security/Alerts", disp["moveToFolder"])

    def test_nested_raw_add_label_resolves_to_the_real_id(self):
        """A nested label in `add[]` must resolve like sync, not to its alias.

        Regression: the `add[0]` branch normalized before the lookup, so a raw
        `add: [Lists/Commercial]` became `Lists-Commercial`, missed the
        path-keyed map, and was used as the folder id — while
        `_build_rule_action` resolves the raw path and gets a Graph id. Keys
        then diverged for every nested raw rule, not just explicit ones.
        """
        path_map = {"Lists/Commercial": "real-comm-id"}
        plan_ctx = RuleContext.for_plan(
            name_to_id={}, folder_map=path_map, move_to_folders=True
        )
        client = MagicMock()
        client.ensure_folder_path.return_value = "real-comm-id"
        sync_ctx = RuleContext(
            client=client, name_to_id={}, folder_map=path_map, move_to_folders=True
        )

        spec = {"add": ["Lists/Commercial"]}
        plan_action = _build_plan_action(dict(spec), plan_ctx)
        sync_action = _build_rule_action(dict(spec), sync_ctx)

        self.assertEqual("real-comm-id", plan_action["moveToFolderId"])
        self.assertEqual(sync_action, plan_action)
        crit = _build_rule_criteria({"from": "shop.example.com"})
        self.assertEqual(
            _create_rule_key(crit, sync_action), _create_rule_key(crit, plan_action)
        )

    def test_explicit_destination_loads_path_map_under_categories_only(self):
        """`--categories-only` must still resolve an explicit destination.

        Regression: the map was gated on `move_to_folders` alone, but both
        builders honour an explicit `moveToFolder` regardless of that flag. With
        `--categories-only` the plan therefore fell back to the literal path
        while apply used the Graph id, so an existing rule read as "Would
        create".
        """
        client = _make_client(folder_path_map={"Security/Alerts": "real-sec-id"})
        payload = OutlookRulesPlanPayload(
            client=client, config_path="/t.yaml", move_to_folders=False
        )
        filters = [{
            "match": {"from": "sec.example.net"},
            "action": {"add": ["Security/Alerts"], "moveToFolder": "Security/Alerts"},
        }]
        with patch("core.yamlio.load_config", return_value={"filters": filters}):
            envelope = OutlookRulesPlanProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        result = envelope.payload
        self.assertIsNotNone(result)
        items = cast(OutlookRulesPlanResult, result).plan_items
        self.assertEqual(1, len(items))
        self.assertIn("'moveToFolderId': 'real-sec-id'", items[0])
        client.get_folder_path_map.assert_called_once()

    def test_no_explicit_destination_skips_the_map_under_categories_only(self):
        """Contrast: with nothing to resolve, the map must not be fetched.

        Keeps the fix above from turning into an unconditional extra API call on
        every categories-only plan.
        """
        client = _make_client(folder_path_map={"Security/Alerts": "real-sec-id"})
        payload = OutlookRulesPlanPayload(
            client=client, config_path="/t.yaml", move_to_folders=False
        )
        filters = [{
            "match": {"from": "a@example.com"},
            "action": {"add": ["Tech/Grafana"], "noMoveToFolder": True},
        }]
        with patch("core.yamlio.load_config", return_value={"filters": filters}):
            envelope = OutlookRulesPlanProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        client.get_folder_path_map.assert_not_called()

    def test_plan_processor_requests_a_path_keyed_map(self):
        """The processor must source folder ids by path, as sync and sweep do.

        Asserted at the client-call level: with only `get_folder_id_map`
        populated (displayName keys), a nested destination cannot resolve.
        """
        client = _make_client(folder_path_map=self.PATH_MAP)
        client.get_folder_id_map.return_value = {"Alerts": "wrong-id"}
        payload = OutlookRulesPlanPayload(
            client=client, config_path="/t.yaml", move_to_folders=True
        )
        with patch(
            "core.yamlio.load_config",
            return_value={"filters": [{"match": self.MATCH, "action": dict(self.ACTION)}]},
        ):
            envelope = OutlookRulesPlanProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        client.get_folder_path_map.assert_called_once()
        client.get_folder_id_map.assert_not_called()


class TestSweepHonoursKeepInInboxEndToEnd(unittest.TestCase):
    """Real derive output through the real sweep processor, NOT dry-run.

    The helper-level tests mock the action spec directly. This one derives it
    from a unified config, so it covers the derive->sweep seam where the marker
    could be lost or overridden, and asserts on `move_message` — the call that
    actually takes mail out of the inbox — rather than on a resolved folder ID.

    Non-dry-run on purpose: `_resolve_destination_folder` branches on `dry_run`,
    so a dry-run-only test leaves the live path unproven.
    """

    def _derive_outlook_action(self, yaml_text: str, archive: bool) -> dict:
        import tempfile

        import yaml as _yaml

        from mail.config_cli.pipeline_derive import (
            DeriveFiltersProcessor,
            DeriveFiltersRequest,
        )

        with tempfile.TemporaryDirectory() as td:
            ip = Path(td) / "in.yaml"
            ip.write_text(yaml_text)
            og, oo = Path(td) / "g.yaml", Path(td) / "o.yaml"
            res = DeriveFiltersProcessor().process(
                DeriveFiltersRequest(
                    in_path=str(ip),
                    out_gmail=str(og),
                    out_outlook=str(oo),
                    outlook_archive_on_remove_inbox=archive,
                    outlook_move_to_folders=not archive,
                )
            )
            self.assertTrue(res.ok(), "derive step failed")
            doc = _yaml.safe_load(oo.read_text())
        return doc["filters"][0]

    def _sweep(self, spec: dict) -> MagicMock:
        client = _make_client(folder_path_map={"Tech/Grafana": "fid-graf", "Archive": "fid-arch"})
        client.ensure_folder_path.return_value = "fid-arch"
        client.search_inbox_messages.return_value = ["m1", "m2"]
        payload = OutlookRulesSweepPayload(
            client=client,
            config_path="/t.yaml",
            dry_run=False,
            move_to_folders=True,
        )
        with patch("core.yamlio.load_config", return_value={"filters": [spec]}):
            envelope = OutlookRulesSweepProcessor().process(payload)
        self.assertEqual(envelope.status, "success")
        return client

    KEEP_PLUS_REMOVE = (
        "filters:\n"
        "  - match:\n"
        "      from: grafana.com\n"
        "    action:\n"
        "      add: [Tech/Grafana]\n"
        "      keepInInbox: true\n"
        "      remove: [INBOX]\n"
    )

    UNMARKED_REMOVE = (
        "filters:\n"
        "  - match:\n"
        "      from: shop.example.com\n"
        "    action:\n"
        "      add: [Lists/Commercial]\n"
        "      remove: [INBOX]\n"
    )

    def test_sweep_does_not_move_keep_in_inbox_rule(self):
        """keepInInbox + move_to_folders: sweep must not move anything."""
        spec = self._derive_outlook_action(self.KEEP_PLUS_REMOVE, archive=False)
        client = self._sweep(spec)
        client.move_message.assert_not_called()

    def test_sweep_does_not_move_keep_in_inbox_rule_under_archive_flag(self):
        """Same, with --outlook-archive-on-remove-inbox.

        Regression: the archive branch set `moveToFolder: Archive` without
        checking the marker, and every consumer prioritises an explicit
        destination — so the sweep moved mail to Archive despite keepInInbox.
        """
        spec = self._derive_outlook_action(self.KEEP_PLUS_REMOVE, archive=True)
        client = self._sweep(spec)
        client.move_message.assert_not_called()

    def test_sweep_still_moves_unmarked_rule_under_archive_flag(self):
        """Contrast: an unmarked remove:[INBOX] rule must still be archived."""
        spec = self._derive_outlook_action(self.UNMARKED_REMOVE, archive=True)
        client = self._sweep(spec)
        self.assertEqual(2, client.move_message.call_count)


if __name__ == "__main__":
    unittest.main()
