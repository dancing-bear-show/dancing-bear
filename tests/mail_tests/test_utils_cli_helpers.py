"""Tests for mail/utils/cli_helpers.py."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from tests.mail_tests.fixtures import make_args as _make_args


class TestPreviewCriteria(unittest.TestCase):
    """Tests for preview_criteria helper."""

    def test_empty_criteria(self):
        from mail.utils.cli_helpers import preview_criteria
        result = preview_criteria({})
        self.assertEqual(result, "<complex>")

    def test_none_criteria(self):
        from mail.utils.cli_helpers import preview_criteria
        result = preview_criteria(None)
        self.assertEqual(result, "<complex>")

    def test_from_only(self):
        from mail.utils.cli_helpers import preview_criteria
        result = preview_criteria({"from": "user@example.com"})
        self.assertEqual(result, "from:user@example.com")

    def test_to_only(self):
        from mail.utils.cli_helpers import preview_criteria
        result = preview_criteria({"to": "recipient@example.com"})
        self.assertEqual(result, "to:recipient@example.com")

    def test_subject_only(self):
        from mail.utils.cli_helpers import preview_criteria
        result = preview_criteria({"subject": "Important"})
        self.assertEqual(result, "subject:Important")

    def test_multiple_fields(self):
        from mail.utils.cli_helpers import preview_criteria
        result = preview_criteria({"from": "a@b.com", "to": "c@d.com", "subject": "Hi"})
        self.assertIn("from:a@b.com", result)
        self.assertIn("to:c@d.com", result)
        self.assertIn("subject:Hi", result)

    def test_query_shows_ellipsis(self):
        from mail.utils.cli_helpers import preview_criteria
        result = preview_criteria({"query": "some long query string"})
        self.assertIn("query=", result)

    def test_complex_criteria_without_known_fields(self):
        from mail.utils.cli_helpers import preview_criteria
        result = preview_criteria({"unknown_field": "value"})
        self.assertEqual(result, "<complex>")


class TestIsOutlookProfile(unittest.TestCase):
    """Tests for is_outlook_profile helper."""

    def test_none_profile_returns_false(self):
        from mail.utils.cli_helpers import is_outlook_profile
        self.assertFalse(is_outlook_profile(None))

    def test_empty_string_returns_false(self):
        from mail.utils.cli_helpers import is_outlook_profile
        self.assertFalse(is_outlook_profile(""))

    def test_profile_with_no_client_id_returns_false(self):
        from mail.utils.cli_helpers import is_outlook_profile
        with patch("mail.utils.cli_helpers.get_outlook_client_id_for_profile", return_value=None):
            result = is_outlook_profile("gmail_personal")
        self.assertFalse(result)

    def test_profile_with_client_id_returns_true(self):
        from mail.utils.cli_helpers import is_outlook_profile
        with patch("mail.utils.cli_helpers.get_outlook_client_id_for_profile", return_value="some-client-id"):
            result = is_outlook_profile("outlook_personal")
        self.assertTrue(result)

    def test_profile_with_empty_client_id_returns_false(self):
        from mail.utils.cli_helpers import is_outlook_profile
        with patch("mail.utils.cli_helpers.get_outlook_client_id_for_profile", return_value=""):
            result = is_outlook_profile("some_profile")
        self.assertFalse(result)


class TestGmailProviderFromArgs(unittest.TestCase):
    """Tests for gmail_provider_from_args helper."""

    @patch("mail.utils.cli_helpers.persist_if_provided")
    @patch("mail.utils.cli_helpers.resolve_paths_profile", return_value=("/c.json", "/t.json"))
    @patch("mail.utils.cli_helpers.GmailProvider")
    def test_returns_provider(self, mock_provider_cls, mock_resolve, mock_persist):
        from mail.utils.cli_helpers import gmail_provider_from_args
        mock_instance = MagicMock()
        mock_provider_cls.return_value = mock_instance

        result = gmail_provider_from_args(_make_args())
        self.assertEqual(result, mock_instance)

    @patch("mail.utils.cli_helpers.persist_if_provided")
    @patch("mail.utils.cli_helpers.resolve_paths_profile", return_value=("/c.json", "/t.json"))
    @patch("mail.utils.cli_helpers.GmailProvider")
    def test_passes_cache_dir(self, mock_provider_cls, mock_resolve, mock_persist):
        from mail.utils.cli_helpers import gmail_provider_from_args
        mock_provider_cls.return_value = MagicMock()

        gmail_provider_from_args(_make_args(cache="/tmp/cache"))  # nosec B108 - test-only temp file, not a security concern

        mock_provider_cls.assert_called_once_with(
            credentials_path="/c.json",
            token_path="/t.json",  # nosec B106 - test fixture path, not a real credential
            cache_dir="/tmp/cache",  # nosec B108 - test-only temp file, not a security concern
        )

    @patch("mail.utils.cli_helpers.persist_if_provided")
    @patch("mail.utils.cli_helpers.resolve_paths_profile", return_value=("/c.json", "/t.json"))
    @patch("mail.utils.cli_helpers.GmailProvider")
    def test_does_not_authenticate(self, mock_provider_cls, mock_resolve, mock_persist):
        """gmail_provider_from_args should NOT call authenticate."""
        from mail.utils.cli_helpers import gmail_provider_from_args
        mock_instance = MagicMock()
        mock_provider_cls.return_value = mock_instance

        gmail_provider_from_args(_make_args())
        mock_instance.authenticate.assert_not_called()


class TestWithGmailClientDecorator(unittest.TestCase):
    """Tests for the with_gmail_client decorator."""

    @patch("mail.utils.cli_helpers.gmail_provider_from_args")
    def test_decorator_injects_client(self, mock_from_args):
        from mail.utils.cli_helpers import with_gmail_client
        mock_client = MagicMock()
        mock_from_args.return_value = mock_client
        captured = {}

        @with_gmail_client
        def handler(args):
            captured["client"] = getattr(args, "_gmail_client", None)

        args = _make_args()
        handler(args)

        mock_client.authenticate.assert_called_once()
        self.assertEqual(captured["client"], mock_client)

    @patch("mail.utils.cli_helpers.gmail_provider_from_args")
    def test_decorator_calls_wrapped_function(self, mock_from_args):
        from mail.utils.cli_helpers import with_gmail_client
        mock_from_args.return_value = MagicMock()
        called = []

        @with_gmail_client
        def handler(args):
            called.append(True)
            return 42

        result = handler(_make_args())
        self.assertEqual(len(called), 1)
        self.assertEqual(result, 42)


class TestGmailClientAuthenticated(unittest.TestCase):
    """Tests for gmail_client_authenticated helper."""

    @patch("mail.utils.cli_helpers.gmail_provider_from_args")
    def test_returns_authenticated_client(self, mock_from_args):
        from mail.utils.cli_helpers import gmail_client_authenticated
        mock_client = MagicMock()
        mock_from_args.return_value = mock_client

        result = gmail_client_authenticated(_make_args())
        mock_client.authenticate.assert_called_once()
        self.assertEqual(result, mock_client)


class TestOutlookClientFromArgs(unittest.TestCase):
    """Tests for outlook_client_from_args helper."""

    def test_raises_on_none_client(self):
        from mail.utils.cli_helpers import outlook_client_from_args
        with patch("mail.outlook.helpers.get_outlook_client", return_value=(None, "some_error")):
            with self.assertRaises(RuntimeError) as ctx:
                outlook_client_from_args(_make_args())
            self.assertIn("Could not initialize Outlook client", str(ctx.exception))

    def test_raises_on_error(self):
        from mail.utils.cli_helpers import outlook_client_from_args
        mock_client = MagicMock()
        with patch("mail.outlook.helpers.get_outlook_client", return_value=(mock_client, "some_error")):
            with self.assertRaises(RuntimeError):
                outlook_client_from_args(_make_args())

    def test_returns_client_on_success(self):
        from mail.utils.cli_helpers import outlook_client_from_args
        mock_client = MagicMock()
        with patch("mail.outlook.helpers.get_outlook_client", return_value=(mock_client, None)):
            result = outlook_client_from_args(_make_args())
        self.assertEqual(result, mock_client)


if __name__ == "__main__":
    unittest.main()
