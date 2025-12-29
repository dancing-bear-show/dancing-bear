"""Tests for mail/accounts/commands.py accounts command orchestration."""

import unittest
from unittest.mock import MagicMock, patch

from core.pipeline import ResultEnvelope
from mail.accounts.commands import (
    run_accounts_list,
    run_accounts_export_labels,
    run_accounts_sync_labels,
    run_accounts_export_filters,
    run_accounts_sync_filters,
    run_accounts_plan_labels,
    run_accounts_plan_filters,
    run_accounts_export_signatures,
    run_accounts_sync_signatures,
)
from tests.mail_tests.fixtures import make_args as _make_args


def make_args(**kwargs):
    """Create args namespace with accounts-specific defaults."""
    defaults = {
        "config": "/path/to/config.yaml",
        "out_dir": "/tmp/out",
        "labels": "/path/to/labels.yaml",
        "filters": "/path/to/filters.yaml",
        "accounts": None,
        "dry_run": False,
        "require_forward_verified": False,
        "send_as": None,
    }
    defaults.update(kwargs)
    return _make_args(**defaults)


class TestRunAccountsList(unittest.TestCase):
    """Tests for run_accounts_list function."""

    @patch("mail.accounts.commands.AccountsListProducer")
    @patch("mail.accounts.commands.AccountsListProcessor")
    @patch("mail.accounts.commands.AccountsListRequestConsumer")
    @patch("mail.accounts.commands.AccountsListRequest")
    def test_returns_zero_on_success(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = MagicMock(spec=ResultEnvelope)
        mock_envelope.ok.return_value = True
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args()
        result = run_accounts_list(args)

        self.assertEqual(result, 0)
        mock_producer.return_value.produce.assert_called_once_with(mock_envelope)

    @patch("mail.accounts.commands.AccountsListProducer")
    @patch("mail.accounts.commands.AccountsListProcessor")
    @patch("mail.accounts.commands.AccountsListRequestConsumer")
    @patch("mail.accounts.commands.AccountsListRequest")
    def test_returns_one_on_failure(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = MagicMock(spec=ResultEnvelope)
        mock_envelope.ok.return_value = False
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args()
        result = run_accounts_list(args)

        self.assertEqual(result, 1)


class TestRunAccountsExportLabels(unittest.TestCase):
    """Tests for run_accounts_export_labels function."""

    @patch("mail.accounts.commands.AccountsExportLabelsProducer")
    @patch("mail.accounts.commands.AccountsExportLabelsProcessor")
    @patch("mail.accounts.commands.AccountsExportLabelsRequestConsumer")
    @patch("mail.accounts.commands.AccountsExportLabelsRequest")
    def test_returns_zero_on_success(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = MagicMock(spec=ResultEnvelope)
        mock_envelope.ok.return_value = True
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args(out_dir="/output")
        result = run_accounts_export_labels(args)

        self.assertEqual(result, 0)
        mock_request.assert_called_once()

    @patch("mail.accounts.commands.AccountsExportLabelsProducer")
    @patch("mail.accounts.commands.AccountsExportLabelsProcessor")
    @patch("mail.accounts.commands.AccountsExportLabelsRequestConsumer")
    @patch("mail.accounts.commands.AccountsExportLabelsRequest")
    def test_passes_accounts_filter(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = MagicMock(spec=ResultEnvelope)
        mock_envelope.ok.return_value = True
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args(accounts=["personal", "work"])
        run_accounts_export_labels(args)

        call_kwargs = mock_request.call_args
        self.assertEqual(call_kwargs.kwargs.get("accounts_filter"), ["personal", "work"])


class TestRunAccountsSyncLabels(unittest.TestCase):
    """Tests for run_accounts_sync_labels function."""

    @patch("mail.accounts.commands.AccountsSyncLabelsProducer")
    @patch("mail.accounts.commands.AccountsSyncLabelsProcessor")
    @patch("mail.accounts.commands.AccountsSyncLabelsRequestConsumer")
    @patch("mail.accounts.commands.AccountsSyncLabelsRequest")
    def test_returns_zero_on_success(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = MagicMock(spec=ResultEnvelope)
        mock_envelope.ok.return_value = True
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args(labels="/path/to/labels.yaml")
        result = run_accounts_sync_labels(args)

        self.assertEqual(result, 0)

    @patch("mail.accounts.commands.AccountsSyncLabelsProducer")
    @patch("mail.accounts.commands.AccountsSyncLabelsProcessor")
    @patch("mail.accounts.commands.AccountsSyncLabelsRequestConsumer")
    @patch("mail.accounts.commands.AccountsSyncLabelsRequest")
    def test_passes_dry_run_flag(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = MagicMock(spec=ResultEnvelope)
        mock_envelope.ok.return_value = True
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args(dry_run=True)
        run_accounts_sync_labels(args)

        call_kwargs = mock_request.call_args
        self.assertTrue(call_kwargs.kwargs.get("dry_run"))
        mock_producer.assert_called_once_with(dry_run=True)


class TestRunAccountsExportFilters(unittest.TestCase):
    """Tests for run_accounts_export_filters function."""

    @patch("mail.accounts.commands.AccountsExportFiltersProducer")
    @patch("mail.accounts.commands.AccountsExportFiltersProcessor")
    @patch("mail.accounts.commands.AccountsExportFiltersRequestConsumer")
    @patch("mail.accounts.commands.AccountsExportFiltersRequest")
    def test_returns_zero_on_success(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = MagicMock(spec=ResultEnvelope)
        mock_envelope.ok.return_value = True
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args()
        result = run_accounts_export_filters(args)

        self.assertEqual(result, 0)


class TestRunAccountsSyncFilters(unittest.TestCase):
    """Tests for run_accounts_sync_filters function."""

    @patch("mail.accounts.commands.AccountsSyncFiltersProducer")
    @patch("mail.accounts.commands.AccountsSyncFiltersProcessor")
    @patch("mail.accounts.commands.AccountsSyncFiltersRequestConsumer")
    @patch("mail.accounts.commands.AccountsSyncFiltersRequest")
    def test_returns_zero_on_success(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = MagicMock(spec=ResultEnvelope)
        mock_envelope.ok.return_value = True
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args()
        result = run_accounts_sync_filters(args)

        self.assertEqual(result, 0)

    @patch("mail.accounts.commands.AccountsSyncFiltersProducer")
    @patch("mail.accounts.commands.AccountsSyncFiltersProcessor")
    @patch("mail.accounts.commands.AccountsSyncFiltersRequestConsumer")
    @patch("mail.accounts.commands.AccountsSyncFiltersRequest")
    def test_passes_require_forward_verified(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = MagicMock(spec=ResultEnvelope)
        mock_envelope.ok.return_value = True
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args(require_forward_verified=True)
        run_accounts_sync_filters(args)

        call_kwargs = mock_request.call_args
        self.assertTrue(call_kwargs.kwargs.get("require_forward_verified"))


class TestRunAccountsPlanLabels(unittest.TestCase):
    """Tests for run_accounts_plan_labels function."""

    @patch("mail.accounts.commands.AccountsPlanLabelsProducer")
    @patch("mail.accounts.commands.AccountsPlanLabelsProcessor")
    @patch("mail.accounts.commands.AccountsPlanLabelsRequestConsumer")
    @patch("mail.accounts.commands.AccountsPlanLabelsRequest")
    def test_returns_zero_on_success(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = MagicMock(spec=ResultEnvelope)
        mock_envelope.ok.return_value = True
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args()
        result = run_accounts_plan_labels(args)

        self.assertEqual(result, 0)

    @patch("mail.accounts.commands.AccountsPlanLabelsProducer")
    @patch("mail.accounts.commands.AccountsPlanLabelsProcessor")
    @patch("mail.accounts.commands.AccountsPlanLabelsRequestConsumer")
    @patch("mail.accounts.commands.AccountsPlanLabelsRequest")
    def test_returns_one_on_failure(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = MagicMock(spec=ResultEnvelope)
        mock_envelope.ok.return_value = False
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args()
        result = run_accounts_plan_labels(args)

        self.assertEqual(result, 1)


class TestRunAccountsPlanFilters(unittest.TestCase):
    """Tests for run_accounts_plan_filters function."""

    @patch("mail.accounts.commands.AccountsPlanFiltersProducer")
    @patch("mail.accounts.commands.AccountsPlanFiltersProcessor")
    @patch("mail.accounts.commands.AccountsPlanFiltersRequestConsumer")
    @patch("mail.accounts.commands.AccountsPlanFiltersRequest")
    def test_returns_zero_on_success(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = MagicMock(spec=ResultEnvelope)
        mock_envelope.ok.return_value = True
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args()
        result = run_accounts_plan_filters(args)

        self.assertEqual(result, 0)


class TestRunAccountsExportSignatures(unittest.TestCase):
    """Tests for run_accounts_export_signatures function."""

    @patch("mail.accounts.commands.AccountsExportSignaturesProducer")
    @patch("mail.accounts.commands.AccountsExportSignaturesProcessor")
    @patch("mail.accounts.commands.AccountsExportSignaturesRequestConsumer")
    @patch("mail.accounts.commands.AccountsExportSignaturesRequest")
    def test_returns_zero_on_success(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = MagicMock(spec=ResultEnvelope)
        mock_envelope.ok.return_value = True
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args()
        result = run_accounts_export_signatures(args)

        self.assertEqual(result, 0)


class TestRunAccountsSyncSignatures(unittest.TestCase):
    """Tests for run_accounts_sync_signatures function."""

    @patch("mail.accounts.commands.AccountsSyncSignaturesProducer")
    @patch("mail.accounts.commands.AccountsSyncSignaturesProcessor")
    @patch("mail.accounts.commands.AccountsSyncSignaturesRequestConsumer")
    @patch("mail.accounts.commands.AccountsSyncSignaturesRequest")
    def test_returns_zero_on_success(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = MagicMock(spec=ResultEnvelope)
        mock_envelope.ok.return_value = True
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args()
        result = run_accounts_sync_signatures(args)

        self.assertEqual(result, 0)

    @patch("mail.accounts.commands.AccountsSyncSignaturesProducer")
    @patch("mail.accounts.commands.AccountsSyncSignaturesProcessor")
    @patch("mail.accounts.commands.AccountsSyncSignaturesRequestConsumer")
    @patch("mail.accounts.commands.AccountsSyncSignaturesRequest")
    def test_passes_send_as_filter(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = MagicMock(spec=ResultEnvelope)
        mock_envelope.ok.return_value = True
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args(send_as="user@example.com")
        run_accounts_sync_signatures(args)

        call_kwargs = mock_request.call_args
        self.assertEqual(call_kwargs.kwargs.get("send_as"), "user@example.com")


if __name__ == "__main__":
    unittest.main()
