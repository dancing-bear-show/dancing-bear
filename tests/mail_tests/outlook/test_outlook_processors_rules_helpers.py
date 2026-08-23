"""Tests for mail/outlook/processors_rules_helpers.py helper functions.

Covers the four functions with zero direct coverage:
  - _fetch_rules_with_resilience
  - _build_rule_action
  - _resolve_destination_folder
  - _export_rule_entry
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, call

from mail.outlook.processors_rules_helpers import (
    RuleContext,
    _build_rule_action,
    _export_rule_entry,
    _fetch_rules_with_resilience,
    _resolve_destination_folder,
)


# ---------------------------------------------------------------------------
# _fetch_rules_with_resilience
# ---------------------------------------------------------------------------

class TestFetchRulesWithResilienceHappyPath(unittest.TestCase):
    """Happy-path: successful API call returns results directly."""

    def test_returns_list_from_client(self):
        client = MagicMock()
        expected = [{"id": "r1"}, {"id": "r2"}]
        client.list_filters.return_value = expected

        result = _fetch_rules_with_resilience(client)

        self.assertEqual(result, expected)
        client.list_filters.assert_called_once_with(use_cache=False, ttl=600)

    def test_forwards_use_cache_and_ttl(self):
        client = MagicMock()
        client.list_filters.return_value = []

        _fetch_rules_with_resilience(client, use_cache=True, cache_ttl=300)

        client.list_filters.assert_called_once_with(use_cache=True, ttl=300)


class TestFetchRulesWithResilienceAuthError(unittest.TestCase):
    """Auth errors (401/403) must propagate, not fall back to cache."""

    def _make_auth_error(self, status_code: int) -> Exception:
        err = Exception(f"HTTP {status_code}")
        err.response = MagicMock(status_code=status_code)  # type: ignore[attr-defined]
        return err

    def test_401_propagates(self):
        client = MagicMock()
        client.list_filters.side_effect = self._make_auth_error(401)

        with self.assertRaises(Exception):
            _fetch_rules_with_resilience(client)

    def test_403_propagates(self):
        client = MagicMock()
        client.list_filters.side_effect = self._make_auth_error(403)

        with self.assertRaises(Exception):
            _fetch_rules_with_resilience(client)

    def test_401_does_not_fall_back_to_cache(self):
        client = MagicMock()
        client.list_filters.side_effect = self._make_auth_error(401)

        try:
            _fetch_rules_with_resilience(client)
        except Exception:
            pass

        # list_filters must have been called exactly once — no cache fallback
        self.assertEqual(client.list_filters.call_count, 1)


class TestFetchRulesWithResilienceCacheFallback(unittest.TestCase):
    """Non-auth transient errors must fall back to cache read.

    This is the highest-risk branch: if the fallback is wrong the caller
    sees an empty rule set and treats every existing rule as deletable.
    """

    def test_transient_ioerror_falls_back_to_cache(self):
        client = MagicMock()
        stale_rules = [{"id": "cached-rule"}]

        # First call raises a generic error (no .response attribute);
        # second call (cache) returns stale data.
        client.list_filters.side_effect = [
            IOError("network timeout"),
            stale_rules,
        ]

        result = _fetch_rules_with_resilience(client, cache_ttl=120)

        # Assert exact arguments on BOTH calls, not just call count.
        self.assertEqual(
            client.list_filters.call_args_list,
            [
                call(use_cache=False, ttl=120),
                call(use_cache=True, ttl=120),
            ],
        )
        self.assertEqual(result, stale_rules)

    def test_error_with_non_auth_status_falls_back(self):
        """A 500 error (server error) is not auth; must fall back."""
        client = MagicMock()
        err = Exception("Internal Server Error")
        err.response = MagicMock(status_code=500)  # type: ignore[attr-defined]
        cached = [{"id": "r-500-cached"}]

        client.list_filters.side_effect = [err, cached]

        result = _fetch_rules_with_resilience(client, cache_ttl=60)

        self.assertEqual(
            client.list_filters.call_args_list,
            [
                call(use_cache=False, ttl=60),
                call(use_cache=True, ttl=60),
            ],
        )
        self.assertEqual(result, cached)

    def test_cache_fallback_also_fails_returns_empty_list(self):
        """If both the live call and the cache call fail, return []."""
        client = MagicMock()
        client.list_filters.side_effect = IOError("total failure")

        result = _fetch_rules_with_resilience(client)

        self.assertEqual(result, [])

    def test_cache_fallback_invoked_with_correct_ttl_argument(self):
        """Assert the fallback passes ttl, not just that it was called."""
        client = MagicMock()
        client.list_filters.side_effect = [IOError("down"), []]

        _fetch_rules_with_resilience(client, cache_ttl=900)

        # The second call must carry use_cache=True and the caller's ttl
        second_call = client.list_filters.call_args_list[1]
        self.assertEqual(second_call, call(use_cache=True, ttl=900))


# ---------------------------------------------------------------------------
# _build_rule_action
# ---------------------------------------------------------------------------

class TestBuildRuleActionMoveToFolder(unittest.TestCase):
    """moveToFolder spec: ensure_folder_path called; folder id stored."""

    def test_move_to_folder_calls_ensure_folder_path(self):
        client = MagicMock()
        client.ensure_folder_path.return_value = "folder-id-123"
        ctx = RuleContext(
            client=client,
            name_to_id={},
            folder_map={},
            move_to_folders=False,
        )
        action_spec = {"moveToFolder": "Archive/Newsletters"}

        result = _build_rule_action(action_spec, ctx)

        client.ensure_folder_path.assert_called_once_with("Archive/Newsletters")
        self.assertEqual(result["moveToFolderId"], "folder-id-123")

    def test_move_to_folder_takes_precedence_over_add_labels(self):
        client = MagicMock()
        client.ensure_folder_path.return_value = "fid-explicit"
        ctx = RuleContext(
            client=client,
            name_to_id={"Work": "lab-id"},
            folder_map={},
            move_to_folders=True,
        )
        # Both moveToFolder and add are present; moveToFolder must win
        action_spec = {"moveToFolder": "Explicit/Path", "add": ["Work"]}

        result = _build_rule_action(action_spec, ctx)

        client.ensure_folder_path.assert_called_once_with("Explicit/Path")
        self.assertEqual(result["moveToFolderId"], "fid-explicit")
        self.assertNotIn("addLabelIds", result)

    def test_move_to_folder_uses_string_cast_of_path(self):
        client = MagicMock()
        client.ensure_folder_path.return_value = "fid"
        ctx = RuleContext(client=client, name_to_id={}, folder_map={}, move_to_folders=False)

        _build_rule_action({"moveToFolder": 42}, ctx)  # non-string path

        client.ensure_folder_path.assert_called_once_with("42")


class TestBuildRuleActionMoveToFolderViaLabel(unittest.TestCase):
    """move_to_folders=True with add labels: uses folder_map or ensure_folder_path."""

    def test_uses_folder_map_when_available(self):
        client = MagicMock()
        ctx = RuleContext(
            client=client,
            name_to_id={},
            folder_map={"Newsletter": "cached-fid"},
            move_to_folders=True,
        )
        action_spec = {"add": ["Newsletter"]}

        result = _build_rule_action(action_spec, ctx)

        # folder_map hit: ensure_folder_path must NOT be called
        client.ensure_folder_path.assert_not_called()
        self.assertEqual(result["moveToFolderId"], "cached-fid")

    def test_calls_ensure_folder_path_when_not_in_folder_map(self):
        client = MagicMock()
        client.ensure_folder_path.return_value = "new-fid"
        ctx = RuleContext(
            client=client,
            name_to_id={},
            folder_map={},
            move_to_folders=True,
        )
        action_spec = {"add": ["SomeLabel"]}

        result = _build_rule_action(action_spec, ctx)

        client.ensure_folder_path.assert_called_once_with("SomeLabel")
        self.assertEqual(result["moveToFolderId"], "new-fid")


class TestBuildRuleActionAddLabels(unittest.TestCase):
    """add-label path (move_to_folders=False): name-to-id mapping used."""

    def test_resolves_label_name_to_id(self):
        client = MagicMock()
        ctx = RuleContext(
            client=client,
            name_to_id={"Newsletter": "label-id-99"},
            folder_map={},
            move_to_folders=False,
        )
        action_spec = {"add": ["Newsletter"]}

        result = _build_rule_action(action_spec, ctx)

        self.assertEqual(result["addLabelIds"], ["label-id-99"])
        # No folder operations
        client.ensure_folder_path.assert_not_called()

    def test_resolves_multiple_label_ids(self):
        client = MagicMock()
        ctx = RuleContext(
            client=client,
            name_to_id={"A": "id-a", "B": "id-b"},
            folder_map={},
            move_to_folders=False,
        )
        result = _build_rule_action({"add": ["A", "B"]}, ctx)

        self.assertEqual(sorted(result["addLabelIds"]), ["id-a", "id-b"])

    def test_unknown_label_id_dropped(self):
        """Labels with no name-to-id mapping are silently dropped."""
        client = MagicMock()
        ctx = RuleContext(
            client=client,
            name_to_id={"Known": "kid"},
            folder_map={},
            move_to_folders=False,
        )
        result = _build_rule_action({"add": ["Known", "Unknown"]}, ctx)

        self.assertEqual(result["addLabelIds"], ["kid"])

    def test_all_unknown_labels_produces_no_add_label_ids_key(self):
        client = MagicMock()
        ctx = RuleContext(
            client=client,
            name_to_id={},
            folder_map={},
            move_to_folders=False,
        )
        result = _build_rule_action({"add": ["Ghost"]}, ctx)

        self.assertNotIn("addLabelIds", result)

    def test_forward_is_included_alongside_labels(self):
        client = MagicMock()
        ctx = RuleContext(
            client=client,
            name_to_id={"Work": "wid"},
            folder_map={},
            move_to_folders=False,
        )
        result = _build_rule_action({"add": ["Work"], "forward": "fwd@example.com"}, ctx)

        self.assertEqual(result["addLabelIds"], ["wid"])
        self.assertEqual(result["forward"], "fwd@example.com")

    def test_forward_only_action(self):
        client = MagicMock()
        ctx = RuleContext(client=client, name_to_id={}, folder_map={}, move_to_folders=False)
        result = _build_rule_action({"forward": "archive@example.com"}, ctx)

        self.assertEqual(result["forward"], "archive@example.com")
        self.assertNotIn("addLabelIds", result)


# ---------------------------------------------------------------------------
# _resolve_destination_folder
# ---------------------------------------------------------------------------

class TestResolveDestinationFolderMoveToFolder(unittest.TestCase):
    """moveToFolder in action_spec."""

    def test_dry_run_returns_path_from_folder_paths(self):
        client = MagicMock()
        folder_paths = {"Archive": "fid-archive"}

        result = _resolve_destination_folder(
            action_spec={"moveToFolder": "Archive"},
            move_to_folders=False,
            folder_paths=folder_paths,
            client=client,
            dry_run=True,
        )

        self.assertEqual(result, "fid-archive")
        # dry-run must NOT create/resolve a folder
        client.ensure_folder_path.assert_not_called()

    def test_live_calls_ensure_folder_path(self):
        client = MagicMock()
        client.ensure_folder_path.return_value = "live-fid"

        result = _resolve_destination_folder(
            action_spec={"moveToFolder": "Archive/Deep"},
            move_to_folders=False,
            folder_paths={},
            client=client,
            dry_run=False,
        )

        client.ensure_folder_path.assert_called_once_with("Archive/Deep")
        self.assertEqual(result, "live-fid")

    def test_dry_run_missing_path_returns_none(self):
        """Dry-run with no matching folder_paths entry returns None."""
        client = MagicMock()

        result = _resolve_destination_folder(
            action_spec={"moveToFolder": "Nonexistent"},
            move_to_folders=False,
            folder_paths={},
            client=client,
            dry_run=True,
        )

        self.assertIsNone(result)
        client.ensure_folder_path.assert_not_called()


class TestResolveDestinationFolderMoveToFolderViaAddLabels(unittest.TestCase):
    """move_to_folders=True with add list (no explicit moveToFolder)."""

    def test_dry_run_returns_folder_id_from_map(self):
        client = MagicMock()
        folder_paths = {"Newsletter": "fid-nl"}

        result = _resolve_destination_folder(
            action_spec={"add": ["Newsletter"]},
            move_to_folders=True,
            folder_paths=folder_paths,
            client=client,
            dry_run=True,
        )

        self.assertEqual(result, "fid-nl")
        client.ensure_folder_path.assert_not_called()

    def test_live_calls_ensure_folder_path_with_first_label(self):
        client = MagicMock()
        client.ensure_folder_path.return_value = "created-fid"

        result = _resolve_destination_folder(
            action_spec={"add": ["Primary", "Secondary"]},
            move_to_folders=True,
            folder_paths={},
            client=client,
            dry_run=False,
        )

        client.ensure_folder_path.assert_called_once_with("Primary")
        self.assertEqual(result, "created-fid")


class TestResolveDestinationFolderNoMatch(unittest.TestCase):
    """No moveToFolder and move_to_folders=False returns None."""

    def test_returns_none_when_no_folder_spec(self):
        client = MagicMock()

        result = _resolve_destination_folder(
            action_spec={"add": ["SomeLabel"]},
            move_to_folders=False,
            folder_paths={},
            client=client,
            dry_run=False,
        )

        self.assertIsNone(result)
        client.ensure_folder_path.assert_not_called()

    def test_returns_none_when_empty_action_spec(self):
        client = MagicMock()

        result = _resolve_destination_folder(
            action_spec={},
            move_to_folders=False,
            folder_paths={"Archive": "fid"},
            client=client,
            dry_run=False,
        )

        self.assertIsNone(result)
        client.ensure_folder_path.assert_not_called()


# ---------------------------------------------------------------------------
# _export_rule_entry
# ---------------------------------------------------------------------------

class TestExportRuleEntry(unittest.TestCase):
    """Output shape of _export_rule_entry."""

    def test_from_criteria_included(self):
        r = {"criteria": {"from": "sender@example.com"}, "action": {}}
        entry = _export_rule_entry(r, id_to_name={}, folder_rev={})

        self.assertEqual(entry["match"]["from"], "sender@example.com")

    def test_to_and_subject_criteria_included(self):
        r = {
            "criteria": {"to": "team@example.com", "subject": "URGENT"},
            "action": {},
        }
        entry = _export_rule_entry(r, id_to_name={}, folder_rev={})

        self.assertEqual(entry["match"]["to"], "team@example.com")
        self.assertEqual(entry["match"]["subject"], "URGENT")

    def test_empty_criteria_produces_empty_match(self):
        r = {"criteria": {}, "action": {}}
        entry = _export_rule_entry(r, id_to_name={}, folder_rev={})

        self.assertEqual(entry["match"], {})

    def test_add_label_ids_resolved_to_names(self):
        r = {
            "criteria": {},
            "action": {"addLabelIds": ["id-1", "id-2"]},
        }
        id_to_name = {"id-1": "Newsletter", "id-2": "Work"}
        entry = _export_rule_entry(r, id_to_name=id_to_name, folder_rev={})

        self.assertIn("action", entry)
        self.assertEqual(entry["action"]["add"], ["Newsletter", "Work"])

    def test_unknown_label_id_kept_as_id(self):
        """IDs not in id_to_name are preserved verbatim."""
        r = {"criteria": {}, "action": {"addLabelIds": ["unknown-id"]}}
        entry = _export_rule_entry(r, id_to_name={}, folder_rev={})

        self.assertEqual(entry["action"]["add"], ["unknown-id"])

    def test_forward_action_included(self):
        r = {"criteria": {}, "action": {"forward": "fwd@example.com"}}
        entry = _export_rule_entry(r, id_to_name={}, folder_rev={})

        self.assertEqual(entry["action"]["forward"], "fwd@example.com")

    def test_move_to_folder_resolved_to_path(self):
        r = {"criteria": {}, "action": {"moveToFolderId": "fid-99"}}
        folder_rev = {"fid-99": "Archive/Work"}
        entry = _export_rule_entry(r, id_to_name={}, folder_rev=folder_rev)

        self.assertEqual(entry["action"]["moveToFolder"], "Archive/Work")

    def test_unknown_folder_id_kept_as_id(self):
        """Folder IDs not in folder_rev are preserved verbatim."""
        r = {"criteria": {}, "action": {"moveToFolderId": "fid-unknown"}}
        entry = _export_rule_entry(r, id_to_name={}, folder_rev={})

        self.assertEqual(entry["action"]["moveToFolder"], "fid-unknown")

    def test_no_action_fields_produces_no_action_key(self):
        """If the action block is empty the entry must not have an 'action' key."""
        r = {"criteria": {"from": "x@y.com"}, "action": {}}
        entry = _export_rule_entry(r, id_to_name={}, folder_rev={})

        self.assertNotIn("action", entry)

    def test_full_rule_round_trips(self):
        r = {
            "criteria": {
                "from": "newsletter@corp.com",
                "subject": "Weekly Digest",
            },
            "action": {
                "addLabelIds": ["lid-1"],
                "moveToFolderId": "fid-99",
                "forward": "copy@example.com",
            },
        }
        id_to_name = {"lid-1": "Newsletter"}
        folder_rev = {"fid-99": "Archive/Newsletter"}

        entry = _export_rule_entry(r, id_to_name=id_to_name, folder_rev=folder_rev)

        self.assertEqual(entry["match"]["from"], "newsletter@corp.com")
        self.assertEqual(entry["match"]["subject"], "Weekly Digest")
        self.assertEqual(entry["action"]["add"], ["Newsletter"])
        self.assertEqual(entry["action"]["moveToFolder"], "Archive/Newsletter")
        self.assertEqual(entry["action"]["forward"], "copy@example.com")

    def test_missing_criteria_and_action_keys_handled(self):
        """Rules with no criteria/action keys must not raise."""
        entry = _export_rule_entry({}, id_to_name={}, folder_rev={})

        self.assertIsInstance(entry, dict)
        self.assertIn("match", entry)


if __name__ == "__main__":
    unittest.main(verbosity=2)
