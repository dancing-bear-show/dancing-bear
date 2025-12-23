import unittest


class TestProviderCapabilities(unittest.TestCase):
    def test_gmail_capabilities(self):
        from mail.providers.gmail import GmailProvider

        p = GmailProvider(credentials_path="c.json", token_path="t.json")
        caps = p.capabilities()
        self.assertIn("labels", caps)
        self.assertIn("filters", caps)
        self.assertIn("sweep", caps)
        self.assertIn("forwarding", caps)
        self.assertIn("signatures", caps)

    def test_outlook_capabilities(self):
        from mail.providers.outlook import OutlookProvider

        p = OutlookProvider(client_id="dummy", tenant="consumers")
        caps = p.capabilities()
        self.assertIn("labels", caps)
        self.assertIn("filters", caps)
        self.assertNotIn("sweep", caps)
        self.assertNotIn("forwarding", caps)
        self.assertNotIn("signatures", caps)

