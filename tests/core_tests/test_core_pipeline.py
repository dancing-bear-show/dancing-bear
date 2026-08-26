"""Tests for core/pipeline.py."""

from __future__ import annotations

import unittest
from io import StringIO
from unittest.mock import patch

from core.cli_output import OutputWriter, OutputConfig
from core.pipeline import BaseProducer, ResultEnvelope, SafeProcessor


class TestResultEnvelopeUnwrap(unittest.TestCase):
    """Tests for ResultEnvelope.unwrap() method."""

    def test_unwrap_returns_payload_when_present(self):
        """Test unwrap returns payload when it exists."""
        envelope = ResultEnvelope(status="success", payload={"data": "value"})
        result = envelope.unwrap()
        self.assertEqual(result, {"data": "value"})

    def test_unwrap_returns_payload_of_any_type(self):
        """Test unwrap works with different payload types."""
        # String payload
        envelope = ResultEnvelope(status="success", payload="test string")
        self.assertEqual(envelope.unwrap(), "test string")

        # List payload
        envelope = ResultEnvelope(status="success", payload=[1, 2, 3])
        self.assertEqual(envelope.unwrap(), [1, 2, 3])

        # Integer payload
        envelope = ResultEnvelope(status="success", payload=42)
        self.assertEqual(envelope.unwrap(), 42)

    def test_unwrap_raises_when_payload_is_none(self):
        """Test unwrap raises ValueError when payload is None."""
        envelope = ResultEnvelope(status="error", payload=None)
        with self.assertRaises(ValueError) as ctx:
            envelope.unwrap()
        self.assertEqual(str(ctx.exception), "No payload")

    def test_unwrap_uses_diagnostics_message(self):
        """Test unwrap uses diagnostics message in ValueError."""
        envelope = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"message": "Custom error message"},
        )
        with self.assertRaises(ValueError) as ctx:
            envelope.unwrap()
        self.assertEqual(str(ctx.exception), "Custom error message")

    def test_unwrap_falls_back_to_no_payload_when_no_diagnostics(self):
        """Test unwrap falls back to 'No payload' when diagnostics is None."""
        envelope = ResultEnvelope(status="error", payload=None, diagnostics=None)
        with self.assertRaises(ValueError) as ctx:
            envelope.unwrap()
        self.assertEqual(str(ctx.exception), "No payload")

    def test_unwrap_falls_back_when_diagnostics_has_no_message(self):
        """Test unwrap falls back when diagnostics exists but has no message key."""
        envelope = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"code": 500},
        )
        with self.assertRaises(ValueError) as ctx:
            envelope.unwrap()
        self.assertEqual(str(ctx.exception), "No payload")

    def test_unwrap_works_regardless_of_ok_status(self):
        """Test unwrap only checks payload, not ok() status."""
        # Payload exists but status is error - unwrap should still work
        envelope = ResultEnvelope(status="error", payload="still works")
        self.assertEqual(envelope.unwrap(), "still works")


class TestResultEnvelopeOk(unittest.TestCase):
    """Tests for ResultEnvelope.ok() method."""

    def test_ok_returns_true_for_success(self):
        """Test ok() returns True for 'success' status."""
        envelope = ResultEnvelope(status="success", payload="data")
        self.assertTrue(envelope.ok())

    def test_ok_is_case_insensitive(self):
        """Test ok() is case-insensitive for status."""
        self.assertTrue(ResultEnvelope(status="SUCCESS").ok())
        self.assertTrue(ResultEnvelope(status="Success").ok())
        self.assertTrue(ResultEnvelope(status="success").ok())

    def test_ok_returns_false_for_error(self):
        """Test ok() returns False for non-success status."""
        envelope = ResultEnvelope(status="error")
        self.assertFalse(envelope.ok())

    def test_ok_returns_false_for_failed(self):
        """Test ok() returns False for 'failed' status."""
        envelope = ResultEnvelope(status="failed")
        self.assertFalse(envelope.ok())


class TestBaseProducerConstruction(unittest.TestCase):
    """C6: BaseProducer construction and OutputWriter injection."""

    def test_zero_arg_construction_succeeds(self):
        """BaseProducer() with no args creates a default OutputWriter."""
        producer = BaseProducer()
        self.assertIsInstance(producer._writer, OutputWriter)

    def test_default_writer_is_fresh_instance(self):
        """Two zero-arg constructions each get their own OutputWriter."""
        p1 = BaseProducer()
        p2 = BaseProducer()
        self.assertIsNot(p1._writer, p2._writer)

    def test_injected_writer_is_used(self):
        """BaseProducer(writer=custom) stores and uses the injected writer."""
        buf = StringIO()
        custom = OutputWriter(OutputConfig(file=buf))
        producer = BaseProducer(writer=custom)
        self.assertIs(producer._writer, custom)

    def _capture_stderr_stdout(self, action) -> tuple[str, str]:
        """Run action() with sys.stderr/sys.stdout patched; return (stderr, stdout)."""
        stderr_buf = StringIO()
        stdout_buf = StringIO()
        with patch("sys.stderr", stderr_buf), patch("sys.stdout", stdout_buf):
            action()
        return stderr_buf.getvalue(), stdout_buf.getvalue()

    def test_print_error_goes_to_stderr_not_stdout(self):
        """C6 contract: print_error() output goes to stderr, not stdout.

        This is the canonical test pinning the C6 routing change — other
        domains' tests broke on exactly this boundary (stdout vs stderr).
        """
        producer = BaseProducer()
        failed = ResultEnvelope(status="error", diagnostics={"message": "boom"})

        stderr_out, stdout_out = self._capture_stderr_stdout(lambda: producer.print_error(failed))

        self.assertIn("boom", stderr_out)
        self.assertEqual(stdout_out, "")

    def test_produce_error_message_goes_to_stderr(self):
        """produce() routes error-path message to stderr via the writer."""
        producer = BaseProducer()
        failed = ResultEnvelope(status="error", diagnostics={"message": "produce-error"})

        stderr_out, stdout_out = self._capture_stderr_stdout(lambda: producer.produce(failed))

        self.assertIn("produce-error", stderr_out)
        self.assertEqual(stdout_out, "")

    def test_produce_success_delegates_to_subclass(self):
        """produce() calls _produce_success on happy path."""
        calls = []

        class TrackingProducer(BaseProducer):
            def _produce_success(self, payload, diagnostics):
                calls.append(payload)

        producer = TrackingProducer()
        producer.produce(ResultEnvelope(status="success", payload="mydata"))
        self.assertEqual(calls, ["mydata"])

    def test_print_logs_uses_injected_writer(self):
        """print_logs() writes to the injected writer's stream, not bare print."""
        buf = StringIO()
        custom = OutputWriter(OutputConfig(file=buf))
        producer = BaseProducer(writer=custom)
        producer.print_logs(["line1", "line2"])
        output = buf.getvalue()
        self.assertIn("line1", output)
        self.assertIn("line2", output)


class TestSafeProcessorBasic(unittest.TestCase):
    """SafeProcessor wraps _process_safe with error handling."""

    def test_success_path_returns_envelope_ok(self):
        class OkProcessor(SafeProcessor):
            def _process_safe(self, payload):
                return payload * 2

        result = OkProcessor().process(5)
        self.assertTrue(result.ok())
        self.assertEqual(result.payload, 10)

    def test_exception_path_returns_error_envelope(self):
        class BoomProcessor(SafeProcessor):
            def _process_safe(self, payload):
                raise ValueError("oops")

        result = BoomProcessor().process("anything")
        self.assertFalse(result.ok())
        self.assertIn("oops", result.diagnostics.get("message", ""))


if __name__ == "__main__":
    unittest.main()
