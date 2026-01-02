"""Tests for core/outlook/client.py base client functionality."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch, mock_open

from core.outlook.client import (
    OutlookClientBase,
    _TimeoutRequestsWrapper,
    DEFAULT_TIMEOUT,
    GRAPH,
    SCOPES,
)


# -------------------- Fixtures --------------------

def make_mock_response(json_data=None, status_code=200, text=None):
    """Create a mock HTTP response object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text if text is not None else (str(json_data) if json_data else "")
    resp.json.return_value = json_data

    def raise_for_status():
        if status_code >= 400:
            raise Exception(f"HTTP {status_code}")

    resp.raise_for_status = raise_for_status
    return resp


# -------------------- TimeoutRequestsWrapper Tests --------------------

class TestTimeoutRequestsWrapper(unittest.TestCase):
    """Tests for _TimeoutRequestsWrapper."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_requests = MagicMock()
        self.wrapper = _TimeoutRequestsWrapper(self.mock_requests, 30)

    def test_get_adds_default_timeout(self):
        """Test GET request adds default timeout."""
        self.wrapper.get("https://example.com")
        self.mock_requests.get.assert_called_once_with("https://example.com", timeout=30)

    def test_get_respects_custom_timeout(self):
        """Test GET request respects custom timeout."""
        self.wrapper.get("https://example.com", timeout=60)
        self.mock_requests.get.assert_called_once_with("https://example.com", timeout=60)

    def test_post_adds_default_timeout(self):
        """Test POST request adds default timeout."""
        self.wrapper.post("https://example.com", json={"key": "value"})
        self.mock_requests.post.assert_called_once_with(
            "https://example.com", json={"key": "value"}, timeout=30
        )

    def test_patch_adds_default_timeout(self):
        """Test PATCH request adds default timeout."""
        self.wrapper.patch("https://example.com", json={"key": "value"})
        self.mock_requests.patch.assert_called_once_with(
            "https://example.com", json={"key": "value"}, timeout=30
        )

    def test_delete_adds_default_timeout(self):
        """Test DELETE request adds default timeout."""
        self.wrapper.delete("https://example.com")
        self.mock_requests.delete.assert_called_once_with("https://example.com", timeout=30)

    def test_put_adds_default_timeout(self):
        """Test PUT request adds default timeout."""
        self.wrapper.put("https://example.com", json={"key": "value"})
        self.mock_requests.put.assert_called_once_with(
            "https://example.com", json={"key": "value"}, timeout=30
        )

    def test_head_adds_default_timeout(self):
        """Test HEAD request adds default timeout."""
        self.wrapper.head("https://example.com")
        self.mock_requests.head.assert_called_once_with("https://example.com", timeout=30)

    def test_preserves_other_kwargs(self):
        """Test wrapper preserves other keyword arguments."""
        self.wrapper.get("https://example.com", headers={"X-Custom": "value"}, verify=False)
        self.mock_requests.get.assert_called_once_with(
            "https://example.com", headers={"X-Custom": "value"}, verify=False, timeout=30
        )


# -------------------- OutlookClientBase Tests --------------------

class TestOutlookClientBaseInit(unittest.TestCase):
    """Tests for OutlookClientBase initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default values."""
        client = OutlookClientBase(client_id="test-client-id")
        self.assertEqual(client.client_id, "test-client-id")
        self.assertEqual(client.tenant, "consumers")
        self.assertIsNone(client.token_path)
        self.assertIsNone(client.cache_dir)
        self.assertIsNone(client._token)
        self.assertIsNone(client._cache)
        self.assertIsNone(client._app)
        self.assertEqual(client.GRAPH, GRAPH)

    def test_init_with_custom_values(self):
        """Test initialization with custom values."""
        client = OutlookClientBase(
            client_id="custom-id",
            tenant="common",
            token_path="/tmp/token.json",
            cache_dir="/tmp/cache"
        )
        self.assertEqual(client.client_id, "custom-id")
        self.assertEqual(client.tenant, "common")
        self.assertEqual(client.token_path, "/tmp/token.json")
        self.assertEqual(client.cache_dir, "/tmp/cache")

    def test_inherits_from_config_cache_mixin(self):
        """Test client inherits from ConfigCacheMixin."""
        client = OutlookClientBase(client_id="test-id", cache_dir="/tmp/cache")
        # ConfigCacheMixin should provide cfg_get_json and cfg_put_json methods
        self.assertTrue(hasattr(client, 'cfg_get_json'))
        self.assertTrue(hasattr(client, 'cfg_put_json'))


class TestOutlookClientBaseAuthentication(unittest.TestCase):
    """Tests for OutlookClientBase authentication."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.token_path = os.path.join(self.temp_dir, "token.json")

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch('core.outlook.client._msal')
    def test_authenticate_device_flow_success(self, mock_msal_fn):
        """Test successful device flow authentication."""
        # Mock MSAL components
        mock_msal = MagicMock()
        mock_msal_fn.return_value = mock_msal

        mock_cache = MagicMock()
        mock_cache.serialize.return_value = '{"token": "data"}'
        mock_msal.SerializableTokenCache.return_value = mock_cache

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {
            "user_code": "ABC123",
            "verification_uri": "https://microsoft.com/devicelogin"
        }
        mock_app.acquire_token_by_device_flow.return_value = {
            "access_token": "test-token",
            "expires_in": 3600
        }
        mock_msal.PublicClientApplication.return_value = mock_app

        # Create client and authenticate
        client = OutlookClientBase(client_id="test-id", token_path=self.token_path)

        with patch('builtins.print') as mock_print:
            client.authenticate()

        # Verify device flow was initiated
        mock_app.initiate_device_flow.assert_called_once()
        mock_print.assert_called_once()
        self.assertIn("ABC123", mock_print.call_args[0][0])

        # Verify token was stored
        self.assertIsNotNone(client._token)
        self.assertEqual(client._token["access_token"], "test-token")

        # Verify token was saved to file
        self.assertTrue(os.path.exists(self.token_path))

    @patch('core.outlook.client._msal')
    def test_authenticate_silent_success(self, mock_msal_fn):
        """Test successful silent authentication with cached token."""
        # Mock MSAL components
        mock_msal = MagicMock()
        mock_msal_fn.return_value = mock_msal

        mock_cache = MagicMock()
        mock_cache.serialize.return_value = '{"token": "cached"}'
        mock_msal.SerializableTokenCache.return_value = mock_cache

        mock_app = MagicMock()
        mock_account = {"username": "test@example.com"}
        mock_app.get_accounts.return_value = [mock_account]
        mock_app.acquire_token_silent.return_value = {
            "access_token": "silent-token",
            "expires_in": 3600
        }
        mock_msal.PublicClientApplication.return_value = mock_app

        # Create client and authenticate
        client = OutlookClientBase(client_id="test-id", token_path=self.token_path)
        client.authenticate()

        # Verify silent auth was attempted
        mock_app.acquire_token_silent.assert_called_once()

        # Verify token was set
        self.assertEqual(client._token["access_token"], "silent-token")

        # Verify device flow was NOT called
        mock_app.initiate_device_flow.assert_not_called()

    @patch('core.outlook.client._msal')
    def test_authenticate_loads_existing_token_cache(self, mock_msal_fn):
        """Test loading existing token cache from file."""
        # Mock MSAL components
        mock_msal = MagicMock()
        mock_msal_fn.return_value = mock_msal

        mock_cache = MagicMock()
        mock_cache.serialize.return_value = '{"cached": "data"}'
        mock_msal.SerializableTokenCache.return_value = mock_cache

        mock_app = MagicMock()
        mock_account = {"username": "test@example.com"}
        mock_app.get_accounts.return_value = [mock_account]
        mock_app.acquire_token_silent.return_value = {
            "access_token": "cached-token",
            "expires_in": 3600
        }
        mock_msal.PublicClientApplication.return_value = mock_app

        # Create token cache file
        with open(self.token_path, 'w') as f:
            f.write('{"cached": "token"}')

        # Create client and authenticate
        client = OutlookClientBase(client_id="test-id", token_path=self.token_path)
        client.authenticate()

        # Verify cache was deserialized
        mock_cache.deserialize.assert_called_once()

    @patch('core.outlook.client._msal')
    def test_authenticate_legacy_token_format(self, mock_msal_fn):
        """Test loading legacy simple token format."""
        # Mock MSAL components
        mock_msal = MagicMock()
        mock_msal_fn.return_value = mock_msal

        mock_cache = MagicMock()
        mock_cache.deserialize.side_effect = Exception("Not MSAL format")
        mock_msal.SerializableTokenCache.return_value = mock_cache

        mock_app = MagicMock()
        mock_msal.PublicClientApplication.return_value = mock_app

        # Create legacy token file
        legacy_token = {
            "access_token": "legacy-token",
            "expires_at": time.time() + 3600
        }
        with open(self.token_path, 'w') as f:
            json.dump(legacy_token, f)

        # Create client and authenticate
        client = OutlookClientBase(client_id="test-id", token_path=self.token_path)
        client.authenticate()

        # Verify legacy token was loaded
        self.assertEqual(client._token["access_token"], "legacy-token")

    @patch('core.outlook.client._msal')
    def test_authenticate_device_flow_failure(self, mock_msal_fn):
        """Test device flow authentication failure."""
        # Mock MSAL components
        mock_msal = MagicMock()
        mock_msal_fn.return_value = mock_msal

        mock_cache = MagicMock()
        mock_msal.SerializableTokenCache.return_value = mock_cache

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {
            "user_code": "ABC123",
            "verification_uri": "https://microsoft.com/devicelogin"
        }
        mock_app.acquire_token_by_device_flow.return_value = {
            "error": "user_cancelled",
            "error_description": "User cancelled the flow"
        }
        mock_msal.PublicClientApplication.return_value = mock_app

        # Create client and authenticate
        client = OutlookClientBase(client_id="test-id")

        with self.assertRaises(RuntimeError) as ctx:
            with patch('builtins.print'):
                client.authenticate()

        self.assertIn("Device flow failed", str(ctx.exception))

    @patch('core.outlook.client._msal')
    def test_authenticate_no_user_code_in_flow(self, mock_msal_fn):
        """Test device flow initiation failure."""
        # Mock MSAL components
        mock_msal = MagicMock()
        mock_msal_fn.return_value = mock_msal

        mock_cache = MagicMock()
        mock_msal.SerializableTokenCache.return_value = mock_cache

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {"error": "failed"}
        mock_msal.PublicClientApplication.return_value = mock_app

        # Create client and authenticate
        client = OutlookClientBase(client_id="test-id")

        with self.assertRaises(RuntimeError) as ctx:
            client.authenticate()

        self.assertIn("Failed to start device flow", str(ctx.exception))


class TestOutlookClientBaseHeaders(unittest.TestCase):
    """Tests for OutlookClientBase header generation."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = OutlookClientBase(client_id="test-id")
        self.client._token = {
            "access_token": "test-token",
            "expires_at": time.time() + 3600
        }

    def test_headers_returns_correct_format(self):
        """Test _headers returns proper authorization headers."""
        headers = self.client._headers()

        self.assertEqual(headers["Authorization"], "Bearer test-token")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_headers_raises_without_token(self):
        """Test _headers raises error when not authenticated."""
        client = OutlookClientBase(client_id="test-id")

        with self.assertRaises(RuntimeError) as ctx:
            client._headers()

        self.assertIn("not authenticated", str(ctx.exception))

    @patch('core.outlook.client._msal')
    def test_headers_refreshes_token_silently(self, mock_msal_fn):
        """Test _headers attempts silent token refresh."""
        # Mock MSAL components
        mock_msal = MagicMock()
        mock_msal_fn.return_value = mock_msal

        mock_cache = MagicMock()
        mock_cache.serialize.return_value = '{"refreshed": "token"}'

        mock_app = MagicMock()
        mock_account = {"username": "test@example.com"}
        mock_app.get_accounts.return_value = [mock_account]
        mock_app.acquire_token_silent.return_value = {
            "access_token": "refreshed-token",
            "expires_in": 3600
        }

        # Set up client with app and cache
        self.client._app = mock_app
        self.client._cache = mock_cache
        self.client.token_path = "/tmp/token.json"

        with patch('builtins.open', mock_open()) as mock_file:
            headers = self.client._headers()

        # Verify token was refreshed
        self.assertEqual(self.client._token["access_token"], "refreshed-token")

        # Verify Authorization header uses refreshed token
        self.assertEqual(headers["Authorization"], "Bearer refreshed-token")

        # Verify token was saved
        mock_file.assert_called()

    def test_headers_search_adds_consistency_level(self):
        """Test _headers_search adds ConsistencyLevel header."""
        headers = self.client._headers_search()

        self.assertEqual(headers["Authorization"], "Bearer test-token")
        self.assertEqual(headers["ConsistencyLevel"], "eventual")


class TestOutlookClientBaseMailboxSettings(unittest.TestCase):
    """Tests for OutlookClientBase mailbox settings methods."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = OutlookClientBase(client_id="test-id")
        self.client._token = {
            "access_token": "test-token",
            "expires_at": time.time() + 3600
        }

    @patch('core.outlook.client._requests')
    def test_get_mailbox_timezone_success(self, mock_requests_fn):
        """Test successful mailbox timezone retrieval."""
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_response = make_mock_response(
            json_data={"timeZone": "Pacific Standard Time"}
        )
        mock_requests.get.return_value = mock_response

        tz = self.client.get_mailbox_timezone()

        self.assertEqual(tz, "Pacific Standard Time")
        mock_requests.get.assert_called_once()

    @patch('core.outlook.client._requests')
    def test_get_mailbox_timezone_returns_none_on_error(self, mock_requests_fn):
        """Test mailbox timezone returns None on error."""
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_requests.get.side_effect = Exception("API error")

        tz = self.client.get_mailbox_timezone()

        self.assertIsNone(tz)

    @patch('core.outlook.client._requests')
    def test_get_mailbox_timezone_handles_empty_timezone(self, mock_requests_fn):
        """Test mailbox timezone handles empty/whitespace values."""
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_response = make_mock_response(json_data={"timeZone": "  "})
        mock_requests.get.return_value = mock_response

        tz = self.client.get_mailbox_timezone()

        self.assertIsNone(tz)

    @patch('core.outlook.client._requests')
    def test_get_mailbox_timezone_handles_missing_timezone(self, mock_requests_fn):
        """Test mailbox timezone handles missing timezone field."""
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests

        mock_response = make_mock_response(json_data={})
        mock_requests.get.return_value = mock_response

        tz = self.client.get_mailbox_timezone()

        self.assertIsNone(tz)


class TestOutlookClientBaseConstants(unittest.TestCase):
    """Tests for module-level constants."""

    def test_default_timeout_constant(self):
        """Test DEFAULT_TIMEOUT is set correctly."""
        self.assertIsInstance(DEFAULT_TIMEOUT, tuple)
        self.assertEqual(len(DEFAULT_TIMEOUT), 2)
        self.assertGreater(DEFAULT_TIMEOUT[0], 0)  # connect timeout
        self.assertGreater(DEFAULT_TIMEOUT[1], 0)  # read timeout

    def test_graph_constant(self):
        """Test GRAPH constant is set."""
        self.assertIsInstance(GRAPH, str)
        self.assertIn("graph.microsoft.com", GRAPH)

    def test_scopes_constant(self):
        """Test SCOPES constant is set."""
        self.assertIsInstance(SCOPES, list)
        self.assertGreater(len(SCOPES), 0)


if __name__ == "__main__":
    unittest.main()
