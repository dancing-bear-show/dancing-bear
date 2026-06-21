"""Tests for mail/providers/base.py — CacheMixin and BaseProvider."""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal concrete subclass used throughout the tests
# ---------------------------------------------------------------------------

def _make_concrete_class():
    """Import BaseProvider and return a concrete implementation."""
    from mail.providers.base import BaseProvider

    class ConcreteProvider(BaseProvider):
        _provider_name = "test_provider"

        def authenticate(self) -> None:
            pass  # no-op: required by abstract interface

        def get_profile(self) -> Dict[str, Any]:
            return {"email": "test@example.com"}

        def list_labels(self, use_cache: bool = False, ttl: int = 300) -> List[Dict[str, Any]]:
            return []

        def get_label_id_map(self) -> Dict[str, str]:
            return {}

        def create_label(self, **body: Any) -> Dict[str, Any]:
            return {}

        def update_label(self, label_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
            return {}

        def ensure_label(self, name: str, **kwargs: Any) -> str:
            return "label-id"

        def delete_label(self, label_id: str) -> None:
            pass  # no-op: required by abstract interface

        def list_filters(self, use_cache: bool = False, ttl: int = 300) -> List[Dict[str, Any]]:
            return []

        def create_filter(self, criteria: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
            return {}

        def delete_filter(self, filter_id: str) -> None:
            pass  # no-op: required by abstract interface

        def list_forwarding_addresses_info(self) -> List[Dict[str, Any]]:
            return []

        def get_verified_forwarding_addresses(self) -> List[str]:
            return []

        def list_message_ids(
            self,
            query: Optional[str] = None,
            label_ids: Optional[List[str]] = None,
            max_pages: int = 1,
            page_size: int = 500,
        ) -> List[str]:
            return []

        def batch_modify_messages(
            self,
            ids: List[str],
            add_label_ids: Optional[List[str]] = None,
            remove_label_ids: Optional[List[str]] = None,
        ) -> None:
            pass  # no-op: required by abstract interface

        def list_signatures(self) -> List[Dict[str, Any]]:
            return []

        def update_signature(self, send_as_email: str, signature_html: str) -> Dict[str, Any]:
            return {}

    return ConcreteProvider


# ---------------------------------------------------------------------------
# CacheMixin tests
# ---------------------------------------------------------------------------

class TestCacheMixin(unittest.TestCase):
    """Tests for the CacheMixin class."""

    def test_cache_is_none_when_no_cache_dir(self):
        from mail.providers.base import CacheMixin

        mixin = CacheMixin(cache_dir=None)
        self.assertIsNone(mixin.cache)

    def test_cache_dir_stored(self):
        from mail.providers.base import CacheMixin

        mixin = CacheMixin(cache_dir=None)
        self.assertIsNone(mixin.cache_dir)

    def test_cache_dir_stored_with_value(self):
        from mail.providers.base import CacheMixin

        with patch("mail.providers.base.MailCache") as mock_mail_cache:
            mock_mail_cache.return_value = MagicMock()
            mixin = CacheMixin(cache_dir="/tmp/cache")  # nosec B108 - tmp path in test only

        self.assertEqual(mixin.cache_dir, "/tmp/cache")  # nosec B108

    def test_mail_cache_created_when_cache_dir_given(self):
        from mail.providers.base import CacheMixin

        with patch("mail.providers.base.MailCache") as mock_mail_cache:
            instance = MagicMock()
            mock_mail_cache.return_value = instance
            mixin = CacheMixin(cache_dir="/tmp/cache")  # nosec B108

        mock_mail_cache.assert_called_once_with("/tmp/cache")  # nosec B108
        self.assertIs(mixin.cache, instance)

    def test_provider_name_passed_to_config_cache_mixin(self):
        from mail.providers.base import CacheMixin

        mixin = CacheMixin(cache_dir=None, provider="myprovider")
        self.assertEqual(mixin._cfg_provider, "myprovider")

    def test_default_provider_name(self):
        from mail.providers.base import CacheMixin

        mixin = CacheMixin(cache_dir=None)
        self.assertEqual(mixin._cfg_provider, "default")


# ---------------------------------------------------------------------------
# BaseProvider construction tests
# ---------------------------------------------------------------------------

class TestBaseProviderInit(unittest.TestCase):
    """Tests for BaseProvider.__init__ and attribute storage."""

    def setUp(self):
        self.ConcreteProvider = _make_concrete_class()

    def test_instantiation_stores_credentials_path(self):
        p = self.ConcreteProvider(
            credentials_path="/path/to/creds.json",  # nosec B106
            token_path="/path/to/token.json",  # nosec B106
        )
        self.assertEqual(p.credentials_path, "/path/to/creds.json")

    def test_instantiation_stores_token_path(self):
        p = self.ConcreteProvider(
            credentials_path="/path/to/creds.json",  # nosec B106
            token_path="/path/to/token.json",  # nosec B106
        )
        self.assertEqual(p.token_path, "/path/to/token.json")

    def test_cache_none_by_default(self):
        p = self.ConcreteProvider(
            credentials_path="c.json",  # nosec B106
            token_path="t.json",  # nosec B106
        )
        self.assertIsNone(p.cache)
        self.assertIsNone(p.cache_dir)

    def test_cache_dir_forwarded_to_mixin(self):
        with patch("mail.providers.base.MailCache") as mock_mail_cache:
            mock_mail_cache.return_value = MagicMock()
            p = self.ConcreteProvider(
                credentials_path="c.json",  # nosec B106
                token_path="t.json",  # nosec B106
                cache_dir="/tmp/testcache",  # nosec B108
            )
        self.assertEqual(p.cache_dir, "/tmp/testcache")  # nosec B108
        mock_mail_cache.assert_called_once_with("/tmp/testcache")  # nosec B108

    def test_provider_name_used_for_config_cache(self):
        p = self.ConcreteProvider(
            credentials_path="c.json",  # nosec B106
            token_path="t.json",  # nosec B106
        )
        # ConcreteProvider sets _provider_name = "test_provider"
        self.assertEqual(p._cfg_provider, "test_provider")

    def test_abstract_class_cannot_be_instantiated_directly(self):
        from mail.providers.base import BaseProvider

        with self.assertRaises(TypeError):
            BaseProvider(credentials_path="c.json", token_path="t.json")  # nosec B106

    def test_partial_concrete_class_cannot_be_instantiated(self):
        """A subclass that omits any abstract method still cannot be instantiated."""
        from mail.providers.base import BaseProvider

        class PartialProvider(BaseProvider):
            def authenticate(self) -> None:
                pass
            # remaining abstract methods left unimplemented

        with self.assertRaises(TypeError):
            PartialProvider(credentials_path="c.json", token_path="t.json")  # nosec B106


# ---------------------------------------------------------------------------
# BaseProvider.capabilities tests
# ---------------------------------------------------------------------------

class TestBaseProviderCapabilities(unittest.TestCase):
    """Tests for BaseProvider.capabilities default and override."""

    def setUp(self):
        self.ConcreteProvider = _make_concrete_class()

    def test_default_capabilities_returns_empty_set(self):
        p = self.ConcreteProvider(
            credentials_path="c.json",  # nosec B106
            token_path="t.json",  # nosec B106
        )
        caps = p.capabilities()
        self.assertIsInstance(caps, set)
        self.assertEqual(len(caps), 0)

    def test_capabilities_can_be_overridden(self):
        """Subclass can override capabilities() to advertise features."""
        concrete_provider = self.ConcreteProvider

        class CapableProvider(concrete_provider):
            def capabilities(self) -> set:
                return {"labels", "filters"}

        p = CapableProvider(credentials_path="c.json", token_path="t.json")  # nosec B106
        caps = p.capabilities()
        self.assertIn("labels", caps)
        self.assertIn("filters", caps)

    def test_capabilities_returns_set_type(self):
        p = self.ConcreteProvider(
            credentials_path="c.json",  # nosec B106
            token_path="t.json",  # nosec B106
        )
        self.assertIsInstance(p.capabilities(), set)


# ---------------------------------------------------------------------------
# BaseProvider abstract interface tests
# ---------------------------------------------------------------------------

class TestConcreteProviderInterface(unittest.TestCase):
    """Smoke-tests that all abstract methods are callable on a concrete subclass."""

    def setUp(self):
        concrete_provider = _make_concrete_class()
        self.provider = concrete_provider(
            credentials_path="c.json",  # nosec B106
            token_path="t.json",  # nosec B106
        )

    def test_authenticate_callable(self):
        self.provider.authenticate()  # should not raise

    def test_get_profile_returns_dict(self):
        result = self.provider.get_profile()
        self.assertIsInstance(result, dict)

    def test_list_labels_returns_list(self):
        result = self.provider.list_labels()
        self.assertIsInstance(result, list)

    def test_list_labels_use_cache_param(self):
        result = self.provider.list_labels(use_cache=True, ttl=600)
        self.assertIsInstance(result, list)

    def test_get_label_id_map_returns_dict(self):
        result = self.provider.get_label_id_map()
        self.assertIsInstance(result, dict)

    def test_create_label_returns_dict(self):
        result = self.provider.create_label(name="Test")
        self.assertIsInstance(result, dict)

    def test_update_label_returns_dict(self):
        result = self.provider.update_label("label-id", {"name": "Updated"})
        self.assertIsInstance(result, dict)

    def test_ensure_label_returns_str(self):
        result = self.provider.ensure_label("MyLabel")
        self.assertIsInstance(result, str)

    def test_delete_label_callable(self):
        self.provider.delete_label("label-id")  # should not raise

    def test_list_filters_returns_list(self):
        result = self.provider.list_filters()
        self.assertIsInstance(result, list)

    def test_list_filters_use_cache_param(self):
        result = self.provider.list_filters(use_cache=True, ttl=120)
        self.assertIsInstance(result, list)

    def test_create_filter_returns_dict(self):
        result = self.provider.create_filter({"from": "a@b.com"}, {"addLabelIds": ["INBOX"]})
        self.assertIsInstance(result, dict)

    def test_delete_filter_callable(self):
        self.provider.delete_filter("filter-id")  # should not raise

    def test_list_forwarding_addresses_info_returns_list(self):
        result = self.provider.list_forwarding_addresses_info()
        self.assertIsInstance(result, list)

    def test_get_verified_forwarding_addresses_returns_list(self):
        result = self.provider.get_verified_forwarding_addresses()
        self.assertIsInstance(result, list)

    def test_list_message_ids_returns_list(self):
        result = self.provider.list_message_ids()
        self.assertIsInstance(result, list)

    def test_list_message_ids_all_params(self):
        result = self.provider.list_message_ids(
            query="is:unread",
            label_ids=["INBOX"],
            max_pages=2,
            page_size=100,
        )
        self.assertIsInstance(result, list)

    def test_batch_modify_messages_callable(self):
        self.provider.batch_modify_messages(
            ids=["id1", "id2"],
            add_label_ids=["STARRED"],
            remove_label_ids=["INBOX"],
        )  # should not raise

    def test_list_signatures_returns_list(self):
        result = self.provider.list_signatures()
        self.assertIsInstance(result, list)

    def test_update_signature_returns_dict(self):
        result = self.provider.update_signature("me@example.com", "<b>Hi</b>")
        self.assertIsInstance(result, dict)


# ---------------------------------------------------------------------------
# _provider_name class attribute
# ---------------------------------------------------------------------------

class TestProviderNameClassAttribute(unittest.TestCase):
    """Tests for _provider_name default and subclass override."""

    def test_base_provider_default_name_is_mail(self):
        from mail.providers.base import BaseProvider

        self.assertEqual(BaseProvider._provider_name, "mail")

    def test_subclass_can_override_provider_name(self):
        concrete_provider = _make_concrete_class()
        self.assertEqual(concrete_provider._provider_name, "test_provider")

    def test_provider_name_used_as_cfg_provider(self):
        concrete_provider = _make_concrete_class()
        p = concrete_provider(credentials_path="c.json", token_path="t.json")  # nosec B106
        self.assertEqual(p._cfg_provider, "test_provider")


if __name__ == "__main__":
    unittest.main()
