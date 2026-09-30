"""Default (non-reconcile) Outlook rules sync must match live rules case-insensitively.

Observed live: Graph returns rule criteria UPPERCASE (``SCOUTSTRACKER.CA``) while
derive emits lowercase. The default ``rules.sync`` keyed both sides on the raw
string, so ``rules.sync --dry-run`` reported ``Created: 25`` where
``--reconcile`` reported 3; applied, it would have created 22 duplicate rules.
``--delete-missing`` had the mirror-image defect: every UPPERCASE-stored rule
looked absent from the config and was deleted.

Each test asserts on the client calls, not only on the tally.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from mail.outlook.consumers import OutlookRulesPlanPayload, OutlookRulesSyncPayload
from mail.outlook.processors_rules_helpers import _canon_rule, _create_rule_key
from mail.outlook.processors_rules_index import _index_live_rules
from mail.outlook.processors_rules_plan import OutlookRulesPlanProcessor
from mail.outlook.processors_rules_write import OutlookRulesSyncProcessor

_LOAD = "core.yamlio.load_config"
_NORM = "mail.dsl.normalize_filters_for_outlook"


def _make_client(live: list[dict]) -> MagicMock:
    client = MagicMock()
    client.list_filters.return_value = [dict(r) for r in live]
    client.get_label_id_map.return_value = {}
    client.get_folder_path_map.return_value = {}
    return client


def _sync(client: MagicMock, *, dry_run: bool = False, delete_missing: bool = False,
          reconcile: bool = False):
    return OutlookRulesSyncProcessor().process(OutlookRulesSyncPayload(
        client=client, config_path="/test.yaml", dry_run=dry_run,
        delete_missing=delete_missing, reconcile=reconcile,
    ))


def _plan(client: MagicMock, *, reconcile: bool = False):
    return OutlookRulesPlanProcessor().process(OutlookRulesPlanPayload(
        client=client, config_path="/test.yaml", reconcile=reconcile,
    ))


def _spec(frm: str, forward: str = "kids@example.com") -> dict:
    return {"match": {"from": frm}, "action": {"forward": forward}}


def _live(rid: str, frm: str, forward: str = "kids@example.com", **extra) -> dict:
    return {"id": rid, "criteria": {"from": frm}, "action": {"forward": forward}, **extra}


UPPER_LIVE = _live("scouts", "SCOUTSTRACKER.CA")
LOWER_SPEC = _spec("scoutstracker.ca")


class TestKeyFoldsCriteria(unittest.TestCase):
    """The key both sides are compared on ignores criteria case and OR order."""

    def test_live_and_desired_keys_match_across_case(self):
        self.assertEqual(
            _canon_rule(UPPER_LIVE),
            _create_rule_key({"from": "scoutstracker.ca"}, {"forward": "kids@example.com"}),
        )

    def test_or_token_order_ignored(self):
        self.assertEqual(
            _create_rule_key({"from": "B.COM OR A.COM"}, {}),
            _create_rule_key({"from": "a.com OR b.com"}, {}),
        )

    def test_action_fields_not_folded(self):
        """Action values are Graph ids / addresses and are compared verbatim."""
        self.assertNotEqual(
            _create_rule_key({"from": "a.com"}, {"moveToFolderId": "AAMk-ID"}),
            _create_rule_key({"from": "a.com"}, {"moveToFolderId": "aamk-id"}),
        )


class TestDefaultSyncMatchesCaseInsensitively(unittest.TestCase):

    @patch(_NORM)
    @patch(_LOAD)
    def test_dry_run_uppercase_live_is_not_created(self, mock_load, mock_norm):
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [LOWER_SPEC]
        client = _make_client([UPPER_LIVE])

        env = _sync(client, dry_run=True)

        self.assertEqual(env.status, "success")
        self.assertEqual(env.payload.created, 0)
        self.assertEqual(client.create_filter.call_count, 0)
        self.assertEqual(client.delete_filter.call_count, 0)

    @patch(_NORM)
    @patch(_LOAD)
    def test_real_run_uppercase_live_creates_no_duplicate(self, mock_load, mock_norm):
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [LOWER_SPEC]
        client = _make_client([UPPER_LIVE])

        env = _sync(client, dry_run=False)

        self.assertEqual(env.status, "success")
        self.assertEqual(env.payload.created, 0)
        self.assertEqual(client.create_filter.call_count, 0)

    @patch(_NORM)
    @patch(_LOAD)
    def test_or_token_order_and_case_both_match(self, mock_load, mock_norm):
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [_spec("nintendo.net OR accounts.nintendo.com")]
        client = _make_client([_live("nin", "ACCOUNTS.NINTENDO.COM OR NINTENDO.NET")])

        env = _sync(client, dry_run=False)

        self.assertEqual(env.payload.created, 0)
        self.assertEqual(client.create_filter.call_count, 0)

    @patch(_NORM)
    @patch(_LOAD)
    def test_different_sender_still_created(self, mock_load, mock_norm):
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [LOWER_SPEC, _spec("other-club.ca")]
        client = _make_client([UPPER_LIVE])

        env = _sync(client, dry_run=False)

        self.assertEqual(env.payload.created, 1)
        client.create_filter.assert_called_once_with(
            {"from": "other-club.ca"}, {"forward": "kids@example.com"}
        )

    @patch(_NORM)
    @patch(_LOAD)
    def test_same_criteria_different_action_still_created(self, mock_load, mock_norm):
        """Folding criteria must not merge rules whose actions differ."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [_spec("scoutstracker.ca", forward="new@example.com")]
        client = _make_client([UPPER_LIVE])

        env = _sync(client, dry_run=False)

        self.assertEqual(env.payload.created, 1)
        self.assertEqual(client.create_filter.call_count, 1)


class TestDeleteMissingKeepsUppercaseRules(unittest.TestCase):
    """--delete-missing compares desired keys against live canon keys."""

    @patch(_NORM)
    @patch(_LOAD)
    def test_uppercase_live_rule_in_yaml_is_not_deleted(self, mock_load, mock_norm):
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [LOWER_SPEC]
        stale = _live("stale", "GONE.EXAMPLE")
        client = _make_client([UPPER_LIVE, stale])

        env = _sync(client, dry_run=False, delete_missing=True)

        self.assertEqual(env.status, "success")
        deleted_ids = [c.args[0] for c in client.delete_filter.call_args_list]
        # Only the rule genuinely absent from the config goes.
        self.assertEqual(deleted_ids, ["stale"])
        self.assertEqual(env.payload.deleted, 1)
        self.assertEqual(env.payload.created, 0)
        self.assertEqual(client.create_filter.call_count, 0)

    @patch(_NORM)
    @patch(_LOAD)
    def test_dry_run_counts_only_the_stale_rule(self, mock_load, mock_norm):
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [LOWER_SPEC]
        client = _make_client([UPPER_LIVE, _live("stale", "GONE.EXAMPLE")])

        env = _sync(client, dry_run=True, delete_missing=True)

        self.assertEqual(env.payload.deleted, 1)
        self.assertEqual(env.payload.created, 0)
        self.assertEqual(client.delete_filter.call_count, 0)
        self.assertEqual(client.create_filter.call_count, 0)


class TestPlanSyncParityDefaultMode(unittest.TestCase):
    """plan and sync --dry-run report the same counts, with or without --reconcile."""

    LIVE = [
        UPPER_LIVE,
        _live("nin", "ACCOUNTS.NINTENDO.COM OR NINTENDO.NET"),
    ]
    DESIRED = [
        LOWER_SPEC,
        _spec("nintendo.net OR accounts.nintendo.com"),
        _spec("brand-new.example"),
    ]

    def _run(self, reconcile: bool):
        with patch(_LOAD, return_value={"filters": []}), \
                patch(_NORM, return_value=[dict(s) for s in self.DESIRED]):
            client = _make_client(self.LIVE)
            plan_env = _plan(client, reconcile=reconcile)
            sync_env = _sync(client, dry_run=True, reconcile=reconcile)
        return client, plan_env, sync_env

    def test_default_mode_agrees(self):
        client, plan_env, sync_env = self._run(reconcile=False)
        self.assertEqual(plan_env.payload.would_create, 1)
        self.assertEqual(sync_env.payload.created, 1)
        self.assertEqual(len(plan_env.payload.plan_items), 1)
        self.assertIn("brand-new.example", plan_env.payload.plan_items[0])
        self.assertEqual(client.create_filter.call_count, 0)

    def test_default_mode_matches_reconcile_mode(self):
        _, plan_off, sync_off = self._run(reconcile=False)
        _, plan_on, sync_on = self._run(reconcile=True)
        self.assertEqual(plan_off.payload.would_create, plan_on.payload.would_create)
        self.assertEqual(sync_off.payload.created, sync_on.payload.created)
        self.assertEqual(sync_on.payload.reconciled, 0)


class TestCollapsedLiveRules(unittest.TestCase):
    """Live rules sharing a canon key collapse to one entry in ``existing``.

    Folding case makes more rules collapse. Collapse must only ever HIDE a rule
    (under-deletion), never expose a protected one to deletion or rewrite.
    """

    UNMAPPABLE = _live("unmappable", "BANK.EXAMPLE", unmappedConditions=["bodyContains"])
    MAPPABLE = _live("mappable", "bank.example", unmappedConditions=[])

    def test_unmappable_rule_wins_a_collision_in_either_order(self):
        for rules in ([self.UNMAPPABLE, self.MAPPABLE], [self.MAPPABLE, self.UNMAPPABLE]):
            index = _index_live_rules([dict(r) for r in rules])
            self.assertEqual(len(index), 1)
            self.assertEqual(next(iter(index.values()))["id"], "unmappable")

    @patch(_NORM)
    @patch(_LOAD)
    def test_reconcile_never_rewrites_around_a_hidden_unmappable_rule(self, mock_load, mock_norm):
        """With the mappable sibling listed last, raw last-wins would hide the
        unmappable rule and reconcile would rewrite the sibling beside it."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [_spec("bank.example", forward="new@example.com")]
        for order in ([self.UNMAPPABLE, self.MAPPABLE], [self.MAPPABLE, self.UNMAPPABLE]):
            client = _make_client(order)
            env = _sync(client, dry_run=False, reconcile=True, delete_missing=True)
            self.assertEqual(env.status, "success")
            self.assertEqual(env.payload.reconciled, 0)
            self.assertEqual(env.payload.created, 0)
            self.assertEqual(client.delete_filter.call_count, 0)
            self.assertEqual(client.create_filter.call_count, 0)

    @patch(_NORM)
    @patch(_LOAD)
    def test_case_variant_duplicates_in_yaml_are_not_deleted(self, mock_load, mock_norm):
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [LOWER_SPEC]
        client = _make_client([UPPER_LIVE, _live("scouts-lower", "scoutstracker.ca")])

        env = _sync(client, dry_run=False, delete_missing=True)

        self.assertEqual(client.delete_filter.call_count, 0)
        self.assertEqual(client.create_filter.call_count, 0)
        self.assertEqual(env.payload.deleted, 0)


if __name__ == "__main__":
    unittest.main()
