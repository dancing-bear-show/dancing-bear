"""Tests for core/secrets.py secret masking utilities."""

import unittest

from core.secrets import (
    mask_headers,
    mask_url,
    mask_text,
    _mask_value,
)


class MaskValueTests(unittest.TestCase):
    def test_empty_value(self):
        self.assertEqual(_mask_value(""), "")
        self.assertEqual(_mask_value(None), None)

    def test_bearer_token(self):
        self.assertEqual(_mask_value("Bearer abc123"), "Bearer ***REDACTED***")
        self.assertEqual(_mask_value("bearer xyz"), "Bearer ***REDACTED***")

    def test_token_prefix(self):
        self.assertEqual(_mask_value("Token secret123"), "Token ***REDACTED***")

    def test_basic_auth(self):
        self.assertEqual(_mask_value("Basic dXNlcjpwYXNz"), "Basic ***REDACTED***")

    def test_plain_value(self):
        self.assertEqual(_mask_value("some-api-key"), "***REDACTED***")


class MaskHeadersTests(unittest.TestCase):
    def test_empty_headers(self):
        self.assertEqual(mask_headers({}), {})
        self.assertEqual(mask_headers(None), {})

    def test_authorization_header(self):
        headers = {"Authorization": "Bearer secret123"}
        result = mask_headers(headers)
        self.assertEqual(result["Authorization"], "Bearer ***REDACTED***")

    def test_proxy_authorization(self):
        headers = {"Proxy-Authorization": "Basic creds"}
        result = mask_headers(headers)
        self.assertEqual(result["Proxy-Authorization"], "Basic ***REDACTED***")

    def test_x_api_key(self):
        headers = {"X-API-Key": "my-secret-key"}
        result = mask_headers(headers)
        self.assertEqual(result["X-API-Key"], "***REDACTED***")

    def test_x_auth_token(self):
        headers = {"X-Auth-Token": "token123"}
        result = mask_headers(headers)
        self.assertEqual(result["X-Auth-Token"], "***REDACTED***")

    def test_non_sensitive_headers_unchanged(self):
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/html",
        }
        result = mask_headers(headers)
        self.assertEqual(result["Content-Type"], "application/json")
        self.assertEqual(result["Accept"], "text/html")

    def test_mixed_headers(self):
        headers = {
            "Authorization": "Bearer secret",
            "Content-Type": "application/json",
        }
        result = mask_headers(headers)
        self.assertEqual(result["Authorization"], "Bearer ***REDACTED***")
        self.assertEqual(result["Content-Type"], "application/json")


class MaskUrlTests(unittest.TestCase):
    def test_empty_url(self):
        self.assertEqual(mask_url(""), "")
        self.assertEqual(mask_url(None), "")

    def test_url_without_query(self):
        url = "https://api.example.com/v1/users"
        self.assertEqual(mask_url(url), url)

    def test_url_with_token_param(self):
        url = "https://api.example.com?token=secret123"
        result = mask_url(url)
        self.assertIn("token=***REDACTED***", result)
        self.assertNotIn("secret123", result)

    def test_url_with_access_token(self):
        url = "https://api.example.com?access_token=xyz789"
        result = mask_url(url)
        self.assertIn("access_token=***REDACTED***", result)

    def test_url_with_password(self):
        url = "https://api.example.com?password=hunter2"
        result = mask_url(url)
        self.assertIn("password=***REDACTED***", result)

    def test_url_with_mixed_params(self):
        url = "https://api.example.com?user=john&token=secret&page=1"
        result = mask_url(url)
        self.assertIn("user=john", result)
        self.assertIn("token=***REDACTED***", result)
        self.assertIn("page=1", result)

    def test_url_preserves_structure(self):
        url = "https://api.example.com:8080/path?token=x#fragment"
        result = mask_url(url)
        self.assertTrue(result.startswith("https://api.example.com:8080/path"))
        self.assertIn("#fragment", result)


class MaskTextTests(unittest.TestCase):
    def test_empty_text(self):
        self.assertEqual(mask_text(""), "")
        self.assertEqual(mask_text(None), "")

    def test_authorization_bearer(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("eyJ", result)

    def test_authorization_basic(self):
        text = "Authorization: Basic dXNlcm5hbWU6cGFzc3dvcmQ="
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("dXNlcm5hbWU", result)

    def test_x_api_key_header(self):
        text = "X-API-KEY: sk-1234567890abcdef"
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("sk-1234567890", result)

    def test_token_equals(self):
        text = "token=abc123def456"
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("abc123", result)

    def test_json_token_field(self):
        text = '{"access_token": "secret-value-here"}'
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("secret-value-here", result)

    def test_json_password_field(self):
        text = '{"password": "hunter2"}'
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("hunter2", result)

    def test_github_token(self):
        text = "Using token ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        result = mask_text(text)
        self.assertIn("gh_***REDACTED***", result)
        self.assertNotIn("ghp_x", result)

    def test_github_oauth_token(self):
        text = "gho_abcdefghijklmnopqrstuvwxyz123456"
        result = mask_text(text)
        self.assertIn("gh_***REDACTED***", result)

    def test_aws_secret_key(self):
        text = "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("wJalrXUtnFEMI", result)

    def test_aws_session_token(self):
        text = "aws_session_token: FwoGZXIvYXdzEBYaDPxxx"
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)

    def test_url_query_token(self):
        text = "GET /api?token=secret123&user=john"
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)
        self.assertIn("user=john", result)

    def test_non_sensitive_text_unchanged(self):
        text = "This is a normal log message with no secrets"
        result = mask_text(text)
        self.assertEqual(result, text)

    def test_atlassian_token(self):
        text = "ATATT3xFfGF0abcdefghijklmnopqrst"
        result = mask_text(text)
        self.assertIn("AT***REDACTED***", result)


if __name__ == "__main__":
    unittest.main()
