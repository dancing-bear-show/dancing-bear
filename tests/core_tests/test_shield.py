import unittest

from mail.utils.shield import mask_value, shield_dict, _mask_str


class ShieldTests(unittest.TestCase):
    def test_masks_github_token(self):
        raw = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        masked = mask_value("token", raw)
        self.assertNotEqual(masked, raw)
        self.assertIn("len=", masked)

    def test_masks_slack_token_even_with_generic_key(self):
        raw = "xoxp-1234567890-ABCDEFGHIJKL-MNOPQRSTUVWXYZ"
        masked = mask_value("value", raw)
        self.assertNotEqual(masked, raw)

    def test_masks_client_id_partially(self):
        raw = "5be42a80-4050-47e2-8bd7-7e0529d6cff3"
        masked = mask_value("client_id", raw)
        self.assertNotEqual(masked, raw)
        self.assertIn("…", masked)

    def test_paths_show_existence(self):
        masked = mask_value("credentials", "/etc/hosts")
        self.assertIn("exists:", masked)

    def test_mask_short_string(self):
        # Test strings shorter than head+tail
        result = _mask_str("abc")
        self.assertEqual(result, "***")
        result = _mask_str("12345678")  # exactly 8 chars (4+4)
        self.assertEqual(result, "***")

    def test_mask_long_string(self):
        # Test strings longer than head+tail
        result = _mask_str("abcdefghijklmnop")
        self.assertIn("abcd", result)
        self.assertIn("mnop", result)
        self.assertIn("len=16", result)

    def test_normal_value_not_masked(self):
        # Non-secret keys with normal values should pass through
        result = mask_value("username", "john_doe")
        self.assertEqual(result, "john_doe")

    def test_mask_value_with_secret_keys(self):
        # Test various secret key names
        for key in ["token", "secret", "password", "api_key", "access_token"]:
            result = mask_value(key, "sensitive_value_12345")
            self.assertNotEqual(result, "sensitive_value_12345")
            self.assertIn("…", result)

    def test_mask_value_client_id_suffix(self):
        # Test keys ending with _client_id
        result = mask_value("oauth_client_id", "client-12345")
        self.assertIn("…", result)

    def test_path_with_backslash(self):
        # Windows-style path
        result = mask_value("file", "C:\\Users\\test\\file.txt")
        self.assertIn("exists:", result)

    def test_path_nonexistent(self):
        # Non-existent path
        result = mask_value("config", "/nonexistent/path/to/file")
        self.assertIn("exists: no", result)

    def test_shield_dict_with_secrets(self):
        data = {
            "username": "alice",
            "password": "secret123",
            "api_key": "sk-test-abcdefghijklmnop",
            "count": 42,
        }
        result = shield_dict(data)
        # username should pass through
        self.assertEqual(result["username"], "alice")
        # password and api_key should be masked
        self.assertNotEqual(result["password"], "secret123")
        self.assertNotEqual(result["api_key"], "sk-test-abcdefghijklmnop")
        # non-string values should pass through
        self.assertEqual(result["count"], 42)

    def test_shield_dict_empty(self):
        result = shield_dict({})
        self.assertEqual(result, {})

    def test_shield_dict_none(self):
        result = shield_dict(None)
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()

