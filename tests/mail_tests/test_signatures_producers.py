"""Tests for mail/signatures/producers.py signature output producers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.pipeline import ResultEnvelope
from tests.fixtures import capture_stdout

from mail.signatures.producers import (
    SignaturesExportProducer,
    SignaturesSyncProducer,
    SignaturesNormalizeProducer,
)
from mail.signatures.processors import (
    SignaturesExportResult,
    SignaturesSyncResult,
    SignaturesNormalizeResult,
)


class TestSignaturesExportProducer(unittest.TestCase):
    """Tests for SignaturesExportProducer."""

    def test_prints_error_on_failure(self):
        producer = SignaturesExportProducer()
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "Gmail auth failed"},
        )
        with capture_stdout() as buf:
            producer.produce(result)
        self.assertIn("Gmail auth failed", buf.getvalue())

    def test_prints_default_error_when_no_diagnostics(self):
        producer = SignaturesExportProducer()
        result = ResultEnvelope(status="error", payload=None)
        with capture_stdout() as buf:
            producer.produce(result)
        self.assertIn("Signatures export failed", buf.getvalue())

    def test_writes_yaml_and_prints_path(self):
        producer = SignaturesExportProducer()
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "signatures.yaml"
            payload = SignaturesExportResult(
                gmail_signatures=[
                    {"sendAs": "user@example.com", "signature_html": "<p>Sig</p>"}
                ],
                default_html="<p>Default</p>",
                out_path=out_path,
            )
            result = ResultEnvelope(status="success", payload=payload)
            with capture_stdout() as buf:
                producer.produce(result)
            output = buf.getvalue()
            self.assertIn("Exported signatures to", output)
            self.assertIn(str(out_path), output)
            self.assertTrue(out_path.exists())

    def test_includes_ios_asset_in_message(self):
        producer = SignaturesExportProducer()
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "signatures.yaml"
            ios_path = Path(td) / "ios_signature.html"
            payload = SignaturesExportResult(
                gmail_signatures=[],
                default_html="<p>Default</p>",
                out_path=out_path,
                ios_asset_path=ios_path,
            )
            result = ResultEnvelope(status="success", payload=payload)
            with capture_stdout() as buf:
                producer.produce(result)
            output = buf.getvalue()
            self.assertIn("iOS asset at", output)
            self.assertIn(str(ios_path), output)

    def test_writes_empty_signatures_list(self):
        producer = SignaturesExportProducer()
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "signatures.yaml"
            payload = SignaturesExportResult(
                gmail_signatures=[],
                out_path=out_path,
            )
            result = ResultEnvelope(status="success", payload=payload)
            with capture_stdout():
                producer.produce(result)
            self.assertTrue(out_path.exists())
            content = out_path.read_text()
            self.assertIn("signatures:", content)


class TestSignaturesSyncProducer(unittest.TestCase):
    """Tests for SignaturesSyncProducer."""

    def test_prints_error_on_failure(self):
        producer = SignaturesSyncProducer()
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "Sync failed"},
        )
        with capture_stdout() as buf:
            producer.produce(result)
        self.assertIn("Sync failed", buf.getvalue())

    def test_prints_default_error_when_no_diagnostics(self):
        producer = SignaturesSyncProducer()
        result = ResultEnvelope(status="error", payload=None)
        with capture_stdout() as buf:
            producer.produce(result)
        self.assertIn("Signatures sync failed", buf.getvalue())

    def test_prints_gmail_updates(self):
        producer = SignaturesSyncProducer()
        payload = SignaturesSyncResult(
            gmail_updates=[
                "Updated user@example.com",
                "Updated alias@example.com",
            ],
            dry_run=False,
        )
        result = ResultEnvelope(status="success", payload=payload)
        with capture_stdout() as buf:
            producer.produce(result)
        output = buf.getvalue()
        self.assertIn("Updated user@example.com", output)
        self.assertIn("Updated alias@example.com", output)

    def test_prints_dry_run_updates(self):
        producer = SignaturesSyncProducer()
        payload = SignaturesSyncResult(
            gmail_updates=["Would update user@example.com"],
            dry_run=True,
        )
        result = ResultEnvelope(status="success", payload=payload)
        with capture_stdout() as buf:
            producer.produce(result)
        output = buf.getvalue()
        self.assertIn("Would update user@example.com", output)

    def test_prints_ios_asset_written(self):
        producer = SignaturesSyncProducer()
        ios_path = Path("/tmp/ios_signature.html")
        payload = SignaturesSyncResult(
            gmail_updates=[],
            ios_asset_written=ios_path,
        )
        result = ResultEnvelope(status="success", payload=payload)
        with capture_stdout() as buf:
            producer.produce(result)
        output = buf.getvalue()
        self.assertIn("Wrote iOS signature asset to", output)
        self.assertIn(str(ios_path), output)

    def test_prints_outlook_note_written(self):
        producer = SignaturesSyncProducer()
        note_path = Path("/tmp/OUTLOOK_README.txt")
        payload = SignaturesSyncResult(
            gmail_updates=[],
            outlook_note_written=note_path,
        )
        result = ResultEnvelope(status="success", payload=payload)
        with capture_stdout() as buf:
            producer.produce(result)
        output = buf.getvalue()
        self.assertIn("Wrote Outlook guidance to", output)
        self.assertIn(str(note_path), output)

    def test_handles_empty_updates(self):
        producer = SignaturesSyncProducer()
        payload = SignaturesSyncResult(gmail_updates=[])
        result = ResultEnvelope(status="success", payload=payload)
        with capture_stdout() as buf:
            producer.produce(result)
        # Should not raise, output may be empty
        self.assertIsNotNone(buf.getvalue())


class TestSignaturesNormalizeProducer(unittest.TestCase):
    """Tests for SignaturesNormalizeProducer."""

    def test_prints_error_on_failure(self):
        producer = SignaturesNormalizeProducer()
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "No signature HTML found"},
        )
        with capture_stdout() as buf:
            producer.produce(result)
        self.assertIn("No signature HTML found", buf.getvalue())

    def test_prints_default_error_when_no_diagnostics(self):
        producer = SignaturesNormalizeProducer()
        result = ResultEnvelope(status="error", payload=None)
        with capture_stdout() as buf:
            producer.produce(result)
        self.assertIn("Signatures normalize failed", buf.getvalue())

    def test_prints_output_path(self):
        producer = SignaturesNormalizeProducer()
        out_path = Path("/tmp/signature.html")
        payload = SignaturesNormalizeResult(out_path=out_path, success=True)
        result = ResultEnvelope(status="success", payload=payload)
        with capture_stdout() as buf:
            producer.produce(result)
        output = buf.getvalue()
        self.assertIn("Wrote normalized signature to", output)
        self.assertIn(str(out_path), output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
