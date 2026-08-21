"""Tests for OutlookClientBase and _TimeoutRequestsWrapper — unique tests not in test_core_outlook_client.py."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.outlook.client import (
    OutlookClientBase,
    _TimeoutRequestsWrapper,
)


class TestTimeoutRequestsWrapper(unittest.TestCase):
    """Tests for _TimeoutRequestsWrapper — exception propagation."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_requests = MagicMock()
        self.wrapper = _TimeoutRequestsWrapper(self.mock_requests, 30)

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
    """Tests for OutlookClientBase initialization — unique behaviors."""

    def test_init_missing_required_client_id_raises_type_error(self):
        """Test OutlookClientBase() without client_id raises TypeError (required positional arg)."""
        with self.assertRaises(TypeError):
            OutlookClientBase()


if __name__ == "__main__":
    unittest.main()
