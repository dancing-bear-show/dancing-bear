"""Tests for core/pipeline.py."""

from __future__ import annotations

import unittest

from core.pipeline import ResultEnvelope


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


if __name__ == "__main__":
    unittest.main()
