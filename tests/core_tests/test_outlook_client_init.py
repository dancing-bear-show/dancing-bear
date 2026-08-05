"""Tests for OutlookClientBase initialization, constants, and _TimeoutRequestsWrapper."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.outlook.client import (
    OutlookClientBase,
    _TimeoutRequestsWrapper,
)
from core.constants import (
    DEFAULT_REQUEST_TIMEOUT,
    GRAPH_API_URL,
    GRAPH_API_SCOPES,
)


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

    def test_get_propagates_underlying_exception(self):
        """Test GET propagates exceptions raised by the wrapped requests module unchanged."""
        self.mock_requests.get.side_effect = ConnectionError("connection refused")
        with self.assertRaises(ConnectionError):
            self.wrapper.get("https://example.com")

    def test_post_propagates_underlying_exception(self):
        """Test POST propagates exceptions raised by the wrapped requests module unchanged."""
        self.mock_requests.post.side_effect = TimeoutError("request timed out")
        with self.assertRaises(TimeoutError):
            self.wrapper.post("https://example.com", json={"key": "value"})

    def test_patch_propagates_underlying_exception(self):
        """Test PATCH propagates exceptions raised by the wrapped requests module unchanged."""
        self.mock_requests.patch.side_effect = TimeoutError("request timed out")
        with self.assertRaises(TimeoutError):
            self.wrapper.patch("https://example.com", json={"key": "value"})

    def test_delete_propagates_underlying_exception(self):
        """Test DELETE propagates exceptions raised by the wrapped requests module unchanged."""
        self.mock_requests.delete.side_effect = ConnectionError("connection refused")
        with self.assertRaises(ConnectionError):
            self.wrapper.delete("https://example.com")

    def test_put_propagates_underlying_exception(self):
        """Test PUT propagates exceptions raised by the wrapped requests module unchanged."""
        self.mock_requests.put.side_effect = TimeoutError("request timed out")
        with self.assertRaises(TimeoutError):
            self.wrapper.put("https://example.com", json={"key": "value"})


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
        self.assertEqual(client.GRAPH, GRAPH_API_URL)

    def test_init_with_custom_values(self):
        """Test initialization with custom values."""
        client = OutlookClientBase(
            client_id="custom-id",
            tenant="common",
            token_path="/tmp/token.json",  # nosec  # Test uses temp directory
            cache_dir="/tmp/cache"  # nosec  # Test uses temp directory
        )
        self.assertEqual(client.client_id, "custom-id")
        self.assertEqual(client.tenant, "common")
        self.assertEqual(client.token_path, "/tmp/token.json")  # nosec  # Test assertion
        self.assertEqual(client.cache_dir, "/tmp/cache")  # nosec  # Test assertion

    def test_inherits_from_config_cache_mixin(self):
        """Test client inherits from ConfigCacheMixin."""
        client = OutlookClientBase(client_id="test-id", cache_dir="/tmp/cache")  # nosec  # Test uses temp directory
        # ConfigCacheMixin should provide cfg_get_json and cfg_put_json methods
        self.assertTrue(hasattr(client, 'cfg_get_json'))
        self.assertTrue(hasattr(client, 'cfg_put_json'))

    def test_init_missing_required_client_id_raises_type_error(self):
        """Test OutlookClientBase() without client_id raises TypeError (required positional arg)."""
        with self.assertRaises(TypeError):
            OutlookClientBase()


class TestOutlookClientBaseConstants(unittest.TestCase):
    """Tests for module-level constants."""

    def test_default_timeout_constant(self):
        """Test DEFAULT_REQUEST_TIMEOUT is set correctly."""
        self.assertIsInstance(DEFAULT_REQUEST_TIMEOUT, tuple)
        self.assertEqual(len(DEFAULT_REQUEST_TIMEOUT), 2)
        self.assertGreater(DEFAULT_REQUEST_TIMEOUT[0], 0)  # connect timeout
        self.assertGreater(DEFAULT_REQUEST_TIMEOUT[1], 0)  # read timeout

    def test_graph_constant(self):
        """Test GRAPH_API_URL constant is set."""
        self.assertIsInstance(GRAPH_API_URL, str)
        self.assertIn("graph.microsoft.com", GRAPH_API_URL)

    def test_scopes_constant(self):
        """Test GRAPH_API_SCOPES constant is set."""
        self.assertIsInstance(GRAPH_API_SCOPES, list)
        self.assertGreater(len(GRAPH_API_SCOPES), 0)


if __name__ == "__main__":
    unittest.main()
