"""Tests for uncovered Outlook producer output branches and helper functions."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from calendars.context import OutlookContext


class TestOutlookContextEnsureClient(unittest.TestCase):
    """Tests for OutlookContext.ensure_client fallback branches."""

    def test_resolve_falls_through_to_env_vars_when_unset(self):
        """resolve() threads through to real env-var resolution when nothing
        is set on the context and profile config resolvers are unavailable —
        distinct from the other tests here, which mock resolve_outlook_credentials
        away entirely and never exercise its real env-var fallback."""
        old_id = os.environ.get("MAIL_ASSISTANT_OUTLOOK_CLIENT_ID")
        old_tenant = os.environ.get("MAIL_ASSISTANT_OUTLOOK_TENANT")
        try:
            os.environ["MAIL_ASSISTANT_OUTLOOK_CLIENT_ID"] = "ENV_CLIENT"
            os.environ["MAIL_ASSISTANT_OUTLOOK_TENANT"] = "common"
            with patch("mail.config_resolver.get_outlook_client_id", return_value=None), \
                 patch("mail.config_resolver.get_outlook_tenant", return_value=None), \
                 patch("mail.config_resolver.get_outlook_token_path", return_value=None):
                ctx = OutlookContext()
                client_id, tenant, token_path = ctx.resolve()
            self.assertEqual(client_id, "ENV_CLIENT")
            self.assertEqual(tenant, "common")
            self.assertIsNone(token_path)
        finally:
            if old_id is None:
                os.environ.pop("MAIL_ASSISTANT_OUTLOOK_CLIENT_ID", None)
            else:
                os.environ["MAIL_ASSISTANT_OUTLOOK_CLIENT_ID"] = old_id
            if old_tenant is None:
                os.environ.pop("MAIL_ASSISTANT_OUTLOOK_TENANT", None)
            else:
                os.environ["MAIL_ASSISTANT_OUTLOOK_TENANT"] = old_tenant


if __name__ == "__main__":
    unittest.main()
