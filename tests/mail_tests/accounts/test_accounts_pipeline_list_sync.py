"""Tests for AccountsSyncLabelsProcessor and AccountsSyncFiltersProcessor.

Covers the sync pipeline branches not exercised elsewhere: label sync across
gmail/outlook providers, filter sync delegation (gmail), direct Outlook filter
sync, and the unsupported-provider fallback -- including dry-run vs apply for
both labels and filters.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tests.fakes.gmail import FakeGmailClient
from tests.fakes.outlook import FakeOutlookClient

from mail.accounts.pipeline_list_sync import (
    AccountsSyncLabelsRequest,
    AccountsSyncLabelsProcessor,
    AccountsSyncFiltersRequest,
    AccountsSyncFiltersProcessor,
)


def make_account_dict(
    name: str = "personal",
    provider: str = "gmail",
    credentials: str = "/creds.json",
    token: str = "/token.json",  # nosec B107 - test fixture path
) -> dict:
    """Create an account dict (as returned by load_accounts) for testing."""
    return {"name": name, "provider": provider, "credentials": credentials, "token": token}


class TestAccountsSyncLabelsProcessor(unittest.TestCase):
    """Tests for AccountsSyncLabelsProcessor._process_safe."""

    @patch("mail.accounts.helpers.load_accounts")
    @patch("core.yamlio.load_config")
    @patch("mail.accounts.helpers.build_provider_for_account")
    def test_process_creates_new_gmail_labels_when_applying(self, mock_build, mock_load_config, mock_load_accounts):
        mock_load_accounts.return_value = [make_account_dict(name="personal", provider="gmail")]
        mock_load_config.return_value = {"labels": [{"name": "VIP"}]}
        client = FakeGmailClient(labels=[])
        mock_build.return_value = client

        request = AccountsSyncLabelsRequest(
            config_path="/config.yaml",
            labels_path="/labels.yaml",
            dry_run=False,
        )
        processor = AccountsSyncLabelsProcessor()
        envelope = processor.process(request)

        self.assertTrue(envelope.ok())
        self.assertEqual(len(envelope.payload.synced), 1)
        info = envelope.payload.synced[0]
        self.assertEqual(info.account_name, "personal")
        self.assertEqual(info.provider, "gmail")
        self.assertEqual(info.created, 1)
        self.assertEqual(info.updated, 0)
        # Apply mode must actually create the label via the client.
        self.assertEqual(len(client.labels), 1)
        self.assertEqual(client.labels[0]["name"], "VIP")

    @patch("mail.accounts.helpers.load_accounts")
    @patch("core.yamlio.load_config")
    @patch("mail.accounts.helpers.build_provider_for_account")
    def test_process_dry_run_does_not_mutate_client(self, mock_build, mock_load_config, mock_load_accounts):
        mock_load_accounts.return_value = [make_account_dict(name="personal", provider="gmail")]
        mock_load_config.return_value = {"labels": [{"name": "VIP"}]}
        client = FakeGmailClient(labels=[])
        mock_build.return_value = client

        request = AccountsSyncLabelsRequest(
            config_path="/config.yaml",
            labels_path="/labels.yaml",
            dry_run=True,
        )
        processor = AccountsSyncLabelsProcessor()
        envelope = processor.process(request)

        self.assertTrue(envelope.ok())
        info = envelope.payload.synced[0]
        # Dry run still reports what *would* happen...
        self.assertEqual(info.created, 1)
        # ...but must not have actually created the label on the client.
        self.assertEqual(client.labels, [])

    @patch("mail.accounts.helpers.load_accounts")
    @patch("core.yamlio.load_config")
    @patch("mail.accounts.helpers.build_provider_for_account")
    def test_process_normalizes_labels_for_outlook_provider(self, mock_build, mock_load_config, mock_load_accounts):
        mock_load_accounts.return_value = [make_account_dict(name="work", provider="outlook")]
        mock_load_config.return_value = {"labels": [{"name": "Parent/Child"}]}
        client = FakeOutlookClient(categories=[])
        client.list_labels = lambda: []
        client.create_label = lambda **body: {"id": "LBL_1", **body}
        mock_build.return_value = client

        request = AccountsSyncLabelsRequest(
            config_path="/config.yaml",
            labels_path="/labels.yaml",
            dry_run=False,
        )
        processor = AccountsSyncLabelsProcessor()
        envelope = processor.process(request)

        self.assertTrue(envelope.ok())
        info = envelope.payload.synced[0]
        self.assertEqual(info.provider, "outlook")
        self.assertEqual(info.account_name, "work")
        # Normalization path must have run (created count reflects a label).
        self.assertEqual(info.created, 1)

    @patch("mail.accounts.helpers.load_accounts")
    @patch("core.yamlio.load_config")
    @patch("mail.accounts.helpers.build_provider_for_account")
    def test_process_updates_existing_label_when_fields_changed(self, mock_build, mock_load_config, mock_load_accounts):
        mock_load_accounts.return_value = [make_account_dict(name="personal", provider="gmail")]
        mock_load_config.return_value = {"labels": [{"name": "VIP", "color": {"backgroundColor": "#fff"}}]}
        client = FakeGmailClient(labels=[{"id": "LBL_1", "name": "VIP", "color": {"backgroundColor": "#000"}}])
        mock_build.return_value = client

        request = AccountsSyncLabelsRequest(
            config_path="/config.yaml",
            labels_path="/labels.yaml",
            dry_run=False,
        )
        processor = AccountsSyncLabelsProcessor()
        envelope = processor.process(request)

        info = envelope.payload.synced[0]
        self.assertEqual(info.created, 0)
        self.assertEqual(info.updated, 1)
        self.assertEqual(client.labels[0]["color"], {"backgroundColor": "#fff"})

    @patch("mail.accounts.helpers.load_accounts")
    @patch("core.yamlio.load_config")
    @patch("mail.accounts.helpers.build_provider_for_account")
    def test_process_returns_error_envelope_on_exception(self, mock_build, mock_load_config, mock_load_accounts):
        mock_load_accounts.side_effect = FileNotFoundError("Config not found")

        request = AccountsSyncLabelsRequest(config_path="/missing.yaml", labels_path="/labels.yaml")
        processor = AccountsSyncLabelsProcessor()
        envelope = processor.process(request)

        self.assertFalse(envelope.ok())
        self.assertIn("Config not found", envelope.diagnostics["message"])
        mock_build.assert_not_called()

    @patch("mail.accounts.helpers.load_accounts")
    @patch("core.yamlio.load_config")
    def test_process_filters_accounts_by_accounts_filter(self, mock_load_config, mock_load_accounts):
        mock_load_accounts.return_value = [
            make_account_dict(name="personal", provider="gmail"),
            make_account_dict(name="work", provider="gmail"),
        ]
        mock_load_config.return_value = {"labels": []}

        with patch("mail.accounts.helpers.build_provider_for_account") as mock_build:
            mock_build.return_value = FakeGmailClient(labels=[])
            request = AccountsSyncLabelsRequest(
                config_path="/config.yaml",
                labels_path="/labels.yaml",
                accounts_filter="work",
            )
            processor = AccountsSyncLabelsProcessor()
            envelope = processor.process(request)

        self.assertEqual(len(envelope.payload.synced), 1)
        self.assertEqual(envelope.payload.synced[0].account_name, "work")


class TestAccountsSyncFiltersProcessorGmail(unittest.TestCase):
    """Tests for the gmail delegation branch of AccountsSyncFiltersProcessor."""

    @patch("mail.accounts.helpers.load_accounts")
    @patch("mail.filters.commands.run_filters_sync")
    def test_process_delegates_gmail_to_run_filters_sync(self, mock_run_sync, mock_load_accounts):
        mock_load_accounts.return_value = [
            make_account_dict(  # nosec B106 - test fixture path, not a credential
                name="personal", provider="gmail", credentials="/c.json", token="/t.json"
            )
        ]

        request = AccountsSyncFiltersRequest(
            config_path="/config.yaml",
            filters_path="/filters.yaml",
            dry_run=False,
            require_forward_verified=True,
        )
        processor = AccountsSyncFiltersProcessor()
        envelope = processor.process(request)

        self.assertTrue(envelope.ok())
        info = envelope.payload.synced[0]
        self.assertEqual(info.provider, "gmail")
        self.assertEqual(info.created, -1)
        self.assertEqual(info.errors, 0)

        mock_run_sync.assert_called_once()
        called_ns = mock_run_sync.call_args.args[0]
        self.assertEqual(called_ns.config, "/filters.yaml")
        self.assertFalse(called_ns.dry_run)
        self.assertTrue(called_ns.require_forward_verified)
        self.assertFalse(called_ns.delete_missing)
        self.assertEqual(called_ns.credentials, "/c.json")
        self.assertEqual(called_ns.token, "/t.json")  # nosec B106 - test fixture path, not a credential

    @patch("mail.accounts.helpers.load_accounts")
    @patch("mail.filters.commands.run_filters_sync")
    def test_process_passes_dry_run_flag_through_to_gmail_sync(self, mock_run_sync, mock_load_accounts):
        mock_load_accounts.return_value = [make_account_dict(name="personal", provider="gmail")]

        request = AccountsSyncFiltersRequest(
            config_path="/config.yaml",
            filters_path="/filters.yaml",
            dry_run=True,
        )
        processor = AccountsSyncFiltersProcessor()
        processor.process(request)

        called_ns = mock_run_sync.call_args.args[0]
        self.assertTrue(called_ns.dry_run)


class TestAccountsSyncFiltersProcessorOutlook(unittest.TestCase):
    """Tests for the outlook direct-sync branch of AccountsSyncFiltersProcessor."""

    @patch("mail.accounts.helpers.load_accounts")
    @patch("core.yamlio.load_config")
    @patch("mail.accounts.helpers.build_client_for_account")
    def test_process_creates_new_outlook_filter_when_applying(self, mock_build, mock_load_config, mock_load_accounts):
        mock_load_accounts.return_value = [make_account_dict(name="work", provider="outlook")]
        mock_load_config.return_value = {
            "filters": [{"match": {"from": "boss@example.com"}, "action": {"add": ["VIP"]}}]
        }
        client = FakeOutlookClient(categories=[{"id": "CAT_1", "displayName": "VIP"}])
        client.list_filters = lambda: []
        client.get_label_id_map = lambda: {"VIP": "CAT_1"}
        client.create_filter = lambda criteria, action: {"id": "NEW"}
        mock_build.return_value = client

        request = AccountsSyncFiltersRequest(
            config_path="/config.yaml",
            filters_path="/filters.yaml",
            dry_run=False,
        )
        processor = AccountsSyncFiltersProcessor()
        envelope = processor.process(request)

        self.assertTrue(envelope.ok())
        info = envelope.payload.synced[0]
        self.assertEqual(info.provider, "outlook")
        self.assertEqual(info.created, 1)
        self.assertEqual(info.errors, 0)

    @patch("mail.accounts.helpers.load_accounts")
    @patch("core.yamlio.load_config")
    @patch("mail.accounts.helpers.build_client_for_account")
    def test_process_dry_run_does_not_call_create_filter(self, mock_build, mock_load_config, mock_load_accounts):
        mock_load_accounts.return_value = [make_account_dict(name="work", provider="outlook")]
        mock_load_config.return_value = {
            "filters": [{"match": {"from": "boss@example.com"}, "action": {"add": ["VIP"]}}]
        }
        client = FakeOutlookClient(categories=[{"id": "CAT_1", "displayName": "VIP"}])
        client.list_filters = lambda: []
        client.get_label_id_map = lambda: {"VIP": "CAT_1"}
        create_calls = []
        client.create_filter = lambda criteria, action: create_calls.append((criteria, action))
        mock_build.return_value = client

        request = AccountsSyncFiltersRequest(
            config_path="/config.yaml",
            filters_path="/filters.yaml",
            dry_run=True,
        )
        processor = AccountsSyncFiltersProcessor()
        envelope = processor.process(request)

        info = envelope.payload.synced[0]
        self.assertEqual(info.created, 1)
        self.assertEqual(create_calls, [])

    @patch("mail.accounts.helpers.load_accounts")
    @patch("core.yamlio.load_config")
    @patch("mail.accounts.helpers.build_client_for_account")
    def test_process_records_error_when_outlook_create_filter_raises(self, mock_build, mock_load_config, mock_load_accounts):
        mock_load_accounts.return_value = [make_account_dict(name="work", provider="outlook")]
        mock_load_config.return_value = {
            "filters": [{"match": {"from": "boss@example.com"}, "action": {"add": ["VIP"]}}]
        }
        client = FakeOutlookClient(categories=[{"id": "CAT_1", "displayName": "VIP"}])
        client.list_filters = lambda: []
        client.get_label_id_map = lambda: {"VIP": "CAT_1"}

        def _raise(criteria, action):
            raise RuntimeError("Graph API error")

        client.create_filter = _raise
        mock_build.return_value = client

        request = AccountsSyncFiltersRequest(
            config_path="/config.yaml",
            filters_path="/filters.yaml",
            dry_run=False,
        )
        processor = AccountsSyncFiltersProcessor()
        envelope = processor.process(request)

        self.assertTrue(envelope.ok())
        info = envelope.payload.synced[0]
        self.assertEqual(info.created, 0)
        self.assertEqual(info.errors, 1)


class TestAccountsSyncFiltersProcessorUnsupported(unittest.TestCase):
    """Tests for the unsupported-provider fallback branch."""

    @patch("mail.accounts.helpers.load_accounts")
    def test_process_records_unsupported_provider_without_syncing(self, mock_load_accounts):
        mock_load_accounts.return_value = [make_account_dict(name="other", provider="yahoo")]

        request = AccountsSyncFiltersRequest(config_path="/config.yaml", filters_path="/filters.yaml")
        processor = AccountsSyncFiltersProcessor()
        envelope = processor.process(request)

        self.assertTrue(envelope.ok())
        info = envelope.payload.synced[0]
        self.assertEqual(info.account_name, "other")
        self.assertEqual(info.provider, "yahoo")
        self.assertEqual(info.created, -1)
        self.assertEqual(info.errors, 0)

    @patch("mail.accounts.helpers.load_accounts")
    def test_process_treats_missing_provider_as_empty_string(self, mock_load_accounts):
        mock_load_accounts.return_value = [{"name": "no-provider"}]

        request = AccountsSyncFiltersRequest(config_path="/config.yaml", filters_path="/filters.yaml")
        processor = AccountsSyncFiltersProcessor()
        envelope = processor.process(request)

        info = envelope.payload.synced[0]
        self.assertEqual(info.provider, "")
        self.assertEqual(info.created, -1)

    @patch("mail.accounts.helpers.load_accounts")
    def test_process_returns_error_envelope_on_exception(self, mock_load_accounts):
        mock_load_accounts.side_effect = FileNotFoundError("Config not found")

        request = AccountsSyncFiltersRequest(config_path="/missing.yaml", filters_path="/filters.yaml")
        processor = AccountsSyncFiltersProcessor()
        envelope = processor.process(request)

        self.assertFalse(envelope.ok())
        self.assertIn("Config not found", envelope.diagnostics["message"])


if __name__ == "__main__":
    unittest.main()
