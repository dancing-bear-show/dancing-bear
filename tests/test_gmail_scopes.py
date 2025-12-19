import unittest


class GmailScopesTests(unittest.TestCase):
    def test_gmail_scopes_include_send_and_compose(self):
        from mail_assistant.gmail_api import SCOPES

        required = {
            "https://www.googleapis.com/auth/gmail.settings.basic",
            "https://www.googleapis.com/auth/gmail.labels",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/gmail.send",
        }
        self.assertTrue(required.issubset(set(SCOPES)), msg=f"Missing scopes: {required - set(SCOPES)}")


if __name__ == "__main__":
    unittest.main()

