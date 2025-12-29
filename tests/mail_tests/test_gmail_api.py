"""Tests for mail/gmail_api.py Gmail client wrapper."""

import base64
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

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


class TestGmailClientWithMockedService(unittest.TestCase):
    """Tests for GmailClient methods using mocked service."""

    def setUp(self):
        self.client = GmailClient("/fake/creds.json", "/fake/token.json")
        self.mock_service = MagicMock()
        self.client._service = self.mock_service

    def test_get_profile(self):
        self.mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "user@example.com"
        }
        result = self.client.get_profile()
        self.assertEqual(result["emailAddress"], "user@example.com")

    def test_list_labels(self):
        self.mock_service.users().labels().list().execute.return_value = {
            "labels": [
                {"id": "INBOX", "name": "INBOX"},
                {"id": "LBL_1", "name": "CustomLabel"},
            ]
        }
        result = self.client.list_labels()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], "INBOX")

    def test_get_label_id_map(self):
        self.mock_service.users().labels().list().execute.return_value = {
            "labels": [
                {"id": "LBL_A", "name": "Work"},
                {"id": "LBL_B", "name": "Personal"},
            ]
        }
        result = self.client.get_label_id_map()
        self.assertEqual(result["Work"], "LBL_A")
        self.assertEqual(result["Personal"], "LBL_B")

    def test_create_label(self):
        self.mock_service.users().labels().create().execute.return_value = {
            "id": "NEW_LBL",
            "name": "NewLabel",
        }
        result = self.client.create_label("NewLabel", color={"backgroundColor": "#ff0000"})
        self.assertEqual(result["id"], "NEW_LBL")

    def test_update_label(self):
        self.mock_service.users().labels().update().execute.return_value = {
            "id": "LBL_1",
            "name": "UpdatedLabel",
        }
        result = self.client.update_label("LBL_1", {"name": "UpdatedLabel"})
        self.assertEqual(result["name"], "UpdatedLabel")

    def test_delete_label(self):
        self.client.delete_label("LBL_1")
        self.mock_service.users().labels().delete.assert_called()

    def test_list_filters(self):
        self.mock_service.users().settings().filters().list().execute.return_value = {
            "filter": [
                {"id": "F1", "criteria": {"from": "test@example.com"}},
            ]
        }
        result = self.client.list_filters()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "F1")

    def test_list_filters_alternative_key(self):
        # Some API versions use "filters" instead of "filter"
        self.mock_service.users().settings().filters().list().execute.return_value = {
            "filters": [
                {"id": "F2", "criteria": {"to": "me@example.com"}},
            ]
        }
        result = self.client.list_filters()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "F2")

    def test_create_filter(self):
        self.mock_service.users().settings().filters().create().execute.return_value = {
            "id": "NEW_F",
            "criteria": {"from": "sender@test.com"},
            "action": {"addLabelIds": ["LBL_1"]},
        }
        result = self.client.create_filter(
            criteria={"from": "sender@test.com"},
            action={"addLabelIds": ["LBL_1"]},
        )
        self.assertEqual(result["id"], "NEW_F")

    def test_delete_filter(self):
        self.client.delete_filter("F1")
        self.mock_service.users().settings().filters().delete.assert_called()

    def test_list_forwarding_addresses(self):
        self.mock_service.users().settings().forwardingAddresses().list().execute.return_value = {
            "forwardingAddresses": [
                {"forwardingEmail": "forward@example.com", "verificationStatus": "accepted"},
            ]
        }
        result = self.client.list_forwarding_addresses()
        self.assertEqual(result, ["forward@example.com"])

    def test_get_verified_forwarding_addresses(self):
        self.mock_service.users().settings().forwardingAddresses().list().execute.return_value = {
            "forwardingAddresses": [
                {"forwardingEmail": "verified@example.com", "verificationStatus": "accepted"},
                {"forwardingEmail": "pending@example.com", "verificationStatus": "pending"},
            ]
        }
        result = self.client.get_verified_forwarding_addresses()
        self.assertEqual(result, ["verified@example.com"])

    def test_list_send_as(self):
        self.mock_service.users().settings().sendAs().list().execute.return_value = {
            "sendAs": [
                {"sendAsEmail": "user@example.com", "isPrimary": True, "signature": "<p>Sig</p>"},
            ]
        }
        result = self.client.list_send_as()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sendAsEmail"], "user@example.com")

    def test_list_signatures(self):
        self.mock_service.users().settings().sendAs().list().execute.return_value = {
            "sendAs": [
                {"sendAsEmail": "user@example.com", "isPrimary": True, "signature": "<p>Sig</p>", "displayName": "User"},
            ]
        }
        result = self.client.list_signatures()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sendAsEmail"], "user@example.com")
        self.assertEqual(result[0]["isPrimary"], True)
        self.assertIn("signature", result[0])

    def test_update_signature(self):
        self.mock_service.users().settings().sendAs().patch().execute.return_value = {
            "sendAsEmail": "user@example.com",
            "signature": "<p>New Sig</p>",
        }
        result = self.client.update_signature("user@example.com", "<p>New Sig</p>")
        self.assertIn("signature", result)

    def test_batch_modify_messages(self):
        self.client.batch_modify_messages(
            ids=["m1", "m2"],
            add_label_ids=["LBL_1"],
            remove_label_ids=["INBOX"],
        )
        self.mock_service.users().messages().batchModify.assert_called()

    def test_batch_modify_messages_empty_ids(self):
        # Should not call API with empty ids
        self.client.batch_modify_messages(ids=[], add_label_ids=["LBL_1"])
        self.mock_service.users().messages().batchModify.assert_not_called()

    def test_get_message(self):
        self.mock_service.users().messages().get().execute.return_value = {
            "id": "m1",
            "payload": {"headers": []},
        }
        result = self.client.get_message("m1")
        self.assertEqual(result["id"], "m1")

    def test_send_message_raw(self):
        self.mock_service.users().messages().send().execute.return_value = {"id": "SENT_1"}
        raw = b"From: test@example.com\r\nSubject: Test\r\n\r\nBody"
        result = self.client.send_message_raw(raw)
        self.assertEqual(result["id"], "SENT_1")

    def test_create_draft_raw(self):
        self.mock_service.users().drafts().create().execute.return_value = {"id": "DRAFT_1"}
        raw = b"From: test@example.com\r\nSubject: Draft\r\n\r\nBody"
        result = self.client.create_draft_raw(raw)
        self.assertEqual(result["id"], "DRAFT_1")

    def test_get_auto_forwarding(self):
        self.mock_service.users().settings().getAutoForwarding().execute.return_value = {
            "enabled": True,
            "emailAddress": "forward@example.com",
            "disposition": "archive",
        }
        result = self.client.get_auto_forwarding()
        self.assertTrue(result["enabled"])
        self.assertEqual(result["emailAddress"], "forward@example.com")

    def test_update_auto_forwarding(self):
        self.mock_service.users().settings().updateAutoForwarding().execute.return_value = {
            "enabled": True,
            "emailAddress": "new@example.com",
            "disposition": "trash",
        }
        result = self.client.update_auto_forwarding(
            enabled=True,
            email="new@example.com",
            disposition="trash",
        )
        self.assertTrue(result["enabled"])


class TestGmailClientEnsureLabel(unittest.TestCase):
    """Tests for ensure_label method."""

    def setUp(self):
        self.client = GmailClient("/fake/creds.json", "/fake/token.json")
        self.mock_service = MagicMock()
        self.client._service = self.mock_service

    def test_ensure_label_returns_existing_id(self):
        self.mock_service.users().labels().list().execute.return_value = {
            "labels": [{"id": "LBL_EXISTING", "name": "ExistingLabel"}]
        }
        result = self.client.ensure_label("ExistingLabel")
        self.assertEqual(result, "LBL_EXISTING")
        self.mock_service.users().labels().create.assert_not_called()

    def test_ensure_label_creates_new(self):
        self.mock_service.users().labels().list().execute.return_value = {
            "labels": []
        }
        self.mock_service.users().labels().create().execute.return_value = {
            "id": "NEW_LBL",
            "name": "NewLabel",
        }
        result = self.client.ensure_label("NewLabel")
        self.assertEqual(result, "NEW_LBL")


if __name__ == "__main__":
    unittest.main()
