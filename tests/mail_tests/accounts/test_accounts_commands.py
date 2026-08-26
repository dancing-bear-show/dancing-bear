"""Tests for mail/accounts/commands.py accounts command orchestration."""

import unittest
from unittest.mock import patch

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
from tests.fixtures import test_path
from tests.mail_tests.fixtures import (
    make_args as _make_args,
    make_success_envelope,
    make_error_envelope,
)


def make_args(**kwargs):
    """Create args namespace with accounts-specific defaults."""
    defaults = {
        "config": "/path/to/config.yaml",
        "out_dir": test_path("out"),  # nosec B108 - test fixture path
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
        mock_envelope = make_success_envelope()
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
        mock_envelope = make_error_envelope()
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
        mock_envelope = make_success_envelope()
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
        mock_envelope = make_success_envelope()
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
        mock_envelope = make_success_envelope()
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args(labels="/path/to/labels.yaml")
        result = run_accounts_sync_labels(args)

        self.assertEqual(result, 0)

    @patch("mail.accounts.commands.AccountsSyncLabelsProducer")
    @patch("mail.accounts.commands.AccountsSyncLabelsProcessor")
    @patch("mail.accounts.commands.AccountsSyncLabelsRequestConsumer")
    @patch("mail.accounts.commands.AccountsSyncLabelsRequest")
    def test_passes_dry_run_flag(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = make_success_envelope()
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args(dry_run=True)
        run_accounts_sync_labels(args)

        call_kwargs = mock_request.call_args
        self.assertTrue(call_kwargs.kwargs.get("dry_run"))
        mock_producer.assert_called_once_with(dry_run=True)


class TestRunAccountsSyncFilters(unittest.TestCase):
    """Tests for run_accounts_sync_filters function."""

    @patch("mail.accounts.commands.AccountsSyncFiltersProducer")
    @patch("mail.accounts.commands.AccountsSyncFiltersProcessor")
    @patch("mail.accounts.commands.AccountsSyncFiltersRequestConsumer")
    @patch("mail.accounts.commands.AccountsSyncFiltersRequest")
    def test_returns_zero_on_success(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = make_success_envelope()
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args()
        result = run_accounts_sync_filters(args)

        self.assertEqual(result, 0)

    @patch("mail.accounts.commands.AccountsSyncFiltersProducer")
    @patch("mail.accounts.commands.AccountsSyncFiltersProcessor")
    @patch("mail.accounts.commands.AccountsSyncFiltersRequestConsumer")
    @patch("mail.accounts.commands.AccountsSyncFiltersRequest")
    def test_passes_require_forward_verified(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = make_success_envelope()
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
        mock_envelope = make_success_envelope()
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args()
        result = run_accounts_plan_labels(args)

        self.assertEqual(result, 0)

    @patch("mail.accounts.commands.AccountsPlanLabelsProducer")
    @patch("mail.accounts.commands.AccountsPlanLabelsProcessor")
    @patch("mail.accounts.commands.AccountsPlanLabelsRequestConsumer")
    @patch("mail.accounts.commands.AccountsPlanLabelsRequest")
    def test_returns_one_on_failure(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = make_error_envelope()
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args()
        result = run_accounts_plan_labels(args)

        self.assertEqual(result, 1)


class TestRunAccountsSimpleSuccessCommands(unittest.TestCase):
    """Tests for accounts commands whose only coverage is a bare success path.

    run_accounts_export_filters, run_accounts_plan_filters, and
    run_accounts_export_signatures each patch their own
    Request/RequestConsumer/Processor/Producer quartet, run with default args,
    and assert exit code 0 — no distinguishing behavior beyond the command
    name. Table-driven over (case name, command prefix, entry point) to avoid
    duplicating that scaffolding per command.
    """

    _SIMPLE_SUCCESS_COMMANDS = [
        ("export_filters", "AccountsExportFilters", "run_accounts_export_filters"),
        ("plan_filters", "AccountsPlanFilters", "run_accounts_plan_filters"),
        ("export_signatures", "AccountsExportSignatures", "run_accounts_export_signatures"),
    ]

    def test_returns_zero_on_success(self):
        module = "mail.accounts.commands"
        entry_points = {
            "run_accounts_export_filters": run_accounts_export_filters,
            "run_accounts_plan_filters": run_accounts_plan_filters,
            "run_accounts_export_signatures": run_accounts_export_signatures,
        }
        for case_name, command_prefix, entry_point_name in self._SIMPLE_SUCCESS_COMMANDS:
            with self.subTest(command=case_name):
                with patch(f"{module}.{command_prefix}Producer"), \
                        patch(f"{module}.{command_prefix}Processor") as mock_processor, \
                        patch(f"{module}.{command_prefix}RequestConsumer"), \
                        patch(f"{module}.{command_prefix}Request"):
                    mock_envelope = make_success_envelope()
                    mock_processor.return_value.process.return_value = mock_envelope

                    entry_point = entry_points[entry_point_name]
                    args = make_args()
                    result = entry_point(args)

                    self.assertEqual(result, 0)


class TestRunAccountsSyncSignatures(unittest.TestCase):
    """Tests for run_accounts_sync_signatures function."""

    @patch("mail.accounts.commands.AccountsSyncSignaturesProducer")
    @patch("mail.accounts.commands.AccountsSyncSignaturesProcessor")
    @patch("mail.accounts.commands.AccountsSyncSignaturesRequestConsumer")
    @patch("mail.accounts.commands.AccountsSyncSignaturesRequest")
    def test_returns_zero_on_success(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = make_success_envelope()
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args()
        result = run_accounts_sync_signatures(args)

        self.assertEqual(result, 0)

    @patch("mail.accounts.commands.AccountsSyncSignaturesProducer")
    @patch("mail.accounts.commands.AccountsSyncSignaturesProcessor")
    @patch("mail.accounts.commands.AccountsSyncSignaturesRequestConsumer")
    @patch("mail.accounts.commands.AccountsSyncSignaturesRequest")
    def test_passes_send_as_filter(self, mock_request, mock_consumer, mock_processor, mock_producer):
        mock_envelope = make_success_envelope()
        mock_processor.return_value.process.return_value = mock_envelope

        args = make_args(send_as="user@example.com")
        run_accounts_sync_signatures(args)

        call_kwargs = mock_request.call_args
        self.assertEqual(call_kwargs.kwargs.get("send_as"), "user@example.com")


if __name__ == "__main__":
    unittest.main()
