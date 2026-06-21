"""Tests for mail/providers/gmail.py – GmailProvider delegation layer."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


def _make_provider():
    """Return a GmailProvider with a fully-mocked GmailClient."""
    from mail.providers.gmail import GmailProvider

    with patch("mail.providers.gmail.GmailClient") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        provider = GmailProvider(
            credentials_path="c.json",  # nosec B106 - test fixture path
            token_path="t.json",  # nosec B106 - test fixture path
        )
    # Attach mock_client so callers can inspect it
    provider._client = mock_client
    return provider, mock_client


class TestGmailProviderInit(unittest.TestCase):
    """Constructor wires GmailClient with the right arguments."""

    def test_client_created_with_credentials_and_token(self):
        from mail.providers.gmail import GmailProvider

        with patch("mail.providers.gmail.GmailClient") as mock_cls:
            mock_cls.return_value = MagicMock()
            GmailProvider(
                credentials_path="/creds.json",  # nosec B106
                token_path="/tok.json",  # nosec B106
            )
        mock_cls.assert_called_once_with(
            credentials_path="/creds.json",  # nosec B106
            token_path="/tok.json",  # nosec B106
            cache_dir=None,
        )

    def test_client_created_with_cache_dir(self):
        from mail.providers.gmail import GmailProvider

        with patch("mail.providers.gmail.GmailClient") as mock_cls, \
             patch("mail.providers.base.MailCache"):
            mock_cls.return_value = MagicMock()
            GmailProvider(
                credentials_path="/creds.json",  # nosec B106
                token_path="/tok.json",  # nosec B106
                cache_dir="/cache",
            )
        mock_cls.assert_called_once_with(
            credentials_path="/creds.json",  # nosec B106
            token_path="/tok.json",  # nosec B106
            cache_dir="/cache",
        )

    def test_provider_name(self):
        from mail.providers.gmail import GmailProvider

        with patch("mail.providers.gmail.GmailClient"):
            p = GmailProvider(credentials_path="c.json", token_path="t.json")  # nosec B106
        self.assertEqual(p._provider_name, "gmail")


class TestGmailProviderLifecycle(unittest.TestCase):
    def test_authenticate_delegates(self):
        provider, client = _make_provider()
        provider.authenticate()
        client.authenticate.assert_called_once_with()

    def test_get_profile_delegates(self):
        provider, client = _make_provider()
        client.get_profile.return_value = {"emailAddress": "user@example.com"}
        result = provider.get_profile()
        client.get_profile.assert_called_once_with()
        self.assertEqual(result, {"emailAddress": "user@example.com"})


class TestGmailProviderLabels(unittest.TestCase):
    def test_list_labels_default_args(self):
        provider, client = _make_provider()
        client.list_labels.return_value = [{"id": "INBOX"}]
        result = provider.list_labels()
        client.list_labels.assert_called_once_with(use_cache=False, ttl=300)
        self.assertEqual(result, [{"id": "INBOX"}])

    def test_list_labels_custom_args(self):
        provider, client = _make_provider()
        client.list_labels.return_value = []
        provider.list_labels(use_cache=True, ttl=60)
        client.list_labels.assert_called_once_with(use_cache=True, ttl=60)

    def test_get_label_id_map_delegates(self):
        provider, client = _make_provider()
        client.get_label_id_map.return_value = {"INBOX": "INBOX"}
        result = provider.get_label_id_map()
        client.get_label_id_map.assert_called_once_with()
        self.assertEqual(result, {"INBOX": "INBOX"})

    def test_create_label_delegates(self):
        provider, client = _make_provider()
        client.create_label.return_value = {"id": "Label_1", "name": "MyLabel"}
        result = provider.create_label(name="MyLabel")
        client.create_label.assert_called_once_with(name="MyLabel")
        self.assertEqual(result["name"], "MyLabel")

    def test_update_label_delegates(self):
        provider, client = _make_provider()
        client.update_label.return_value = {"id": "Label_1", "name": "Updated"}
        result = provider.update_label("Label_1", {"name": "Updated"})
        client.update_label.assert_called_once_with("Label_1", {"name": "Updated"})
        self.assertEqual(result["name"], "Updated")

    def test_ensure_label_delegates(self):
        provider, client = _make_provider()
        client.ensure_label.return_value = "Label_42"
        result = provider.ensure_label("MyLabel", color="blue")
        client.ensure_label.assert_called_once_with("MyLabel", color="blue")
        self.assertEqual(result, "Label_42")

    def test_delete_label_delegates(self):
        provider, client = _make_provider()
        provider.delete_label("Label_1")
        client.delete_label.assert_called_once_with("Label_1")

    def test_delete_label_returns_none(self):
        provider, client = _make_provider()
        client.delete_label.return_value = None
        result = provider.delete_label("Label_1")
        self.assertIsNone(result)


class TestGmailProviderFilters(unittest.TestCase):
    def test_list_filters_default_args(self):
        provider, client = _make_provider()
        client.list_filters.return_value = [{"id": "f1"}]
        result = provider.list_filters()
        client.list_filters.assert_called_once_with(use_cache=False, ttl=300)
        self.assertEqual(result, [{"id": "f1"}])

    def test_list_filters_custom_args(self):
        provider, client = _make_provider()
        client.list_filters.return_value = []
        provider.list_filters(use_cache=True, ttl=120)
        client.list_filters.assert_called_once_with(use_cache=True, ttl=120)

    def test_create_filter_delegates(self):
        provider, client = _make_provider()
        criteria = {"from": "boss@example.com"}
        action = {"addLabelIds": ["IMPORTANT"]}
        client.create_filter.return_value = {"id": "f1"}
        result = provider.create_filter(criteria, action)
        client.create_filter.assert_called_once_with(criteria, action)
        self.assertEqual(result["id"], "f1")

    def test_delete_filter_delegates(self):
        provider, client = _make_provider()
        provider.delete_filter("f1")
        client.delete_filter.assert_called_once_with("f1")

    def test_delete_filter_returns_none(self):
        provider, client = _make_provider()
        client.delete_filter.return_value = None
        result = provider.delete_filter("f1")
        self.assertIsNone(result)


class TestGmailProviderForwarding(unittest.TestCase):
    def test_list_forwarding_addresses_info_delegates(self):
        provider, client = _make_provider()
        client.list_forwarding_addresses_info.return_value = [{"forwardingEmail": "a@b.com"}]
        result = provider.list_forwarding_addresses_info()
        client.list_forwarding_addresses_info.assert_called_once_with()
        self.assertEqual(result[0]["forwardingEmail"], "a@b.com")

    def test_get_verified_forwarding_addresses_delegates(self):
        provider, client = _make_provider()
        client.get_verified_forwarding_addresses.return_value = ["a@b.com"]
        result = provider.get_verified_forwarding_addresses()
        client.get_verified_forwarding_addresses.assert_called_once_with()
        self.assertEqual(result, ["a@b.com"])

    def test_get_auto_forwarding_delegates(self):
        provider, client = _make_provider()
        client.get_auto_forwarding.return_value = {"enabled": True, "emailAddress": "a@b.com"}
        result = provider.get_auto_forwarding()
        client.get_auto_forwarding.assert_called_once_with()
        self.assertTrue(result["enabled"])

    def test_set_auto_forwarding_enabled(self):
        provider, client = _make_provider()
        client.update_auto_forwarding.return_value = {"enabled": True}
        result = provider.set_auto_forwarding(enabled=True, email="a@b.com", disposition="trash")
        client.update_auto_forwarding.assert_called_once_with(
            enabled=True, email="a@b.com", disposition="trash"
        )
        self.assertTrue(result["enabled"])

    def test_set_auto_forwarding_disabled_no_email(self):
        provider, client = _make_provider()
        client.update_auto_forwarding.return_value = {"enabled": False}
        provider.set_auto_forwarding(enabled=False)
        client.update_auto_forwarding.assert_called_once_with(
            enabled=False, email=None, disposition=None
        )


class TestGmailProviderMessages(unittest.TestCase):
    def test_list_message_ids_defaults(self):
        provider, client = _make_provider()
        client.list_message_ids.return_value = ["id1", "id2"]
        result = provider.list_message_ids()
        client.list_message_ids.assert_called_once_with(
            query=None, label_ids=None, max_pages=1, page_size=500
        )
        self.assertEqual(result, ["id1", "id2"])

    def test_list_message_ids_with_query(self):
        provider, client = _make_provider()
        client.list_message_ids.return_value = ["id3"]
        provider.list_message_ids(query="is:unread", label_ids=["INBOX"], max_pages=2, page_size=100)
        client.list_message_ids.assert_called_once_with(
            query="is:unread", label_ids=["INBOX"], max_pages=2, page_size=100
        )

    def test_batch_modify_messages_delegates(self):
        provider, client = _make_provider()
        provider.batch_modify_messages(
            ["id1", "id2"],
            add_label_ids=["IMPORTANT"],
            remove_label_ids=["UNREAD"],
        )
        client.batch_modify_messages.assert_called_once_with(
            ["id1", "id2"],
            add_label_ids=["IMPORTANT"],
            remove_label_ids=["UNREAD"],
        )

    def test_batch_modify_messages_returns_none(self):
        provider, client = _make_provider()
        client.batch_modify_messages.return_value = None
        result = provider.batch_modify_messages(["id1"])
        self.assertIsNone(result)

    def test_get_message_text_delegates(self):
        provider, client = _make_provider()
        client.get_message_text.return_value = "Hello world"
        result = provider.get_message_text("id1")
        client.get_message_text.assert_called_once_with("id1")
        self.assertEqual(result, "Hello world")

    def test_get_message_default_fmt(self):
        provider, client = _make_provider()
        client.get_message.return_value = {"id": "id1", "payload": {}}
        result = provider.get_message("id1")
        client.get_message.assert_called_once_with("id1", fmt="full")
        self.assertEqual(result["id"], "id1")

    def test_get_message_custom_fmt(self):
        provider, client = _make_provider()
        client.get_message.return_value = {"id": "id1"}
        provider.get_message("id1", fmt="metadata")
        client.get_message.assert_called_once_with("id1", fmt="metadata")

    def test_get_messages_metadata_defaults(self):
        provider, client = _make_provider()
        client.get_messages_metadata.return_value = [{"id": "id1"}]
        result = provider.get_messages_metadata(["id1"])
        client.get_messages_metadata.assert_called_once_with(["id1"], use_cache=True)
        self.assertEqual(len(result), 1)

    def test_get_messages_metadata_no_cache(self):
        provider, client = _make_provider()
        client.get_messages_metadata.return_value = []
        provider.get_messages_metadata(["id1"], use_cache=False)
        client.get_messages_metadata.assert_called_once_with(["id1"], use_cache=False)


class TestGmailProviderSendDraft(unittest.TestCase):
    def test_send_message_raw_delegates(self):
        provider, client = _make_provider()
        raw = b"From: a\r\nTo: b\r\n\r\nHello"
        client.send_message_raw.return_value = {"id": "msg1"}
        result = provider.send_message_raw(raw)
        client.send_message_raw.assert_called_once_with(raw, None)
        self.assertEqual(result["id"], "msg1")

    def test_send_message_raw_with_thread_id(self):
        provider, client = _make_provider()
        raw = b"headers\r\n\r\nbody"
        client.send_message_raw.return_value = {"id": "msg2", "threadId": "t1"}
        result = provider.send_message_raw(raw, thread_id="t1")
        client.send_message_raw.assert_called_once_with(raw, "t1")
        self.assertEqual(result["threadId"], "t1")

    def test_create_draft_raw_delegates(self):
        provider, client = _make_provider()
        raw = b"draft bytes"
        client.create_draft_raw.return_value = {"id": "draft1"}
        result = provider.create_draft_raw(raw)
        client.create_draft_raw.assert_called_once_with(raw, None)
        self.assertEqual(result["id"], "draft1")

    def test_create_draft_raw_with_thread_id(self):
        provider, client = _make_provider()
        raw = b"draft bytes"
        client.create_draft_raw.return_value = {"id": "draft2"}
        provider.create_draft_raw(raw, thread_id="t99")
        client.create_draft_raw.assert_called_once_with(raw, "t99")


class TestGmailProviderSignatures(unittest.TestCase):
    def test_list_signatures_delegates(self):
        provider, client = _make_provider()
        client.list_signatures.return_value = [{"sendAsEmail": "me@example.com"}]
        result = provider.list_signatures()
        client.list_signatures.assert_called_once_with()
        self.assertEqual(result[0]["sendAsEmail"], "me@example.com")

    def test_update_signature_delegates(self):
        provider, client = _make_provider()
        client.update_signature.return_value = {"sendAsEmail": "me@example.com", "signature": "<b>Hi</b>"}
        result = provider.update_signature("me@example.com", "<b>Hi</b>")
        client.update_signature.assert_called_once_with("me@example.com", "<b>Hi</b>")
        self.assertEqual(result["signature"], "<b>Hi</b>")


class TestGmailProviderCapabilities(unittest.TestCase):
    def test_capabilities_returns_expected_set(self):
        provider, _ = _make_provider()
        caps = provider.capabilities()
        self.assertIsInstance(caps, set)
        self.assertEqual(caps, {"labels", "filters", "sweep", "forwarding", "signatures"})

    def test_capabilities_contains_all_five(self):
        provider, _ = _make_provider()
        for cap in ("labels", "filters", "sweep", "forwarding", "signatures"):
            with self.subTest(cap=cap):
                self.assertIn(cap, provider.capabilities())


if __name__ == "__main__":
    unittest.main()
