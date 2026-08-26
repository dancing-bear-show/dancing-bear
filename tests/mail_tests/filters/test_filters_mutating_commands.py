"""Tests for Gmail-mutating filter command functions.

Covers run_filters_sweep, run_filters_sweep_range, run_filters_prune_empty,
run_filters_add_forward_by_label, run_filters_add_from_token, and
run_filters_rm_from_token — all six functions that write to a live Gmail mailbox.
"""

from __future__ import annotations

import io
import unittest
from contextlib import contextmanager, redirect_stdout
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
# Shared pipeline-patching helpers
#
# Every command under test follows the same consumer -> processor -> producer
# shape, but each patches a *different* trio of class names (e.g.
# FiltersSweepConsumer vs FiltersPruneConsumer) and each test asserts
# different things about the result (return codes, dry_run forwarding,
# diagnostics handling). These helpers only collapse the repeated
# `patch(...)`/stdout-capture scaffolding; every test still wires its own
# consume/process return values and makes its own assertions.
# ---------------------------------------------------------------------------


@contextmanager
def _patched_pipeline(consumer_name: str, processor_name: str, producer_name: str):
    """Patch commands.<consumer_name>/<processor_name>/<producer_name> plus
    MailContext.from_args, yielding (MockConsumer, MockProcessor, MockProducer).
    """
    with (
        patch("mail.filters.commands.MailContext.from_args"),
        patch(f"mail.filters.commands.{consumer_name}") as mock_consumer,
        patch(f"mail.filters.commands.{processor_name}") as mock_processor,
        patch(f"mail.filters.commands.{producer_name}") as mock_producer,
    ):
        yield mock_consumer, mock_processor, mock_producer


def _run_capturing_stdout(run_fn, args):
    """Call run_fn(args) under redirect_stdout, returning (result, output)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = run_fn(args)
    return result, buf.getvalue()


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

        with _patched_pipeline(
            "FiltersSweepConsumer", "FiltersSweepProcessor", "FiltersSweepProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
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
        with _patched_pipeline(
            "FiltersSweepConsumer", "FiltersSweepProcessor", "FiltersSweepProducer"
        ) as (MockConsumer, _MockProcessor, _MockProducer):
            MockConsumer.return_value.consume.side_effect = ValueError("bad config")

            result, output = _run_capturing_stdout(run_filters_sweep, make_args())

        self.assertEqual(result, 1)
        self.assertIn("bad config", output)

    def test_sweep_processor_failure_returns_nonzero(self):
        """Failure path: processor returns failed envelope → non-zero exit code."""
        payload = _make_sweep_payload()
        envelope = make_error_envelope(diagnostics={"message": "sweep failed", "code": 3})

        with _patched_pipeline(
            "FiltersSweepConsumer", "FiltersSweepProcessor", "FiltersSweepProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result, output = _run_capturing_stdout(run_filters_sweep, make_args())

        self.assertEqual(result, 3)
        self.assertIn("sweep failed", output)
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

        with _patched_pipeline(
            "FiltersSweepRangeConsumer", "FiltersSweepRangeProcessor", "FiltersSweepRangeProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
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
        with _patched_pipeline(
            "FiltersSweepRangeConsumer", "FiltersSweepRangeProcessor", "FiltersSweepRangeProducer"
        ) as (MockConsumer, _MockProcessor, _MockProducer):
            MockConsumer.return_value.consume.side_effect = ValueError("invalid range")

            result, output = _run_capturing_stdout(run_filters_sweep_range, make_args())

        self.assertEqual(result, 1)
        self.assertIn("invalid range", output)

    def test_sweep_range_processor_failure_returns_nonzero(self):
        """Failure path: failed envelope → non-zero exit code, producer not called."""
        payload = _make_sweep_range_payload()
        envelope = make_error_envelope(diagnostics={"message": "range error", "code": 2})

        with _patched_pipeline(
            "FiltersSweepRangeConsumer", "FiltersSweepRangeProcessor", "FiltersSweepRangeProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result, output = _run_capturing_stdout(run_filters_sweep_range, make_args())

        self.assertEqual(result, 2)
        self.assertIn("range error", output)
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

        with _patched_pipeline(
            "FiltersPruneConsumer", "FiltersPruneProcessor", "FiltersPruneProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
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

        with _patched_pipeline(
            "FiltersPruneConsumer", "FiltersPruneProcessor", "FiltersPruneProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result = run_filters_prune_empty(make_args())

        self.assertEqual(result, 0)
        MockProducer.assert_called_once_with(payload.client, dry_run=True)

    def test_prune_consumer_value_error_returns_one(self):
        """Failure path: consumer ValueError → exit code 1."""
        with _patched_pipeline(
            "FiltersPruneConsumer", "FiltersPruneProcessor", "FiltersPruneProducer"
        ) as (MockConsumer, _MockProcessor, _MockProducer):
            MockConsumer.return_value.consume.side_effect = ValueError("no filters")

            result, output = _run_capturing_stdout(run_filters_prune_empty, make_args())

        self.assertEqual(result, 1)
        self.assertIn("no filters", output)

    def test_prune_processor_failure_returns_nonzero(self):
        """Failure path: failed envelope → non-zero exit code, producer not called."""
        payload = _make_prune_payload()
        envelope = make_error_envelope(diagnostics={"message": "prune failed", "code": 5})

        with _patched_pipeline(
            "FiltersPruneConsumer", "FiltersPruneProcessor", "FiltersPruneProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result, output = _run_capturing_stdout(run_filters_prune_empty, make_args())

        self.assertEqual(result, 5)
        self.assertIn("prune failed", output)
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

        with _patched_pipeline(
            "FiltersAddForwardConsumer", "FiltersAddForwardProcessor", "FiltersAddForwardProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
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

        with _patched_pipeline(
            "FiltersAddForwardConsumer", "FiltersAddForwardProcessor", "FiltersAddForwardProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result = run_filters_add_forward_by_label(make_args())

        self.assertEqual(result, 0)
        MockProducer.assert_called_once_with(payload.client, dry_run=True)

    def test_add_forward_consumer_value_error_returns_one(self):
        """Failure path: consumer ValueError → exit code 1, error message printed."""
        with _patched_pipeline(
            "FiltersAddForwardConsumer", "FiltersAddForwardProcessor", "FiltersAddForwardProducer"
        ) as (MockConsumer, _MockProcessor, _MockProducer):
            MockConsumer.return_value.consume.side_effect = ValueError("missing --email")

            result, output = _run_capturing_stdout(run_filters_add_forward_by_label, make_args())

        self.assertEqual(result, 1)
        self.assertIn("missing --email", output)

    def test_add_forward_processor_failure_returns_code_from_diagnostics(self):
        """Failure path: processor returns failed envelope → code from diagnostics."""
        payload = _make_add_forward_payload()
        envelope = make_error_envelope(
            diagnostics={"message": "Filters add-forward failed.", "code": 2}
        )

        with _patched_pipeline(
            "FiltersAddForwardConsumer", "FiltersAddForwardProcessor", "FiltersAddForwardProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result, output = _run_capturing_stdout(run_filters_add_forward_by_label, make_args())

        self.assertEqual(result, 2)
        self.assertIn("Filters add-forward failed.", output)
        MockProducer.return_value.produce.assert_not_called()

    def test_add_forward_processor_failure_none_diagnostics_returns_one(self):
        """Failure path: failed envelope with None diagnostics → exit code 1, default message."""
        payload = _make_add_forward_payload()
        envelope = make_error_envelope(diagnostics=None)

        with _patched_pipeline(
            "FiltersAddForwardConsumer", "FiltersAddForwardProcessor", "FiltersAddForwardProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result, output = _run_capturing_stdout(run_filters_add_forward_by_label, make_args())

        self.assertEqual(result, 1)
        self.assertIn("Filters add-forward failed.", output)
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

        with _patched_pipeline(
            "FiltersAddTokenConsumer", "FiltersAddTokenProcessor", "FiltersAddTokenProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
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

        with _patched_pipeline(
            "FiltersAddTokenConsumer", "FiltersAddTokenProcessor", "FiltersAddTokenProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result = run_filters_add_from_token(make_args())

        self.assertEqual(result, 0)
        MockProducer.assert_called_once_with(payload.client, dry_run=True)

    def test_add_token_consumer_value_error_returns_one(self):
        """Failure path: consumer ValueError → exit code 1."""
        with _patched_pipeline(
            "FiltersAddTokenConsumer", "FiltersAddTokenProcessor", "FiltersAddTokenProducer"
        ) as (MockConsumer, _MockProcessor, _MockProducer):
            MockConsumer.return_value.consume.side_effect = ValueError("missing --needle")

            result, output = _run_capturing_stdout(run_filters_add_from_token, make_args())

        self.assertEqual(result, 1)
        self.assertIn("missing --needle", output)

    def test_add_token_processor_failure_returns_nonzero(self):
        """Failure path: failed envelope → non-zero exit code, producer not called."""
        payload = _make_token_payload()
        envelope = make_error_envelope(diagnostics={"message": "token error", "code": 4})

        with _patched_pipeline(
            "FiltersAddTokenConsumer", "FiltersAddTokenProcessor", "FiltersAddTokenProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result, output = _run_capturing_stdout(run_filters_add_from_token, make_args())

        self.assertEqual(result, 4)
        self.assertIn("token error", output)
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

        with _patched_pipeline(
            "FiltersRemoveTokenConsumer", "FiltersRemoveTokenProcessor", "FiltersRemoveTokenProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
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

        with _patched_pipeline(
            "FiltersRemoveTokenConsumer", "FiltersRemoveTokenProcessor", "FiltersRemoveTokenProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result = run_filters_rm_from_token(make_args())

        self.assertEqual(result, 0)
        MockProducer.assert_called_once_with(payload.client, dry_run=True)

    def test_rm_token_consumer_value_error_returns_one(self):
        """Failure path: consumer ValueError → exit code 1."""
        with _patched_pipeline(
            "FiltersRemoveTokenConsumer", "FiltersRemoveTokenProcessor", "FiltersRemoveTokenProducer"
        ) as (MockConsumer, _MockProcessor, _MockProducer):
            MockConsumer.return_value.consume.side_effect = ValueError("missing --remove")

            result, output = _run_capturing_stdout(run_filters_rm_from_token, make_args())

        self.assertEqual(result, 1)
        self.assertIn("missing --remove", output)

    def test_rm_token_processor_failure_returns_nonzero(self):
        """Failure path: failed envelope → non-zero exit code, producer not called."""
        payload = _make_token_payload()
        envelope = make_error_envelope(diagnostics={"message": "remove failed", "code": 6})

        with _patched_pipeline(
            "FiltersRemoveTokenConsumer", "FiltersRemoveTokenProcessor", "FiltersRemoveTokenProducer"
        ) as (MockConsumer, MockProcessor, MockProducer):
            MockConsumer.return_value.consume.return_value = payload
            MockProcessor.return_value.process.return_value = envelope

            result, output = _run_capturing_stdout(run_filters_rm_from_token, make_args())

        self.assertEqual(result, 6)
        self.assertIn("remove failed", output)
        MockProducer.return_value.produce.assert_not_called()


if __name__ == "__main__":
    unittest.main()
