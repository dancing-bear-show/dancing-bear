"""Tests for mail/utils/shield.py."""

from __future__ import annotations

import unittest


class TestMaskStr(unittest.TestCase):
    """Tests for the _mask_str helper."""

    def test_short_value_returns_stars(self):
        from mail.utils.shield import _mask_str
        result = _mask_str("abc")
        self.assertEqual(result, "***")

    def test_exact_head_plus_tail_returns_stars(self):
        from mail.utils.shield import _mask_str
        # head=4, tail=4, so exactly 8 chars => "***"
        result = _mask_str("12345678")
        self.assertEqual(result, "***")

    def test_long_value_shows_head_and_tail(self):
        from mail.utils.shield import _mask_str
        result = _mask_str("abcde12345fghij")
        self.assertIn("abcd", result)
        self.assertIn("ghij", result)
        self.assertIn("len=15", result)

    def test_custom_head_tail(self):
        from mail.utils.shield import _mask_str
        result = _mask_str("ABCDEFGHIJKLMN", head=2, tail=2)
        self.assertIn("AB", result)
        self.assertIn("MN", result)


class TestContainsSecretishValue(unittest.TestCase):
    """Tests for _contains_secretish_value pattern matching."""

    def _check(self, value: str) -> bool:
        from mail.utils.shield import _contains_secretish_value
        return _contains_secretish_value(value)

    # --- GitHub personal access token ---
    def test_github_token_matches(self):
        self.assertTrue(self._check("ghp_ABCDEFGHIJ1234567890XY"))

    def test_github_token_too_short_does_not_match(self):
        self.assertFalse(self._check("ghp_short"))

    # --- Grafana service account token ---
    def test_grafana_token_matches(self):
        self.assertTrue(self._check("glsa_ABCDEFGHIJ1234567890"))

    # --- Slack tokens ---
    def test_slack_bot_token_matches(self):
        self.assertTrue(self._check("xoxb-ABCDEFGH-1234567890-XYZA"))

    def test_slack_app_token_matches(self):
        self.assertTrue(self._check("xoxa-ABCDE-12345678901234"))

    def test_slack_prefix_too_short_does_not_match(self):
        self.assertFalse(self._check("xoxb-short"))

    # --- API tokens (LaunchDarkly style) ---
    def test_api_token_matches(self):
        self.assertTrue(self._check("api-ABCDEF1234567890"))

    def test_api_token_too_short_does_not_match(self):
        self.assertFalse(self._check("api-ABC123"))

    # --- Rootly ---
    def test_rootly_token_matches(self):
        self.assertTrue(self._check("rootly_ABCDEFGHIJKLMNOP"))

    # --- OpenAI tokens ---
    def test_openai_live_token_matches(self):
        self.assertTrue(self._check("sk-live-ABCDEFGHIJ1234567890XY"))

    def test_openai_test_token_matches(self):
        self.assertTrue(self._check("sk-test-ABCDEFGHIJ1234567890XY"))

    def test_openai_proj_token_matches(self):
        self.assertTrue(self._check("sk-proj-ABCDEFGHIJ1234567890XY"))

    # --- Google OAuth access token ---
    def test_google_oauth_token_matches(self):
        self.assertTrue(self._check("ya29.ABCDEFGHIJKLMNOPQRSTU1234567890"))

    # --- Google API key ---
    def test_google_api_key_matches(self):
        self.assertTrue(self._check("AIzaABCDEFGHIJKLMNOPQRST"))

    # --- JWT-like tokens ---
    def test_jwt_token_matches(self):
        self.assertTrue(self._check("eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyMTIzIn0.SflKxwRJSMeKKF"))

    def test_jwt_too_short_does_not_match(self):
        self.assertFalse(self._check("eyJ.eyJ.abc"))

    # --- MSAL/Graph tokens ---
    def test_msal_token_matches(self):
        self.assertTrue(self._check("M.ABCDEFGHIJKLMNOPQRSTU.long_opaque_token_value"))

    # --- Benign value ---
    def test_plain_word_does_not_match(self):
        self.assertFalse(self._check("hello"))

    def test_empty_string_does_not_match(self):
        self.assertFalse(self._check(""))


class TestMaskValue(unittest.TestCase):
    """Tests for mask_value()."""

    def _mask(self, key: str, val: str) -> str:
        from mail.utils.shield import mask_value
        return mask_value(key, val)

    # --- Path detection ---
    def test_unix_path_shows_exists_hint(self):
        result = self._mask("some_key", "/etc/hosts")
        self.assertIn("/etc/hosts", result)
        self.assertIn("exists:", result)

    def test_windows_path_shows_exists_hint(self):
        result = self._mask("some_key", "C:\\Users\\test\\token.json")
        self.assertIn("exists:", result)

    def test_nonexistent_path_shows_no(self):
        result = self._mask("some_key", "/nonexistent/fake/path/file.json")
        self.assertIn("no", result)

    # --- Secret-key names ---
    def test_token_key_masks_value(self):
        result = self._mask("token", "abcdefghijklmnopqrstuvwxyz")
        self.assertIn("…", result)
        self.assertNotIn("ghijklmno", result)

    def test_secret_key_masks_value(self):
        result = self._mask("my_secret", "super_secret_password_long")
        self.assertIn("…", result)

    def test_password_key_masks_value(self):
        result = self._mask("password", "s3cr3tPassw0rdValue!")
        self.assertIn("…", result)

    def test_api_key_key_masks_value(self):
        result = self._mask("api_key", "some_long_api_key_value_here")
        self.assertIn("…", result)

    def test_access_token_key_masks_value(self):
        result = self._mask("access_token", "some_long_access_token_value12")
        self.assertIn("…", result)

    def test_bearer_key_masks_value(self):
        result = self._mask("bearer", "BearerTokenValueThatIsLong")
        self.assertIn("…", result)

    # --- client_id is mildly sensitive but NOT in SECRET_KEYS exclusion ---
    def test_client_id_is_masked(self):
        result = self._mask("client_id", "some_long_client_id_value_here12")
        self.assertIn("…", result)

    # --- Non-sensitive keys ---
    def test_non_sensitive_key_returns_value_unchanged(self):
        result = self._mask("display_name", "Brian")
        self.assertEqual(result, "Brian")

    def test_email_key_not_masked(self):
        result = self._mask("email", "user@example.com")
        self.assertEqual(result, "user@example.com")

    # --- Secret value pattern in non-secret key ---
    def test_value_containing_github_token_masked_regardless_of_key(self):
        result = self._mask("random_field", "ghp_ABCDEFGHIJ1234567890XY")
        self.assertIn("…", result)

    # --- Empty / None-like ---
    def test_empty_key_non_sensitive_value_returned(self):
        result = self._mask("", "plain text")
        self.assertEqual(result, "plain text")

    def test_empty_value_non_sensitive_key(self):
        from mail.utils.shield import mask_value
        # mask_value converts None-ish by using `val or ""`
        result = mask_value("email", "")
        self.assertEqual(result, "")


class TestShieldDict(unittest.TestCase):
    """Tests for shield_dict()."""

    def _shield(self, data):
        from mail.utils.shield import shield_dict
        return shield_dict(data)

    def test_empty_dict_returns_empty(self):
        result = self._shield({})
        self.assertEqual(result, {})

    def test_none_returns_empty(self):
        result = self._shield(None)
        self.assertEqual(result, {})

    def test_sensitive_string_value_is_masked(self):
        result = self._shield({"token": "abcdefghijklmnopqrstuvwxyz"})
        self.assertIn("token", result)
        self.assertNotEqual(result["token"], "abcdefghijklmnopqrstuvwxyz")
        self.assertIn("…", result["token"])

    def test_non_sensitive_string_value_unchanged(self):
        result = self._shield({"display_name": "Alice"})
        self.assertEqual(result["display_name"], "Alice")

    def test_non_string_value_passed_through(self):
        result = self._shield({"count": 42, "enabled": True})
        self.assertEqual(result["count"], 42)
        self.assertTrue(result["enabled"])

    def test_none_value_passed_through(self):
        result = self._shield({"token": None})
        self.assertIsNone(result["token"])

    def test_mixed_dict(self):
        data = {
            "display_name": "Alice",
            "token": "abcdefghijklmnopqrstuvwxyz",
            "count": 10,
        }
        result = self._shield(data)
        self.assertEqual(result["display_name"], "Alice")
        self.assertEqual(result["count"], 10)
        self.assertIn("…", result["token"])

    def test_returns_new_dict_not_same_object(self):
        data = {"display_name": "Bob"}
        result = self._shield(data)
        self.assertIsNot(result, data)

    def test_partial_match_key_with_token_suffix(self):
        # "refresh_token" contains "token" -> should be masked
        result = self._shield({"refresh_token": "abcdefghijklmnopqrstuvwxyz"})
        self.assertIn("…", result["refresh_token"])

    def test_key_with_key_substring(self):
        # "api_key" contains "key" and "api_key" -> masked
        result = self._shield({"api_key": "abcdefghijklmnopqrstuvwxyz"})
        self.assertIn("…", result["api_key"])


if __name__ == "__main__":
    unittest.main()
