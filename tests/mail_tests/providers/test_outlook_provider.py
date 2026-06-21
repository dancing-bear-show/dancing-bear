"""Tests for mail/providers/outlook.py OutlookProvider."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


def _make_provider(client_id="dummy-client-id", tenant="consumers", token_path=None, cache_dir=None):
    """Return an OutlookProvider with a mocked OutlookClient."""
    with patch("mail.providers.outlook.OutlookClient") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        from mail.providers.outlook import OutlookProvider
        provider = OutlookProvider(
            client_id=client_id,
            tenant=tenant,
            token_path=token_path,
            cache_dir=cache_dir,
        )
        provider._client = mock_client
        return provider, mock_client


class TestOutlookProviderInit(unittest.TestCase):
    """Tests for OutlookProvider.__init__."""

    def test_creates_outlook_client_with_correct_args(self):
        with patch("mail.providers.outlook.OutlookClient") as mock_cls:
            mock_cls.return_value = MagicMock()
            from mail.providers.outlook import OutlookProvider
            OutlookProvider(client_id="my-id", tenant="consumers", token_path="/t.json")  # nosec B106 - test fixture path
        mock_cls.assert_called_once_with(
            client_id="my-id",
            tenant="consumers",
            token_path="/t.json",  # nosec B106 - test fixture path
            cache_dir=None,
        )

    def test_default_tenant_is_consumers(self):
        with patch("mail.providers.outlook.OutlookClient") as mock_cls:
            mock_cls.return_value = MagicMock()
            from mail.providers.outlook import OutlookProvider
            OutlookProvider(client_id="cid")
        call_kwargs = mock_cls.call_args.kwargs
        self.assertEqual(call_kwargs["tenant"], "consumers")

    def test_token_path_none_when_not_provided(self):
        with patch("mail.providers.outlook.OutlookClient") as mock_cls:
            mock_cls.return_value = MagicMock()
            from mail.providers.outlook import OutlookProvider
            OutlookProvider(client_id="cid")
        call_kwargs = mock_cls.call_args.kwargs
        self.assertIsNone(call_kwargs["token_path"])

    def test_cache_dir_forwarded(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("mail.providers.outlook.OutlookClient") as mock_cls:
                mock_cls.return_value = MagicMock()
                from mail.providers.outlook import OutlookProvider
                OutlookProvider(client_id="cid", cache_dir=tmpdir)
            call_kwargs = mock_cls.call_args.kwargs
            self.assertEqual(call_kwargs["cache_dir"], tmpdir)

    def test_provider_name_is_outlook(self):
        from mail.providers.outlook import OutlookProvider
        self.assertEqual(OutlookProvider._provider_name, "outlook")


class TestOutlookProviderAuthenticate(unittest.TestCase):
    """Tests for OutlookProvider.authenticate."""

    def test_delegates_to_client(self):
        provider, mock_client = _make_provider()
        provider.authenticate()
        mock_client.authenticate.assert_called_once_with()


class TestOutlookProviderGetProfile(unittest.TestCase):
    """Tests for OutlookProvider.get_profile."""

    def test_returns_minimal_structure(self):
        provider, _ = _make_provider()
        result = provider.get_profile()
        self.assertEqual(result, {"provider": "outlook"})

    def test_does_not_call_client(self):
        provider, mock_client = _make_provider()
        provider.get_profile()
        mock_client.get_profile.assert_not_called()


class TestOutlookProviderListLabels(unittest.TestCase):
    """Tests for OutlookProvider.list_labels."""

    def test_delegates_to_client(self):
        provider, mock_client = _make_provider()
        mock_client.list_labels.return_value = [{"displayName": "Inbox"}]
        result = provider.list_labels()
        mock_client.list_labels.assert_called_once_with(use_cache=False, ttl=300)
        self.assertEqual(result, [{"displayName": "Inbox"}])

    def test_forwards_use_cache_and_ttl(self):
        provider, mock_client = _make_provider()
        mock_client.list_labels.return_value = []
        provider.list_labels(use_cache=True, ttl=60)
        mock_client.list_labels.assert_called_once_with(use_cache=True, ttl=60)


class TestOutlookProviderGetLabelIdMap(unittest.TestCase):
    """Tests for OutlookProvider.get_label_id_map."""

    def test_delegates_to_client(self):
        provider, mock_client = _make_provider()
        mock_client.get_label_id_map.return_value = {"Inbox": "abc123"}
        result = provider.get_label_id_map()
        mock_client.get_label_id_map.assert_called_once_with()
        self.assertEqual(result, {"Inbox": "abc123"})


class TestOutlookProviderCreateLabel(unittest.TestCase):
    """Tests for OutlookProvider.create_label."""

    def test_extracts_name_and_color_from_body(self):
        provider, mock_client = _make_provider()
        mock_client.create_label.return_value = {"id": "x", "displayName": "Work"}
        result = provider.create_label(name="Work", color="red")
        mock_client.create_label.assert_called_once_with(name="Work", color="red")
        self.assertEqual(result["displayName"], "Work")

    def test_accepts_displayName_key(self):
        provider, mock_client = _make_provider()
        mock_client.create_label.return_value = {"id": "y"}
        provider.create_label(displayName="Travel", color=None)
        mock_client.create_label.assert_called_once_with(name="Travel", color=None)

    def test_name_takes_priority_over_displayName(self):
        provider, mock_client = _make_provider()
        mock_client.create_label.return_value = {}
        provider.create_label(name="Primary", displayName="Secondary")
        call_kwargs = mock_client.create_label.call_args.kwargs
        self.assertEqual(call_kwargs["name"], "Primary")

    def test_color_defaults_to_none_when_absent(self):
        provider, mock_client = _make_provider()
        mock_client.create_label.return_value = {}
        provider.create_label(name="Test")
        call_kwargs = mock_client.create_label.call_args.kwargs
        self.assertIsNone(call_kwargs["color"])


class TestOutlookProviderUpdateLabel(unittest.TestCase):
    """Tests for OutlookProvider.update_label."""

    def test_delegates_to_client(self):
        provider, mock_client = _make_provider()
        mock_client.update_label.return_value = {"id": "abc", "displayName": "Updated"}
        result = provider.update_label("abc", {"displayName": "Updated"})
        mock_client.update_label.assert_called_once_with("abc", {"displayName": "Updated"})
        self.assertEqual(result["id"], "abc")


class TestOutlookProviderEnsureLabel(unittest.TestCase):
    """Tests for OutlookProvider.ensure_label."""

    def test_delegates_to_client(self):
        provider, mock_client = _make_provider()
        mock_client.ensure_label.return_value = "label-id-123"
        result = provider.ensure_label("Work")
        mock_client.ensure_label.assert_called_once_with("Work")
        self.assertEqual(result, "label-id-123")

    def test_forwards_extra_kwargs(self):
        provider, mock_client = _make_provider()
        mock_client.ensure_label.return_value = "id"
        provider.ensure_label("Work", color="blue")
        mock_client.ensure_label.assert_called_once_with("Work", color="blue")


class TestOutlookProviderDeleteLabel(unittest.TestCase):
    """Tests for OutlookProvider.delete_label."""

    def test_delegates_to_client(self):
        provider, mock_client = _make_provider()
        provider.delete_label("label-xyz")
        mock_client.delete_label.assert_called_once_with("label-xyz")

    def test_returns_none(self):
        provider, mock_client = _make_provider()
        mock_client.delete_label.return_value = None
        result = provider.delete_label("id")
        self.assertIsNone(result)


class TestOutlookProviderListFilters(unittest.TestCase):
    """Tests for OutlookProvider.list_filters."""

    def test_delegates_to_client(self):
        provider, mock_client = _make_provider()
        mock_client.list_filters.return_value = [{"id": "f1"}]
        result = provider.list_filters()
        mock_client.list_filters.assert_called_once_with(use_cache=False, ttl=300)
        self.assertEqual(result, [{"id": "f1"}])

    def test_forwards_use_cache_and_ttl(self):
        provider, mock_client = _make_provider()
        mock_client.list_filters.return_value = []
        provider.list_filters(use_cache=True, ttl=120)
        mock_client.list_filters.assert_called_once_with(use_cache=True, ttl=120)


class TestOutlookProviderCreateFilter(unittest.TestCase):
    """Tests for OutlookProvider.create_filter."""

    def test_delegates_to_client(self):
        provider, mock_client = _make_provider()
        criteria = {"from": "boss@example.com"}
        action = {"moveToFolder": "Work"}
        mock_client.create_filter.return_value = {"id": "f99"}
        result = provider.create_filter(criteria, action)
        mock_client.create_filter.assert_called_once_with(criteria, action)
        self.assertEqual(result, {"id": "f99"})


class TestOutlookProviderDeleteFilter(unittest.TestCase):
    """Tests for OutlookProvider.delete_filter."""

    def test_delegates_to_client(self):
        provider, mock_client = _make_provider()
        provider.delete_filter("filter-001")
        mock_client.delete_filter.assert_called_once_with("filter-001")

    def test_returns_none(self):
        provider, mock_client = _make_provider()
        mock_client.delete_filter.return_value = None
        result = provider.delete_filter("filter-001")
        self.assertIsNone(result)


class TestOutlookProviderForwarding(unittest.TestCase):
    """Tests for unsupported forwarding methods."""

    def test_list_forwarding_addresses_info_returns_empty_list(self):
        provider, _ = _make_provider()
        result = provider.list_forwarding_addresses_info()
        self.assertEqual(result, [])

    def test_get_verified_forwarding_addresses_returns_empty_list(self):
        provider, _ = _make_provider()
        result = provider.get_verified_forwarding_addresses()
        self.assertEqual(result, [])

    def test_forwarding_does_not_call_client(self):
        provider, mock_client = _make_provider()
        provider.list_forwarding_addresses_info()
        provider.get_verified_forwarding_addresses()
        mock_client.list_forwarding_addresses_info.assert_not_called()
        mock_client.get_verified_forwarding_addresses.assert_not_called()


class TestOutlookProviderNotImplemented(unittest.TestCase):
    """Tests for methods that raise NotImplementedError."""

    def test_list_message_ids_raises(self):
        provider, _ = _make_provider()
        with self.assertRaises(NotImplementedError):
            provider.list_message_ids()

    def test_list_message_ids_raises_with_args(self):
        provider, _ = _make_provider()
        with self.assertRaises(NotImplementedError):
            provider.list_message_ids(query="subject:hello", label_ids=["inbox"], max_pages=2)

    def test_batch_modify_messages_raises(self):
        provider, _ = _make_provider()
        with self.assertRaises(NotImplementedError):
            provider.batch_modify_messages(ids=["msg1", "msg2"])

    def test_batch_modify_messages_raises_with_label_args(self):
        provider, _ = _make_provider()
        with self.assertRaises(NotImplementedError):
            provider.batch_modify_messages(
                ids=["msg1"],
                add_label_ids=["Work"],
                remove_label_ids=["Inbox"],
            )

    def test_list_signatures_raises(self):
        provider, _ = _make_provider()
        with self.assertRaises(NotImplementedError):
            provider.list_signatures()

    def test_update_signature_raises(self):
        provider, _ = _make_provider()
        with self.assertRaises(NotImplementedError):
            provider.update_signature("me@example.com", "<p>Hello</p>")


class TestOutlookProviderCapabilities(unittest.TestCase):
    """Tests for OutlookProvider.capabilities."""

    def test_includes_labels(self):
        provider, _ = _make_provider()
        self.assertIn("labels", provider.capabilities())

    def test_includes_filters(self):
        provider, _ = _make_provider()
        self.assertIn("filters", provider.capabilities())

    def test_excludes_sweep(self):
        provider, _ = _make_provider()
        self.assertNotIn("sweep", provider.capabilities())

    def test_excludes_forwarding(self):
        provider, _ = _make_provider()
        self.assertNotIn("forwarding", provider.capabilities())

    def test_excludes_signatures(self):
        provider, _ = _make_provider()
        self.assertNotIn("signatures", provider.capabilities())

    def test_returns_set(self):
        provider, _ = _make_provider()
        self.assertIsInstance(provider.capabilities(), set)


if __name__ == "__main__":
    unittest.main()
