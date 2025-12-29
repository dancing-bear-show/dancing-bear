"""Tests for mail/accounts/pipeline.py pipeline components."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core.pipeline import ResultEnvelope
from mail.accounts.pipeline import (
    # Shared abstractions
    SimpleConsumer,
    AccountsResultProducer,
    canonicalize_filter,
    # List accounts
    AccountsListRequest,
    AccountInfo,
    AccountsListResult,
    AccountsListRequestConsumer,
    AccountsListProcessor,
    AccountsListProducer,)
from tests.mail_tests.fixtures import capture_stdout


# -----------------------------------------------------------------------------
# Account factories - reusable across tests
# -----------------------------------------------------------------------------


def make_account_info(
    name: str = "personal",
    provider: str = "gmail",
    credentials: str = "/creds.json",
    token: str = "/token.json",  # nosec B106 - test fixture path
) -> AccountInfo:
    """Create an AccountInfo for testing."""
    return AccountInfo(name=name, provider=provider, credentials=credentials, token=token)


def make_account_dict(
    name: str = "personal",
    provider: str = "gmail",
    credentials: str = "/creds.json",
    token: str = "/token.json",  # nosec B106 - test fixture path
) -> dict:
    """Create an account dict (as returned by load_accounts) for testing."""
    return {"name": name, "provider": provider, "credentials": credentials, "token": token}


# Re-import pipeline classes that were cut off by the edit
from mail.accounts.pipeline import (
    # Export labels
    AccountsExportLabelsRequest,
    ExportedLabelsInfo,
    AccountsExportLabelsResult,
    AccountsExportLabelsProcessor,
    AccountsExportLabelsProducer,
    # Export filters
    AccountsExportFiltersRequest,
    ExportedFiltersInfo,
    AccountsExportFiltersResult,
    AccountsExportFiltersProcessor,
    AccountsExportFiltersProducer,
    # Plan labels
    AccountsPlanLabelsRequest,
    LabelsPlanInfo,
    AccountsPlanLabelsResult,
    AccountsPlanLabelsProcessor,
    AccountsPlanLabelsProducer,
    # Sync labels
    AccountsSyncLabelsRequest,
    SyncedLabelInfo,
    AccountsSyncLabelsResult,
    AccountsSyncLabelsProcessor,
    AccountsSyncLabelsProducer,
    # Plan filters
    AccountsPlanFiltersRequest,
    FiltersPlanInfo,
    AccountsPlanFiltersResult,
    AccountsPlanFiltersProcessor,
    AccountsPlanFiltersProducer,
    # Sync filters
    AccountsSyncFiltersRequest,
    SyncedFiltersInfo,
    AccountsSyncFiltersResult,
    AccountsSyncFiltersProcessor,
    AccountsSyncFiltersProducer,
    # Export signatures
    AccountsExportSignaturesRequest,
    ExportedSignaturesInfo,
    AccountsExportSignaturesResult,
    AccountsExportSignaturesProcessor,
    AccountsExportSignaturesProducer,
    # Sync signatures
    AccountsSyncSignaturesRequest,
    SyncedSignaturesInfo,
    AccountsSyncSignaturesResult,
    AccountsSyncSignaturesProcessor,
    AccountsSyncSignaturesProducer,
)


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
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Error: Something went wrong", buf.getvalue())

    def test_produce_calls_produce_items_on_success(self):
        class TestProducer(AccountsResultProducer[str]):
            def _produce_items(self, payload: str) -> None:
                print(f"Payload: {payload}")

        producer = TestProducer()
        envelope = ResultEnvelope(status="success", payload="test data")
        buf = io.StringIO()
        with redirect_stdout(buf):
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
        info = AccountInfo(
            name="personal",
            provider="gmail",
            credentials="/creds.json",
            token="/token.json",  # nosec B106 - test fixture path, not actual token
        )
        self.assertEqual(info.name, "personal")
        self.assertEqual(info.provider, "gmail")

    def test_accounts_list_result_default(self):
        result = AccountsListResult()
        self.assertEqual(result.accounts, [])

    def test_accounts_list_result_with_accounts(self):
        info = AccountInfo(name="test", provider="gmail", credentials="", token="")  # nosec B106
        result = AccountsListResult(accounts=[info])
        self.assertEqual(len(result.accounts), 1)


class TestAccountsListProcessor(unittest.TestCase):
    """Tests for AccountsListProcessor."""

    @patch("mail.accounts.helpers.load_accounts")
    def test_process_returns_success_envelope(self, mock_load):
        mock_load.return_value = [
            {"name": "personal", "provider": "gmail", "credentials": "/c.json", "token": "/t.json"},
            {"name": "work", "provider": "outlook", "credentials": "/c2.json", "token": "/t2.json"},
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
        self.assertEqual(envelope.payload.accounts[0].name, "<noname>")
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
            AccountInfo(name="personal", provider="gmail", credentials="/c.json", token="/t.json"),  # nosec B106
            AccountInfo(name="work", provider="outlook", credentials="/c2.json", token="/t2.json"),  # nosec B106
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsListProducer()
        buf = io.StringIO()
        with redirect_stdout(buf):
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


class TestAccountsExportLabelsProducer(unittest.TestCase):
    """Tests for AccountsExportLabelsProducer."""

    def test_produce_items_outputs_export_info(self):
        result = AccountsExportLabelsResult(exports=[
            ExportedLabelsInfo(account_name="personal", output_path="/out/labels.yaml", label_count=5),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsExportLabelsProducer()
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("Exported labels for personal", output)
        self.assertIn("/out/labels.yaml", output)


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


class TestAccountsExportFiltersProducer(unittest.TestCase):
    """Tests for AccountsExportFiltersProducer."""

    def test_produce_items_outputs_export_info(self):
        result = AccountsExportFiltersResult(exports=[
            ExportedFiltersInfo(account_name="work", output_path="/out/filters.yaml", filter_count=7),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsExportFiltersProducer()
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("Exported filters for work", output)
        self.assertIn("/out/filters.yaml", output)


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


class TestAccountsPlanLabelsProducer(unittest.TestCase):
    """Tests for AccountsPlanLabelsProducer."""

    def test_produce_items_outputs_plan_info(self):
        result = AccountsPlanLabelsResult(plans=[
            LabelsPlanInfo(account_name="personal", provider="gmail", to_create=2, to_update=1),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsPlanLabelsProducer()
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("[plan-labels]", output)
        self.assertIn("personal", output)
        self.assertIn("provider=gmail", output)
        self.assertIn("create=2", output)
        self.assertIn("update=1", output)


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


class TestAccountsSyncLabelsProducer(unittest.TestCase):
    """Tests for AccountsSyncLabelsProducer."""

    def test_produce_items_outputs_sync_info(self):
        result = AccountsSyncLabelsResult(synced=[
            SyncedLabelInfo(account_name="personal", provider="gmail", created=3, updated=1),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsSyncLabelsProducer(dry_run=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("[labels sync]", output)
        self.assertIn("personal", output)
        self.assertIn("created=3", output)

    def test_produce_items_includes_would_for_dry_run(self):
        result = AccountsSyncLabelsResult(synced=[
            SyncedLabelInfo(account_name="personal", provider="gmail", created=3, updated=1),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsSyncLabelsProducer(dry_run=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("would", output)


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


class TestAccountsPlanFiltersProducer(unittest.TestCase):
    """Tests for AccountsPlanFiltersProducer."""

    def test_produce_items_outputs_plan_info(self):
        result = AccountsPlanFiltersResult(plans=[
            FiltersPlanInfo(account_name="personal", provider="gmail", to_create=4),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsPlanFiltersProducer()
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("[plan-filters]", output)
        self.assertIn("personal", output)
        self.assertIn("create=4", output)

    def test_produce_items_outputs_unsupported_for_negative(self):
        result = AccountsPlanFiltersResult(plans=[
            FiltersPlanInfo(account_name="other", provider="yahoo", to_create=-1),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsPlanFiltersProducer()
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("not supported", output)


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


class TestAccountsSyncFiltersProducer(unittest.TestCase):
    """Tests for AccountsSyncFiltersProducer."""

    def test_produce_items_outputs_sync_info(self):
        result = AccountsSyncFiltersResult(synced=[
            SyncedFiltersInfo(account_name="personal", provider="outlook", created=2, errors=0),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsSyncFiltersProducer(dry_run=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("[filters sync]", output)
        self.assertIn("personal", output)
        self.assertIn("created=2", output)

    def test_produce_items_shows_delegated_for_negative(self):
        result = AccountsSyncFiltersResult(synced=[
            SyncedFiltersInfo(account_name="personal", provider="gmail", created=-1, errors=0),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsSyncFiltersProducer(dry_run=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("(delegated)", output)


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


class TestAccountsExportSignaturesProducer(unittest.TestCase):
    """Tests for AccountsExportSignaturesProducer."""

    def test_produce_items_outputs_export_info(self):
        result = AccountsExportSignaturesResult(exports=[
            ExportedSignaturesInfo(
                account_name="personal",
                provider="gmail",
                output_path="/out/sigs.yaml",
                signature_count=1,
            ),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsExportSignaturesProducer()
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("Exported signatures for personal", output)


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


class TestAccountsSyncSignaturesProducer(unittest.TestCase):
    """Tests for AccountsSyncSignaturesProducer."""

    def test_produce_items_outputs_delegated_status(self):
        result = AccountsSyncSignaturesResult(synced=[
            SyncedSignaturesInfo(account_name="personal", provider="gmail", status="delegated"),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsSyncSignaturesProducer()
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("[signatures sync]", output)
        self.assertIn("(delegated)", output)

    def test_produce_items_outputs_wrote_guidance_status(self):
        result = AccountsSyncSignaturesResult(synced=[
            SyncedSignaturesInfo(account_name="work", provider="outlook", status="wrote_guidance"),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsSyncSignaturesProducer()
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("wrote guidance", output)

    def test_produce_items_outputs_generic_status(self):
        result = AccountsSyncSignaturesResult(synced=[
            SyncedSignaturesInfo(account_name="other", provider="yahoo", status="unsupported"),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsSyncSignaturesProducer()
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("status=unsupported", output)


class TestAccountsListRequestConsumerAlias(unittest.TestCase):
    """Tests for AccountsListRequestConsumer type alias."""

    def test_alias_works_as_simple_consumer(self):
        request = AccountsListRequest(config_path="/config.yaml")
        consumer = AccountsListRequestConsumer(request)
        result = consumer.consume()
        self.assertEqual(result.config_path, "/config.yaml")


if __name__ == "__main__":
    unittest.main()
