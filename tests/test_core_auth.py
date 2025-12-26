"""Tests for core/auth.py credential resolution."""

import os
import unittest
from unittest.mock import patch

from core.auth import resolve_gmail_credentials, resolve_outlook_credentials


class TestResolveGmailCredentials(unittest.TestCase):
    """Tests for resolve_gmail_credentials."""

    def test_explicit_args_take_priority(self):
        creds, token = resolve_gmail_credentials(  # noqa: S106
            profile=None,
            credentials_path="/explicit/creds.json",
            token_path="/explicit/token.json",
        )
        self.assertEqual(creds, "/explicit/creds.json")
        self.assertEqual(token, "/explicit/token.json")

    def test_returns_resolved_paths_when_no_args(self):
        # When no explicit args, resolve_gmail_credentials delegates to
        # resolve_paths_profile which checks INI files and defaults
        creds, token = resolve_gmail_credentials(
            profile=None,
            credentials_path=None,
            token_path=None,
        )
        # Should return some paths (from INI, env, or defaults)
        self.assertIsNotNone(creds)
        self.assertIsNotNone(token)
        self.assertTrue(creds.endswith(".json"))
        self.assertTrue(token.endswith(".json"))


class TestResolveOutlookCredentials(unittest.TestCase):
    """Tests for resolve_outlook_credentials."""

    def test_explicit_args_take_priority(self):
        client_id, tenant, token = resolve_outlook_credentials(  # noqa: S106
            profile=None,
            client_id="explicit-client-id",
            tenant="explicit-tenant",
            token_path="/explicit/outlook_token.json",
        )
        self.assertEqual(client_id, "explicit-client-id")
        self.assertEqual(tenant, "explicit-tenant")
        self.assertEqual(token, "/explicit/outlook_token.json")

    @patch.dict(os.environ, {
        "MAIL_ASSISTANT_OUTLOOK_CLIENT_ID": "env-client-id",
        "MAIL_ASSISTANT_OUTLOOK_TENANT": "env-tenant",
    })
    def test_env_vars_used_when_no_args(self):
        client_id, tenant, token = resolve_outlook_credentials(
            profile=None,
            client_id=None,
            tenant=None,
            token_path=None,
        )
        self.assertEqual(client_id, "env-client-id")
        self.assertEqual(tenant, "env-tenant")

    def test_tenant_defaults_to_consumers(self):
        with patch.dict(os.environ, {}, clear=True):
            _, tenant, _ = resolve_outlook_credentials(
                profile=None,
                client_id="test-id",
                tenant=None,
                token_path=None,
            )
            self.assertEqual(tenant, "consumers")


if __name__ == "__main__":
    unittest.main()
