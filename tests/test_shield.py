import unittest

from mail_assistant.utils.shield import mask_value


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


if __name__ == "__main__":
    unittest.main()

