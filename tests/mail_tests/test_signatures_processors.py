"""Tests for mail/signatures/processors.py signature processing functionality."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from mail.signatures.processors import (
    _SafeDict,
    _render_template,
    SignaturesExportProcessor,
    SignaturesExportResult,
    SignaturesSyncProcessor,
    SignaturesSyncResult,
    SignaturesNormalizeProcessor,
    SignaturesNormalizeResult,
)
from mail.signatures.consumers import (
    SignaturesExportPayload,
    SignaturesSyncPayload,
    SignaturesNormalizePayload,
)


class FakeMailContext:
    """Fake MailContext for testing."""

    def __init__(self, gmail_client: Optional[Any] = None):
        self._gmail_client = gmail_client

    def get_gmail_client(self):
        if self._gmail_client is None:
            raise RuntimeError("No Gmail client configured")
        return self._gmail_client


class FakeGmailClient:
    """Fake Gmail client for testing signatures."""

    def __init__(self, signatures: Optional[List[Dict[str, Any]]] = None):
        self._signatures = signatures or []
        self._updated: Dict[str, str] = {}

    def authenticate(self):
        pass

    def list_signatures(self) -> List[Dict[str, Any]]:
        return self._signatures

    def update_signature(self, email: str, html: str) -> Dict[str, Any]:
        self._updated[email] = html
        return {"sendAsEmail": email, "signature": html}


class TestSafeDict(unittest.TestCase):
    """Tests for _SafeDict class."""

    def test_returns_value_for_existing_key(self):
        d = _SafeDict(name="John", email="john@example.com")
        self.assertEqual(d["name"], "John")
        self.assertEqual(d["email"], "john@example.com")

    def test_returns_placeholder_for_missing_key(self):
        d = _SafeDict(name="John")
        self.assertEqual(d["missing"], "{missing}")

    def test_placeholder_preserves_key_name(self):
        d = _SafeDict()
        self.assertEqual(d["displayName"], "{displayName}")
        self.assertEqual(d["email"], "{email}")


class TestRenderTemplate(unittest.TestCase):
    """Tests for _render_template function."""

    def test_substitutes_variables(self):
        template = "<p>Hello {name}, your email is {email}</p>"
        result = _render_template(template, {"name": "John", "email": "john@test.com"})
        self.assertEqual(result, "<p>Hello John, your email is john@test.com</p>")

    def test_preserves_missing_variables(self):
        template = "<p>Hello {name}, {greeting}</p>"
        result = _render_template(template, {"name": "John"})
        self.assertEqual(result, "<p>Hello John, {greeting}</p>")

    def test_handles_empty_substitutions(self):
        template = "<p>Hello {name}</p>"
        result = _render_template(template, {})
        self.assertEqual(result, "<p>Hello {name}</p>")

    def test_handles_empty_template(self):
        result = _render_template("", {"name": "John"})
        self.assertEqual(result, "")


class TestSignaturesExportResult(unittest.TestCase):
    """Tests for SignaturesExportResult dataclass."""

    def test_default_values(self):
        result = SignaturesExportResult()
        self.assertEqual(result.gmail_signatures, [])
        self.assertIsNone(result.default_html)
        self.assertIsNone(result.ios_asset_path)

    def test_with_values(self):
        result = SignaturesExportResult(
            gmail_signatures=[{"sendAs": "test@example.com"}],
            default_html="<p>Sig</p>",
            out_path=Path("/tmp/out"),
        )
        self.assertEqual(len(result.gmail_signatures), 1)
        self.assertEqual(result.default_html, "<p>Sig</p>")


class TestSignaturesSyncResult(unittest.TestCase):
    """Tests for SignaturesSyncResult dataclass."""

    def test_default_values(self):
        result = SignaturesSyncResult()
        self.assertEqual(result.gmail_updates, [])
        self.assertIsNone(result.ios_asset_written)
        self.assertIsNone(result.outlook_note_written)
        self.assertFalse(result.dry_run)

    def test_dry_run_flag(self):
        result = SignaturesSyncResult(dry_run=True)
        self.assertTrue(result.dry_run)


class TestSignaturesNormalizeResult(unittest.TestCase):
    """Tests for SignaturesNormalizeResult dataclass."""

    def test_default_values(self):
        result = SignaturesNormalizeResult()
        self.assertTrue(result.success)

    def test_with_path(self):
        result = SignaturesNormalizeResult(out_path=Path("/tmp/sig.html"), success=True)
        self.assertEqual(result.out_path, Path("/tmp/sig.html"))


class TestSignaturesExportProcessor(unittest.TestCase):
    """Tests for SignaturesExportProcessor."""

    def test_exports_gmail_signatures(self):
        with tempfile.TemporaryDirectory() as td:
            client = FakeGmailClient(signatures=[
                {"sendAsEmail": "user@example.com", "isPrimary": True, "signature": "<p>Primary sig</p>", "displayName": "User"},
                {"sendAsEmail": "alias@example.com", "isPrimary": False, "signature": "<p>Alias sig</p>", "displayName": "Alias"},
            ])
            context = FakeMailContext(gmail_client=client)
            payload = SignaturesExportPayload(
                context=context,
                out_path=Path(td) / "signatures.yaml",
                assets_dir=Path(td) / "assets",
            )

            processor = SignaturesExportProcessor()
            result = processor.process(payload)

            self.assertEqual(result.status, "success")
            self.assertEqual(len(result.payload.gmail_signatures), 2)
            self.assertEqual(result.payload.default_html, "<p>Primary sig</p>")
            self.assertTrue(result.payload.ios_asset_path.exists())

    def test_handles_no_gmail_client(self):
        with tempfile.TemporaryDirectory() as td:
            context = FakeMailContext(gmail_client=None)
            payload = SignaturesExportPayload(
                context=context,
                out_path=Path(td) / "signatures.yaml",
                assets_dir=Path(td) / "assets",
            )

            processor = SignaturesExportProcessor()
            result = processor.process(payload)

            self.assertEqual(result.status, "success")
            self.assertEqual(result.payload.gmail_signatures, [])

    def test_handles_no_primary_signature(self):
        with tempfile.TemporaryDirectory() as td:
            client = FakeGmailClient(signatures=[
                {"sendAsEmail": "user@example.com", "isPrimary": False, "signature": "<p>Not primary</p>"},
            ])
            context = FakeMailContext(gmail_client=client)
            payload = SignaturesExportPayload(
                context=context,
                out_path=Path(td) / "signatures.yaml",
                assets_dir=Path(td) / "assets",
            )

            processor = SignaturesExportProcessor()
            result = processor.process(payload)

            self.assertEqual(result.status, "success")
            self.assertIsNone(result.payload.default_html)
            self.assertIsNone(result.payload.ios_asset_path)


class TestSignaturesSyncProcessor(unittest.TestCase):
    """Tests for SignaturesSyncProcessor."""

    def test_sync_with_default_html_dry_run(self):
        client = FakeGmailClient(signatures=[
            {"sendAsEmail": "user@example.com", "isPrimary": True, "displayName": "User"},
        ])
        context = FakeMailContext(gmail_client=client)
        config = {
            "signatures": {
                "default_html": "<p>Hello {displayName}</p>",
            }
        }
        payload = SignaturesSyncPayload(
            context=context,
            config=config,
            dry_run=True,
        )

        processor = SignaturesSyncProcessor()
        result = processor.process(payload)

        self.assertEqual(result.status, "success")
        self.assertTrue(result.payload.dry_run)
        self.assertEqual(len(result.payload.gmail_updates), 1)
        self.assertIn("Would update", result.payload.gmail_updates[0])

    def test_sync_with_default_html_live(self):
        client = FakeGmailClient(signatures=[
            {"sendAsEmail": "user@example.com", "isPrimary": True, "displayName": "User"},
        ])
        context = FakeMailContext(gmail_client=client)
        config = {
            "signatures": {
                "default_html": "<p>Hello {displayName}</p>",
            }
        }
        payload = SignaturesSyncPayload(
            context=context,
            config=config,
            dry_run=False,
        )

        processor = SignaturesSyncProcessor()
        result = processor.process(payload)

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.payload.gmail_updates), 1)
        self.assertIn("Updated", result.payload.gmail_updates[0])
        self.assertIn("user@example.com", client._updated)

    def test_sync_with_specific_gmail_entries(self):
        client = FakeGmailClient(signatures=[
            {"sendAsEmail": "user@example.com", "displayName": "User"},
            {"sendAsEmail": "alias@example.com", "displayName": "Alias"},
        ])
        context = FakeMailContext(gmail_client=client)
        config = {
            "signatures": {
                "gmail": [
                    {"sendAs": "user@example.com", "signature_html": "<p>User sig</p>"},
                    {"sendAs": "alias@example.com", "signature_html": "<p>Alias sig</p>"},
                ]
            }
        }
        payload = SignaturesSyncPayload(
            context=context,
            config=config,
            dry_run=False,
        )

        processor = SignaturesSyncProcessor()
        result = processor.process(payload)

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.payload.gmail_updates), 2)

    def test_sync_filters_by_send_as(self):
        client = FakeGmailClient(signatures=[
            {"sendAsEmail": "user@example.com", "displayName": "User"},
            {"sendAsEmail": "alias@example.com", "displayName": "Alias"},
        ])
        context = FakeMailContext(gmail_client=client)
        config = {
            "signatures": {
                "gmail": [
                    {"sendAs": "user@example.com", "signature_html": "<p>User sig</p>"},
                    {"sendAs": "alias@example.com", "signature_html": "<p>Alias sig</p>"},
                ]
            }
        }
        payload = SignaturesSyncPayload(
            context=context,
            config=config,
            dry_run=False,
            send_as="user@example.com",
        )

        processor = SignaturesSyncProcessor()
        result = processor.process(payload)

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.payload.gmail_updates), 1)
        self.assertIn("user@example.com", result.payload.gmail_updates[0])

    def test_sync_writes_ios_asset(self):
        context = FakeMailContext(gmail_client=None)
        config = {
            "signatures": {
                "default_html": "<p>Signature</p>",
                "ios": True,
            }
        }
        payload = SignaturesSyncPayload(
            context=context,
            config=config,
            dry_run=False,
        )

        processor = SignaturesSyncProcessor()
        with patch.object(Path, "write_text"):
            with patch.object(Path, "mkdir"):
                result = processor.process(payload)

        self.assertEqual(result.status, "success")
        self.assertIsNotNone(result.payload.ios_asset_written)

    def test_sync_writes_outlook_note(self):
        context = FakeMailContext(gmail_client=None)
        config = {
            "signatures": {
                "default_html": "<p>Signature</p>",
            }
        }
        payload = SignaturesSyncPayload(
            context=context,
            config=config,
            dry_run=False,
        )

        processor = SignaturesSyncProcessor()
        with patch.object(Path, "write_text"):
            with patch.object(Path, "mkdir"):
                result = processor.process(payload)

        self.assertEqual(result.status, "success")
        self.assertIsNotNone(result.payload.outlook_note_written)


class TestSignaturesNormalizeProcessor(unittest.TestCase):
    """Tests for SignaturesNormalizeProcessor."""

    def test_normalizes_default_html(self):
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "signature.html"
            config = {
                "signatures": {
                    "default_html": "<p>Hello {name}, from {company}</p>",
                }
            }
            payload = SignaturesNormalizePayload(
                config=config,
                out_html=out_path,
                variables={"name": "John", "company": "Acme"},
            )

            processor = SignaturesNormalizeProcessor()
            result = processor.process(payload)

            self.assertEqual(result.status, "success")
            self.assertTrue(result.payload.success)
            self.assertTrue(out_path.exists())
            content = out_path.read_text()
            self.assertIn("Hello John", content)
            self.assertIn("Acme", content)

    def test_normalizes_from_gmail_list(self):
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "signature.html"
            config = {
                "signatures": {
                    "gmail": [
                        {"sendAs": "user@example.com", "signature_html": "<p>Gmail sig for {name}</p>"},
                    ]
                }
            }
            payload = SignaturesNormalizePayload(
                config=config,
                out_html=out_path,
                variables={"name": "Jane"},
            )

            processor = SignaturesNormalizeProcessor()
            result = processor.process(payload)

            self.assertEqual(result.status, "success")
            content = out_path.read_text()
            self.assertIn("Gmail sig for Jane", content)

    def test_returns_error_when_no_signature_html(self):
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "signature.html"
            config = {"signatures": {}}
            payload = SignaturesNormalizePayload(
                config=config,
                out_html=out_path,
                variables={},
            )

            processor = SignaturesNormalizeProcessor()
            result = processor.process(payload)

            self.assertEqual(result.status, "error")
            self.assertIn("No signature HTML found", result.diagnostics["error"])

    def test_returns_error_when_empty_config(self):
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "signature.html"
            payload = SignaturesNormalizePayload(
                config={},
                out_html=out_path,
                variables={},
            )

            processor = SignaturesNormalizeProcessor()
            result = processor.process(payload)

            self.assertEqual(result.status, "error")

    def test_preserves_unsubstituted_variables(self):
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "signature.html"
            config = {
                "signatures": {
                    "default_html": "<p>{name} - {title}</p>",
                }
            }
            payload = SignaturesNormalizePayload(
                config=config,
                out_html=out_path,
                variables={"name": "John"},  # title not provided
            )

            processor = SignaturesNormalizeProcessor()
            result = processor.process(payload)

            self.assertEqual(result.status, "success")
            content = out_path.read_text()
            self.assertIn("John", content)
            self.assertIn("{title}", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
