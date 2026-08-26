"""Shared test fixtures for outlook auth and messages-search tests."""

from __future__ import annotations

import types
from unittest.mock import MagicMock


def make_fake_msal_module(flow_success=True, has_accounts=True, silent_success=True,
                          device_success=True, acquire_success=True, user_code="ABC123"):
    """Factory for creating fake msal modules with configurable behavior."""
    msal = types.ModuleType("msal")

    class _Cache:
        def __init__(self):
            self._s = "{}"

        def serialize(self):
            return self._s

        def deserialize(self, s):
            self._s = s or "{}"

    class _App:
        def __init__(self, client_id, authority=None, token_cache=None):
            self.client_id = client_id
            self.authority = authority
            self.token_cache = token_cache

        def initiate_device_flow(self, scopes):  # NOSONAR S1172 - mirrors msal API; stub ignores args
            if not flow_success or not device_success:
                return {}
            return {
                "user_code": user_code,
                "verification_uri": "https://microsoft.com/devicelogin",
                "message": f"Visit https://microsoft.com/devicelogin and enter {user_code}",
                "expires_in": 900,
            }

        def acquire_token_by_device_flow(self, flow):  # NOSONAR S1172 - mirrors msal API; stub ignores args
            if not acquire_success or not device_success:
                return {"error": "authorization_pending"}
            return {"access_token": "fake-token", "expires_in": 3600}

        def get_accounts(self):
            if not has_accounts:
                return []
            return [{"username": "user@example.com"}]

        def acquire_token_silent(self, scopes, account=None):  # NOSONAR S1172 - mirrors msal API; stub ignores args
            if not silent_success:
                return None
            return {"access_token": "fake-token", "expires_in": 3600}

    msal.SerializableTokenCache = _Cache
    msal.PublicClientApplication = _App
    return msal


def make_graph_message(
    *,
    id: str = "msg-1",
    subject: str = "Hello",
    received: str = "2026-01-15T20:00:00Z",
    from_name: str = "Sender",
    from_addr: str = "sender@example.com",
    preview: str = "Body preview",
    has_attachments: bool = False,
) -> dict:
    """Build a Graph API message payload for messages-search tests."""
    return {
        "id": id,
        "subject": subject,
        "receivedDateTime": received,
        "from": {"emailAddress": {"name": from_name, "address": from_addr}},
        "bodyPreview": preview,
        "hasAttachments": has_attachments,
    }


def make_response(messages: list, next_link: str = None) -> MagicMock:
    """Build a mock Graph API response wrapping `messages`."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    data = {"value": messages}
    if next_link:
        data["@odata.nextLink"] = next_link
    resp.json.return_value = data
    return resp
