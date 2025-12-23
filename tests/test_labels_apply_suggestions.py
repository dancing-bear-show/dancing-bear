import unittest

from tests.fixtures import FakeGmailClient, capture_stdout, make_args, write_yaml


def _make_fake_client_class():
    """Create a FakeGmailClient class that accepts constructor args."""
    class ConstructableFakeGmailClient(FakeGmailClient):
        def __init__(self, credentials_path: str, token_path: str, cache_dir=None):
            super().__init__()
            self.credentials_path = credentials_path
            self.token_path = token_path
            self.cache_dir = cache_dir
    return ConstructableFakeGmailClient


class LabelsApplySuggestionsTests(unittest.TestCase):
    def test_dry_run_apply_suggestions(self):
        import mail_assistant.__main__ as cli

        # Patch lazy loader to return our fake client class
        original_lazy = cli._lazy_gmail_client
        cli._lazy_gmail_client = _make_fake_client_class
        try:
            cfg = {
                "suggestions": [
                    {"domain": "news@example.com", "label": "Lists/Newsletters"},
                    {"domain": "hr@company.com", "label": "Work/HR"},
                ]
            }
            cfg_path = write_yaml(cfg, filename="suggestions.yaml")
            args = make_args(
                credentials="cred.json",
                token="tok.json",
                config=cfg_path,
                dry_run=True,
                sweep_days=None,
                pages=1,
                batch_size=2,
            )

            with capture_stdout() as buf:
                rc = cli._cmd_labels_apply_suggestions(args)
            out = buf.getvalue()

            self.assertEqual(rc, 0)
            self.assertIn("Would create: from:(news@example.com)", out)
            self.assertIn("Would create: from:(hr@company.com)", out)
        finally:
            cli._lazy_gmail_client = original_lazy


if __name__ == "__main__":
    unittest.main()
