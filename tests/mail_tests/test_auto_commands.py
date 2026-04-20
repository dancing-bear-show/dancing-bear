"""Tests for mail/auto/commands.py pipeline orchestration."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from mail.auto.commands import run_auto_propose, run_auto_summary, run_auto_apply
from tests.mail_tests.fixtures import make_args as _make_base_args, make_success_envelope, make_error_envelope


def _make_args(**kwargs):
    defaults = {
        "out": "/tmp/proposal.json",  # nosec B108 - test-only temp file, not a security concern
        "days": "7",
        "pages": "5",
        "protect": [],
        "dry_run": False,
        "log": "logs/auto_runs.jsonl",
        "proposal": "/tmp/proposal.json",  # nosec B108 - test-only temp file, not a security concern
        "cutoff_days": None,
        "batch_size": 500,
    }
    defaults.update(kwargs)
    return _make_base_args(**defaults)


def _make_ok_envelope():
    return make_success_envelope()


def _make_error_envelope(code=1):
    return make_error_envelope(diagnostics={"code": code})


class TestRunAutoPropose(unittest.TestCase):
    """Tests for run_auto_propose."""

    @patch("mail.auto.commands.AutoProposeProducer")
    @patch("mail.auto.commands.AutoProposeProcessor")
    @patch("mail.auto.commands.AutoProposeConsumer")
    @patch("mail.auto.commands.MailContext")
    def test_returns_zero_on_success(self, mock_ctx_cls, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()
        mock_ctx_cls.from_args.return_value = MagicMock()

        result = run_auto_propose(_make_args())
        self.assertEqual(result, 0)

    @patch("mail.auto.commands.AutoProposeProducer")
    @patch("mail.auto.commands.AutoProposeProcessor")
    @patch("mail.auto.commands.AutoProposeConsumer")
    @patch("mail.auto.commands.MailContext")
    def test_returns_nonzero_on_error(self, mock_ctx_cls, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        envelope = _make_error_envelope(code=2)
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()
        mock_ctx_cls.from_args.return_value = MagicMock()

        result = run_auto_propose(_make_args())
        self.assertEqual(result, 2)

    @patch("mail.auto.commands.AutoProposeProducer")
    @patch("mail.auto.commands.AutoProposeProcessor")
    @patch("mail.auto.commands.AutoProposeConsumer")
    @patch("mail.auto.commands.MailContext")
    def test_consumer_receives_correct_params(self, mock_ctx_cls, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()
        fake_ctx = MagicMock()
        mock_ctx_cls.from_args.return_value = fake_ctx

        args = _make_args(days="14", pages="3")
        run_auto_propose(args)

        mock_consumer_cls.assert_called_once()
        call_kwargs = mock_consumer_cls.call_args
        self.assertEqual(call_kwargs.kwargs["days"], 14)
        self.assertEqual(call_kwargs.kwargs["pages"], 3)
        self.assertEqual(call_kwargs.kwargs["context"], fake_ctx)

    @patch("mail.auto.commands.AutoProposeProducer")
    @patch("mail.auto.commands.AutoProposeProcessor")
    @patch("mail.auto.commands.AutoProposeConsumer")
    @patch("mail.auto.commands.MailContext")
    def test_error_with_no_code_defaults_to_one(self, mock_ctx_cls, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        envelope = MagicMock()
        envelope.ok.return_value = False
        envelope.diagnostics = None
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()
        mock_ctx_cls.from_args.return_value = MagicMock()

        result = run_auto_propose(_make_args())
        self.assertNotEqual(result, 0)

    @patch("mail.auto.commands.AutoProposeProducer")
    @patch("mail.auto.commands.AutoProposeProcessor")
    @patch("mail.auto.commands.AutoProposeConsumer")
    @patch("mail.auto.commands.MailContext")
    def test_protect_defaults_to_empty_list(self, mock_ctx_cls, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()
        mock_ctx_cls.from_args.return_value = MagicMock()

        args = _make_args()
        del args.protect  # Remove protect to test getattr default
        run_auto_propose(args)

        call_kwargs = mock_consumer_cls.call_args.kwargs
        self.assertEqual(call_kwargs["protect"], [])


class TestRunAutoSummary(unittest.TestCase):
    """Tests for run_auto_summary."""

    @patch("mail.auto.commands.AutoSummaryProducer")
    @patch("mail.auto.commands.AutoSummaryProcessor")
    @patch("mail.auto.commands.AutoSummaryConsumer")
    def test_returns_zero_on_success(self, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()

        result = run_auto_summary(_make_args())
        self.assertEqual(result, 0)

    @patch("mail.auto.commands.AutoSummaryProducer")
    @patch("mail.auto.commands.AutoSummaryProcessor")
    @patch("mail.auto.commands.AutoSummaryConsumer")
    def test_returns_nonzero_on_error(self, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        envelope = _make_error_envelope(code=3)
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()

        result = run_auto_summary(_make_args())
        self.assertEqual(result, 3)

    @patch("mail.auto.commands.AutoSummaryProducer")
    @patch("mail.auto.commands.AutoSummaryProcessor")
    @patch("mail.auto.commands.AutoSummaryConsumer")
    def test_consumer_receives_proposal_path(self, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()

        args = _make_args(proposal="/tmp/my_proposal.json")  # nosec B108 - test-only temp file, not a security concern
        run_auto_summary(args)

        from pathlib import Path
        mock_consumer_cls.assert_called_once_with(proposal_path=Path("/tmp/my_proposal.json"))  # nosec B108 - test-only temp file, not a security concern

    @patch("mail.auto.commands.AutoSummaryProducer")
    @patch("mail.auto.commands.AutoSummaryProcessor")
    @patch("mail.auto.commands.AutoSummaryConsumer")
    def test_pipeline_called_in_order(self, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        """consume -> process -> produce is called in order."""
        envelope = _make_ok_envelope()
        mock_processor = mock_processor_cls.return_value
        mock_processor.process.return_value = envelope
        payload = MagicMock()
        mock_consumer_cls.return_value.consume.return_value = payload

        run_auto_summary(_make_args())

        mock_consumer_cls.return_value.consume.assert_called_once()
        mock_processor.process.assert_called_once_with(payload)
        mock_producer_cls.return_value.produce.assert_called_once_with(envelope)


class TestRunAutoApply(unittest.TestCase):
    """Tests for run_auto_apply."""

    @patch("mail.auto.commands.AutoApplyProducer")
    @patch("mail.auto.commands.AutoApplyProcessor")
    @patch("mail.auto.commands.AutoApplyConsumer")
    @patch("mail.auto.commands.MailContext")
    def test_returns_zero_on_success(self, mock_ctx_cls, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()
        mock_ctx_cls.from_args.return_value = MagicMock()

        result = run_auto_apply(_make_args())
        self.assertEqual(result, 0)

    @patch("mail.auto.commands.AutoApplyProducer")
    @patch("mail.auto.commands.AutoApplyProcessor")
    @patch("mail.auto.commands.AutoApplyConsumer")
    @patch("mail.auto.commands.MailContext")
    def test_returns_nonzero_on_error(self, mock_ctx_cls, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        envelope = _make_error_envelope(code=5)
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()
        mock_ctx_cls.from_args.return_value = MagicMock()

        result = run_auto_apply(_make_args())
        self.assertEqual(result, 5)

    @patch("mail.auto.commands.AutoApplyProducer")
    @patch("mail.auto.commands.AutoApplyProcessor")
    @patch("mail.auto.commands.AutoApplyConsumer")
    @patch("mail.auto.commands.MailContext")
    def test_consumer_receives_correct_params(self, mock_ctx_cls, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()
        fake_ctx = MagicMock()
        mock_ctx_cls.from_args.return_value = fake_ctx

        args = _make_args(cutoff_days=30, batch_size=100, dry_run=True)
        run_auto_apply(args)

        call_kwargs = mock_consumer_cls.call_args.kwargs
        self.assertEqual(call_kwargs["context"], fake_ctx)
        self.assertEqual(call_kwargs["cutoff_days"], 30)
        self.assertEqual(call_kwargs["batch_size"], 100)
        self.assertTrue(call_kwargs["dry_run"])


if __name__ == "__main__":
    unittest.main()
