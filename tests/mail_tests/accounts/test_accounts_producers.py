"""Tests for AccountsResult producer classes."""

from __future__ import annotations

import unittest

from core.pipeline import ResultEnvelope
from mail.accounts.pipeline_list import (
    AccountsListResult,
    AccountInfo,
    AccountsListProducer,
)
from mail.accounts.pipeline_list_export import (
    ExportedLabelsInfo,
    AccountsExportLabelsResult,
    AccountsExportLabelsProducer,
    ExportedFiltersInfo,
    AccountsExportFiltersResult,
    AccountsExportFiltersProducer,
)
from mail.accounts.pipeline_list_plan import (
    LabelsPlanInfo,
    AccountsPlanLabelsResult,
    AccountsPlanLabelsProducer,
    FiltersPlanInfo,
    AccountsPlanFiltersResult,
    AccountsPlanFiltersProducer,
)
from mail.accounts.pipeline_list_sync import (
    SyncedLabelInfo,
    AccountsSyncLabelsResult,
    AccountsSyncLabelsProducer,
    SyncedFiltersInfo,
    AccountsSyncFiltersResult,
    AccountsSyncFiltersProducer,
)
from mail.accounts.pipeline_list_signatures import (
    ExportedSignaturesInfo,
    AccountsExportSignaturesResult,
    AccountsExportSignaturesProducer,
    SyncedSignaturesInfo,
    AccountsSyncSignaturesResult,
    AccountsSyncSignaturesProducer,
)
from tests.fixtures import capture_stdout


def make_account_info(
    name: str = "personal",
    provider: str = "gmail",
    credentials: str = "/creds.json",
    token: str = "/token.json",  # nosec B107 - test fixture path
) -> AccountInfo:
    """Create an AccountInfo for testing."""
    return AccountInfo(name=name, provider=provider, credentials=credentials, token=token)


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


class TestAccountsExportLabelsProducer(unittest.TestCase):
    """Tests for AccountsExportLabelsProducer."""

    def test_produce_items_outputs_export_info(self):
        result = AccountsExportLabelsResult(exports=[
            ExportedLabelsInfo(account_name="personal", output_path="/out/labels.yaml", label_count=5),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsExportLabelsProducer()
        with capture_stdout() as buf:
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("Exported labels for personal", output)
        self.assertIn("/out/labels.yaml", output)


class TestAccountsExportFiltersProducer(unittest.TestCase):
    """Tests for AccountsExportFiltersProducer."""

    def test_produce_items_outputs_export_info(self):
        result = AccountsExportFiltersResult(exports=[
            ExportedFiltersInfo(account_name="work", output_path="/out/filters.yaml", filter_count=7),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsExportFiltersProducer()
        with capture_stdout() as buf:
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("Exported filters for work", output)
        self.assertIn("/out/filters.yaml", output)


class TestAccountsPlanLabelsProducer(unittest.TestCase):
    """Tests for AccountsPlanLabelsProducer."""

    def test_produce_items_outputs_plan_info(self):
        result = AccountsPlanLabelsResult(plans=[
            LabelsPlanInfo(account_name="personal", provider="gmail", to_create=2, to_update=1),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsPlanLabelsProducer()
        with capture_stdout() as buf:
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("[plan-labels]", output)
        self.assertIn("personal", output)
        self.assertIn("provider=gmail", output)
        self.assertIn("create=2", output)
        self.assertIn("update=1", output)


class TestAccountsSyncLabelsProducer(unittest.TestCase):
    """Tests for AccountsSyncLabelsProducer."""

    def test_produce_items_outputs_sync_info(self):
        result = AccountsSyncLabelsResult(synced=[
            SyncedLabelInfo(account_name="personal", provider="gmail", created=3, updated=1),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsSyncLabelsProducer(dry_run=False)
        with capture_stdout() as buf:
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
        with capture_stdout() as buf:
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("would", output)


class TestAccountsPlanFiltersProducer(unittest.TestCase):
    """Tests for AccountsPlanFiltersProducer."""

    def test_produce_items_outputs_plan_info(self):
        result = AccountsPlanFiltersResult(plans=[
            FiltersPlanInfo(account_name="personal", provider="gmail", to_create=4),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsPlanFiltersProducer()
        with capture_stdout() as buf:
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
        with capture_stdout() as buf:
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("not supported", output)


class TestAccountsSyncFiltersProducer(unittest.TestCase):
    """Tests for AccountsSyncFiltersProducer."""

    def test_produce_items_outputs_sync_info(self):
        result = AccountsSyncFiltersResult(synced=[
            SyncedFiltersInfo(account_name="personal", provider="outlook", created=2, errors=0),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsSyncFiltersProducer(dry_run=False)
        with capture_stdout() as buf:
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
        with capture_stdout() as buf:
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("(delegated)", output)


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
        with capture_stdout() as buf:
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("Exported signatures for personal", output)


class TestAccountsSyncSignaturesProducer(unittest.TestCase):
    """Tests for AccountsSyncSignaturesProducer."""

    def test_produce_items_outputs_delegated_status(self):
        result = AccountsSyncSignaturesResult(synced=[
            SyncedSignaturesInfo(account_name="personal", provider="gmail", status="delegated"),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsSyncSignaturesProducer()
        with capture_stdout() as buf:
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
        with capture_stdout() as buf:
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("wrote guidance", output)

    def test_produce_items_outputs_generic_status(self):
        result = AccountsSyncSignaturesResult(synced=[
            SyncedSignaturesInfo(account_name="other", provider="yahoo", status="unsupported"),
        ])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = AccountsSyncSignaturesProducer()
        with capture_stdout() as buf:
            producer.produce(envelope)
        output = buf.getvalue()
        self.assertIn("status=unsupported", output)


if __name__ == "__main__":
    unittest.main()
