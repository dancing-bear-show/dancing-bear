"""Tests for mail/providers/__init__.py provider factory."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestGetProvider(unittest.TestCase):
    """Tests for get_provider factory function."""

    def test_raises_for_unknown_provider(self):
        from mail.providers import get_provider
        with self.assertRaises(ValueError) as ctx:
            get_provider("unknown", credentials_path="/c.json", token_path="/t.json")  # nosec B106 - test fixture path, not a real credential
        self.assertIn("Unsupported provider", str(ctx.exception))
        self.assertIn("unknown", str(ctx.exception))

    def test_raises_for_empty_name(self):
        from mail.providers import get_provider
        with self.assertRaises(ValueError):
            get_provider("", credentials_path="/c.json", token_path="/t.json")  # nosec B106 - test fixture path, not a real credential

    def test_raises_for_none_name(self):
        from mail.providers import get_provider
        with self.assertRaises(ValueError):
            get_provider(None, credentials_path="/c.json", token_path="/t.json")  # nosec B106 - test fixture path, not a real credential

    def test_gmail_returns_gmail_provider(self):
        from mail.providers import get_provider
        with patch("mail.providers.gmail.GmailProvider") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            result = get_provider("gmail", credentials_path="/c.json", token_path="/t.json")  # nosec B106 - test fixture path, not a real credential
        self.assertEqual(result, mock_instance)

    def test_gmail_case_insensitive(self):
        from mail.providers import get_provider
        with patch("mail.providers.gmail.GmailProvider") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            result = get_provider("Gmail", credentials_path="/c.json", token_path="/t.json")  # nosec B106 - test fixture path, not a real credential
        self.assertEqual(result, mock_instance)

    def test_gmail_uppercase(self):
        from mail.providers import get_provider
        with patch("mail.providers.gmail.GmailProvider") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            result = get_provider("GMAIL", credentials_path="/c.json", token_path="/t.json")  # nosec B106 - test fixture path, not a real credential
        self.assertEqual(result, mock_instance)

    def test_outlook_returns_outlook_provider(self):
        from mail.providers import get_provider
        with patch("mail.providers.outlook.OutlookProvider") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            result = get_provider("outlook", credentials_path="my-client-id", token_path="/t.json")  # nosec B106 - test fixture path, not a real credential
        self.assertEqual(result, mock_instance)

    def test_outlook_passes_credentials_path_as_client_id(self):
        """For Outlook, credentials_path is the client_id."""
        from mail.providers import get_provider
        with patch("mail.providers.outlook.OutlookProvider") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_provider("outlook", credentials_path="my-client-id", token_path="/t.json")  # nosec B106 - test fixture path, not a real credential
        mock_cls.assert_called_once_with(
            client_id="my-client-id",
            token_path="/t.json",  # nosec B106 - test fixture path, not a real credential
            cache_dir=None,
        )

    def test_gmail_passes_cache_dir(self):
        from mail.providers import get_provider
        with patch("mail.providers.gmail.GmailProvider") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_provider("gmail", credentials_path="/c.json", token_path="/t.json", cache_dir="/cache")  # nosec B106 - test fixture path, not a real credential
        mock_cls.assert_called_once_with(
            credentials_path="/c.json",
            token_path="/t.json",  # nosec B106 - test fixture path, not a real credential
            cache_dir="/cache",
        )

    def test_outlook_passes_cache_dir(self):
        from mail.providers import get_provider
        with patch("mail.providers.outlook.OutlookProvider") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_provider("outlook", credentials_path="cid", token_path="/t.json", cache_dir="/cache")  # nosec B106 - test fixture path, not a real credential
        mock_cls.assert_called_once_with(
            client_id="cid",
            token_path="/t.json",  # nosec B106 - test fixture path, not a real credential
            cache_dir="/cache",
        )

    def test_error_message_includes_provider_name(self):
        from mail.providers import get_provider
        with self.assertRaises(ValueError) as ctx:
            get_provider("yahoo", credentials_path="/c.json", token_path="/t.json")  # nosec B106 - test fixture path, not a real credential
        self.assertIn("yahoo", str(ctx.exception))


class TestProvidersAllExports(unittest.TestCase):
    """Tests that __all__ exports are present."""

    def test_base_provider_exported(self):
        from mail import providers
        self.assertIn("BaseProvider", providers.__all__)

    def test_get_provider_exported(self):
        from mail import providers
        self.assertIn("get_provider", providers.__all__)


if __name__ == "__main__":
    unittest.main()
