"""Coverage-filling tests for mail/outlook/helpers.py.

Targets:
- Line 14 and lines 96-109: get_outlook_client function (import error path, missing client_id,
  successful authentication)
- Line 53→55: _find_outlook_account where acc_name is set but not found → falls through to
  provider-based lookup
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from mail.outlook.helpers import (
    _find_outlook_account,
    resolve_outlook_args,
)


# ---------------------------------------------------------------------------
# _find_outlook_account branch: named account not found → falls back to provider match
# ---------------------------------------------------------------------------

class TestFindOutlookAccount(unittest.TestCase):
    """Cover _find_outlook_account with acc_name set but not matched."""

    def _write_accounts_yaml(self, content: str) -> str:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(content)
            return f.name

    def test_named_account_found_directly(self):
        """Happy path: acc_name matches a named account → returned immediately."""
        cfg_path = self._write_accounts_yaml("""
accounts:
  - name: work
    provider: outlook
    client_id: work-cid
  - name: personal
    provider: outlook
    client_id: personal-cid
""")
        try:
            result = _find_outlook_account(cfg_path, "personal")
            self.assertIsNotNone(result)
            self.assertEqual(result["client_id"], "personal-cid")
        finally:
            os.unlink(cfg_path)

    def test_named_account_not_found_falls_back_to_provider_match(self):
        """Line 53→55: acc_name provided but not found → falls through to provider lookup."""
        cfg_path = self._write_accounts_yaml("""
accounts:
  - name: personal
    provider: outlook
    client_id: fallback-cid
""")
        try:
            result = _find_outlook_account(cfg_path, "nonexistent")
            # Falls back to first Outlook provider account
            self.assertIsNotNone(result)
            self.assertEqual(result["client_id"], "fallback-cid")
        finally:
            os.unlink(cfg_path)

    def test_no_cfg_path_returns_none(self):
        """Guard: cfg_path is None → returns None without reading."""
        result = _find_outlook_account(None, "work")
        self.assertIsNone(result)

    def test_nonexistent_path_returns_none(self):
        """Guard: cfg_path doesn't exist → returns None."""
        result = _find_outlook_account("/nonexistent/path.yaml", "work")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# get_outlook_client — import error, missing client_id, success
# ---------------------------------------------------------------------------

class TestGetOutlookClient(unittest.TestCase):
    """Cover lines 96-109 in get_outlook_client."""

    def _import_fn(self):
        from mail.outlook.helpers import get_outlook_client
        return get_outlook_client

    def test_import_error_returns_none_and_error_code(self):
        """Line 14 / lines 97-100: OutlookClient import fails → (None, 1)."""
        get_outlook_client = self._import_fn()

        args = MagicMock()
        args.profile = None
        args.client_id = None
        args.tenant = None
        args.token = None
        args.cache_dir = None
        args.cache = None
        args.accounts_config = None
        args.account = None

        with patch("mail.outlook.helpers.resolve_outlook_args") as mock_resolve:
            mock_resolve.return_value = ("client-id", "tenant", None, None)
            with patch.dict("sys.modules", {"core.outlook": None}):
                # Simulating ImportError by patching the import inside the function
                import builtins
                real_import = builtins.__import__

                def failing_import(name, *args, **kwargs):
                    if name == "core.outlook":
                        raise ImportError("msal not installed")
                    return real_import(name, *args, **kwargs)

                with patch("builtins.__import__", side_effect=failing_import):
                    client, code = get_outlook_client(args)

        self.assertIsNone(client)
        self.assertEqual(code, 1)

    def test_missing_client_id_returns_none_and_error_code_2(self):
        """Lines 103-105: client_id resolves to None → (None, 2)."""
        get_outlook_client = self._import_fn()

        args = MagicMock()
        args.profile = None
        args.client_id = None
        args.tenant = None
        args.token = None
        args.cache_dir = None
        args.cache = None
        args.accounts_config = None
        args.account = None

        fake_outlook_module = MagicMock()
        fake_outlook_module.OutlookClient = MagicMock()

        with patch("mail.outlook.helpers.resolve_outlook_args") as mock_resolve:
            mock_resolve.return_value = (None, None, None, None)
            import builtins
            real_import = builtins.__import__

            def patched_import(name, *a, **kw):
                if name == "core.outlook":
                    return fake_outlook_module
                return real_import(name, *a, **kw)

            with patch("builtins.__import__", side_effect=patched_import):
                import io as _io
                buf = _io.StringIO()
                import contextlib
                with contextlib.redirect_stderr(buf):
                    client, code = get_outlook_client(args)

        self.assertIsNone(client)
        self.assertEqual(code, 2)
        self.assertIn("Missing", buf.getvalue())

    def test_successful_client_returns_zero_code(self):
        """Lines 107-109: happy path — client_id present, authenticate called → (client, 0)."""
        get_outlook_client = self._import_fn()

        fake_client_instance = MagicMock()
        fake_client_class = MagicMock(return_value=fake_client_instance)
        fake_outlook_module = MagicMock()
        fake_outlook_module.OutlookClient = fake_client_class

        args = MagicMock()

        with patch("mail.outlook.helpers.resolve_outlook_args") as mock_resolve:
            mock_resolve.return_value = ("my-client-id", "consumers", "/path/token.json", None)
            import builtins
            real_import = builtins.__import__

            def patched_import(name, *a, **kw):
                if name == "core.outlook":
                    return fake_outlook_module
                return real_import(name, *a, **kw)

            with patch("builtins.__import__", side_effect=patched_import):
                client, code = get_outlook_client(args)

        self.assertEqual(code, 0)
        self.assertIs(client, fake_client_instance)
        fake_client_instance.authenticate.assert_called_once()


# ---------------------------------------------------------------------------
# resolve_outlook_args: cache_dir populated from accounts config even when
# client_id already set via profile (lines 83-86)
# ---------------------------------------------------------------------------

class TestResolveOutlookArgsCacheFromConfig(unittest.TestCase):
    """Cover the second _find_outlook_account call in resolve_outlook_args.

    When client_id was set from profile but cache_dir was not, the function
    makes a second config lookup to pick up cache_dir.
    """

    def test_cache_dir_from_config_when_client_id_from_profile(self):
        """Lines 83-86: client_id set via profile but cache_dir missing → fetched from config."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
accounts:
  - name: personal
    provider: outlook
    client_id: cfg-client
    cache: /path/to/cache
""")
            cfg_path = f.name

        try:
            args = MagicMock()
            args.profile = "work"
            args.client_id = None
            args.tenant = None
            args.token = None
            args.cache_dir = None
            args.cache = None
            args.accounts_config = cfg_path
            args.account = None

            with patch("mail.outlook.helpers.resolve_outlook_credentials") as mock_resolve:
                # Profile resolves client_id but not cache
                mock_resolve.return_value = ("profile-client-id", "consumers", None)
                client_id, _, _, cache_dir = resolve_outlook_args(args)

            # client_id from profile, cache_dir from accounts config
            self.assertEqual(client_id, "profile-client-id")
            self.assertEqual(cache_dir, "/path/to/cache")
        finally:
            os.unlink(cfg_path)

    def test_cache_dir_not_fetched_when_already_set(self):
        """Happy path: cache_dir already set on args → second config lookup skipped."""
        args = MagicMock()
        args.profile = None
        args.client_id = "direct-cid"
        args.tenant = "consumers"
        args.token = None
        args.cache_dir = "/already/set"
        args.cache = None
        args.accounts_config = None
        args.account = None

        with patch("mail.outlook.helpers.resolve_outlook_credentials") as mock_resolve:
            mock_resolve.return_value = ("direct-cid", "consumers", None)
            _, _, _, cache_dir = resolve_outlook_args(args)

        self.assertEqual(cache_dir, "/already/set")


if __name__ == "__main__":
    unittest.main(verbosity=2)
