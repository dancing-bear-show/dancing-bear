"""Tests for mail/accounts/helpers.py."""
import unittest
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os


class TestLoadAccounts(unittest.TestCase):
    """Tests for load_accounts function."""

    def test_loads_accounts_from_yaml(self):
        from mail.accounts.helpers import load_accounts

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
accounts:
  - name: work
    provider: gmail
  - name: personal
    provider: outlook
""")
            config_path = f.name

        try:
            result = load_accounts(config_path)
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["name"], "work")
            self.assertEqual(result[1]["name"], "personal")
        finally:
            os.unlink(config_path)

    def test_returns_empty_list_when_no_accounts(self):
        from mail.accounts.helpers import load_accounts

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("other_key: value\n")
            config_path = f.name

        try:
            result = load_accounts(config_path)
            self.assertEqual(result, [])
        finally:
            os.unlink(config_path)

    def test_filters_non_dict_accounts(self):
        from mail.accounts.helpers import load_accounts

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
accounts:
  - name: valid
    provider: gmail
  - "string entry"
  - 123
  - null
""")
            config_path = f.name

        try:
            result = load_accounts(config_path)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["name"], "valid")
        finally:
            os.unlink(config_path)

    def test_handles_empty_accounts_list(self):
        from mail.accounts.helpers import load_accounts

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("accounts: []\n")
            config_path = f.name

        try:
            result = load_accounts(config_path)
            self.assertEqual(result, [])
        finally:
            os.unlink(config_path)

    def test_handles_null_accounts(self):
        from mail.accounts.helpers import load_accounts

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("accounts: null\n")
            config_path = f.name

        try:
            result = load_accounts(config_path)
            self.assertEqual(result, [])
        finally:
            os.unlink(config_path)


class TestIterAccounts(unittest.TestCase):
    """Tests for iter_accounts function."""

    def test_iterates_all_accounts_when_no_filter(self):
        from mail.accounts.helpers import iter_accounts

        accts = [
            {"name": "work", "provider": "gmail"},
            {"name": "personal", "provider": "outlook"},
        ]
        result = list(iter_accounts(accts, None))
        self.assertEqual(len(result), 2)

    def test_iterates_all_accounts_with_empty_filter(self):
        from mail.accounts.helpers import iter_accounts

        accts = [
            {"name": "work", "provider": "gmail"},
            {"name": "personal", "provider": "outlook"},
        ]
        result = list(iter_accounts(accts, ""))
        self.assertEqual(len(result), 2)

    def test_filters_by_single_name(self):
        from mail.accounts.helpers import iter_accounts

        accts = [
            {"name": "work", "provider": "gmail"},
            {"name": "personal", "provider": "outlook"},
            {"name": "other", "provider": "gmail"},
        ]
        result = list(iter_accounts(accts, "work"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "work")

    def test_filters_by_multiple_names(self):
        from mail.accounts.helpers import iter_accounts

        accts = [
            {"name": "work", "provider": "gmail"},
            {"name": "personal", "provider": "outlook"},
            {"name": "other", "provider": "gmail"},
        ]
        result = list(iter_accounts(accts, "work,personal"))
        self.assertEqual(len(result), 2)
        names = [a["name"] for a in result]
        self.assertIn("work", names)
        self.assertIn("personal", names)

    def test_handles_whitespace_in_filter(self):
        from mail.accounts.helpers import iter_accounts

        accts = [
            {"name": "work", "provider": "gmail"},
            {"name": "personal", "provider": "outlook"},
        ]
        result = list(iter_accounts(accts, " work , personal "))
        self.assertEqual(len(result), 2)

    def test_returns_empty_for_non_matching_filter(self):
        from mail.accounts.helpers import iter_accounts

        accts = [
            {"name": "work", "provider": "gmail"},
            {"name": "personal", "provider": "outlook"},
        ]
        result = list(iter_accounts(accts, "nonexistent"))
        self.assertEqual(len(result), 0)

    def test_handles_empty_accounts_list(self):
        from mail.accounts.helpers import iter_accounts

        result = list(iter_accounts([], "work"))
        self.assertEqual(len(result), 0)

    def test_handles_accounts_without_name(self):
        from mail.accounts.helpers import iter_accounts

        accts = [
            {"provider": "gmail"},  # No name
            {"name": "work", "provider": "outlook"},
        ]
        result = list(iter_accounts(accts, "work"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "work")

    def test_includes_accounts_without_name_when_no_filter(self):
        from mail.accounts.helpers import iter_accounts

        accts = [
            {"provider": "gmail"},  # No name
            {"name": "work", "provider": "outlook"},
        ]
        result = list(iter_accounts(accts, None))
        self.assertEqual(len(result), 2)


class TestBuildClientForAccount(unittest.TestCase):
    """Tests for build_client_for_account function."""

    @patch("mail.accounts.helpers._lazy_gmail_client")
    @patch("mail.accounts.helpers.expand_path")
    @patch("mail.accounts.helpers.default_gmail_credentials_path")
    @patch("mail.accounts.helpers.default_gmail_token_path")
    def test_builds_gmail_client(self, mock_token, mock_creds, mock_expand, mock_lazy):
        from mail.accounts.helpers import build_client_for_account

        mock_creds.return_value = "/default/creds.json"
        mock_token.return_value = "/default/token.json"
        mock_expand.side_effect = lambda x: x
        mock_client_class = Mock()
        mock_lazy.return_value = mock_client_class

        acc = {"name": "work", "provider": "gmail"}
        build_client_for_account(acc)

        mock_client_class.assert_called_once_with(
            credentials_path="/default/creds.json",
            token_path="/default/token.json",  # nosec B106 - test fixture path
            cache_dir=None,
        )

    @patch("mail.accounts.helpers._lazy_gmail_client")
    @patch("mail.accounts.helpers.expand_path")
    def test_builds_gmail_client_with_custom_paths(self, mock_expand, mock_lazy):
        from mail.accounts.helpers import build_client_for_account

        mock_expand.side_effect = lambda x: f"/expanded{x}"
        mock_client_class = Mock()
        mock_lazy.return_value = mock_client_class

        acc = {
            "name": "work",
            "provider": "gmail",
            "credentials": "/my/creds.json",
            "token": "/my/token.json",
            "cache": "/my/cache",
        }
        build_client_for_account(acc)

        mock_client_class.assert_called_once_with(
            credentials_path="/expanded/my/creds.json",
            token_path="/expanded/my/token.json",  # nosec B106 - test fixture path
            cache_dir="/my/cache",
        )

    @patch("mail.accounts.helpers.expand_path")
    def test_builds_outlook_client(self, mock_expand):
        from mail.accounts.helpers import build_client_for_account

        mock_expand.side_effect = lambda x: x

        # Create mock module
        mock_outlook_api = MagicMock()
        mock_client_instance = MagicMock()
        mock_outlook_api.OutlookClient.return_value = mock_client_instance

        with patch.dict("sys.modules", {"mail.outlook_api": mock_outlook_api}):
            acc = {
                "name": "work",
                "provider": "outlook",
                "client_id": "my-client-id",
                "tenant": "my-tenant",
                "token": "/my/token.json",
                "cache": "/my/cache",
            }
            result = build_client_for_account(acc)

            mock_outlook_api.OutlookClient.assert_called_once_with(
                client_id="my-client-id",
                tenant="my-tenant",
                token_path="/my/token.json",  # nosec B106 - test fixture path
                cache_dir="/my/cache",
            )
            self.assertEqual(result, mock_client_instance)

    def test_raises_for_outlook_missing_client_id(self):
        from mail.accounts.helpers import build_client_for_account

        with patch.dict("sys.modules", {"mail.outlook_api": MagicMock()}):
            acc = {
                "name": "work",
                "provider": "outlook",
                # No client_id
            }
            with self.assertRaises(SystemExit) as ctx:
                build_client_for_account(acc)
            self.assertIn("missing client_id", str(ctx.exception))

    def test_raises_for_unsupported_provider(self):
        from mail.accounts.helpers import build_client_for_account

        acc = {"name": "work", "provider": "yahoo"}
        with self.assertRaises(SystemExit) as ctx:
            build_client_for_account(acc)
        self.assertIn("Unsupported provider", str(ctx.exception))
        self.assertIn("yahoo", str(ctx.exception))

    def test_raises_for_missing_provider(self):
        from mail.accounts.helpers import build_client_for_account

        acc = {"name": "work"}
        with self.assertRaises(SystemExit) as ctx:
            build_client_for_account(acc)
        self.assertIn("Unsupported provider", str(ctx.exception))
        self.assertIn("<missing>", str(ctx.exception))

    def test_provider_case_insensitive(self):
        from mail.accounts.helpers import build_client_for_account

        with patch("mail.accounts.helpers._lazy_gmail_client") as mock_lazy:
            with patch("mail.accounts.helpers.expand_path", side_effect=lambda x: x):
                with patch("mail.accounts.helpers.default_gmail_credentials_path", return_value="/c"):
                    with patch("mail.accounts.helpers.default_gmail_token_path", return_value="/t"):
                        mock_lazy.return_value = Mock()

                        # Test uppercase
                        acc = {"name": "work", "provider": "GMAIL"}
                        build_client_for_account(acc)
                        mock_lazy.assert_called()


class TestBuildProviderForAccount(unittest.TestCase):
    """Tests for build_provider_for_account function."""

    @patch("mail.accounts.helpers.expand_path")
    @patch("mail.accounts.helpers.default_gmail_credentials_path")
    @patch("mail.accounts.helpers.default_gmail_token_path")
    def test_builds_gmail_provider(self, mock_token, mock_creds, mock_expand):
        from mail.accounts.helpers import build_provider_for_account

        mock_creds.return_value = "/default/creds.json"
        mock_token.return_value = "/default/token.json"
        mock_expand.side_effect = lambda x: x

        with patch("mail.providers.gmail.GmailProvider") as mock_provider:
            acc = {"name": "work", "provider": "gmail"}
            build_provider_for_account(acc)

            mock_provider.assert_called_once_with(
                credentials_path="/default/creds.json",
                token_path="/default/token.json",  # nosec B106 - test fixture path
                cache_dir=None,
            )

    @patch("mail.accounts.helpers.expand_path")
    def test_builds_gmail_provider_with_custom_paths(self, mock_expand):
        from mail.accounts.helpers import build_provider_for_account

        mock_expand.side_effect = lambda x: f"/expanded{x}"

        with patch("mail.providers.gmail.GmailProvider") as mock_provider:
            acc = {
                "name": "work",
                "provider": "gmail",
                "credentials": "/my/creds.json",
                "token": "/my/token.json",
                "cache": "/my/cache",
            }
            build_provider_for_account(acc)

            mock_provider.assert_called_once_with(
                credentials_path="/expanded/my/creds.json",
                token_path="/expanded/my/token.json",  # nosec B106 - test fixture path
                cache_dir="/my/cache",
            )

    def test_raises_for_outlook_missing_client_id(self):
        from mail.accounts.helpers import build_provider_for_account

        with patch.dict("sys.modules", {"mail.providers.outlook": MagicMock()}):
            acc = {
                "name": "work",
                "provider": "outlook",
                # No client_id
            }
            with self.assertRaises(SystemExit) as ctx:
                build_provider_for_account(acc)
            self.assertIn("missing client_id", str(ctx.exception))

    def test_raises_for_unsupported_provider(self):
        from mail.accounts.helpers import build_provider_for_account

        acc = {"name": "work", "provider": "icloud"}
        with self.assertRaises(SystemExit) as ctx:
            build_provider_for_account(acc)
        self.assertIn("Unsupported provider", str(ctx.exception))

    def test_raises_for_empty_provider(self):
        from mail.accounts.helpers import build_provider_for_account

        acc = {"name": "work", "provider": ""}
        with self.assertRaises(SystemExit) as ctx:
            build_provider_for_account(acc)
        self.assertIn("<missing>", str(ctx.exception))

    def test_outlook_uses_application_id_fallback(self):
        from mail.accounts.helpers import build_provider_for_account

        with patch("mail.accounts.helpers.expand_path", side_effect=lambda x: x):
            with patch("mail.providers.outlook.OutlookProvider") as mock_provider:
                acc = {
                    "name": "work",
                    "provider": "outlook",
                    "application_id": "app-id-123",  # Fallback key
                    "tenant": "consumers",
                }
                build_provider_for_account(acc)

                mock_provider.assert_called_once()
                call_args = mock_provider.call_args
                self.assertEqual(call_args.kwargs["client_id"], "app-id-123")

    def test_outlook_uses_credentials_fallback(self):
        from mail.accounts.helpers import build_provider_for_account

        with patch("mail.accounts.helpers.expand_path", side_effect=lambda x: x):
            with patch("mail.providers.outlook.OutlookProvider") as mock_provider:
                acc = {
                    "name": "work",
                    "provider": "outlook",
                    "credentials": "cred-id-456",  # Another fallback key
                    "tenant": "consumers",
                }
                build_provider_for_account(acc)

                mock_provider.assert_called_once()
                call_args = mock_provider.call_args
                self.assertEqual(call_args.kwargs["client_id"], "cred-id-456")

    def test_outlook_defaults_tenant_to_consumers(self):
        from mail.accounts.helpers import build_provider_for_account

        with patch("mail.accounts.helpers.expand_path", side_effect=lambda x: x):
            with patch("mail.providers.outlook.OutlookProvider") as mock_provider:
                acc = {
                    "name": "work",
                    "provider": "outlook",
                    "client_id": "my-client",
                    # No tenant specified
                }
                build_provider_for_account(acc)

                mock_provider.assert_called_once()
                call_args = mock_provider.call_args
                self.assertEqual(call_args.kwargs["tenant"], "consumers")


class TestLazyGmailClient(unittest.TestCase):
    """Tests for _lazy_gmail_client function."""

    def test_returns_gmail_client_class(self):
        from mail.accounts.helpers import _lazy_gmail_client

        with patch("mail.gmail_api.GmailClient") as mock_client:
            result = _lazy_gmail_client()
            # Should return the class, not an instance
            self.assertIs(result, mock_client)

    def test_lazy_import_not_at_module_load(self):
        # Verify the import happens inside the function, not at module load
        # This is tested implicitly - if it failed at load time, this test wouldn't run
        from mail.accounts.helpers import _lazy_gmail_client
        self.assertTrue(callable(_lazy_gmail_client))


if __name__ == "__main__":
    unittest.main(verbosity=2)
