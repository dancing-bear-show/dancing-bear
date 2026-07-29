"""Tests for GmailClient initialization, headers, service property, and encode/decode."""

import base64
import os
import tempfile
import unittest
from unittest.mock import patch

from mail.gmail_api import (
    GmailClient,
    SCOPES,
    ensure_google_api,
)


class TestScopes(unittest.TestCase):
    """Tests for Gmail API scopes."""

    def test_scopes_include_required_permissions(self):
        scope_texts = [s.split("/")[-1] for s in SCOPES]
        self.assertIn("gmail.settings.basic", scope_texts)
        self.assertIn("gmail.labels", scope_texts)
        self.assertIn("gmail.readonly", scope_texts)
        self.assertIn("gmail.modify", scope_texts)
        self.assertIn("gmail.compose", scope_texts)
        self.assertIn("gmail.send", scope_texts)


class TestEnsureGoogleApi(unittest.TestCase):
    """Tests for ensure_google_api function."""

    def test_raises_when_dependencies_missing(self):
        with patch("mail.gmail_api.Credentials", None), \
             patch("mail.gmail_api.InstalledAppFlow", None), \
             patch("mail.gmail_api.build", None), \
             patch("mail.gmail_api.Request", None):
            with self.assertRaises(RuntimeError) as ctx:
                ensure_google_api()
            self.assertIn("Google API libraries not installed", str(ctx.exception))


class TestGmailClientInit(unittest.TestCase):
    """Tests for GmailClient initialization."""

    def test_init_expands_paths(self):
        with patch.object(os.path, "expanduser", side_effect=lambda x: x.replace("~", "/home/user")):
            client = GmailClient("~/creds.json", "~/token.json")
            self.assertIn("/home/user", client.credentials_path)
            self.assertIn("/home/user", client.token_path)

    def test_init_with_cache_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client = GmailClient("/fake/creds.json", "/fake/token.json", cache_dir=tmpdir)
            self.assertIsNotNone(client.cache)
            self.assertEqual(client.cache_dir, tmpdir)

    def test_init_without_cache_dir(self):
        client = GmailClient("/fake/creds.json", "/fake/token.json", cache_dir=None)
        self.assertIsNone(client.cache)


class TestGmailClientHeadersToDict(unittest.TestCase):
    """Tests for GmailClient.headers_to_dict static method."""

    def test_parses_headers(self):
        msg = {
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "To", "value": "recipient@example.com"},
                    {"name": "Subject", "value": "Test Subject"},
                ]
            }
        }
        result = GmailClient.headers_to_dict(msg)
        self.assertEqual(result["from"], "sender@example.com")
        self.assertEqual(result["to"], "recipient@example.com")
        self.assertEqual(result["subject"], "Test Subject")

    def test_lowercase_header_names(self):
        msg = {
            "payload": {
                "headers": [
                    {"name": "Content-Type", "value": "text/plain"},
                    {"name": "X-Custom-Header", "value": "custom value"},
                ]
            }
        }
        result = GmailClient.headers_to_dict(msg)
        self.assertEqual(result["content-type"], "text/plain")
        self.assertEqual(result["x-custom-header"], "custom value")

    def test_handles_missing_payload(self):
        result = GmailClient.headers_to_dict({})
        self.assertEqual(result, {})

    def test_handles_missing_headers(self):
        result = GmailClient.headers_to_dict({"payload": {}})
        self.assertEqual(result, {})

    def test_handles_none_headers(self):
        result = GmailClient.headers_to_dict({"payload": {"headers": None}})
        self.assertEqual(result, {})

    def test_skips_headers_without_name_or_value(self):
        msg = {
            "payload": {
                "headers": [
                    {"name": "Valid", "value": "value"},
                    {"name": None, "value": "orphan value"},
                    {"name": "NoValue"},
                ]
            }
        }
        result = GmailClient.headers_to_dict(msg)
        self.assertEqual(len(result), 1)
        self.assertEqual(result["valid"], "value")


class TestGmailClientServiceProperty(unittest.TestCase):
    """Tests for GmailClient.service property."""

    def test_service_raises_when_not_authenticated(self):
        client = GmailClient("/fake/creds.json", "/fake/token.json")
        with self.assertRaises(RuntimeError) as ctx:
            _ = client.service
        self.assertIn("not authenticated", str(ctx.exception))


class TestGmailClientEncodeDecode(unittest.TestCase):
    """Tests for message encoding methods."""

    def test_encode_message_raw(self):
        client = GmailClient("/fake/creds.json", "/fake/token.json")
        raw_bytes = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
        encoded = client._encode_message_raw(raw_bytes)

        # Verify it's valid base64
        decoded = base64.urlsafe_b64decode(encoded.encode("utf-8"))
        self.assertEqual(decoded, raw_bytes)


if __name__ == "__main__":
    unittest.main()
