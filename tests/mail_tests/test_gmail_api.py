"""Tests for mail/gmail_api.py Gmail client wrapper."""

import base64
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

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


class TestGmailClientListMessageIds(unittest.TestCase):
    """Tests for list_message_ids with pagination."""

    def setUp(self):
        self.client = GmailClient("/fake/creds.json", "/fake/token.json")
        self.mock_service = MagicMock()
        self.client._service = self.mock_service

    @patch("mail.paging.paginate_gmail_messages")
    @patch("mail.paging.gather_pages")
    def test_list_message_ids_with_query(self, mock_gather, mock_paginate):
        mock_paginate.return_value = iter([["m1", "m2"]])
        mock_gather.return_value = ["m1", "m2"]

        result = self.client.list_message_ids(query="is:unread", max_pages=2, page_size=100)

        self.assertEqual(result, ["m1", "m2"])
        mock_paginate.assert_called_once()
        mock_gather.assert_called_once_with(mock_paginate.return_value, max_pages=2)

    @patch("mail.paging.paginate_gmail_messages")
    @patch("mail.paging.gather_pages")
    def test_list_message_ids_with_labels(self, mock_gather, mock_paginate):
        mock_paginate.return_value = iter([["m3", "m4"]])
        mock_gather.return_value = ["m3", "m4"]

        result = self.client.list_message_ids(label_ids=["INBOX"], max_pages=1, page_size=500)

        self.assertEqual(result, ["m3", "m4"])
        mock_gather.assert_called_once_with(mock_paginate.return_value, max_pages=1)


class TestGmailClientMessageMetadata(unittest.TestCase):
    """Tests for message metadata retrieval with caching."""

    def setUp(self):
        self.client = GmailClient("/fake/creds.json", "/fake/token.json")
        self.mock_service = MagicMock()
        self.client._service = self.mock_service

    def test_get_message_metadata_without_cache(self):
        self.mock_service.users().messages().get().execute.return_value = {
            "id": "m1",
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@test.com"},
                    {"name": "Subject", "value": "Test"},
                ]
            },
        }
        result = self.client.get_message_metadata("m1", use_cache=False)
        self.assertEqual(result["id"], "m1")

    def test_get_message_metadata_with_cache_miss(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.client = GmailClient("/fake/creds.json", "/fake/token.json", cache_dir=tmpdir)
            self.client._service = self.mock_service

            self.mock_service.users().messages().get().execute.return_value = {
                "id": "m2",
                "payload": {"headers": []},
            }

            result = self.client.get_message_metadata("m2", use_cache=True)
            self.assertEqual(result["id"], "m2")

    def test_get_message_metadata_with_cache_hit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.client = GmailClient("/fake/creds.json", "/fake/token.json", cache_dir=tmpdir)
            self.client._service = self.mock_service

            # First call - cache miss
            self.mock_service.users().messages().get().execute.return_value = {
                "id": "m3",
                "payload": {"headers": []},
            }
            result1 = self.client.get_message_metadata("m3", use_cache=True)

            # Second call - should use cache
            result2 = self.client.get_message_metadata("m3", use_cache=True)

            self.assertEqual(result1, result2)
            # API should only be called once
            self.assertEqual(self.mock_service.users().messages().get().execute.call_count, 1)

    def test_get_messages_metadata_batch(self):
        self.mock_service.users().messages().get().execute.side_effect = [
            {"id": "m1", "payload": {"headers": []}},
            {"id": "m2", "payload": {"headers": []}},
        ]
        result = self.client.get_messages_metadata(["m1", "m2"], use_cache=False)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], "m1")
        self.assertEqual(result[1]["id"], "m2")

    def test_get_messages_metadata_with_error(self):
        # First succeeds, second fails, third succeeds
        self.mock_service.users().messages().get().execute.side_effect = [
            {"id": "m1", "payload": {"headers": []}},
            RuntimeError("API error"),
            {"id": "m3", "payload": {"headers": []}},
        ]
        result = self.client.get_messages_metadata(["m1", "m2", "m3"], use_cache=False)
        # Should skip m2 due to error
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], "m1")
        self.assertEqual(result[1]["id"], "m3")


class TestGmailClientGetMessageText(unittest.TestCase):
    """Tests for get_message_text complex parsing."""

    def setUp(self):
        self.client = GmailClient("/fake/creds.json", "/fake/token.json")
        self.mock_service = MagicMock()
        self.client._service = self.mock_service

    def test_get_message_text_plain(self):
        # Single-part text/plain message
        plain_text = "Hello World"
        encoded = base64.urlsafe_b64encode(plain_text.encode("utf-8")).decode("utf-8")

        self.mock_service.users().messages().get().execute.return_value = {
            "id": "m1",
            "payload": {
                "mimeType": "text/plain",
                "body": {"data": encoded},
            },
        }

        result = self.client.get_message_text("m1")
        self.assertEqual(result, plain_text)

    def test_get_message_text_html(self):
        # Single-part text/html message
        html_text = "<p>Hello <strong>World</strong></p>"
        encoded = base64.urlsafe_b64encode(html_text.encode("utf-8")).decode("utf-8")

        self.mock_service.users().messages().get().execute.return_value = {
            "id": "m2",
            "payload": {
                "mimeType": "text/html",
                "body": {"data": encoded},
            },
        }

        result = self.client.get_message_text("m2")
        # Should be converted to plain text
        self.assertIn("Hello", result)
        self.assertIn("World", result)
        # Should not have HTML tags
        self.assertNotIn("<p>", result)

    def test_get_message_text_multipart_prefers_plain(self):
        # Multipart message with both plain and HTML
        plain_text = "Plain version"
        html_text = "<p>HTML version</p>"
        plain_encoded = base64.urlsafe_b64encode(plain_text.encode("utf-8")).decode("utf-8")
        html_encoded = base64.urlsafe_b64encode(html_text.encode("utf-8")).decode("utf-8")

        self.mock_service.users().messages().get().execute.return_value = {
            "id": "m3",
            "payload": {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": plain_encoded}},
                    {"mimeType": "text/html", "body": {"data": html_encoded}},
                ],
            },
        }

        result = self.client.get_message_text("m3")
        # Should prefer plain text
        self.assertEqual(result, plain_text)

    def test_get_message_text_multipart_html_only(self):
        # Multipart message with only HTML
        html_text = "<p>HTML only</p>"
        html_encoded = base64.urlsafe_b64encode(html_text.encode("utf-8")).decode("utf-8")

        self.mock_service.users().messages().get().execute.return_value = {
            "id": "m4",
            "payload": {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/html", "body": {"data": html_encoded}},
                ],
            },
        }

        result = self.client.get_message_text("m4")
        # Should use HTML and convert to plain
        self.assertIn("HTML only", result)
        self.assertNotIn("<p>", result)

    def test_get_message_text_nested_parts(self):
        # Nested multipart message
        plain_text = "Nested plain"
        plain_encoded = base64.urlsafe_b64encode(plain_text.encode("utf-8")).decode("utf-8")

        self.mock_service.users().messages().get().execute.return_value = {
            "id": "m5",
            "payload": {
                "mimeType": "multipart/mixed",
                "parts": [
                    {
                        "mimeType": "multipart/alternative",
                        "parts": [
                            {"mimeType": "text/plain", "body": {"data": plain_encoded}},
                        ],
                    },
                ],
            },
        }

        result = self.client.get_message_text("m5")
        self.assertEqual(result, plain_text)

    def test_get_message_text_fallback_to_snippet(self):
        # No readable parts - fallback to snippet
        self.mock_service.users().messages().get().execute.return_value = {
            "id": "m6",
            "snippet": "This is the snippet",
            "payload": {
                "mimeType": "multipart/mixed",
                "parts": [],
            },
        }

        result = self.client.get_message_text("m6")
        self.assertEqual(result, "This is the snippet")

    def test_get_message_text_empty_body(self):
        # Message with no data
        self.mock_service.users().messages().get().execute.return_value = {
            "id": "m7",
            "snippet": "",
            "payload": {
                "mimeType": "text/plain",
                "body": {},
            },
        }

        result = self.client.get_message_text("m7")
        self.assertEqual(result, "")


class TestGmailClientForwarding(unittest.TestCase):
    """Tests for forwarding address methods."""

    def setUp(self):
        self.client = GmailClient("/fake/creds.json", "/fake/token.json")
        self.mock_service = MagicMock()
        self.client._service = self.mock_service

    def test_create_forwarding_address(self):
        self.mock_service.users().settings().forwardingAddresses().create().execute.return_value = {
            "forwardingEmail": "forward@example.com",
            "verificationStatus": "pending",
        }

        result = self.client.create_forwarding_address("forward@example.com")
        self.assertEqual(result["forwardingEmail"], "forward@example.com")
        self.assertEqual(result["verificationStatus"], "pending")

    def test_list_forwarding_addresses_info(self):
        self.mock_service.users().settings().forwardingAddresses().list().execute.return_value = {
            "forwardingAddresses": [
                {"forwardingEmail": "addr1@example.com", "verificationStatus": "accepted"},
                {"forwardingEmail": "addr2@example.com", "verificationStatus": "pending"},
            ]
        }

        result = self.client.list_forwarding_addresses_info()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["forwardingEmail"], "addr1@example.com")
        self.assertEqual(result[1]["verificationStatus"], "pending")


class TestGmailClientCaching(unittest.TestCase):
    """Tests for cache-enabled methods."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.client = GmailClient("/fake/creds.json", "/fake/token.json", cache_dir=self.tmpdir.name)
        self.mock_service = MagicMock()
        self.client._service = self.mock_service

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_list_labels_with_cache_miss(self):
        self.mock_service.users().labels().list().execute.return_value = {
            "labels": [{"id": "LBL_1", "name": "TestLabel"}]
        }

        result = self.client.list_labels(use_cache=True, ttl=300)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "LBL_1")

    def test_list_labels_with_cache_hit(self):
        # First call - cache miss
        self.mock_service.users().labels().list().execute.return_value = {
            "labels": [{"id": "LBL_1", "name": "TestLabel"}]
        }
        result1 = self.client.list_labels(use_cache=True, ttl=300)

        # Second call - should use cache
        result2 = self.client.list_labels(use_cache=True, ttl=300)

        self.assertEqual(result1, result2)
        # API should only be called once
        self.assertEqual(self.mock_service.users().labels().list().execute.call_count, 1)

    def test_list_filters_with_cache_miss(self):
        self.mock_service.users().settings().filters().list().execute.return_value = {
            "filter": [{"id": "F1", "criteria": {"from": "test@example.com"}}]
        }

        result = self.client.list_filters(use_cache=True, ttl=300)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "F1")

    def test_list_filters_with_cache_hit(self):
        # First call - cache miss
        self.mock_service.users().settings().filters().list().execute.return_value = {
            "filters": [{"id": "F2", "criteria": {"to": "me@example.com"}}]
        }
        result1 = self.client.list_filters(use_cache=True, ttl=300)

        # Second call - should use cache
        result2 = self.client.list_filters(use_cache=True, ttl=300)

        self.assertEqual(result1, result2)
        # API should only be called once
        self.assertEqual(self.mock_service.users().settings().filters().list().execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
