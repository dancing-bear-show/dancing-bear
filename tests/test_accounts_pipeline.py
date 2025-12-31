"""Unit tests for mail/accounts/pipeline.py"""
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from mail.accounts.pipeline import (
    AccountsExportLabelsRequest,
    AccountsListRequest,
    AccountsPlanFiltersRequest,
    AccountsPlanLabelsRequest,
    _build_filter_dsl_entry,
    _build_label_id_to_name_map,
    _build_label_update_dict,
    _build_outlook_filter_action,
    _convert_label_ids_to_names,
    _extract_filter_criteria,
    _needs_label_update,
    _sync_labels_for_account,
    canonicalize_filter,
)


class TestHelperFunctions(unittest.TestCase):
    """Test helper functions for pipeline operations."""

    def test_canonicalize_filter(self):
        """Test filter canonicalization."""
        f1 = {
            "criteria": {"from": "test@example.com", "subject": "Test"},
            "action": {"addLabelIds": ["label1", "label2"]},
        }
        f2 = {
            "match": {"from": "test@example.com", "subject": "Test"},
            "action": {"add": ["label2", "label1"]},
        }
        # Should produce same canonical form (sorted)
        self.assertEqual(canonicalize_filter(f1), canonicalize_filter(f2))

    def test_canonicalize_filter_with_forward(self):
        """Test filter canonicalization with forward action."""
        f = {
            "criteria": {"from": "test@example.com"},
            "action": {"forward": "forward@example.com"},
        }
        result = canonicalize_filter(f)
        self.assertIn("forward@example.com", result)

    def test_build_label_id_to_name_map(self):
        """Test building label ID to name mapping."""
        labels = [
            {"id": "id1", "name": "Label1"},
            {"id": "id2", "name": "Label2"},
            {"id": "id3", "name": "Label3"},
        ]
        result = _build_label_id_to_name_map(labels)
        self.assertEqual(result, {"id1": "Label1", "id2": "Label2", "id3": "Label3"})

    def test_build_label_id_to_name_map_with_missing_fields(self):
        """Test label ID mapping with missing fields."""
        labels = [{"id": "id1"}, {"name": "Label2"}, {}]
        result = _build_label_id_to_name_map(labels)
        # Missing fields get empty string defaults, last one wins for duplicate keys
        self.assertEqual(result, {"id1": "", "": ""})

    def test_convert_label_ids_to_names(self):
        """Test converting label IDs to names."""
        id_to_name = {"id1": "Label1", "id2": "Label2"}
        ids = ["id1", "id2", "id3"]
        result = _convert_label_ids_to_names(ids, id_to_name)
        self.assertEqual(result, ["Label1", "Label2"])

    def test_convert_label_ids_to_names_empty(self):
        """Test converting empty ID list."""
        result = _convert_label_ids_to_names(None, {})
        self.assertEqual(result, [])

    def test_extract_filter_criteria(self):
        """Test extracting relevant filter criteria."""
        criteria = {
            "from": "test@example.com",
            "to": "dest@example.com",
            "subject": "Test",
            "query": "is:important",
            "irrelevant": "ignored",
            "empty": None,
            "blank": "",
        }
        result = _extract_filter_criteria(criteria)
        expected = {
            "from": "test@example.com",
            "to": "dest@example.com",
            "subject": "Test",
            "query": "is:important",
        }
        self.assertEqual(result, expected)

    def test_build_filter_dsl_entry(self):
        """Test building DSL filter entry."""
        filter_obj = {
            "criteria": {"from": "test@example.com", "subject": "Test"},
            "action": {
                "forward": "forward@example.com",
                "addLabelIds": ["id1", "id2"],
                "removeLabelIds": ["id3"],
            },
        }
        id_to_name = {"id1": "Label1", "id2": "Label2", "id3": "Label3"}
        result = _build_filter_dsl_entry(filter_obj, id_to_name)

        self.assertEqual(result["match"]["from"], "test@example.com")
        self.assertEqual(result["match"]["subject"], "Test")
        self.assertEqual(result["action"]["forward"], "forward@example.com")
        self.assertEqual(result["action"]["add"], ["Label1", "Label2"])
        self.assertEqual(result["action"]["remove"], ["Label3"])

    def test_needs_label_update_gmail(self):
        """Test label update detection for Gmail."""
        spec = {"color": "#ff0000", "labelListVisibility": "labelShow"}
        current = {"color": "#00ff00", "labelListVisibility": "labelShow"}
        self.assertTrue(_needs_label_update(spec, current, "gmail"))

    def test_needs_label_update_gmail_no_change(self):
        """Test label update detection when no change needed."""
        spec = {"color": "#ff0000"}
        current = {"color": "#ff0000"}
        self.assertFalse(_needs_label_update(spec, current, "gmail"))

    def test_needs_label_update_outlook(self):
        """Test label update detection for Outlook."""
        spec = {"color": "#ff0000"}
        current = {"color": "#00ff00"}
        self.assertTrue(_needs_label_update(spec, current, "outlook"))

    def test_build_label_update_dict_gmail(self):
        """Test building label update dict for Gmail."""
        spec = {"color": "#ff0000", "labelListVisibility": "labelShow"}
        current = {"color": "#00ff00", "labelListVisibility": "labelHide"}
        result = _build_label_update_dict("TestLabel", spec, current, "gmail")

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "TestLabel")
        self.assertEqual(result["color"], "#ff0000")
        self.assertEqual(result["labelListVisibility"], "labelShow")

    def test_build_label_update_dict_no_change(self):
        """Test building label update dict when no changes needed."""
        spec = {"color": "#ff0000"}
        current = {"color": "#ff0000"}
        result = _build_label_update_dict("TestLabel", spec, current, "gmail")
        self.assertIsNone(result)

    def test_build_outlook_filter_action(self):
        """Test building Outlook filter action."""
        action_spec = {"add": ["Label1", "Label2"], "forward": "forward@example.com"}
        name_to_id = {"Label1": "id1", "Label2": "id2"}

        result = _build_outlook_filter_action(action_spec, name_to_id)

        self.assertEqual(result["addLabelIds"], ["id1", "id2"])
        self.assertEqual(result["forward"], "forward@example.com")

    def test_build_outlook_filter_action_filters_missing(self):
        """Test Outlook filter action filters out missing IDs."""
        action_spec = {"add": ["Label1", "MissingLabel"]}
        name_to_id = {"Label1": "id1"}

        result = _build_outlook_filter_action(action_spec, name_to_id)

        self.assertEqual(result["addLabelIds"], ["id1"])


class TestSyncLabelsForAccount(unittest.TestCase):
    """Test the _sync_labels_for_account helper function."""

    def test_sync_labels_creates_new_labels(self):
        """Test syncing creates new labels."""
        client = MagicMock()
        desired = [{"name": "NewLabel", "color": "#ff0000"}]
        existing = {}

        created, updated = _sync_labels_for_account(client, desired, existing, "gmail", dry_run=False)

        self.assertEqual(created, 1)
        self.assertEqual(updated, 0)
        client.create_label.assert_called_once_with(name="NewLabel", color="#ff0000")

    def test_sync_labels_dry_run(self):
        """Test syncing in dry-run mode doesn't create labels."""
        client = MagicMock()
        desired = [{"name": "NewLabel", "color": "#ff0000"}]
        existing = {}

        created, updated = _sync_labels_for_account(client, desired, existing, "gmail", dry_run=True)

        self.assertEqual(created, 1)
        self.assertEqual(updated, 0)
        client.create_label.assert_not_called()

    def test_sync_labels_updates_existing(self):
        """Test syncing updates existing labels."""
        client = MagicMock()
        desired = [{"name": "ExistingLabel", "color": "#ff0000"}]
        existing = {"ExistingLabel": {"id": "id1", "name": "ExistingLabel", "color": "#00ff00"}}

        created, updated = _sync_labels_for_account(client, desired, existing, "gmail", dry_run=False)

        self.assertEqual(created, 0)
        self.assertEqual(updated, 1)
        client.update_label.assert_called_once()

    def test_sync_labels_skips_unnamed(self):
        """Test syncing skips labels without names."""
        client = MagicMock()
        desired = [{"color": "#ff0000"}, {"name": "ValidLabel"}]
        existing = {}

        created, updated = _sync_labels_for_account(client, desired, existing, "gmail", dry_run=False)

        self.assertEqual(created, 1)
        self.assertEqual(client.create_label.call_count, 1)


class TestAccountsListProcessor(unittest.TestCase):
    """Test AccountsListProcessor."""

    @patch('mail.accounts.helpers.load_accounts')
    def test_list_processor_success(self, mock_load_accounts):
        """Test listing accounts successfully."""
        from mail.accounts.pipeline import AccountsListProcessor, RequestConsumer

        mock_load_accounts.return_value = [
            {"name": "account1", "provider": "gmail", "credentials": "creds1.json", "token": "token1.json"},
            {"name": "account2", "provider": "outlook", "credentials": "creds2.json", "token": "token2.json"},
        ]

        request = AccountsListRequest(config_path="test_config.yaml")
        processor = AccountsListProcessor()
        envelope = processor.process(RequestConsumer(request).consume())

        self.assertTrue(envelope.ok())
        result = envelope.unwrap()
        self.assertEqual(len(result.accounts), 2)
        self.assertEqual(result.accounts[0].name, "account1")
        self.assertEqual(result.accounts[0].provider, "gmail")


class TestAccountsExportLabelsProcessor(unittest.TestCase):
    """Test AccountsExportLabelsProcessor."""

    @patch('mail.yamlio.dump_config')
    def test_export_labels_success(self, mock_dump_config):
        """Test exporting labels successfully."""
        from mail.accounts.pipeline import AccountsExportLabelsProcessor, RequestConsumer, AccountAuthenticator

        # Mock authenticated accounts
        mock_client = MagicMock()
        mock_client.list_labels.return_value = [
            {"id": "id1", "name": "Label1", "color": "#ff0000", "type": "user"},
            {"id": "INBOX", "name": "INBOX", "type": "system"},  # Should be filtered
        ]

        with TemporaryDirectory() as tmpdir:
            with patch.object(AccountAuthenticator, 'iter_authenticated_accounts', return_value=[({"name": "test_account"}, mock_client)]):
                request = AccountsExportLabelsRequest(
                    config_path="test_config.yaml",
                    out_dir=tmpdir,
                    accounts_filter=None
                )
                processor = AccountsExportLabelsProcessor()
                envelope = processor.process(RequestConsumer(request).consume())

                self.assertTrue(envelope.ok())
                result = envelope.unwrap()
                self.assertEqual(len(result.exports), 1)
                self.assertEqual(result.exports[0].account_name, "test_account")
                self.assertEqual(result.exports[0].label_count, 1)


class TestAccountsPlanLabelsProcessor(unittest.TestCase):
    """Test AccountsPlanLabelsProcessor."""

    @patch('mail.accounts.helpers.load_accounts')
    @patch('mail.yamlio.load_config')
    @patch('mail.accounts.helpers.build_provider_for_account')
    @patch('mail.accounts.helpers.iter_accounts')
    def test_plan_labels_finds_new_labels(self, mock_iter, mock_build, mock_load_config, mock_load_accounts):
        """Test planning identifies new labels to create."""
        from mail.accounts.pipeline import AccountsPlanLabelsProcessor, RequestConsumer

        mock_load_accounts.return_value = [{"name": "test", "provider": "gmail"}]
        mock_load_config.return_value = {
            "labels": [{"name": "NewLabel", "color": "#ff0000"}]
        }
        mock_iter.return_value = [{"name": "test", "provider": "gmail"}]

        mock_client = MagicMock()
        mock_client.list_labels.return_value = []
        mock_build.return_value = mock_client

        request = AccountsPlanLabelsRequest(
            config_path="test_config.yaml",
            labels_path="labels.yaml"
        )
        processor = AccountsPlanLabelsProcessor()
        envelope = processor.process(RequestConsumer(request).consume())

        self.assertTrue(envelope.ok())
        result = envelope.unwrap()
        self.assertEqual(len(result.plans), 1)
        self.assertEqual(result.plans[0].to_create, 1)
        self.assertEqual(result.plans[0].to_update, 0)


class TestAccountsPlanFiltersProcessor(unittest.TestCase):
    """Test AccountsPlanFiltersProcessor."""

    @patch('mail.accounts.helpers.load_accounts')
    @patch('mail.yamlio.load_config')
    @patch('mail.accounts.helpers.build_provider_for_account')
    @patch('mail.accounts.helpers.iter_accounts')
    def test_plan_filters_unsupported_provider(self, mock_iter, mock_build, mock_load_config, mock_load_accounts):
        """Test planning for unsupported provider."""
        from mail.accounts.pipeline import AccountsPlanFiltersProcessor, RequestConsumer

        mock_load_accounts.return_value = [{"name": "test", "provider": "unsupported"}]
        mock_load_config.return_value = {"filters": []}
        mock_iter.return_value = [{"name": "test", "provider": "unsupported"}]

        mock_client = MagicMock()
        mock_client.list_filters.return_value = []
        mock_build.return_value = mock_client

        request = AccountsPlanFiltersRequest(
            config_path="test_config.yaml",
            filters_path="filters.yaml"
        )
        processor = AccountsPlanFiltersProcessor()
        envelope = processor.process(RequestConsumer(request).consume())

        self.assertTrue(envelope.ok())
        result = envelope.unwrap()
        self.assertEqual(len(result.plans), 1)
        self.assertEqual(result.plans[0].to_create, -1)  # Unsupported


if __name__ == "__main__":
    unittest.main()
