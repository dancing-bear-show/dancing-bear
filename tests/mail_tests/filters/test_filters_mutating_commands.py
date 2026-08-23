"""Tests for Gmail-mutating filter command functions.

Covers run_filters_sweep, run_filters_sweep_range, run_filters_prune_empty,
run_filters_add_forward_by_label, run_filters_add_from_token, and
run_filters_rm_from_token — all six functions that write to a live Gmail mailbox.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mail.filters.commands import (
    run_filters_sweep,
    run_filters_sweep_range,
    run_filters_prune_empty,
    run_filters_add_forward_by_label,
    run_filters_add_from_token,
    run_filters_rm_from_token,
)

from tests.mail_tests.fixtures import make_args, make_success_envelope, make_error_envelope


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

def _make_sweep_payload(client=None):
    """Return a SimpleNamespace that mimics FiltersSweepPayload."""
    from mail.filters.producers import SweepProducerConfig
    from mail.filters.processors_sweep import SweepConfig
    return SimpleNamespace(
        filters=[],
        sweep_config=SweepConfig(days=None, only_inbox=False),
        producer_config=SweepProducerConfig(pages=1, batch_size=10, max_msgs=None, dry_run=False),
        client=client or MagicMock(),
    )


def _make_sweep_range_payload(client=None):
    """Return a SimpleNamespace that mimics FiltersSweepRangePayload."""
    from mail.filters.producers import SweepProducerConfig
    return SimpleNamespace(
        filters=[],
        from_days=0,
        to_days=10,
        step_days=5,
        producer_config=SweepProducerConfig(pages=1, batch_size=10, max_msgs=None, dry_run=False),
        client=client or MagicMock(),
    )


def _make_prune_payload(client=None, dry_run=False):
    """Return a SimpleNamespace that mimics FiltersPrunePayload."""
    return SimpleNamespace(
        filters=[],
        days=None,
        only_inbox=False,
        pages=2,
        dry_run=dry_run,
        client=client or MagicMock(),
    )


def _make_add_forward_payload(client=None, dry_run=False):
    """Return a SimpleNamespace that mimics FiltersAddForwardPayload."""
    return SimpleNamespace(
        filters=[],
        id_to_name={},
        label_prefix="Forward",
        destination="dest@example.com",
        require_verified=False,
        verified_forward_addresses={"dest@example.com"},
        dry_run=dry_run,
        client=client or MagicMock(),
    )


def _make_token_payload(client=None, dry_run=False):
    """Return a SimpleNamespace that mimics FiltersAddTokenPayload / FiltersRemoveTokenPayload."""
    return SimpleNamespace(
        filters=[],
        id_to_name={},
        label_prefix="Lists",
        needle="example",
        tokens=["new@example.com"],
        dry_run=dry_run,
        client=client or MagicMock(),
    )


# ---------------------------------------------------------------------------
# run_filters_sweep
# ---------------------------------------------------------------------------

class TestRunFiltersSweep(unittest.TestCase):
    """Tests for run_filters_sweep."""

    def test_sweep_success_returns_zero(self):
        """Happy path: consumer succeeds, processor succeeds, producer runs."""
        payload = _make_sweep_payload()
        envelope = make_success_envelope()

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersSweepConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersSweepProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersSweepProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result = run_filters_sweep(make_args())

        self.assertEqual(result, 0)
        MockConsumer.return_value.consume.assert_called_once_with()
        MockProcessor.return_value.process.assert_called_once_with(payload)
        MockProducer.assert_called_once_with(payload.client, payload.producer_config)
        MockProducer.return_value.produce.assert_called_once_with(envelope)

    def test_sweep_consumer_value_error_returns_one(self):
        """Failure path: consumer ValueError → exit code 1."""
        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersSweepConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersSweepProcessor"),
            patch("mail.filters.commands.FiltersSweepProducer"),
        ):
            MockConsumer.return_value.consume.side_effect = ValueError("bad config")

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = run_filters_sweep(make_args())

        self.assertEqual(result, 1)
        self.assertIn("bad config", buf.getvalue())

    def test_sweep_processor_failure_returns_nonzero(self):
        """Failure path: processor returns failed envelope → non-zero exit code."""
        payload = _make_sweep_payload()
        envelope = make_error_envelope(diagnostics={"message": "sweep failed", "code": 3})

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersSweepConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersSweepProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersSweepProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = run_filters_sweep(make_args())

        self.assertEqual(result, 3)
        self.assertIn("sweep failed", buf.getvalue())
        MockProducer.return_value.produce.assert_not_called()


# ---------------------------------------------------------------------------
# run_filters_sweep_range
# ---------------------------------------------------------------------------

class TestRunFiltersSweepRange(unittest.TestCase):
    """Tests for run_filters_sweep_range."""

    def test_sweep_range_success_returns_zero(self):
        """Happy path: all stages succeed."""
        payload = _make_sweep_range_payload()
        envelope = make_success_envelope()

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersSweepRangeConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersSweepRangeProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersSweepRangeProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result = run_filters_sweep_range(make_args())

        self.assertEqual(result, 0)
        MockConsumer.return_value.consume.assert_called_once_with()
        MockProcessor.return_value.process.assert_called_once_with(payload)
        MockProducer.assert_called_once_with(payload.client, payload.producer_config)
        MockProducer.return_value.produce.assert_called_once_with(envelope)

    def test_sweep_range_consumer_value_error_returns_one(self):
        """Failure path: consumer ValueError → exit code 1."""
        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersSweepRangeConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersSweepRangeProcessor"),
            patch("mail.filters.commands.FiltersSweepRangeProducer"),
        ):
            MockConsumer.return_value.consume.side_effect = ValueError("invalid range")

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = run_filters_sweep_range(make_args())

        self.assertEqual(result, 1)
        self.assertIn("invalid range", buf.getvalue())

    def test_sweep_range_processor_failure_returns_nonzero(self):
        """Failure path: failed envelope → non-zero exit code, producer not called."""
        payload = _make_sweep_range_payload()
        envelope = make_error_envelope(diagnostics={"message": "range error", "code": 2})

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersSweepRangeConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersSweepRangeProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersSweepRangeProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = run_filters_sweep_range(make_args())

        self.assertEqual(result, 2)
        self.assertIn("range error", buf.getvalue())
        MockProducer.return_value.produce.assert_not_called()


# ---------------------------------------------------------------------------
# run_filters_prune_empty
# ---------------------------------------------------------------------------

class TestRunFiltersPruneEmpty(unittest.TestCase):
    """Tests for run_filters_prune_empty."""

    def test_prune_success_returns_zero(self):
        """Happy path: pruning succeeds, producer called with correct dry_run=False."""
        payload = _make_prune_payload(dry_run=False)
        envelope = make_success_envelope()

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersPruneConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersPruneProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersPruneProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result = run_filters_prune_empty(make_args())

        self.assertEqual(result, 0)
        MockConsumer.return_value.consume.assert_called_once_with()
        MockProcessor.return_value.process.assert_called_once_with(payload)
        MockProducer.assert_called_once_with(payload.client, dry_run=False)
        MockProducer.return_value.produce.assert_called_once_with(envelope)

    def test_prune_dry_run_producer_receives_dry_run_true(self):
        """Happy path: dry_run=True from payload is forwarded to the producer."""
        payload = _make_prune_payload(dry_run=True)
        envelope = make_success_envelope()

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersPruneConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersPruneProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersPruneProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result = run_filters_prune_empty(make_args())

        self.assertEqual(result, 0)
        MockProducer.assert_called_once_with(payload.client, dry_run=True)

    def test_prune_consumer_value_error_returns_one(self):
        """Failure path: consumer ValueError → exit code 1."""
        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersPruneConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersPruneProcessor"),
            patch("mail.filters.commands.FiltersPruneProducer"),
        ):
            MockConsumer.return_value.consume.side_effect = ValueError("no filters")

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = run_filters_prune_empty(make_args())

        self.assertEqual(result, 1)
        self.assertIn("no filters", buf.getvalue())

    def test_prune_processor_failure_returns_nonzero(self):
        """Failure path: failed envelope → non-zero exit code, producer not called."""
        payload = _make_prune_payload()
        envelope = make_error_envelope(diagnostics={"message": "prune failed", "code": 5})

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersPruneConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersPruneProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersPruneProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = run_filters_prune_empty(make_args())

        self.assertEqual(result, 5)
        self.assertIn("prune failed", buf.getvalue())
        MockProducer.return_value.produce.assert_not_called()


# ---------------------------------------------------------------------------
# run_filters_add_forward_by_label (custom inline pipeline)
# ---------------------------------------------------------------------------

class TestRunFiltersAddForwardByLabel(unittest.TestCase):
    """Tests for run_filters_add_forward_by_label.

    This function has its own inline pipeline (not _run_filter_pipeline), so
    we test its error branches specifically: consumer ValueError, processor
    failure with diagnostics, and processor failure with None diagnostics.
    """

    def test_add_forward_success_returns_zero(self):
        """Happy path: all stages succeed, producer called with payload.client and dry_run."""
        payload = _make_add_forward_payload(dry_run=False)
        envelope = make_success_envelope()

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersAddForwardConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersAddForwardProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersAddForwardProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result = run_filters_add_forward_by_label(make_args())

        self.assertEqual(result, 0)
        MockConsumer.return_value.consume.assert_called_once_with()
        MockProcessor.return_value.process.assert_called_once_with(payload)
        # The inline pipeline reads client and dry_run from payload (not context)
        MockProducer.assert_called_once_with(payload.client, dry_run=False)
        MockProducer.return_value.produce.assert_called_once_with(envelope)

    def test_add_forward_dry_run_forwarded_to_producer(self):
        """Happy path: dry_run=True is passed through to the producer."""
        payload = _make_add_forward_payload(dry_run=True)
        envelope = make_success_envelope()

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersAddForwardConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersAddForwardProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersAddForwardProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result = run_filters_add_forward_by_label(make_args())

        self.assertEqual(result, 0)
        MockProducer.assert_called_once_with(payload.client, dry_run=True)

    def test_add_forward_consumer_value_error_returns_one(self):
        """Failure path: consumer ValueError → exit code 1, error message printed."""
        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersAddForwardConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersAddForwardProcessor"),
            patch("mail.filters.commands.FiltersAddForwardProducer"),
        ):
            MockConsumer.return_value.consume.side_effect = ValueError("missing --email")

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = run_filters_add_forward_by_label(make_args())

        self.assertEqual(result, 1)
        self.assertIn("missing --email", buf.getvalue())

    def test_add_forward_processor_failure_returns_code_from_diagnostics(self):
        """Failure path: processor returns failed envelope → code from diagnostics."""
        payload = _make_add_forward_payload()
        envelope = make_error_envelope(
            diagnostics={"message": "Filters add-forward failed.", "code": 2}
        )

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersAddForwardConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersAddForwardProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersAddForwardProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = run_filters_add_forward_by_label(make_args())

        self.assertEqual(result, 2)
        self.assertIn("Filters add-forward failed.", buf.getvalue())
        MockProducer.return_value.produce.assert_not_called()

    def test_add_forward_processor_failure_none_diagnostics_returns_one(self):
        """Failure path: failed envelope with None diagnostics → exit code 1, default message."""
        payload = _make_add_forward_payload()
        envelope = make_error_envelope(diagnostics=None)

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersAddForwardConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersAddForwardProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersAddForwardProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = run_filters_add_forward_by_label(make_args())

        self.assertEqual(result, 1)
        self.assertIn("Filters add-forward failed.", buf.getvalue())
        MockProducer.return_value.produce.assert_not_called()


# ---------------------------------------------------------------------------
# run_filters_add_from_token
# ---------------------------------------------------------------------------

class TestRunFiltersAddFromToken(unittest.TestCase):
    """Tests for run_filters_add_from_token."""

    def test_add_token_success_returns_zero(self):
        """Happy path: all stages succeed, producer receives client and dry_run=False."""
        payload = _make_token_payload(dry_run=False)
        envelope = make_success_envelope()

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersAddTokenConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersAddTokenProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersAddTokenProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result = run_filters_add_from_token(make_args())

        self.assertEqual(result, 0)
        MockConsumer.return_value.consume.assert_called_once_with()
        MockProcessor.return_value.process.assert_called_once_with(payload)
        MockProducer.assert_called_once_with(payload.client, dry_run=False)
        MockProducer.return_value.produce.assert_called_once_with(envelope)

    def test_add_token_dry_run_forwarded(self):
        """Happy path: dry_run=True is forwarded to the producer."""
        payload = _make_token_payload(dry_run=True)
        envelope = make_success_envelope()

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersAddTokenConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersAddTokenProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersAddTokenProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result = run_filters_add_from_token(make_args())

        self.assertEqual(result, 0)
        MockProducer.assert_called_once_with(payload.client, dry_run=True)

    def test_add_token_consumer_value_error_returns_one(self):
        """Failure path: consumer ValueError → exit code 1."""
        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersAddTokenConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersAddTokenProcessor"),
            patch("mail.filters.commands.FiltersAddTokenProducer"),
        ):
            MockConsumer.return_value.consume.side_effect = ValueError("missing --needle")

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = run_filters_add_from_token(make_args())

        self.assertEqual(result, 1)
        self.assertIn("missing --needle", buf.getvalue())

    def test_add_token_processor_failure_returns_nonzero(self):
        """Failure path: failed envelope → non-zero exit code, producer not called."""
        payload = _make_token_payload()
        envelope = make_error_envelope(diagnostics={"message": "token error", "code": 4})

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersAddTokenConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersAddTokenProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersAddTokenProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = run_filters_add_from_token(make_args())

        self.assertEqual(result, 4)
        self.assertIn("token error", buf.getvalue())
        MockProducer.return_value.produce.assert_not_called()


# ---------------------------------------------------------------------------
# run_filters_rm_from_token
# ---------------------------------------------------------------------------

class TestRunFiltersRmFromToken(unittest.TestCase):
    """Tests for run_filters_rm_from_token."""

    def test_rm_token_success_returns_zero(self):
        """Happy path: all stages succeed, producer receives client and dry_run=False."""
        payload = _make_token_payload(dry_run=False)
        envelope = make_success_envelope()

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersRemoveTokenConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersRemoveTokenProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersRemoveTokenProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result = run_filters_rm_from_token(make_args())

        self.assertEqual(result, 0)
        MockConsumer.return_value.consume.assert_called_once_with()
        MockProcessor.return_value.process.assert_called_once_with(payload)
        MockProducer.assert_called_once_with(payload.client, dry_run=False)
        MockProducer.return_value.produce.assert_called_once_with(envelope)

    def test_rm_token_dry_run_forwarded(self):
        """Happy path: dry_run=True is forwarded to the producer."""
        payload = _make_token_payload(dry_run=True)
        envelope = make_success_envelope()

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersRemoveTokenConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersRemoveTokenProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersRemoveTokenProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result = run_filters_rm_from_token(make_args())

        self.assertEqual(result, 0)
        MockProducer.assert_called_once_with(payload.client, dry_run=True)

    def test_rm_token_consumer_value_error_returns_one(self):
        """Failure path: consumer ValueError → exit code 1."""
        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersRemoveTokenConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersRemoveTokenProcessor"),
            patch("mail.filters.commands.FiltersRemoveTokenProducer"),
        ):
            MockConsumer.return_value.consume.side_effect = ValueError("missing --remove")

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = run_filters_rm_from_token(make_args())

        self.assertEqual(result, 1)
        self.assertIn("missing --remove", buf.getvalue())

    def test_rm_token_processor_failure_returns_nonzero(self):
        """Failure path: failed envelope → non-zero exit code, producer not called."""
        payload = _make_token_payload()
        envelope = make_error_envelope(diagnostics={"message": "remove failed", "code": 6})

        with (
            patch("mail.filters.commands.MailContext.from_args"),
            patch("mail.filters.commands.FiltersRemoveTokenConsumer") as MockConsumer,
            patch("mail.filters.commands.FiltersRemoveTokenProcessor") as MockProcessor,
            patch("mail.filters.commands.FiltersRemoveTokenProducer") as MockProducer,
        ):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = run_filters_rm_from_token(make_args())

        self.assertEqual(result, 6)
        self.assertIn("remove failed", buf.getvalue())
        MockProducer.return_value.produce.assert_not_called()


if __name__ == "__main__":
    unittest.main()
