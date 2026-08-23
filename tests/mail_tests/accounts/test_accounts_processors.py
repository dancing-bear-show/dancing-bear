"""Tests for accounts pipeline processors, dataclasses, and consumer."""

from __future__ import annotations

import argparse
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from core.pipeline import ResultEnvelope
from mail.accounts.pipeline_auth import (
    SimpleConsumer,
    AccountsResultProducer,
    canonicalize_filter,
)
from mail.accounts.pipeline_list import (
    AccountsListRequest,
    AccountInfo,
    AccountsListResult,
    AccountsListRequestConsumer,
    AccountsListProcessor,
    AccountsListProducer,
)
from mail.accounts.pipeline_list_export import (
    AccountsExportLabelsRequest,
    ExportedLabelsInfo,
    AccountsExportFiltersRequest,
    ExportedFiltersInfo,
)
from mail.accounts.pipeline_list_plan import (
    AccountsPlanLabelsRequest,
    LabelsPlanInfo,
    AccountsPlanFiltersRequest,
    FiltersPlanInfo,
)
from mail.accounts.pipeline_list_sync import (
    AccountsSyncLabelsRequest,
    SyncedLabelInfo,
    AccountsSyncFiltersRequest,
    SyncedFiltersInfo,
)
from mail.accounts.pipeline_list_signatures import (
    AccountsExportSignaturesRequest,
    ExportedSignaturesInfo,
    AccountsExportSignaturesProcessor,
    AccountsSyncSignaturesRequest,
    SyncedSignaturesInfo,
    AccountsSyncSignaturesProcessor,
)
from tests.fixtures import capture_stdout


# -----------------------------------------------------------------------------
# Account factories - reusable across tests
# -----------------------------------------------------------------------------


def make_account_info(
    name: str = "personal",
    provider: str = "gmail",
    credentials: str = "/creds.json",
    token: str = "/token.json",  # nosec B107 - test fixture path
) -> AccountInfo:
    """Create an AccountInfo for testing."""
    return AccountInfo(name=name, provider=provider, credentials=credentials, token=token)


def make_account_dict(
    name: str = "personal",
    provider: str = "gmail",
    credentials: str = "/creds.json",
    token: str = "/token.json",  # nosec B107 - test fixture path
) -> dict:
    """Create an account dict (as returned by load_accounts) for testing."""
    return {"name": name, "provider": provider, "credentials": credentials, "token": token}


class TestSimpleConsumer(unittest.TestCase):
    """Tests for SimpleConsumer generic wrapper."""

    def test_consume_returns_request(self):
        request = {"key": "value"}
        consumer = SimpleConsumer(request)
        self.assertEqual(consumer.consume(), request)

    def test_consume_returns_typed_request(self):
        request = AccountsListRequest(config_path="/path/to/config.yaml")
        consumer = SimpleConsumer[AccountsListRequest](request)
        result = consumer.consume()
        self.assertIsInstance(result, AccountsListRequest)
        self.assertEqual(result.config_path, "/path/to/config.yaml")


class TestAccountsResultProducer(unittest.TestCase):
    """Tests for AccountsResultProducer base class."""

    def test_produce_prints_error_on_failure(self):
        class TestProducer(AccountsResultProducer[str]):
            def _produce_items(self, payload: str) -> None:
                print(f"Items: {payload}")

        producer = TestProducer()
        envelope = ResultEnvelope(
            status="error",
            diagnostics={"message": "Something went wrong"},
        )
        with capture_stdout() as buf:
            producer.produce(envelope)
        self.assertIn("Error: Something went wrong", buf.getvalue())

    def test_produce_calls_produce_items_on_success(self):
        class TestProducer(AccountsResultProducer[str]):
            def _produce_items(self, payload: str) -> None:
                print(f"Payload: {payload}")

        producer = TestProducer()
        envelope = ResultEnvelope(status="success", payload="test data")
        with capture_stdout() as buf:
            producer.produce(envelope)
        self.assertIn("Payload: test data", buf.getvalue())

    def test_produce_items_raises_not_implemented(self):
        producer = AccountsResultProducer()
        with self.assertRaises(NotImplementedError):
            producer._produce_items("test")


class TestCanonicalizeFilter(unittest.TestCase):
    """Tests for canonicalize_filter helper function."""

    def test_canonicalize_with_criteria_key(self):
        f = {
            "criteria": {"from": "test@example.com", "subject": "Hello"},
            "action": {"addLabelIds": ["LBL_1", "LBL_2"]},
        }
        result = canonicalize_filter(f)
        self.assertIn("'from': 'test@example.com'", result)
        self.assertIn("'subject': 'Hello'", result)
        self.assertIn("'add': ('LBL_1', 'LBL_2')", result)

    def test_canonicalize_with_match_key(self):
        f = {
            "match": {"from": "test@example.com"},
            "action": {"add": ["Label1"]},
        }
        result = canonicalize_filter(f)
        self.assertIn("'from': 'test@example.com'", result)
        self.assertIn("'add': ('Label1',)", result)

    def test_canonicalize_with_forward_action(self):
        f = {
            "criteria": {"from": "test@example.com"},
            "action": {"forward": "forward@example.com"},
        }
        result = canonicalize_filter(f)
        self.assertIn("'forward': 'forward@example.com'", result)

    def test_canonicalize_empty_filter(self):
        f = {}
        result = canonicalize_filter(f)
        self.assertIn("'from': None", result)
        self.assertIn("'add': ()", result)

    def test_canonicalize_sorts_add_ids(self):
        f = {
            "action": {"addLabelIds": ["Z", "A", "M"]},
        }
        result = canonicalize_filter(f)
        self.assertIn("'add': ('A', 'M', 'Z')", result)


class TestAccountsListDataclasses(unittest.TestCase):
    """Tests for AccountsList dataclasses."""

    def test_accounts_list_request(self):
        req = AccountsListRequest(config_path="/config.yaml")
        self.assertEqual(req.config_path, "/config.yaml")

    def test_account_info(self):
        info = make_account_info()
        self.assertEqual(info.name, "personal")
        self.assertEqual(info.provider, "gmail")

    def test_accounts_list_result_default(self):
        result = AccountsListResult()
        self.assertEqual(result.accounts, [])

    def test_accounts_list_result_with_accounts(self):
        info = make_account_info(name="test")
        result = AccountsListResult(accounts=[info])
        self.assertEqual(len(result.accounts), 1)


class TestAccountsListProcessor(unittest.TestCase):
    """Tests for AccountsListProcessor."""

    @patch("mail.accounts.helpers.load_accounts")
    def test_process_returns_success_envelope(self, mock_load):
        mock_load.return_value = [
            make_account_dict(name="personal", provider="gmail"),
            make_account_dict(name="work", provider="outlook"),
        ]
        request = AccountsListRequest(config_path="/config.yaml")
        processor = AccountsListProcessor()
        envelope = processor.process(request)

        self.assertTrue(envelope.ok())
        self.assertEqual(len(envelope.payload.accounts), 2)
        self.assertEqual(envelope.payload.accounts[0].name, "personal")
        self.assertEqual(envelope.payload.accounts[1].provider, "outlook")

    @patch("mail.accounts.helpers.load_accounts")
    def test_process_handles_missing_fields(self, mock_load):
        mock_load.return_value = [{}]
        request = AccountsListRequest(config_path="/config.yaml")
        processor = AccountsListProcessor()
        envelope = processor.process(request)

        self.assertTrue(envelope.ok())
        self.assertEqual(envelope.payload.accounts[0].name, "account")
        self.assertEqual(envelope.payload.accounts[0].provider, "")

    @patch("mail.accounts.helpers.load_accounts")
    def test_process_returns_error_on_exception(self, mock_load):
        mock_load.side_effect = FileNotFoundError("Config not found")
        request = AccountsListRequest(config_path="/missing.yaml")
        processor = AccountsListProcessor()
        envelope = processor.process(request)

        self.assertFalse(envelope.ok())
        self.assertIn("Config not found", envelope.diagnostics["message"])


class TestAccountsListProducer(unittest.TestCase):
    """Tests for AccountsListProducer."""

    def test_produce_items_outputs_formatted_accounts(self):
        result = AccountsListResult(accounts=[
            make_account_info(name="personal", provider="gmail"),
            make_account_info(name="work", provider="outlook"),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsListProducer()
        with capture_stdout() as buf:
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("personal", output)
        self.assertIn("provider=gmail", output)
        self.assertIn("work", output)
        self.assertIn("provider=outlook", output)


class TestAccountsExportLabelsDataclasses(unittest.TestCase):
    """Tests for AccountsExportLabels dataclasses."""

    def test_export_labels_request(self):
        req = AccountsExportLabelsRequest(
            config_path="/config.yaml",
            out_dir="/output",
            accounts_filter=["personal"],
        )
        self.assertEqual(req.config_path, "/config.yaml")
        self.assertEqual(req.accounts_filter, ["personal"])

    def test_exported_labels_info(self):
        info = ExportedLabelsInfo(
            account_name="personal",
            output_path="/out/labels.yaml",
            label_count=10,
        )
        self.assertEqual(info.label_count, 10)


class TestAccountsExportFiltersDataclasses(unittest.TestCase):
    """Tests for AccountsExportFilters dataclasses."""

    def test_export_filters_request(self):
        req = AccountsExportFiltersRequest(
            config_path="/config.yaml",
            out_dir="/output",
        )
        self.assertEqual(req.config_path, "/config.yaml")
        self.assertIsNone(req.accounts_filter)

    def test_exported_filters_info(self):
        info = ExportedFiltersInfo(
            account_name="work",
            output_path="/out/filters.yaml",
            filter_count=3,
        )
        self.assertEqual(info.filter_count, 3)


class TestAccountsPlanLabelsDataclasses(unittest.TestCase):
    """Tests for AccountsPlanLabels dataclasses."""

    def test_plan_labels_request(self):
        req = AccountsPlanLabelsRequest(
            config_path="/config.yaml",
            labels_path="/labels.yaml",
        )
        self.assertEqual(req.labels_path, "/labels.yaml")

    def test_labels_plan_info(self):
        info = LabelsPlanInfo(
            account_name="personal",
            provider="gmail",
            to_create=3,
            to_update=1,
        )
        self.assertEqual(info.to_create, 3)
        self.assertEqual(info.to_update, 1)


class TestAccountsSyncLabelsDataclasses(unittest.TestCase):
    """Tests for AccountsSyncLabels dataclasses."""

    def test_sync_labels_request(self):
        req = AccountsSyncLabelsRequest(
            config_path="/config.yaml",
            labels_path="/labels.yaml",
            dry_run=True,
        )
        self.assertTrue(req.dry_run)

    def test_synced_label_info(self):
        info = SyncedLabelInfo(
            account_name="personal",
            provider="gmail",
            created=5,
            updated=2,
        )
        self.assertEqual(info.created, 5)


class TestAccountsPlanFiltersDataclasses(unittest.TestCase):
    """Tests for AccountsPlanFilters dataclasses."""

    def test_plan_filters_request(self):
        req = AccountsPlanFiltersRequest(
            config_path="/config.yaml",
            filters_path="/filters.yaml",
        )
        self.assertEqual(req.filters_path, "/filters.yaml")

    def test_filters_plan_info(self):
        info = FiltersPlanInfo(
            account_name="personal",
            provider="gmail",
            to_create=5,
        )
        self.assertEqual(info.to_create, 5)


class TestAccountsSyncFiltersDataclasses(unittest.TestCase):
    """Tests for AccountsSyncFilters dataclasses."""

    def test_sync_filters_request(self):
        req = AccountsSyncFiltersRequest(
            config_path="/config.yaml",
            filters_path="/filters.yaml",
            dry_run=True,
            require_forward_verified=True,
        )
        self.assertTrue(req.dry_run)
        self.assertTrue(req.require_forward_verified)

    def test_synced_filters_info(self):
        info = SyncedFiltersInfo(
            account_name="personal",
            provider="gmail",
            created=3,
            errors=1,
        )
        self.assertEqual(info.created, 3)
        self.assertEqual(info.errors, 1)


class TestAccountsExportSignaturesDataclasses(unittest.TestCase):
    """Tests for AccountsExportSignatures dataclasses."""

    def test_export_signatures_request(self):
        req = AccountsExportSignaturesRequest(
            config_path="/config.yaml",
            out_dir="/output",
        )
        self.assertEqual(req.out_dir, "/output")

    def test_exported_signatures_info(self):
        info = ExportedSignaturesInfo(
            account_name="personal",
            provider="gmail",
            output_path="/out/sigs.yaml",
            signature_count=2,
        )
        self.assertEqual(info.signature_count, 2)


class TestAccountsSyncSignaturesDataclasses(unittest.TestCase):
    """Tests for AccountsSyncSignatures dataclasses."""

    def test_sync_signatures_request(self):
        req = AccountsSyncSignaturesRequest(
            config_path="/config.yaml",
            send_as="user@example.com",
            dry_run=True,
        )
        self.assertEqual(req.send_as, "user@example.com")
        self.assertTrue(req.dry_run)

    def test_synced_signatures_info(self):
        info = SyncedSignaturesInfo(
            account_name="personal",
            provider="gmail",
            status="delegated",
        )
        self.assertEqual(info.status, "delegated")


class TestAccountsExportSignaturesProcessor(unittest.TestCase):
    """Tests for AccountsExportSignaturesProcessor._process_safe and its helpers."""

    @patch("mail.accounts.helpers.build_provider_for_account")
    @patch("mail.accounts.helpers.iter_accounts")
    @patch("mail.accounts.helpers.load_accounts")
    def test_process_exports_gmail_signatures_with_primary(
        self, mock_load, mock_iter, mock_build
    ):
        acct = make_account_dict(name="personal", provider="gmail")
        mock_load.return_value = [acct]
        mock_iter.return_value = [acct]

        mock_client = MagicMock()
        mock_client.list_signatures.return_value = [
            {"sendAsEmail": "a@example.com", "isPrimary": False, "signature": "<p>secondary</p>"},
            {"sendAsEmail": "b@example.com", "isPrimary": True, "signature": "<p>primary</p>"},
        ]
        mock_build.return_value = mock_client

        with TemporaryDirectory() as tmpdir:
            request = AccountsExportSignaturesRequest(config_path="/config.yaml", out_dir=tmpdir)
            processor = AccountsExportSignaturesProcessor()
            envelope = processor.process(request)

            self.assertTrue(envelope.ok())
            result = envelope.unwrap()
            self.assertEqual(len(result.exports), 1)
            export = result.exports[0]
            self.assertEqual(export.account_name, "personal")
            self.assertEqual(export.provider, "gmail")
            self.assertEqual(export.signature_count, 2)

            mock_client.authenticate.assert_called_once()
            asset_path = f"{tmpdir}/personal_assets/ios_signature.html"
            with open(asset_path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "<p>primary</p>")

    @patch("mail.accounts.helpers.build_provider_for_account")
    @patch("mail.accounts.helpers.iter_accounts")
    @patch("mail.accounts.helpers.load_accounts")
    def test_process_exports_gmail_signatures_no_primary(
        self, mock_load, mock_iter, mock_build
    ):
        """No isPrimary signature means no default_html/ios asset gets written."""
        acct = make_account_dict(name="personal", provider="gmail")
        mock_load.return_value = [acct]
        mock_iter.return_value = [acct]

        mock_client = MagicMock()
        mock_client.list_signatures.return_value = [
            {"sendAsEmail": "a@example.com", "isPrimary": False, "signature": "<p>secondary</p>"},
        ]
        mock_build.return_value = mock_client

        with TemporaryDirectory() as tmpdir:
            request = AccountsExportSignaturesRequest(config_path="/config.yaml", out_dir=tmpdir)
            processor = AccountsExportSignaturesProcessor()
            envelope = processor.process(request)

            self.assertTrue(envelope.ok())
            export = envelope.unwrap().exports[0]
            self.assertEqual(export.signature_count, 1)
            asset_path = Path(tmpdir) / "personal_assets" / "ios_signature.html"
            self.assertFalse(asset_path.exists())

    @patch("mail.accounts.helpers.iter_accounts")
    @patch("mail.accounts.helpers.load_accounts")
    def test_process_exports_outlook_writes_guidance(self, mock_load, mock_iter):
        acct = make_account_dict(name="work", provider="outlook")
        mock_load.return_value = [acct]
        mock_iter.return_value = [acct]

        with TemporaryDirectory() as tmpdir:
            request = AccountsExportSignaturesRequest(config_path="/config.yaml", out_dir=tmpdir)
            processor = AccountsExportSignaturesProcessor()
            envelope = processor.process(request)

            self.assertTrue(envelope.ok())
            export = envelope.unwrap().exports[0]
            self.assertEqual(export.provider, "outlook")
            self.assertEqual(export.signature_count, 0)
            readme_path = f"{tmpdir}/work_assets/OUTLOOK_README.txt"
            with open(readme_path, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("Microsoft Graph", content)

    @patch("mail.accounts.helpers.iter_accounts")
    @patch("mail.accounts.helpers.load_accounts")
    def test_process_exports_unsupported_provider_zero_count(self, mock_load, mock_iter):
        acct = make_account_dict(name="other", provider="yahoo")
        mock_load.return_value = [acct]
        mock_iter.return_value = [acct]

        with TemporaryDirectory() as tmpdir:
            request = AccountsExportSignaturesRequest(config_path="/config.yaml", out_dir=tmpdir)
            processor = AccountsExportSignaturesProcessor()
            envelope = processor.process(request)

            self.assertTrue(envelope.ok())
            export = envelope.unwrap().exports[0]
            self.assertEqual(export.provider, "yahoo")
            self.assertEqual(export.signature_count, 0)

    @patch("mail.accounts.helpers.load_accounts")
    def test_process_returns_error_envelope_on_exception(self, mock_load):
        mock_load.side_effect = FileNotFoundError("missing config")
        request = AccountsExportSignaturesRequest(config_path="/missing.yaml", out_dir="/out")
        processor = AccountsExportSignaturesProcessor()
        envelope = processor.process(request)

        self.assertFalse(envelope.ok())
        self.assertIn("missing config", envelope.diagnostics["message"])


class TestAccountsSyncSignaturesProcessor(unittest.TestCase):
    """Tests for AccountsSyncSignaturesProcessor._process_safe and its helpers."""

    @patch("mail.signatures.commands.run_signatures_sync")
    @patch("mail.accounts.helpers.iter_accounts")
    @patch("mail.accounts.helpers.load_accounts")
    def test_process_delegates_gmail_sync(self, mock_load, mock_iter, mock_run_sync):
        acct = make_account_dict(name="personal", provider="gmail", credentials="/c.json", token="/t.json")  # nosec B106 - test fixture path, not a credential
        mock_load.return_value = [acct]
        mock_iter.return_value = [acct]

        request = AccountsSyncSignaturesRequest(
            config_path="/config.yaml", send_as="a@example.com", dry_run=True
        )
        processor = AccountsSyncSignaturesProcessor()
        envelope = processor.process(request)

        self.assertTrue(envelope.ok())
        result = envelope.unwrap()
        self.assertEqual(len(result.synced), 1)
        self.assertEqual(result.synced[0].account_name, "personal")
        self.assertEqual(result.synced[0].provider, "gmail")
        self.assertEqual(result.synced[0].status, "delegated")

        mock_run_sync.assert_called_once()
        ns = mock_run_sync.call_args[0][0]
        self.assertIsInstance(ns, argparse.Namespace)
        self.assertEqual(ns.credentials, "/c.json")
        self.assertEqual(ns.token, "/t.json")
        self.assertEqual(ns.config, "/config.yaml")
        self.assertEqual(ns.send_as, "a@example.com")
        self.assertTrue(ns.dry_run)

    @patch("mail.accounts.helpers.iter_accounts")
    @patch("mail.accounts.helpers.load_accounts")
    def test_process_writes_outlook_guidance(self, mock_load, mock_iter):
        acct = make_account_dict(name="work", provider="outlook")
        mock_load.return_value = [acct]
        mock_iter.return_value = [acct]

        cwd = os.getcwd()
        with TemporaryDirectory() as tmpdir:
            try:
                os.chdir(tmpdir)
                request = AccountsSyncSignaturesRequest(config_path="/config.yaml")
                processor = AccountsSyncSignaturesProcessor()
                envelope = processor.process(request)
            finally:
                os.chdir(cwd)

            self.assertTrue(envelope.ok())
            result = envelope.unwrap()
            self.assertEqual(len(result.synced), 1)
            self.assertEqual(result.synced[0].provider, "outlook")
            self.assertEqual(result.synced[0].status, "wrote_guidance")
            self.assertTrue(
                (Path(tmpdir) / "signatures_assets" / "OUTLOOK_README.txt").exists()
            )

    @patch("mail.accounts.helpers.iter_accounts")
    @patch("mail.accounts.helpers.load_accounts")
    def test_process_marks_unsupported_provider(self, mock_load, mock_iter):
        acct = make_account_dict(name="other", provider="yahoo")
        mock_load.return_value = [acct]
        mock_iter.return_value = [acct]

        request = AccountsSyncSignaturesRequest(config_path="/config.yaml")
        processor = AccountsSyncSignaturesProcessor()
        envelope = processor.process(request)

        self.assertTrue(envelope.ok())
        result = envelope.unwrap()
        self.assertEqual(len(result.synced), 1)
        self.assertEqual(result.synced[0].account_name, "other")
        self.assertEqual(result.synced[0].provider, "yahoo")
        self.assertEqual(result.synced[0].status, "unsupported")

    @patch("mail.accounts.helpers.load_accounts")
    def test_process_returns_error_envelope_on_exception(self, mock_load):
        mock_load.side_effect = FileNotFoundError("missing config")
        request = AccountsSyncSignaturesRequest(config_path="/missing.yaml")
        processor = AccountsSyncSignaturesProcessor()
        envelope = processor.process(request)

        self.assertFalse(envelope.ok())
        self.assertIn("missing config", envelope.diagnostics["message"])


class TestAccountsListRequestConsumerAlias(unittest.TestCase):
    """Tests for AccountsListRequestConsumer type alias."""

    def test_alias_works_as_simple_consumer(self):
        request = AccountsListRequest(config_path="/config.yaml")
        consumer = AccountsListRequestConsumer(request)
        result = consumer.consume()
        self.assertEqual(result.config_path, "/config.yaml")


if __name__ == "__main__":
    unittest.main()
