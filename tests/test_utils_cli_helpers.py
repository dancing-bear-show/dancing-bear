import unittest
from types import SimpleNamespace


class TestCLIHelpers(unittest.TestCase):
    def test_preview_criteria(self):
        from mail.utils.cli_helpers import preview_criteria

        self.assertEqual(preview_criteria({}), "<complex>")
        self.assertEqual(preview_criteria({"from": "a@b"}), "from:a@b")
        self.assertEqual(
            preview_criteria({"from": "a@b", "to": "c@d", "subject": "Hi"}),
            "from:a@b to:c@d subject:Hi",
        )
        # Query should be elided
        self.assertIn("query=…", preview_criteria({"query": "some long body"}))

    def test_gmail_provider_from_args(self):
        from mail.utils.cli_helpers import gmail_provider_from_args
        from mail.providers.gmail import GmailProvider

        args = SimpleNamespace(credentials="cred.json", token="tok.json", cache=".cache/x")
        prov = gmail_provider_from_args(args)
        self.assertIsInstance(prov, GmailProvider)

