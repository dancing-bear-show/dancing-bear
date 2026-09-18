"""Tests for criteria-based rule reconciliation in OutlookRulesSyncProcessor.

The reconcile feature (``--reconcile`` flag) lets sync match a live rule to a
desired rule by criteria alone, so an action change is treated as an in-place
update (delete + create) rather than two unrelated rules.

Each test class documents:
- The invariant being asserted.
- The regression it guards against.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from mail.outlook.processors_rules_write import OutlookRulesSyncProcessor
from mail.outlook.processors_rules_helpers import (
    _criteria_key,
    _norm_criteria_field,
)
from mail.outlook.consumers import OutlookRulesSyncPayload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(**kwargs) -> MagicMock:
    """Return a MagicMock client pre-configured with sensible defaults."""
    client = MagicMock()
    client.list_filters.return_value = kwargs.pop("list_filters", [])
    client.get_label_id_map.return_value = kwargs.pop("name_to_id", {})
    client.get_folder_path_map.return_value = kwargs.pop("folder_path_map", {})
    for k, v in kwargs.items():
        setattr(client, k, v)
    return client


def _sync_payload(
    client: MagicMock,
    *,
    dry_run: bool = False,
    delete_missing: bool = False,
    reconcile: bool = False,
) -> OutlookRulesSyncPayload:
    return OutlookRulesSyncPayload(
        client=client,
        config_path="/test.yaml",
        dry_run=dry_run,
        delete_missing=delete_missing,
        reconcile=reconcile,
    )


# ---------------------------------------------------------------------------
# _norm_criteria_field -- unit tests for the normalisation primitive
# ---------------------------------------------------------------------------

class TestNormCriteriaField(unittest.TestCase):
    """Unit tests for the OR-list normalisation helper."""

    def test_none_returns_none(self):
        """None input -> None output, preserving None-comparable key slots."""
        self.assertIsNone(_norm_criteria_field(None))

    def test_single_token_is_case_folded(self):
        """Single-value field is case-folded to a one-element tuple."""
        self.assertEqual(_norm_criteria_field("EXAMPLE.COM"), ("example.com",))

    def test_or_list_is_split_sorted_folded(self):
        """OR-joined list is split, stripped, case-folded, and sorted.

        Guards the primary case-insensitive matching requirement: live rules
        store criteria in UPPERCASE; desired rules use lowercase. Without this
        normalisation every live rule would look like a new rule and reconcile
        would create a duplicate instead of matching.
        """
        result = _norm_criteria_field("NINTENDO.NET OR ACCOUNTS.NINTENDO.COM")
        self.assertEqual(result, ("accounts.nintendo.com", "nintendo.net"))

    def test_or_list_with_extra_whitespace(self):
        """Extra whitespace around OR is tolerated via strip()."""
        result = _norm_criteria_field("A.COM  OR  B.COM")
        self.assertEqual(result, ("a.com", "b.com"))

    def test_order_insensitive(self):
        """Two fields listing the same senders in different order compare equal."""
        r1 = _norm_criteria_field("B.COM OR A.COM")
        r2 = _norm_criteria_field("A.COM OR B.COM")
        self.assertEqual(r1, r2)


# ---------------------------------------------------------------------------
# _criteria_key -- case-insensitive criteria matching
# ---------------------------------------------------------------------------

class TestCriteriaKey(unittest.TestCase):
    """_criteria_key must produce identical output for UPPERCASE live criteria
    and lowercase desired criteria.

    Regression guard: without case-insensitive normalisation the reconcile index
    would never match any live rule, effectively turning --reconcile into a
    no-op that still creates duplicate rules.
    """

    def test_uppercase_and_lowercase_produce_same_key(self):
        """NINTENDO.NET (live) and nintendo.net (desired) hash to the same key."""
        live_crit = {"from": "NINTENDO.NET OR ACCOUNTS.NINTENDO.COM"}
        desired_crit = {"from": "nintendo.net OR accounts.nintendo.com"}
        self.assertEqual(_criteria_key(live_crit), _criteria_key(desired_crit))

    def test_none_fields_match_none_fields(self):
        """Criteria with no 'to' or 'subject' fields compare equal across cases."""
        c1 = {"from": "SENDER@EXAMPLE.COM", "to": None, "subject": None}
        c2 = {"from": "sender@example.com"}
        self.assertEqual(_criteria_key(c1), _criteria_key(c2))

    def test_different_criteria_do_not_collide(self):
        """Different sender lists produce different keys."""
        c1 = {"from": "a@example.com"}
        c2 = {"from": "b@example.com"}
        self.assertNotEqual(_criteria_key(c1), _criteria_key(c2))


# ---------------------------------------------------------------------------
# Reconcile OFF -- existing behaviour unchanged
# ---------------------------------------------------------------------------

class TestReconcileOff(unittest.TestCase):
    """When reconcile=False (the default), an action change is seen as a new rule.

    Regression guard: the --reconcile flag must be opt-in.  A user running
    today's `rules.sync` must not get different deletion behaviour.  If this
    test starts failing it means reconciliation was made the default and the
    opt-in contract was broken.
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_action_change_creates_new_rule_without_reconcile(self, mock_norm, mock_load):
        """Without --reconcile, an action-changed rule is created as new; old one is not deleted."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "news@example.com"}, "action": {"forward": "x@other.com"}},
        ]
        live_rule = {
            "id": "live-rule-1",
            "criteria": {"from": "news@example.com"},
            "action": {"addLabelIds": ["label-99"]},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _sync_payload(client, reconcile=False, dry_run=False, delete_missing=False)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        # Without reconcile, the desired rule looks new -> created=1
        self.assertEqual(envelope.payload.created, 1)
        self.assertEqual(envelope.payload.reconciled, 0)
        # A fresh create_filter call is made for the desired rule
        client.create_filter.assert_called_once()
        # delete_filter was NOT called -- the stale live rule survives
        client.delete_filter.assert_not_called()

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_action_same_no_op_without_reconcile(self, mock_norm, mock_load):
        """Without --reconcile, a matching rule is a no-op (no create, no delete)."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "news@example.com"}, "action": {"forward": "x@other.com"}},
        ]
        live_rule = {
            "id": "live-rule-2",
            "criteria": {"from": "news@example.com"},
            "action": {"forward": "x@other.com"},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _sync_payload(client, reconcile=False, dry_run=False)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.created, 0)
        self.assertEqual(envelope.payload.reconciled, 0)
        client.create_filter.assert_not_called()
        client.delete_filter.assert_not_called()


# ---------------------------------------------------------------------------
# Reconcile ON -- action-change case
# ---------------------------------------------------------------------------

class TestReconcileActionChange(unittest.TestCase):
    """With --reconcile, a criteria match with a different action is updated.

    The live rule is deleted and recreated with the desired action.
    Exactly one rule remains for those criteria after the operation.

    This is the primary use case: the keepInInbox work changed moveToFolderId
    rules to addLabelIds rules, so every affected rule would otherwise be
    created as new and the stale one would survive (without --delete-missing).
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_action_change_reconciles_rule(self, mock_norm, mock_load):
        """criteria match + action change + reconcile=True -> reconciled=1, no orphan."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "news@example.com"}, "action": {"forward": "x@other.com"}},
        ]
        live_rule = {
            "id": "live-rule-1",
            "criteria": {"from": "news@example.com"},
            "action": {"addLabelIds": ["old-label-id"]},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _sync_payload(client, reconcile=True, dry_run=False)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        # created=0 because this was a reconcile, not a net-new rule
        self.assertEqual(envelope.payload.created, 0)
        self.assertEqual(envelope.payload.reconciled, 1)
        # delete_filter was called for the stale rule
        client.delete_filter.assert_called_once_with("live-rule-1")
        # create_filter was called once for the desired action
        client.create_filter.assert_called_once()

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_action_same_no_reconcile_needed(self, mock_norm, mock_load):
        """criteria match + action same + reconcile=True -> no-op (created=0, reconciled=0)."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "news@example.com"}, "action": {"forward": "x@other.com"}},
        ]
        live_rule = {
            "id": "live-rule-2",
            "criteria": {"from": "news@example.com"},
            "action": {"forward": "x@other.com"},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _sync_payload(client, reconcile=True, dry_run=False)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.created, 0)
        self.assertEqual(envelope.payload.reconciled, 0)
        client.create_filter.assert_not_called()
        client.delete_filter.assert_not_called()


# ---------------------------------------------------------------------------
# Case-insensitive criteria matching
# ---------------------------------------------------------------------------

class TestReconcileCaseInsensitive(unittest.TestCase):
    """Live criteria UPPERCASE must match desired criteria lowercase.

    Regression guard: live rules store criteria like 'NINTENDO.NET OR
    ACCOUNTS.NINTENDO.COM'; the derive step emits lowercase.  Without
    case-insensitive normalisation the reconcile index would never match and
    every affected rule would be treated as new, creating duplicates.
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_uppercase_live_matches_lowercase_desired(self, mock_norm, mock_load):
        """UPPERCASE live criteria and lowercase desired criteria reconcile correctly."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {
                "match": {"from": "nintendo.net OR accounts.nintendo.com"},
                "action": {"forward": "games@example.com"},
            },
        ]
        live_rule = {
            "id": "nintendo-rule",
            "criteria": {"from": "NINTENDO.NET OR ACCOUNTS.NINTENDO.COM"},
            "action": {"addLabelIds": ["old-label"]},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _sync_payload(client, reconcile=True, dry_run=False)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.reconciled, 1)
        self.assertEqual(envelope.payload.created, 0)
        # Stale rule deleted, desired rule created
        client.delete_filter.assert_called_once_with("nintendo-rule")
        client.create_filter.assert_called_once()


# ---------------------------------------------------------------------------
# Duplicate live criteria handling
# ---------------------------------------------------------------------------

class TestReconcileDuplicateLiveCriteria(unittest.TestCase):
    """When two live rules share criteria, only the first is reconciled.

    The second is left in 'existing' with its old canon key and is eligible
    for --delete-missing.  This is the correct behaviour: duplicate live rules
    were observed in real mailboxes, and reconciling only the first prevents
    the reconcile path from creating multiple rules for the same criteria.
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_first_duplicate_reconciled_second_ignored_by_reconcile(self, mock_norm, mock_load):
        """Two live rules sharing criteria: first is reconciled, second is not."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "dup@example.com"}, "action": {"forward": "new@example.com"}},
        ]
        live_rule_a = {
            "id": "dup-rule-a",
            "criteria": {"from": "dup@example.com"},
            "action": {"addLabelIds": ["old-label-1"]},
        }
        live_rule_b = {
            "id": "dup-rule-b",
            "criteria": {"from": "dup@example.com"},
            "action": {"addLabelIds": ["old-label-2"]},
        }
        client = _make_client(list_filters=[live_rule_a, live_rule_b])
        payload = _sync_payload(client, reconcile=True, dry_run=False)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        # Exactly one reconcile happened
        self.assertEqual(envelope.payload.reconciled, 1)
        self.assertEqual(envelope.payload.created, 0)
        # Only one delete_filter call was made (the reconciled rule)
        self.assertEqual(client.delete_filter.call_count, 1)
        # create_filter called once for the desired action
        client.create_filter.assert_called_once()

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_second_duplicate_deleted_by_delete_missing(self, mock_norm, mock_load):
        """Second duplicate survives reconcile but is deleted by --delete-missing.

        Regression guard: --delete-missing must not double-delete a rule that
        reconciliation already handled.
        """
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "dup@example.com"}, "action": {"forward": "new@example.com"}},
        ]
        live_rule_a = {
            "id": "dup-rule-a",
            "criteria": {"from": "dup@example.com"},
            "action": {"addLabelIds": ["old-label-1"]},
        }
        live_rule_b = {
            "id": "dup-rule-b",
            "criteria": {"from": "dup@example.com"},
            "action": {"addLabelIds": ["old-label-2"]},
        }
        client = _make_client(list_filters=[live_rule_a, live_rule_b])
        payload = _sync_payload(client, reconcile=True, dry_run=False, delete_missing=True)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.reconciled, 1)
        # The second duplicate is deleted by delete_missing
        self.assertEqual(envelope.payload.deleted, 1)
        # Total delete calls: 1 reconcile + 1 delete-missing = 2
        self.assertEqual(client.delete_filter.call_count, 2)


# ---------------------------------------------------------------------------
# --delete-missing combined with reconcile -- no double-delete
# ---------------------------------------------------------------------------

class TestReconcileWithDeleteMissing(unittest.TestCase):
    """Reconciliation and --delete-missing must not double-delete.

    Regression guard: a reconciled rule is already deleted from the mailbox by
    _create_rule_if_new. _delete_missing_rules must skip it so it is not passed
    to delete_filter a second time. Without the reconciled_rule_ids exclusion,
    the second call would 404 silently, but the deleted count would be wrong
    (over-counted) and the API would be called unnecessarily.
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_reconciled_rule_not_double_deleted(self, mock_norm, mock_load):
        """A reconciled rule is NOT passed to delete_filter by _delete_missing_rules."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "news@example.com"}, "action": {"forward": "x@other.com"}},
        ]
        live_rule = {
            "id": "live-rule-1",
            "criteria": {"from": "news@example.com"},
            "action": {"addLabelIds": ["old-label-id"]},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _sync_payload(client, reconcile=True, dry_run=False, delete_missing=True)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.reconciled, 1)
        self.assertEqual(envelope.payload.deleted, 0)
        # delete_filter called exactly once (from reconcile, not delete-missing)
        client.delete_filter.assert_called_once_with("live-rule-1")

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_stale_unreconciled_rule_deleted_by_delete_missing(self, mock_norm, mock_load):
        """A stale rule with no matching desired criteria IS deleted by --delete-missing."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "keep@example.com"}, "action": {"forward": "x@other.com"}},
        ]
        stale_rule = {
            "id": "stale-rule",
            "criteria": {"from": "gone@example.com"},
            "action": {"forward": "y@other.com"},
        }
        client = _make_client(list_filters=[stale_rule])
        payload = _sync_payload(client, reconcile=True, dry_run=False, delete_missing=True)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.deleted, 1)
        client.delete_filter.assert_called_once_with("stale-rule")

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_correct_final_count_mixed(self, mock_norm, mock_load):
        """Mixed scenario: one reconcile, one stale delete, one genuinely new rule."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            # Reconcile: same criteria as live, different action
            {"match": {"from": "change@example.com"}, "action": {"forward": "new@other.com"}},
            # New: no matching live rule
            {"match": {"from": "brand-new@example.com"}, "action": {"forward": "n@other.com"}},
        ]
        reconcile_live = {
            "id": "reconcile-rule",
            "criteria": {"from": "change@example.com"},
            "action": {"addLabelIds": ["old"]},
        }
        stale_live = {
            "id": "stale-rule",
            "criteria": {"from": "stale@example.com"},
            "action": {"forward": "old@other.com"},
        }
        client = _make_client(list_filters=[reconcile_live, stale_live])
        payload = _sync_payload(client, reconcile=True, dry_run=False, delete_missing=True)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.reconciled, 1)
        self.assertEqual(envelope.payload.created, 1)
        self.assertEqual(envelope.payload.deleted, 1)
        # delete_filter: 1 reconcile + 1 delete-missing = 2 total
        self.assertEqual(client.delete_filter.call_count, 2)
        # create_filter: 1 reconcile + 1 new = 2 total
        self.assertEqual(client.create_filter.call_count, 2)


# ---------------------------------------------------------------------------
# dry_run=True -- preview agrees with live run
# ---------------------------------------------------------------------------

class TestReconcileDryRun(unittest.TestCase):
    """dry_run=True must report the same counts as the live run without mutating.

    Regression guard: this PR fixed four preview/apply divergences. The dry-run
    path must never call create_filter or delete_filter.
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_dry_run_reports_reconcile_without_mutating(self, mock_norm, mock_load):
        """dry_run reconcile: reconciled=1, no mutating API calls."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "news@example.com"}, "action": {"forward": "x@other.com"}},
        ]
        live_rule = {
            "id": "live-rule-1",
            "criteria": {"from": "news@example.com"},
            "action": {"addLabelIds": ["old-label-id"]},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _sync_payload(client, reconcile=True, dry_run=True)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.reconciled, 1)
        self.assertEqual(envelope.payload.created, 0)
        # No mutations in dry-run
        client.create_filter.assert_not_called()
        client.delete_filter.assert_not_called()

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_dry_run_delete_missing_no_mutations(self, mock_norm, mock_load):
        """dry_run + delete_missing: counts stale rules without calling delete_filter."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "keep@example.com"}, "action": {"forward": "x@other.com"}},
        ]
        stale_rule = {
            "id": "stale-rule",
            "criteria": {"from": "stale@example.com"},
            "action": {"forward": "old@other.com"},
        }
        client = _make_client(list_filters=[stale_rule])
        payload = _sync_payload(client, reconcile=True, dry_run=True, delete_missing=True)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.deleted, 1)
        client.delete_filter.assert_not_called()
        client.create_filter.assert_not_called()


# ---------------------------------------------------------------------------
# Defect A: delete fails -> no create, failure visible
# ---------------------------------------------------------------------------

class TestReconcileDeleteFails(unittest.TestCase):
    """When delete_filter raises during reconcile, no create must follow.

    Regression guard: the original bare-except swallowed delete failures and
    proceeded to create anyway, leaving the mailbox with two rules for the same
    criteria.  Worse, the stale rule's id was added to reconciled_rule_ids and
    excluded from --delete-missing, protecting the duplicate from cleanup.

    Invariant: a failed delete -> failed count incremented, create not called,
    reconciled not incremented.
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_delete_fails_no_create_not_reconciled(self, mock_norm, mock_load):
        """delete_filter raises -> create_filter NOT called, reconciled=0, failed=1."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "news@example.com"}, "action": {"forward": "new@other.com"}},
        ]
        live_rule = {
            "id": "live-rule-1",
            "criteria": {"from": "news@example.com"},
            "action": {"addLabelIds": ["old-label-id"]},
        }
        client = _make_client(list_filters=[live_rule])
        client.delete_filter.side_effect = RuntimeError("Graph API 503")

        payload = _sync_payload(client, reconcile=True, dry_run=False)
        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        # Delete failed: must not be counted as reconciled
        self.assertEqual(envelope.payload.reconciled, 0)
        # Failed count must reflect the partial failure
        self.assertEqual(envelope.payload.failed, 1)
        # create_filter must NOT have been called (no duplicate)
        client.create_filter.assert_not_called()
        # delete_filter was attempted once
        client.delete_filter.assert_called_once_with("live-rule-1")


# ---------------------------------------------------------------------------
# Defect B: create fails after delete -> rule is lost, failure visible
# ---------------------------------------------------------------------------

class TestReconcileCreateFails(unittest.TestCase):
    """When create_filter raises after a successful delete, the rule is lost.

    This is the most severe failure path: the live rule is gone, the
    replacement was never created, yet the original code reported reconciled=1.
    Silent data loss reported as success.

    The fix does not retry or re-create -- the live rule is already gone and
    re-creating it from the stale live copy would resurrect an outdated action.
    Instead the failure is surfaced as failed=1 so the user knows to investigate
    and re-run after the transient Graph API error clears.

    Dry-run honest limit: dry_run cannot predict create failures because it makes
    no API calls.  It reports what the live run would attempt, not whether those
    attempts succeed.

    Invariant: a successful delete followed by a failed create -> reconciled=0,
    failed=1, and the create failure is not hidden.
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_create_fails_after_delete_not_reconciled_failed_visible(self, mock_norm, mock_load):
        """delete_filter succeeds, create_filter raises -> reconciled=0, failed=1."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "news@example.com"}, "action": {"forward": "new@other.com"}},
        ]
        live_rule = {
            "id": "live-rule-1",
            "criteria": {"from": "news@example.com"},
            "action": {"addLabelIds": ["old-label-id"]},
        }
        client = _make_client(list_filters=[live_rule])
        client.create_filter.side_effect = RuntimeError("Graph API 503")

        payload = _sync_payload(client, reconcile=True, dry_run=False)
        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.reconciled, 0)
        self.assertEqual(envelope.payload.failed, 1)
        # delete was attempted
        client.delete_filter.assert_called_once_with("live-rule-1")
        # create was attempted (and failed)
        client.create_filter.assert_called_once()


# ---------------------------------------------------------------------------
# Defect C: identical action differing only in case must not churn
# ---------------------------------------------------------------------------

class TestReconcileCaseChurn(unittest.TestCase):
    """A live rule whose action already matches must not be churned on every run.

    Regression guard: live rules store criteria in UPPERCASE (e.g. NINTENDO.NET),
    the derive step emits lowercase (nintendo.net).  Before this fix, the full
    rule key (_create_rule_key) preserved raw case, so a live rule differing only
    in criteria case did not match 'key in existing' and fell through to the
    reconcile path where it was deleted and recreated on EVERY run -- indefinite
    churn against the Graph API.

    The fix uses a case-normalised existing-keys set (via _norm_create_rule_key)
    so a rule whose criteria differ only in case is detected as already-correct
    and left alone.

    Invariant: same criteria (case-insensitive), same action -> created=0,
    reconciled=0, failed=0, no API calls.
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_case_only_difference_no_churn(self, mock_norm, mock_load):
        """Live UPPERCASE criteria + identical action -> no delete, no create, not reconciled."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {
                "match": {"from": "nintendo.net OR accounts.nintendo.com"},
                "action": {"forward": "games@example.com"},
            },
        ]
        # Live rule: same criteria in UPPERCASE, same action
        live_rule = {
            "id": "nintendo-rule",
            "criteria": {"from": "NINTENDO.NET OR ACCOUNTS.NINTENDO.COM"},
            "action": {"forward": "games@example.com"},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _sync_payload(client, reconcile=True, dry_run=False)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.reconciled, 0)
        self.assertEqual(envelope.payload.created, 0)
        self.assertEqual(envelope.payload.failed, 0)
        client.delete_filter.assert_not_called()
        client.create_filter.assert_not_called()

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_same_case_same_action_no_op(self, mock_norm, mock_load):
        """Exact match (same case, same action) is still a no-op -- contrast to case-only test."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {"match": {"from": "news@example.com"}, "action": {"forward": "x@other.com"}},
        ]
        live_rule = {
            "id": "live-2",
            "criteria": {"from": "news@example.com"},
            "action": {"forward": "x@other.com"},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _sync_payload(client, reconcile=True, dry_run=False)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.reconciled, 0)
        self.assertEqual(envelope.payload.created, 0)
        self.assertEqual(envelope.payload.failed, 0)
        client.delete_filter.assert_not_called()
        client.create_filter.assert_not_called()

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_genuine_action_change_still_reconciles(self, mock_norm, mock_load):
        """A real action change (not just case) is still reconciled correctly.

        Regression guard: the case-normalised no-op check must not suppress
        a genuine reconcile where the action is actually different.
        """
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {
                "match": {"from": "nintendo.net"},
                "action": {"forward": "new@example.com"},
            },
        ]
        live_rule = {
            "id": "nintendo-rule",
            "criteria": {"from": "NINTENDO.NET"},
            "action": {"forward": "old@example.com"},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _sync_payload(client, reconcile=True, dry_run=False)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.reconciled, 1)
        self.assertEqual(envelope.payload.created, 0)
        self.assertEqual(envelope.payload.failed, 0)
        client.delete_filter.assert_called_once_with("nintendo-rule")
        client.create_filter.assert_called_once()


# ---------------------------------------------------------------------------
# dry_run with failure-path semantics
# ---------------------------------------------------------------------------

class TestReconcileDryRunFailurePaths(unittest.TestCase):
    """dry_run must report what the live run would ATTEMPT, not predict API outcomes.

    Honest limit: dry_run makes no API calls, so it cannot predict whether a
    delete or create will succeed.  A dry_run reconcile reports reconciled=N
    (what would be attempted), not failed=N (which requires live API calls to
    know).  This is documented behaviour, not a parity claim.

    Invariant: dry_run with a case-only difference -> no mutations, not reconciled.
    Invariant: dry_run with a genuine action change -> no mutations, reconciled=1.
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_dry_run_case_only_no_reconcile(self, mock_norm, mock_load):
        """dry_run, case-only difference -> reconciled=0, no mutations."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {
                "match": {"from": "nintendo.net"},
                "action": {"forward": "games@example.com"},
            },
        ]
        live_rule = {
            "id": "nintendo-rule",
            "criteria": {"from": "NINTENDO.NET"},
            "action": {"forward": "games@example.com"},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _sync_payload(client, reconcile=True, dry_run=True)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.reconciled, 0)
        self.assertEqual(envelope.payload.created, 0)
        client.delete_filter.assert_not_called()
        client.create_filter.assert_not_called()

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_dry_run_genuine_action_change_reconcile_reported(self, mock_norm, mock_load):
        """dry_run, genuine action change -> reconciled=1, no mutations."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {
                "match": {"from": "nintendo.net"},
                "action": {"forward": "new@example.com"},
            },
        ]
        live_rule = {
            "id": "nintendo-rule",
            "criteria": {"from": "NINTENDO.NET"},
            "action": {"forward": "old@example.com"},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _sync_payload(client, reconcile=True, dry_run=True)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.reconciled, 1)
        self.assertEqual(envelope.payload.created, 0)
        client.delete_filter.assert_not_called()
        client.create_filter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
