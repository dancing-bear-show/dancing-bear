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
from unittest.mock import MagicMock, patch

from mail.outlook.processors_rules_write import (
    OutlookRulesSyncProcessor,
    OutlookRulesPlanProcessor,
    OutlookRulesSweepProcessor,
)
from mail.outlook.processors_rules_helpers import RuleContext
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


if __name__ == "__main__":
    unittest.main()
