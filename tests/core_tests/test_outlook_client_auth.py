"""Tests for OutlookClientBase authentication, headers, and mailbox settings."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch, mock_open

from core.outlook.client import OutlookClientBase


def make_mock_response(json_data=None, status_code=200, text=None):
    """Create a mock HTTP response object."""
    resp = MagicMock()
    resp.status_code = status_code
    if text is not None:
        resp.text = text
    elif json_data:
        resp.text = str(json_data)
    else:
        resp.text = ""
    resp.json.return_value = json_data

    def raise_for_status():
        if status_code >= 400:
            raise RuntimeError(f"HTTP {status_code}")

    resp.raise_for_status = raise_for_status
    return resp


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

        client = OutlookClientBase(client_id="test-id", token_path=self.token_path)

        with patch('builtins.print') as mock_print:
            client.authenticate()

        mock_app.initiate_device_flow.assert_called_once()
        mock_print.assert_called_once()
        self.assertIn("ABC123", mock_print.call_args[0][0])

        self.assertIsNotNone(client._token)
        self.assertEqual(client._token["access_token"], "test-token")
        self.assertTrue(os.path.exists(self.token_path))

    @patch('core.outlook.client._msal')
    def test_authenticate_silent_success(self, mock_msal_fn):
        """Test successful silent authentication with cached token."""
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

        client = OutlookClientBase(client_id="test-id", token_path=self.token_path)
        client.authenticate()

        mock_app.acquire_token_silent.assert_called_once()
        self.assertEqual(client._token["access_token"], "silent-token")
        mock_app.initiate_device_flow.assert_not_called()

    @patch('core.outlook.client._msal')
    def test_authenticate_loads_existing_token_cache(self, mock_msal_fn):
        """Test loading existing token cache from file."""
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

        with open(self.token_path, 'w') as f:
            f.write('{"cached": "token"}')

        client = OutlookClientBase(client_id="test-id", token_path=self.token_path)
        client.authenticate()

        mock_cache.deserialize.assert_called_once()

    @patch('core.outlook.client._msal')
    def test_authenticate_legacy_token_format(self, mock_msal_fn):
        """Test loading legacy simple token format."""
        mock_msal = MagicMock()
        mock_msal_fn.return_value = mock_msal

        mock_cache = MagicMock()
        mock_cache.deserialize.side_effect = Exception("Not MSAL format")
        mock_msal.SerializableTokenCache.return_value = mock_cache

        mock_app = MagicMock()
        mock_msal.PublicClientApplication.return_value = mock_app

        legacy_token = {
            "access_token": "legacy-token",
            "expires_at": time.time() + 3600
        }
        with open(self.token_path, 'w') as f:
            json.dump(legacy_token, f)

        client = OutlookClientBase(client_id="test-id", token_path=self.token_path)
        client.authenticate()

        self.assertEqual(client._token["access_token"], "legacy-token")

    @patch('core.outlook.client._msal')
    def test_authenticate_device_flow_failure(self, mock_msal_fn):
        """Test device flow authentication failure."""
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

        client = OutlookClientBase(client_id="test-id")

        with self.assertRaises(RuntimeError) as ctx:
            with patch('builtins.print'):
                client.authenticate()

        self.assertIn("Device flow failed", str(ctx.exception))

    @patch('core.outlook.client._msal')
    def test_authenticate_no_user_code_in_flow(self, mock_msal_fn):
        """Test device flow initiation failure."""
        mock_msal = MagicMock()
        mock_msal_fn.return_value = mock_msal

        mock_cache = MagicMock()
        mock_msal.SerializableTokenCache.return_value = mock_cache

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {"error": "failed"}
        mock_msal.PublicClientApplication.return_value = mock_app

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

        self.client._app = mock_app
        self.client._cache = mock_cache
        self.client.token_path = "/tmp/token.json"  # nosec  # Test uses temp file path

        with patch('builtins.open', mock_open()) as mock_file:
            headers = self.client._headers()

        self.assertEqual(self.client._token["access_token"], "refreshed-token")
        self.assertEqual(headers["Authorization"], "Bearer refreshed-token")
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


if __name__ == "__main__":
    unittest.main()
