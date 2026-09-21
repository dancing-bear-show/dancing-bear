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

from mail.outlook.processors_rules_write import OutlookRulesSyncProcessor, OutlookRulesPlanProcessor
from mail.outlook.processors_rules_helpers import (
    _criteria_key,
    _norm_criteria_field,
)
from mail.outlook.consumers import OutlookRulesSyncPayload, OutlookRulesPlanPayload


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

        # A reconcile failure must NOT report success: run_pipeline maps
        # status="success" to exit code 0, so a scripted run would see a clean
        # exit after a rule was lost. The payload is still attached so the tally
        # (the recovery information) survives.
        self.assertEqual(envelope.status, "error")
        self.assertIsNotNone(envelope.payload, "tally must survive the failure")
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

        # The rule is GONE (delete succeeded, create raised). Exiting 0 here is
        # what let a lost rule look like a clean run; status must be non-success
        # while the payload keeps the tally for recovery.
        self.assertEqual(envelope.status, "error")
        self.assertIsNotNone(envelope.payload, "tally must survive the failure")
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



# ============================================================
# NEW TESTS ADDED: plan preview + data-loss regression fixes
# ============================================================

def _plan_payload(client, *, reconcile=False):
    return OutlookRulesPlanPayload(
        client=client,
        config_path="/test.yaml",
        reconcile=reconcile,
    )


# ---------------------------------------------------------------------------
# DATA-LOSS REGRESSION: case-only no-op + --delete-missing must NOT delete
# ---------------------------------------------------------------------------

class TestCaseOnlyNoOpDeleteMissing(unittest.TestCase):
    """--reconcile --delete-missing must NOT delete a live rule that already has
    the correct action when only the criteria case differs.

    Regression guard: introduced in d0df0e7.  The case-normalised no-op path
    returned (key, False, False, False) without recording the live rule id.
    _delete_missing_rules then compared each live rule's _canon_rule key
    (UPPERCASE criteria verbatim) against desired_keys (lowercase desired key);
    they never matched, and the live rule was deleted.

    The rule was already correct. This was outright data loss: reconcile with
    delete-missing turned a benign case discrepancy into a missing rule.
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_case_only_no_op_not_deleted(self, mock_norm, mock_load):
        """reconcile=True, delete_missing=True, case-only diff -> nothing deleted, nothing created."""
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
            "action": {"forward": "games@example.com"},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _sync_payload(client, reconcile=True, delete_missing=True, dry_run=False)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.created, 0)
        self.assertEqual(envelope.payload.reconciled, 0)
        self.assertEqual(envelope.payload.deleted, 0)
        self.assertEqual(envelope.payload.failed, 0)
        client.delete_filter.assert_not_called()
        client.create_filter.assert_not_called()

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_case_only_no_op_delete_missing_false_unchanged(self, mock_norm, mock_load):
        """delete_missing=False: case-only no-op is still a no-op (baseline)."""
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
            "action": {"forward": "games@example.com"},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _sync_payload(client, reconcile=True, delete_missing=False, dry_run=False)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.created, 0)
        self.assertEqual(envelope.payload.reconciled, 0)
        self.assertEqual(envelope.payload.deleted, 0)
        client.delete_filter.assert_not_called()
        client.create_filter.assert_not_called()


# ---------------------------------------------------------------------------
# PLAN PREVIEW: --reconcile flag on rules.plan
# ---------------------------------------------------------------------------

class TestPlanReconcilePreview(unittest.TestCase):
    """rules.plan --reconcile must report 'Would reconcile' for rules that would
    be deleted and recreated, not 'Would create'.

    Regression guard: before this fix, rules.plan had no --reconcile flag.
    Running plan showed 'Would create' lines for rules with changed actions;
    running sync --reconcile deleted and recreated them.  The plan/apply
    discrepancy meant the documented plan->dry-run->apply discipline could not
    be followed safely.
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_plan_reconcile_shows_would_reconcile(self, mock_norm, mock_load):
        """Plan with --reconcile shows 'Would reconcile' not 'Would create' for action changes."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {
                "match": {"from": "news@example.com"},
                "action": {"forward": "new@other.com"},
            },
        ]
        live_rule = {
            "id": "rule-99",
            "criteria": {"from": "news@example.com"},
            "action": {"forward": "old@other.com"},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _plan_payload(client, reconcile=True)

        envelope = OutlookRulesPlanProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.would_create, 0)
        self.assertEqual(envelope.payload.would_reconcile, 1)
        self.assertEqual(len(envelope.payload.plan_items), 1)
        self.assertIn("Would reconcile", envelope.payload.plan_items[0])
        self.assertIn("rule-99", envelope.payload.plan_items[0])

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_plan_no_reconcile_shows_would_create(self, mock_norm, mock_load):
        """Plan WITHOUT --reconcile still shows 'Would create' for action changes (opt-in guard)."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {
                "match": {"from": "news@example.com"},
                "action": {"forward": "new@other.com"},
            },
        ]
        live_rule = {
            "id": "rule-99",
            "criteria": {"from": "news@example.com"},
            "action": {"forward": "old@other.com"},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _plan_payload(client, reconcile=False)

        envelope = OutlookRulesPlanProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.would_create, 1)
        self.assertEqual(envelope.payload.would_reconcile, 0)
        self.assertIn("Would create", envelope.payload.plan_items[0])
        self.assertNotIn("Would reconcile", envelope.payload.plan_items[0])

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_plan_case_only_no_op_not_reported(self, mock_norm, mock_load):
        """Plan --reconcile with case-only diff emits NO plan items (rule already correct)."""
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
            "action": {"forward": "games@example.com"},
        }
        client = _make_client(list_filters=[live_rule])
        payload = _plan_payload(client, reconcile=True)

        envelope = OutlookRulesPlanProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.would_create, 0)
        self.assertEqual(envelope.payload.would_reconcile, 0)
        self.assertEqual(envelope.payload.plan_items, [])


# ---------------------------------------------------------------------------
# PLAN/SYNC PARITY: plan --reconcile and sync --dry-run agree
# ---------------------------------------------------------------------------

class TestPlanSyncParity(unittest.TestCase):
    """rules.plan --reconcile and rules.sync --reconcile --dry-run must report
    the same set of actions on the same input.

    Regression guard: this PR has already fixed six plan/apply divergences.
    Any new divergence must be caught here before it reaches production.

    Invariant: plan items and sync dry_run created/reconciled counts agree.
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_plan_and_sync_dry_run_agree_on_reconcile(self, mock_norm, mock_load):
        """For an action-change case, plan --reconcile and sync --dry-run reconcile=1 both."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {
                "match": {"from": "news@example.com"},
                "action": {"forward": "new@other.com"},
            },
        ]
        live_rule = {
            "id": "rule-1",
            "criteria": {"from": "news@example.com"},
            "action": {"forward": "old@other.com"},
        }
        client = _make_client(list_filters=[live_rule])

        plan_payload = _plan_payload(client, reconcile=True)
        plan_env = OutlookRulesPlanProcessor().process(plan_payload)

        sync_payload = _sync_payload(client, reconcile=True, dry_run=True)
        sync_env = OutlookRulesSyncProcessor().process(sync_payload)

        # Both agree: no creates, exactly one reconcile
        self.assertEqual(plan_env.payload.would_create, 0)
        self.assertEqual(plan_env.payload.would_reconcile, 1)
        self.assertEqual(sync_env.payload.created, 0)
        self.assertEqual(sync_env.payload.reconciled, 1)

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_plan_and_sync_dry_run_agree_on_create(self, mock_norm, mock_load):
        """For a genuinely new rule, plan and sync dry_run agree on create=1, reconcile=0."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {
                "match": {"from": "brand-new@example.com"},
                "action": {"forward": "x@other.com"},
            },
        ]
        client = _make_client(list_filters=[])  # no live rules

        plan_payload = _plan_payload(client, reconcile=True)
        plan_env = OutlookRulesPlanProcessor().process(plan_payload)

        sync_payload = _sync_payload(client, reconcile=True, dry_run=True)
        sync_env = OutlookRulesSyncProcessor().process(sync_payload)

        self.assertEqual(plan_env.payload.would_create, 1)
        self.assertEqual(plan_env.payload.would_reconcile, 0)
        self.assertEqual(sync_env.payload.created, 1)
        self.assertEqual(sync_env.payload.reconciled, 0)

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_plan_and_sync_dry_run_agree_on_case_only_noop(self, mock_norm, mock_load):
        """A rule differing only in criteria CASE is a no-op in both plan and sync.

        The third parity row, and the one tied to the data-loss regression: a live
        rule that already satisfies the desired spec, where only the criteria
        casing differs.  Both surfaces must report nothing to do -- if plan and
        sync disagree here, one of them is about to churn or destroy a rule that
        is already correct.
        """
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {
                "match": {"from": "nintendo.net OR accounts.nintendo.com"},
                "action": {"forward": "games@other.com"},
            },
        ]
        live_rule = {
            "id": "rule-correct",
            "criteria": {"from": "NINTENDO.NET OR ACCOUNTS.NINTENDO.COM"},
            "action": {"forward": "games@other.com"},
        }
        client = _make_client(list_filters=[live_rule])

        plan_env = OutlookRulesPlanProcessor().process(_plan_payload(client, reconcile=True))
        sync_env = OutlookRulesSyncProcessor().process(
            _sync_payload(client, reconcile=True, dry_run=True)
        )

        # Nothing to do on either surface.
        self.assertEqual(plan_env.payload.would_create, 0)
        self.assertEqual(plan_env.payload.would_reconcile, 0)
        self.assertEqual(plan_env.payload.plan_items, [])
        self.assertEqual(sync_env.payload.created, 0)
        self.assertEqual(sync_env.payload.reconciled, 0)
        self.assertEqual(sync_env.payload.failed, 0)
        # Both surfaces are read-only on this input.
        self.assertEqual(client.delete_filter.call_count, 0)
        self.assertEqual(client.create_filter.call_count, 0)


# ---------------------------------------------------------------------------
# SEQUENCE PRESERVATION
# ---------------------------------------------------------------------------

class TestDryRunNeverCreatesFolders(unittest.TestCase):
    """``rules.sync --dry-run`` must not mutate the mailbox -- including folders.

    Folder resolution is the trap: ``_build_rule_action``'s fallback is
    ``ensure_folder_path``, which CREATES missing folders via Graph, and it runs
    before the per-spec ``dry_run`` check. So a preview whose cached folder map
    missed an ``add`` destination created a folder -- no rule was created, but the
    mailbox changed. Raised in review on PR #359 and probed:

        dry run -> ensure_folder_path called with ('Lists/News',)

    Pre-existing rather than introduced by the reconcile work, and the same
    preview-mutates class this PR has fixed repeatedly (see the sweep path, where
    ``_resolve_destination_folder`` already made the map-only choice).

    ``RuleContext.dry_run`` now carries the flag to the resolver, which falls back
    to the cached map and then to the path itself. The returned value is not a
    Graph id, which is correct for a preview: it only has to be stable and truthy
    so the rule key matches what a live run would build, and nothing in the
    dry-run path sends it to Graph. The parity test below pins that.
    """

    DESIRED = [{"match": {"from": "news.example"}, "action": {"add": ["Lists/News"]}}]
    REAL_ID = "folder-real-id"

    def _client(self, folder_map):
        client = _make_client(
            list_filters=[],
            name_to_id={"Lists/News": "cat-news"},
            folder_path_map=dict(folder_map),
        )
        client.ensure_folder_path.return_value = self.REAL_ID
        return client

    def _run(self, dry_run, folder_map):
        client = self._client(folder_map)
        payload = OutlookRulesSyncPayload(
            client=client, config_path="/test.yaml", dry_run=dry_run,
            move_to_folders=True, delete_missing=False, reconcile=True,
        )
        with patch("core.yamlio.load_config", return_value={"filters": []}), \
                patch("mail.dsl.normalize_filters_for_outlook", return_value=list(self.DESIRED)):
            envelope = OutlookRulesSyncProcessor().process(payload)
        return envelope, client

    def test_dry_run_does_not_call_ensure_folder_path(self):
        """Cache miss under dry-run resolves map-only; no folder is created."""
        envelope, client = self._run(dry_run=True, folder_map={})

        self.assertEqual(
            client.ensure_folder_path.call_count, 0,
            "a dry run called ensure_folder_path, which creates folders via Graph",
        )
        self.assertEqual(client.create_filter.call_count, 0)
        self.assertEqual(client.delete_filter.call_count, 0)
        # The preview is still useful -- it reports the rule it would create.
        self.assertEqual(envelope.payload.created, 1)

    def test_live_run_still_resolves_the_folder(self):
        """Contrast: the live path still creates/resolves the folder as before.

        Without this, the guard could regress into never resolving folders at all,
        which would silently stop moving mail.
        """
        _, client = self._run(dry_run=False, folder_map={})

        self.assertEqual(client.ensure_folder_path.call_count, 1)
        self.assertEqual(client.ensure_folder_path.call_args.args, ("Lists/News",))

    def test_dry_run_and_live_agree_on_counts(self):
        """The guard must not introduce a preview/apply divergence.

        Dry-run now keys on the cached id (or the path on a miss) while live keys
        on the Graph id. If those disagreed, `sync --dry-run` could promise a
        create the live run treats as a no-op.
        """
        for label, fmap in (("cached", {"Lists/News": self.REAL_ID}), ("miss", {})):
            with self.subTest(folder_map=label):
                dry, _ = self._run(dry_run=True, folder_map=fmap)
                live, _ = self._run(dry_run=False, folder_map=fmap)
                self.assertEqual(dry.payload.created, live.payload.created)
                self.assertEqual(dry.payload.reconciled, live.payload.reconciled)


class _GraphOutage(Exception):
    """A non-auth Graph failure (e.g. 503), which triggers the cache fallback."""
    response = type("_Resp", (), {"status_code": 503})()


class TestDestructiveModesRefuseFallbackData(unittest.TestCase):
    """``--reconcile`` / ``--delete-missing`` must not act on rules we never read.

    ``_fetch_rules_with_provenance`` falls back to a cached snapshot when the live
    read fails, and to ``[]`` when even that fails -- and ``[]`` means "unknown",
    not "the mailbox has no rules". Both destructive flags decide what to DELETE
    by comparing desired rules against that list, so fallback data is actively
    dangerous. Raised in review on PR #359 and probed before fixing:

        total failure -> created=2, status=success, zero rules ever read
                         (a duplicate of every rule, beside live rules it cannot see)
        stale cache   -> delete_filter('OLD-ID-no-longer-exists')

    The block is deliberately narrow; the contrast tests below pin that.
    """

    DESIRED = [{"match": {"from": "a.example"}, "action": {"forward": "a@x.com"}}]

    @staticmethod
    def _client(mode):
        client = MagicMock()
        if mode == "empty":
            client.list_filters.side_effect = _GraphOutage()
        elif mode == "fallback":
            def lf(use_cache=False, ttl=600):
                if not use_cache:
                    raise _GraphOutage()
                return [{"id": "OLD-ID", "criteria": {"from": "a.example"},
                         "action": {"forward": "stale@x.com"}}]
            client.list_filters.side_effect = lf
        else:
            client.list_filters.return_value = [
                {"id": "live-1", "criteria": {"from": "a.example"},
                 "action": {"forward": "old@x.com"}}
            ]
        client.get_label_id_map.return_value = {}
        client.get_folder_path_map.return_value = {}
        return client

    def _run(self, mode, **flags):
        client = self._client(mode)
        with patch("core.yamlio.load_config", return_value={"filters": []}), \
                patch("mail.dsl.normalize_filters_for_outlook", return_value=list(self.DESIRED)):
            envelope = OutlookRulesSyncProcessor().process(_sync_payload(client, **flags))
        return envelope, client

    def test_reconcile_refused_when_rules_unreadable(self):
        """Total fetch failure: reconcile refuses rather than duplicating everything."""
        envelope, client = self._run("empty", reconcile=True, dry_run=False)

        self.assertEqual(envelope.status, "error")
        self.assertEqual(client.create_filter.call_count, 0)
        self.assertEqual(client.delete_filter.call_count, 0)
        self.assertIn("--reconcile", (envelope.diagnostics or {}).get("error", ""))

    def test_reconcile_refused_on_cached_snapshot(self):
        """Stale cache: reconcile refuses rather than deleting against stale IDs."""
        envelope, client = self._run("fallback", reconcile=True, dry_run=False)

        self.assertEqual(envelope.status, "error")
        self.assertEqual(client.delete_filter.call_count, 0)

    def test_delete_missing_refused_on_cached_snapshot(self):
        """--delete-missing is destructive on its own and is refused too."""
        envelope, client = self._run("fallback", delete_missing=True, dry_run=False)

        self.assertEqual(envelope.status, "error")
        self.assertEqual(client.delete_filter.call_count, 0)
        self.assertIn("--delete-missing", (envelope.diagnostics or {}).get("error", ""))

    def test_plain_sync_still_runs_on_fallback_data(self):
        """Contrast: plain sync is NOT blocked.

        It only creates missing rules, so stale data costs a duplicate rather than
        a deletion. Blocking it would make a transient Graph error break the common
        path -- a cure worse than the disease.
        """
        envelope, client = self._run("fallback", dry_run=False)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(client.create_filter.call_count, 1)

    def test_live_read_is_not_blocked(self):
        """Contrast: a successful live read reconciles normally.

        Without this, the guard could regress into refusing every reconcile.
        """
        envelope, _ = self._run("live", reconcile=True, delete_missing=True, dry_run=False)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.reconciled, 1)

    def test_auth_failure_still_propagates_as_auth_error(self):
        """A 401/403 is not fallback territory -- it keeps its own diagnostic."""
        client = MagicMock()
        resp = type("_R", (), {"status_code": 401})()
        exc = Exception("unauthorized")
        exc.response = resp
        client.list_filters.side_effect = exc
        client.get_label_id_map.return_value = {}
        client.get_folder_path_map.return_value = {}

        with patch("core.yamlio.load_config", return_value={"filters": []}), \
                patch("mail.dsl.normalize_filters_for_outlook", return_value=list(self.DESIRED)):
            envelope = OutlookRulesSyncProcessor().process(
                _sync_payload(client, reconcile=True, dry_run=False)
            )

        self.assertEqual(envelope.status, "error")
        self.assertIn("Auth failed", (envelope.diagnostics or {}).get("error", ""))

    def test_provenance_helper_reports_each_source(self):
        """Unit-level: the three provenance values every caller branches on."""
        from mail.outlook.processors_rules_helpers import _fetch_rules_with_provenance

        live = MagicMock()
        live.list_filters.return_value = [{"id": "x"}]
        self.assertEqual(_fetch_rules_with_provenance(live)[1], "live")

        empty = MagicMock()
        empty.list_filters.side_effect = _GraphOutage()
        rules, source = _fetch_rules_with_provenance(empty)
        self.assertEqual((rules, source), ([], "empty"))

        fb = MagicMock()

        def lf(use_cache=False, ttl=600):
            if not use_cache:
                raise _GraphOutage()
            return [{"id": "cached"}]

        fb.list_filters.side_effect = lf
        self.assertEqual(_fetch_rules_with_provenance(fb)[1], "fallback")


class TestReconcileFailureExitCode(unittest.TestCase):
    """A reconcile failure must not exit 0.

    ``run_pipeline`` (core/pipeline.py) computes the process exit code as
    ``0 if envelope.ok() else diagnostics["code"]``.  The sync processor used to
    return ``status="success"`` regardless of ``failed``, so a ``create_failed``
    -- a rule deleted with its replacement never created -- exited 0, identical
    to a clean run.  A cron job or workflow step saw success while a filter had
    silently disappeared; the only signal was a ``Failed: N`` line in
    human-readable text that nothing parses.

    Raised in review on PR #359.  These tests assert the EXIT CODE expression
    itself, not just the status field, because the status is one step removed
    from the thing that actually matters to a caller.
    """

    LIVE = [{
        "id": "bank-rule",
        "criteria": {"from": "bank.example"},
        "action": {"forward": "old@other.com"},
    }]
    DESIRED = [{
        "match": {"from": "bank.example"},
        "action": {"forward": "new@other.com"},
    }]

    @staticmethod
    def _exit_code(envelope):
        """Mirror run_pipeline's exit-code expression (core/pipeline.py)."""
        if envelope.ok():
            return 0
        return int((envelope.diagnostics or {}).get("code", 2))

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_create_failed_exits_nonzero(self, mock_norm, mock_load):
        """A lost rule exits nonzero, and the tally survives for recovery."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = list(self.DESIRED)
        client = _make_client(list_filters=[dict(r) for r in self.LIVE])
        client.create_filter.side_effect = Exception("graph 500")

        envelope = OutlookRulesSyncProcessor().process(
            _sync_payload(client, reconcile=True, dry_run=False)
        )

        self.assertNotEqual(
            self._exit_code(envelope), 0,
            "a reconcile that lost a rule exited 0, indistinguishable from success",
        )
        self.assertEqual(envelope.payload.failed, 1)
        # The counts ARE the recovery information; a bare error would discard them.
        self.assertIsNotNone(envelope.payload)
        diag = envelope.diagnostics or {}
        self.assertTrue(diag.get("hint"), "a failure the user must act on needs a hint")

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_successful_reconcile_exits_zero(self, mock_norm, mock_load):
        """Contrast: a clean reconcile still exits 0.

        Without this, making failures exit nonzero could regress into making
        every reconcile exit nonzero, which no caller would tolerate.
        """
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = list(self.DESIRED)
        client = _make_client(list_filters=[dict(r) for r in self.LIVE])

        envelope = OutlookRulesSyncProcessor().process(
            _sync_payload(client, reconcile=True, dry_run=False)
        )

        self.assertEqual(self._exit_code(envelope), 0)
        self.assertEqual(envelope.payload.reconciled, 1)
        self.assertEqual(envelope.payload.failed, 0)

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_fresh_create_failure_counts_as_failed_under_reconcile(self, mock_norm, mock_load):
        """A NEW rule whose create raises is `failed`, not `created`, under reconcile.

        Raised in review: the reconcile delete+create path reported its failures,
        but the fresh-create fallthrough still swallowed the exception and returned
        ``was_created=True``. So a brand-new rule whose create failed printed
        ``Created: 1`` and exited 0 while the rule did not exist -- the same silent
        loss, one branch over.

        A user who opted into a mode that tracks failures should see this one too.
        """
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [{
            "match": {"from": "brand-new@example.com"},
            "action": {"forward": "x@other.com"},
        }]
        client = _make_client(list_filters=[])  # no live rules: fresh-create path
        client.create_filter.side_effect = Exception("graph 500")

        envelope = OutlookRulesSyncProcessor().process(
            _sync_payload(client, reconcile=True, dry_run=False)
        )

        self.assertEqual(envelope.payload.failed, 1)
        self.assertEqual(
            envelope.payload.created, 0,
            "a rule that was never created was counted as created",
        )
        self.assertNotEqual(self._exit_code(envelope), 0)

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_non_reconcile_create_failure_still_exits_zero(self, mock_norm, mock_load):
        """The non-reconcile path is unchanged: a swallowed create still exits 0.

        Deliberate scope limit. On the default path a create failure has always
        been swallowed and counted as created, and changing that is a separate
        behavioural decision from fixing reconcile's lost-rule case.
        """
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [{
            "match": {"from": "brand-new@example.com"},
            "action": {"forward": "x@other.com"},
        }]
        client = _make_client(list_filters=[])
        client.create_filter.side_effect = Exception("graph 500")

        envelope = OutlookRulesSyncProcessor().process(
            _sync_payload(client, reconcile=False, dry_run=False)
        )

        self.assertEqual(self._exit_code(envelope), 0)
        self.assertEqual(envelope.payload.failed, 0)


class TestUnmappableConditionsAreNotRewritten(unittest.TestCase):
    """A live rule with Graph conditions this codebase cannot express is untouched.

    Graph supports conditions (``bodyContains``, ``hasAttachments``,
    ``importance``, ``sentToMe``, ...) that ``_build_rule_conditions`` never
    writes and ``_map_rule`` never parses.  ``_criteria_key`` keys on
    from/to/subject only, so a UI-created rule scoped by sender AND body looks
    identical to a sender-only rule.

    Reconcile recreates by delete+create from the mapped criteria, so rewriting
    such a rule DROPS the extra condition and the replacement matches *more* mail
    than the original -- "from bank.example AND body contains 'wire transfer'"
    becomes every message from that sender.  Broadening a filter unasked is the
    dangerous direction, so these rules are left exactly as they are.

    Three distinct protections are required and each was verified by probe:
      1. not reconciled (no delete+create),
      2. no second rule created beside it (which would be worse -- two rules on
         the same mail when the user asked for one),
      3. not deleted by ``--delete-missing``.

    (3) is the subtle one: skipping the desired spec contributes no key to
    ``desired_keys``, and ``_delete_missing_rules`` deletes exactly those live
    rules whose canon key is absent from that set -- so skipping ALONE marked the
    rule stale and deleted it. A first cut of this fix returned None and probed
    as ``deleted=1``: one data-loss path traded for another.
    """

    LIVE_RULE = {
        "id": "ui-rule",
        "criteria": {"from": "bank.example"},
        "action": {"forward": "old@other.com"},
        "sequence": 3,
        "stopProcessingRules": False,
        "unmappedConditions": ["bodyContains"],
    }
    DESIRED = [{
        "match": {"from": "bank.example"},
        "action": {"forward": "new@other.com"},
    }]

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_not_reconciled_and_no_duplicate_created(self, mock_norm, mock_load):
        """Reconcile neither rewrites the rule nor creates a second one."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = list(self.DESIRED)
        client = _make_client(list_filters=[dict(self.LIVE_RULE)])

        envelope = OutlookRulesSyncProcessor().process(
            _sync_payload(client, reconcile=True, dry_run=False)
        )

        self.assertEqual(envelope.payload.reconciled, 0)
        self.assertEqual(envelope.payload.created, 0)
        self.assertEqual(envelope.payload.failed, 0)
        self.assertEqual(
            client.delete_filter.call_count, 0,
            "reconcile deleted a rule whose extra condition it cannot recreate",
        )
        self.assertEqual(
            client.create_filter.call_count, 0,
            "a second, broader rule was created beside the protected one",
        )

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_delete_missing_does_not_delete_it(self, mock_norm, mock_load):
        """--delete-missing must not treat the protected rule as stale."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = list(self.DESIRED)
        client = _make_client(list_filters=[dict(self.LIVE_RULE)])

        envelope = OutlookRulesSyncProcessor().process(
            _sync_payload(client, reconcile=True, delete_missing=True, dry_run=False)
        )

        self.assertEqual(envelope.payload.deleted, 0)
        self.assertEqual(
            client.delete_filter.call_count, 0,
            "--delete-missing deleted a rule the reconcile pass deliberately skipped",
        )

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_plan_agrees_with_sync_and_promises_nothing(self, mock_norm, mock_load):
        """plan --reconcile reports no action, matching sync --reconcile --dry-run."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = list(self.DESIRED)

        plan_client = _make_client(list_filters=[dict(self.LIVE_RULE)])
        plan_env = OutlookRulesPlanProcessor().process(
            _plan_payload(plan_client, reconcile=True)
        )
        sync_client = _make_client(list_filters=[dict(self.LIVE_RULE)])
        sync_env = OutlookRulesSyncProcessor().process(
            _sync_payload(sync_client, reconcile=True, dry_run=True)
        )

        self.assertEqual(plan_env.payload.plan_items, [])
        self.assertEqual(plan_env.payload.would_create, sync_env.payload.created)
        self.assertEqual(plan_env.payload.would_reconcile, sync_env.payload.reconciled)

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_non_reconcile_path_unchanged(self, mock_norm, mock_load):
        """Without --reconcile the skip does not apply; default behaviour stands.

        Contrast case: the protection is reconcile-only. On the default path an
        action change has always been treated as a brand-new rule, and that must
        not change -- otherwise this fix would quietly disable rule creation for
        anyone whose mailbox has a UI-created rule.
        """
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = list(self.DESIRED)
        client = _make_client(list_filters=[dict(self.LIVE_RULE)])

        envelope = OutlookRulesSyncProcessor().process(
            _sync_payload(client, reconcile=False, dry_run=False)
        )

        self.assertEqual(envelope.payload.created, 1)
        self.assertEqual(client.create_filter.call_count, 1)

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_protected_even_when_a_mappable_sibling_matches_first(self, mock_norm, mock_load):
        """An unmappable rule is protected because it EXISTS, not because a spec hit it.

        Regression on a hole in the first cut of this protection. Protection was
        recorded per desired spec inside ``_create_rule_if_new``, so an earlier
        branch returning first skipped it entirely. With an unmappable rule AND a
        mappable sibling sharing criteria, the sibling's exact key is already in
        ``existing``, so the function returned at the ``key in existing`` branch,
        the unmappable id never entered the protected set, and ``--delete-missing``
        deleted the very rule the skip exists to preserve.

        Probed before the fix: ``deleted ids: ['unmappable']``.

        Reconcile can never faithfully recreate these rules, so deleting one is
        unconditional data loss -- the protected set is therefore seeded from the
        index up front rather than per spec.
        """
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [{
            "match": {"from": "bank.example"},
            "action": {"forward": "new@other.com"},
        }]
        live = [
            {
                "id": "unmappable",
                "criteria": {"from": "bank.example"},
                "action": {"forward": "old@other.com"},
                "unmappedConditions": ["bodyContains"],
            },
            {
                # Same criteria, and ALREADY the desired action, so this one
                # matches on the exact-key branch before any unmappable check.
                "id": "mappable-sibling",
                "criteria": {"from": "bank.example"},
                "action": {"forward": "new@other.com"},
                "unmappedConditions": [],
            },
        ]
        client = _make_client(list_filters=[dict(r) for r in live])

        envelope = OutlookRulesSyncProcessor().process(
            _sync_payload(client, reconcile=True, delete_missing=True, dry_run=False)
        )

        deleted_ids = [c.args[0] for c in client.delete_filter.call_args_list]
        self.assertNotIn(
            "unmappable", deleted_ids,
            "the unmappable rule was deleted despite the reconcile skip",
        )
        self.assertEqual(envelope.payload.deleted, 0)
        # The sibling already implements the desired action: nothing to do at all.
        self.assertEqual(deleted_ids, [])
        self.assertEqual(client.create_filter.call_count, 0)

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_all_unmappable_duplicates_are_protected(self, mock_norm, mock_load):
        """Two unmappable rules sharing a criteria key are BOTH protected.

        The index keeps every id per key, not just the first: protection is per
        rule, since each is individually impossible to recreate faithfully.
        """
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [{
            "match": {"from": "bank.example"},
            "action": {"forward": "new@other.com"},
        }]
        live = [
            {"id": "unmappable-a", "criteria": {"from": "bank.example"},
             "action": {"forward": "a@other.com"},
             "unmappedConditions": ["bodyContains"]},
            {"id": "unmappable-b", "criteria": {"from": "bank.example"},
             "action": {"forward": "b@other.com"},
             "unmappedConditions": ["hasAttachments"]},
        ]
        client = _make_client(list_filters=[dict(r) for r in live])

        envelope = OutlookRulesSyncProcessor().process(
            _sync_payload(client, reconcile=True, delete_missing=True, dry_run=False)
        )

        self.assertEqual(
            [c.args[0] for c in client.delete_filter.call_args_list], [],
            "an unmappable duplicate was deleted; only the first was protected",
        )
        self.assertEqual(envelope.payload.deleted, 0)

    def test_map_rule_reports_unmapped_conditions(self):
        """_map_rule records the Graph condition keys it could not represent.

        Unit-level guard on the marker the protections depend on: if _map_rule
        stops reporting it, every protection above silently becomes a no-op while
        still passing its own assertions.
        """
        from core.outlook._mail_labels import LabelsFiltersMixin

        raw = {
            "id": "ui-rule",
            "conditions": {
                "senderContains": ["bank.example"],
                "bodyContains": ["wire transfer"],
                "hasAttachments": True,
            },
            "actions": {"forwardTo": [{"emailAddress": {"address": "x@y.com"}}]},
        }
        mapped = LabelsFiltersMixin._map_rule(MagicMock(), raw)

        self.assertEqual(mapped["unmappedConditions"], ["bodyContains", "hasAttachments"])
        # The mappable part still round-trips.
        self.assertEqual(mapped["criteria"], {"from": "bank.example"})

    def test_map_rule_reports_unmapped_actions_too(self):
        """Unsupported ACTION keys are reported alongside unsupported conditions.

        Raised in review: the first cut tracked only conditions, but
        ``_build_rule_actions`` writes back just categories/forward/move, so a
        rule with ``markAsRead``, ``delete`` or ``copyToFolder`` reported
        ``unmappedConditions=[]`` and was reconciled freely -- coming back without
        that action. Sharper than the conditions case: a rule that categorises AND
        deletes would be recreated as categorise-only.
        """
        from core.outlook._mail_labels import LabelsFiltersMixin

        raw = {
            "id": "ui-rule",
            "conditions": {"senderContains": ["spam.example"]},
            "actions": {"assignCategories": ["Junk"], "markAsRead": True, "delete": True},
        }
        mapped = LabelsFiltersMixin._map_rule(MagicMock(), raw)

        self.assertEqual(mapped["unmappedConditions"], ["delete", "markAsRead"])
        # The mappable part is still parsed.
        self.assertEqual(mapped["action"], {"addLabelIds": ["Junk"]})

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_rule_with_unmapped_action_is_not_reconciled(self, mock_norm, mock_load):
        """A rule whose action includes `delete` is left entirely alone."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [{
            "match": {"from": "spam.example"},
            "action": {"add": ["Junk", "Extra"]},
        }]
        live_rule = {
            "id": "del-rule",
            "criteria": {"from": "spam.example"},
            "action": {"addLabelIds": ["cat-junk"]},
            "unmappedConditions": ["delete", "markAsRead"],
        }
        client = _make_client(
            list_filters=[live_rule], name_to_id={"Junk": "cat-junk", "Extra": "cat-extra"}
        )

        envelope = OutlookRulesSyncProcessor().process(
            _sync_payload(client, reconcile=True, delete_missing=True, dry_run=False)
        )

        self.assertEqual(envelope.payload.reconciled, 0)
        self.assertEqual(envelope.payload.deleted, 0)
        self.assertEqual(
            client.delete_filter.call_count, 0,
            "a rule that deletes mail was rewritten without its delete action",
        )
        self.assertEqual(client.create_filter.call_count, 0)

    def test_map_rule_reports_exceptions_as_unmappable(self):
        """Graph ``exceptions`` are reported -- the third unmappable surface.

        Raised in review after the conditions and actions fixes. This format has no
        representation for exceptions AT ALL, so every key contributes rather than
        a set difference: a rule reading "categorise newsletters, except ones titled
        URGENT" lost the exception entirely and came back acting on URGENT mail too.

        Keys are prefixed ``exceptions.`` so a diagnostic cannot confuse
        ``exceptions.subjectContains`` with the condition of the same name.
        """
        from core.outlook._mail_labels import LabelsFiltersMixin

        raw = {
            "id": "exc-rule",
            "conditions": {"senderContains": ["newsletter.example"]},
            "exceptions": {"subjectContains": ["URGENT"]},
            "actions": {"assignCategories": ["News"]},
        }
        mapped = LabelsFiltersMixin._map_rule(MagicMock(), raw)

        self.assertEqual(mapped["unmappedConditions"], ["exceptions.subjectContains"])

    def test_map_rule_ignores_an_empty_exceptions_object(self):
        """An empty ``exceptions`` dict must not false-positive.

        Graph may return the key with no content; treating that as unmappable
        would freeze reconciliation for ordinary rules.
        """
        from core.outlook._mail_labels import LabelsFiltersMixin

        raw = {
            "id": "plain",
            "conditions": {"senderContains": ["a.example"]},
            "exceptions": {},
            "actions": {"assignCategories": ["Cat"]},
        }
        mapped = LabelsFiltersMixin._map_rule(MagicMock(), raw)

        self.assertEqual(mapped["unmappedConditions"], [])

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_rule_with_exceptions_is_not_reconciled(self, mock_norm, mock_load):
        """A rule carrying an exception is left entirely alone."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [{
            "match": {"from": "newsletter.example"},
            "action": {"add": ["News", "Extra"]},
        }]
        live_rule = {
            "id": "exc-rule",
            "criteria": {"from": "newsletter.example"},
            "action": {"addLabelIds": ["cat-news"]},
            "unmappedConditions": ["exceptions.subjectContains"],
        }
        client = _make_client(
            list_filters=[live_rule],
            name_to_id={"News": "cat-news", "Extra": "cat-extra"},
        )

        envelope = OutlookRulesSyncProcessor().process(
            _sync_payload(client, reconcile=True, delete_missing=True, dry_run=False)
        )

        self.assertEqual(envelope.payload.reconciled, 0)
        self.assertEqual(envelope.payload.deleted, 0)
        self.assertEqual(
            client.delete_filter.call_count, 0,
            "a rule with an exception was rewritten without it, broadening what it acts on",
        )
        self.assertEqual(client.create_filter.call_count, 0)

    def test_map_rule_reports_empty_list_for_fully_mappable_rule(self):
        """A rule using only from/to/subject reports no unmapped conditions."""
        from core.outlook._mail_labels import LabelsFiltersMixin

        raw = {
            "id": "ordinary",
            "conditions": {
                "senderContains": ["a.example"],
                "subjectContains": ["invoice"],
            },
            "actions": {"assignCategories": ["Cat"]},
        }
        mapped = LabelsFiltersMixin._map_rule(MagicMock(), raw)

        self.assertEqual(mapped["unmappedConditions"], [])


class TestSequencePreservation(unittest.TestCase):
    """When a live rule has a sequence number, reconcile must pass it through to
    create_filter so the replacement preserves its position in the chain.

    Regression guard: create_filter previously hardcoded sequence=1, so any
    reconcile moved the rule to position 1 and silently reordered all later
    rules.  Outlook inbox rules execute in sequence order; a reordering can
    cause later rules to never fire for matched mail (stopProcessingRules=True).
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_sequence_preserved_on_reconcile(self, mock_norm, mock_load):
        """create_filter receives sequence=5 when live rule had sequence=5."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {
                "match": {"from": "news@example.com"},
                "action": {"forward": "new@other.com"},
            },
        ]
        live_rule = {
            "id": "rule-1",
            "criteria": {"from": "news@example.com"},
            "action": {"forward": "old@other.com"},
            "sequence": 5,
            "stopProcessingRules": False,
        }
        client = _make_client(list_filters=[live_rule])
        payload = _sync_payload(client, reconcile=True, dry_run=False)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.payload.reconciled, 1)
        # Verify create_filter was called with sequence=5 and stop_processing_rules=False
        client.create_filter.assert_called_once()
        call_kwargs = client.create_filter.call_args
        self.assertEqual(call_kwargs.kwargs.get("sequence"), 5)
        self.assertFalse(call_kwargs.kwargs.get("stop_processing_rules"))

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_sequence_none_falls_back_to_default(self, mock_norm, mock_load):
        """When live rule has no sequence (old cache), create_filter uses its default."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {
                "match": {"from": "news@example.com"},
                "action": {"forward": "new@other.com"},
            },
        ]
        live_rule = {
            "id": "rule-1",
            "criteria": {"from": "news@example.com"},
            "action": {"forward": "old@other.com"},
            # no 'sequence' or 'stopProcessingRules' keys -- simulates old cache
        }
        client = _make_client(list_filters=[live_rule])
        payload = _sync_payload(client, reconcile=True, dry_run=False)

        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.payload.reconciled, 1)
        client.create_filter.assert_called_once()
        call_kwargs = client.create_filter.call_args
        # None signals create_filter to use its own default (sequence=1)
        self.assertIsNone(call_kwargs.kwargs.get("sequence"))
        self.assertIsNone(call_kwargs.kwargs.get("stop_processing_rules"))


class TestIsEnabledPreservation(unittest.TestCase):
    """A DISABLED rule must not come back enabled after reconcile.

    ``create_filter`` hardcoded ``isEnabled: True`` and ``_map_rule`` never read
    it, so reconciling a rule the user had switched off in the Outlook UI silently
    re-enabled it -- it resumed acting on mail they had deliberately stopped.

    The YAML has no enable/disable directive, so there is no way for the config to
    express "keep this off"; the live rule's own state is the only source of
    truth. Same defect class as the ``sequence`` reset, raised in review on #359.
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_disabled_rule_stays_disabled(self, mock_norm, mock_load):
        """isEnabled=False is passed through to the replacement."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [{
            "match": {"from": "news@example.com"},
            "action": {"forward": "new@other.com"},
        }]
        live_rule = {
            "id": "disabled-rule",
            "criteria": {"from": "news@example.com"},
            "action": {"forward": "old@other.com"},
            "sequence": 4,
            "stopProcessingRules": True,
            "isEnabled": False,
        }
        client = _make_client(list_filters=[live_rule])

        envelope = OutlookRulesSyncProcessor().process(
            _sync_payload(client, reconcile=True, dry_run=False)
        )

        self.assertEqual(envelope.payload.reconciled, 1)
        client.create_filter.assert_called_once()
        self.assertIs(
            client.create_filter.call_args.kwargs.get("is_enabled"), False,
            "a rule the user disabled was silently re-enabled",
        )

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_enabled_rule_stays_enabled(self, mock_norm, mock_load):
        """Contrast: an enabled rule is recreated enabled."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [{
            "match": {"from": "news@example.com"},
            "action": {"forward": "new@other.com"},
        }]
        live_rule = {
            "id": "enabled-rule",
            "criteria": {"from": "news@example.com"},
            "action": {"forward": "old@other.com"},
            "isEnabled": True,
        }
        client = _make_client(list_filters=[live_rule])

        OutlookRulesSyncProcessor().process(
            _sync_payload(client, reconcile=True, dry_run=False)
        )

        self.assertIs(client.create_filter.call_args.kwargs.get("is_enabled"), True)

    def test_create_filter_defaults_to_enabled(self):
        """An ordinary create (no is_enabled passed) still produces an enabled rule.

        Guards backwards compatibility: every non-reconcile caller omits the
        argument, and a rule created disabled by default would silently do nothing.
        """
        from core.outlook._mail_labels import LabelsFiltersMixin

        host = MagicMock()
        host._build_rule_conditions.return_value = {"senderContains": ["a.example"]}
        host._build_rule_actions.return_value = {"assignCategories": ["Cat"]}
        with patch("core.outlook._mail_labels._requests") as mock_req:
            mock_req.return_value.post.return_value.json.return_value = {"id": "new"}
            LabelsFiltersMixin.create_filter(host, {"from": "a.example"}, {"addLabelIds": ["Cat"]})

        sent = mock_req.return_value.post.call_args.kwargs["json"]
        self.assertIs(sent["isEnabled"], True)
        self.assertEqual(sent["sequence"], 1)
        self.assertIs(sent["stopProcessingRules"], True)


# ---------------------------------------------------------------------------
# delete_failed + --delete-missing: the surviving rule must not be destroyed
# ---------------------------------------------------------------------------

class TestDeleteFailedDeleteMissing(unittest.TestCase):
    """After a failed reconcile delete, ``--delete-missing`` must not retry it.

    The reconcile delete raised, so no replacement was created and the live rule
    survives on its OLD action.  It is stale, but it works.

    An earlier version of this test asserted the opposite -- that
    ``--delete-missing`` *should* retry, and that a successful retry showing
    ``deleted=1`` was "honest".  The count was honest; the outcome was not. The
    retry is a delete with no accompanying create, so when it succeeds the rule
    vanishes entirely and the mailbox is left with NO rule for those criteria:
    mail that was being forwarded becomes unfiltered, reported as a
    routine-looking ``Deleted: 1``.

    A stale but functioning rule is strictly better than no rule. The correct
    recovery is a re-run once the API error clears, which ``Failed: 1`` prompts.

    This was raised in review on PR #359 and confirmed by probe: with the retry
    mocked to SUCCEED (rather than fail, as an earlier probe had it), the rule
    was deleted and never recreated.
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_delete_failed_rule_is_not_deleted_by_delete_missing(self, mock_norm, mock_load):
        """delete_failed -> the surviving rule is protected; no second delete."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {
                "match": {"from": "news@example.com"},
                "action": {"forward": "new@other.com"},
            },
        ]
        live_rule = {
            "id": "rule-fail",
            "criteria": {"from": "news@example.com"},
            "action": {"forward": "old@other.com"},
            "sequence": 1,
            "stopProcessingRules": True,
        }
        client = _make_client(list_filters=[live_rule])
        # Reconcile delete fails. Any LATER delete is left SUCCEEDING on purpose:
        # if --delete-missing retried, the rule would really be destroyed and the
        # call-count assertion below fails loudly. Forcing the retry to raise
        # would hide the defect behind an error, which is how the previous
        # version of this test passed while the rule was being lost.
        client.delete_filter.side_effect = [Exception("API error"), None]
        payload = _sync_payload(client, reconcile=True, delete_missing=True, dry_run=False)

        envelope = OutlookRulesSyncProcessor().process(payload)

        # Non-success so the command exits nonzero; payload keeps the tally.
        self.assertEqual(envelope.status, "error")
        self.assertEqual(envelope.payload.failed, 1)
        self.assertEqual(envelope.payload.reconciled, 0)
        # The rule still exists and was NOT deleted.
        self.assertEqual(envelope.payload.deleted, 0)
        self.assertEqual(
            client.delete_filter.call_count,
            1,
            "--delete-missing destroyed a rule whose replacement was never created",
        )
        # One rule in, one tally out.
        p = envelope.payload
        self.assertEqual(p.created + p.reconciled + p.deleted + p.failed, 1)
        # No create_filter since delete failed on reconcile path
        client.create_filter.assert_not_called()


# ---------------------------------------------------------------------------
# create_failed + --delete-missing: no spurious second delete
# ---------------------------------------------------------------------------

class TestCreateFailedDeleteMissing(unittest.TestCase):
    """After create_failed the reconcile delete already succeeded: the rule is gone.

    ``--delete-missing`` must therefore issue NO second delete for that id.  The
    id is added to the protected set, which is what keeps the tallies honest: one
    rule must produce exactly one tally (``failed``), never ``Failed: 1`` plus
    ``Deleted: 1``, which reads as two affected rules.

    The earlier version of this test asserted ``deleted == 0`` while forcing the
    second delete to raise (``side_effect = [None, Exception("404")]``).  That
    passed for the wrong reason -- the count was 0 because the test made the call
    fail, not because no call was made -- so it held while the double-count
    defect was live, and could not tell the two behaviours apart.  Assert the
    call count, not just the tally.
    """

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_filters_for_outlook")
    def test_create_failed_issues_no_second_delete(self, mock_norm, mock_load):
        """create_failed -> the deleted id is protected; delete_missing skips it."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [
            {
                "match": {"from": "news@example.com"},
                "action": {"forward": "new@other.com"},
            },
        ]
        live_rule = {
            "id": "rule-gone",
            "criteria": {"from": "news@example.com"},
            "action": {"forward": "old@other.com"},
            "sequence": 1,
            "stopProcessingRules": True,
        }
        client = _make_client(list_filters=[live_rule])
        # The reconcile delete succeeds; the replacement create then fails.
        # delete_filter is deliberately left succeeding for any further call, so
        # a spurious second delete would be COUNTED and fail this test loudly
        # rather than being masked by a forced 404.
        client.create_filter.side_effect = Exception("API error")
        payload = _sync_payload(client, reconcile=True, delete_missing=True, dry_run=False)

        envelope = OutlookRulesSyncProcessor().process(payload)

        # Non-success so the command exits nonzero; payload keeps the tally.
        self.assertEqual(envelope.status, "error")
        self.assertEqual(envelope.payload.failed, 1)
        self.assertEqual(envelope.payload.reconciled, 0)
        # The rule is already gone: no second delete, and no second tally.
        self.assertEqual(envelope.payload.deleted, 0)
        self.assertEqual(
            client.delete_filter.call_count,
            1,
            "--delete-missing issued a redundant delete for an already-deleted rule",
        )
        # One rule in, one tally out.
        p = envelope.payload
        self.assertEqual(p.created + p.reconciled + p.deleted + p.failed, 1)


# ---------------------------------------------------------------------------
# CLI: --reconcile is registered on rules.plan
# ---------------------------------------------------------------------------

class TestRulesPlanCLIReconcileFlag(unittest.TestCase):
    """rules.plan --reconcile must be a registered CLI flag.

    Regression guard: before this fix, rules.plan had no --reconcile flag.
    A user following plan->dry-run->apply could not preview reconcile changes.
    """

    def test_reconcile_flag_registered_on_rules_plan(self):
        """Parsing rules.plan --reconcile does not raise an error."""
        from core.cli_framework import CLIApp
        from mail.cli.cmd_outlook import register_outlook_commands

        app = CLIApp("mail")
        register_outlook_commands(app)
        # Build the actual parser
        parser = app.build_parser()
        # rules.plan is a dotted subcommand; parse it
        ns = parser.parse_args([
            "outlook", "rules.plan",
            "--config", "/dev/null",
            "--client-id", "x",
            "--reconcile",
        ])
        self.assertTrue(ns.reconcile, "--reconcile not parsed correctly on rules.plan")


# ---------------------------------------------------------------------------
# Folder resolution parity on a stale snapshot
# ---------------------------------------------------------------------------

class TestExistingFolderCacheMissParity(unittest.TestCase):
    """A folder that EXISTS but is missing from the cached snapshot.

    ``_build_rule_action`` (sync, live) resolved via ``ensure_folder_path`` and got
    the real Graph id. Both previews fell back to the folder PATH STRING on a cache
    miss, so they keyed the same rule differently from the apply and reported
    ``Would create`` for a rule the live run treated as a no-op:

        STALE snapshot : plan would_create=1   sync --dry-run 1   sync LIVE 0

    Deferred from #359 because the fix needs a NON-mutating client lookup: plan
    cannot call ``ensure_folder_path``, which creates folders, and #359 had just
    fixed a dry run that did exactly that.

    ``resolve_folder_path`` is that lookup -- it returns ``""`` rather than
    creating. Both previews now consult it after the cached map and before falling
    back to the path, so an existing folder resolves to the id the apply uses, and
    only a genuinely absent folder falls through to the path (where "would create"
    is the honest answer).
    """

    REAL_ID = "folder-real-id"
    DESIRED = [{"match": {"from": "news.example"}, "action": {"moveToFolder": "Archive/News"}}]

    def _client(self, folder_map):
        client = _make_client(
            list_filters=[{
                "id": "news-rule",
                "criteria": {"from": "news.example"},
                "action": {"moveToFolderId": self.REAL_ID},
            }],
            folder_path_map=dict(folder_map),
        )
        client.ensure_folder_path.return_value = self.REAL_ID
        # The folder exists in Graph even when the snapshot missed it.
        client.resolve_folder_path.return_value = self.REAL_ID
        return client

    def _plan(self, folder_map):
        client = self._client(folder_map)
        payload = OutlookRulesPlanPayload(
            client=client, config_path="/test.yaml", move_to_folders=True, reconcile=False,
        )
        with patch("core.yamlio.load_config", return_value={"filters": []}), \
                patch("mail.dsl.normalize_filters_for_outlook", return_value=list(self.DESIRED)):
            return OutlookRulesPlanProcessor().process(payload), client

    def _sync(self, folder_map, dry_run):
        client = self._client(folder_map)
        payload = OutlookRulesSyncPayload(
            client=client, config_path="/test.yaml", dry_run=dry_run,
            move_to_folders=True, delete_missing=False, reconcile=False,
        )
        with patch("core.yamlio.load_config", return_value={"filters": []}), \
                patch("mail.dsl.normalize_filters_for_outlook", return_value=list(self.DESIRED)):
            return OutlookRulesSyncProcessor().process(payload), client

    def test_stale_snapshot_plan_agrees_with_live(self):
        """The regression: plan must not promise a create the apply will not make."""
        plan_env, _ = self._plan({})
        live_env, _ = self._sync({}, dry_run=False)

        self.assertEqual(plan_env.payload.would_create, live_env.payload.created)
        self.assertEqual(
            plan_env.payload.plan_items, [],
            "plan reported an action for a rule that already points at the folder",
        )

    def test_stale_snapshot_dry_run_agrees_with_live(self):
        """sync --dry-run must agree with sync too, not only plan."""
        dry_env, _ = self._sync({}, dry_run=True)
        live_env, _ = self._sync({}, dry_run=False)

        self.assertEqual(dry_env.payload.created, live_env.payload.created)

    def test_fresh_snapshot_unchanged(self):
        """Contrast: when the snapshot has the folder, nothing changes."""
        for surface in (lambda: self._plan({"Archive/News": self.REAL_ID})[0],
                        lambda: self._sync({"Archive/News": self.REAL_ID}, True)[0]):
            env = surface()
            count = getattr(env.payload, "would_create", None)
            if count is None:
                count = env.payload.created
            self.assertEqual(count, 0)

    def test_previews_never_create_a_folder(self):
        """Neither preview may call the mutating resolver. Guards #359's fix."""
        _, plan_client = self._plan({})
        _, dry_client = self._sync({}, dry_run=True)

        for label, client in (("plan", plan_client), ("dry-run", dry_client)):
            with self.subTest(surface=label):
                self.assertEqual(
                    client.ensure_folder_path.call_count, 0,
                    f"{label} called ensure_folder_path, which creates folders",
                )

    def test_absent_folder_still_falls_back_to_the_path(self):
        """A folder that does NOT exist resolves to the path, so plan can still report it.

        ``resolve_folder_path`` returns "" for a missing folder. Treating that as
        the answer would make the rule key fall out of comparison entirely; the
        path keeps the preview usable, and "would create" is then correct.
        """
        client = self._client({})
        client.resolve_folder_path.return_value = ""   # folder genuinely absent
        payload = OutlookRulesPlanPayload(
            client=client, config_path="/test.yaml", move_to_folders=True, reconcile=False,
        )
        with patch("core.yamlio.load_config", return_value={"filters": []}), \
                patch("mail.dsl.normalize_filters_for_outlook", return_value=list(self.DESIRED)):
            env = OutlookRulesPlanProcessor().process(payload)

        self.assertEqual(env.payload.would_create, 1)
        self.assertIn("Archive/News", env.payload.plan_items[0])


# ---------------------------------------------------------------------------
# Exact-duplicate live rules and --delete-missing
# ---------------------------------------------------------------------------

class TestExactDuplicateRulesAreAllDeleted(unittest.TestCase):
    """``--delete-missing`` must remove EVERY copy of an unwanted rule.

    ``existing = {_canon_rule(r): r ...}`` keys on criteria AND action, so live
    rules identical in both collapse to one entry and the rest were invisible to
    the deletion pass:

        3 identical live rules -> 1 entry in `existing`
        reported Deleted: 1, deleted ['dup-3'], STILL LIVE ['dup-1', 'dup-2']

    The user asked for the rule to be removed, was told it was, and two copies
    kept acting on mail. Not hypothetical -- three senders on this mailbox each
    carried three identical rules, deduplicated by hand while working on #359.

    Fixed by iterating the full live rule list rather than the collapsed map.
    The collapse itself is left alone: ``existing`` is still the right shape for
    the membership tests everything else does with it.
    """

    @staticmethod
    def _dups(**extra):
        return [
            {"id": f"dup-{i}", "criteria": {"from": "spam.example"},
             "action": {"forward": "x@y.com"}, **extra}
            for i in (1, 2, 3)
        ]

    def _run(self, live, desired):
        client = _make_client(list_filters=[dict(r) for r in live])
        client.resolve_folder_path.return_value = ""
        with patch("core.yamlio.load_config", return_value={"filters": []}), \
                patch("mail.dsl.normalize_filters_for_outlook", return_value=desired):
            envelope = OutlookRulesSyncProcessor().process(
                _sync_payload(client, reconcile=True, delete_missing=True, dry_run=False)
            )
        return envelope, [c.args[0] for c in client.delete_filter.call_args_list]

    WANT_OTHER = [{"match": {"from": "keep.example"}, "action": {"forward": "k@y.com"}}]
    WANT_THESE = [{"match": {"from": "spam.example"}, "action": {"forward": "x@y.com"}}]

    def test_all_duplicates_deleted_when_not_desired(self):
        """Every copy is deleted, and the reported count matches reality."""
        envelope, deleted = self._run(self._dups(), list(self.WANT_OTHER))

        self.assertEqual(sorted(deleted), ["dup-1", "dup-2", "dup-3"])
        self.assertEqual(
            envelope.payload.deleted, 3,
            "the tally must match what was actually deleted, not the collapsed count",
        )

    def test_duplicates_kept_when_desired(self):
        """Contrast: a desired rule is not deleted just because copies exist.

        Iterating every live rule means the desired-key check has to hold per
        rule; without this, the fix could delete rules the config asks for.
        """
        envelope, deleted = self._run(self._dups(), list(self.WANT_THESE))

        self.assertEqual(deleted, [])
        self.assertEqual(envelope.payload.deleted, 0)

    def test_unmappable_duplicates_still_protected(self):
        """Contrast: the unmappable-rule protection survives the wider iteration."""
        envelope, deleted = self._run(
            self._dups(unmappedConditions=["bodyContains"]), list(self.WANT_THESE)
        )

        self.assertEqual(deleted, [])
        self.assertEqual(envelope.payload.deleted, 0)

    def test_caller_supplied_keys_are_honoured(self):
        """`_delete_missing_rules` must not ignore the keys it was handed.

        A first cut derived `_canon_rule(rule)` for every candidate, which works
        for real callers (they key the same way) but made the caller's mapping a
        second source of truth -- and broke two existing tests that pass synthetic
        keys. Keys come from `all_rules` only when `all_rules` is supplied.
        """
        client = _make_client()
        existing = {"synthetic-keep": {"id": "r-keep"}, "synthetic-drop": {"id": "r-drop"}}
        payload = _sync_payload(client, delete_missing=True, dry_run=False)

        deleted = OutlookRulesSyncProcessor()._delete_missing_rules(
            existing, {"synthetic-keep"}, payload
        )

        self.assertEqual(deleted, 1)
        client.delete_filter.assert_called_once_with("r-drop")


if __name__ == "__main__":
    unittest.main()
