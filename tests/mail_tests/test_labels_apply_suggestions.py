import unittest
from unittest.mock import patch

from tests.mail_tests.fixtures import FakeGmailClient, capture_stdout, make_args, write_yaml


class ConstructableFakeGmailClient(FakeGmailClient):
    """FakeGmailClient that accepts constructor args."""
    def __init__(self, credentials_path: str, token_path: str, cache_dir=None):
        super().__init__()
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.cache_dir = cache_dir


class LabelsApplySuggestionsTests(unittest.TestCase):
    def test_dry_run_apply_suggestions(self):
        cfg = {
            "suggestions": [
                {"domain": "news@example.com", "label": "Lists/Newsletters"},
                {"domain": "hr@company.com", "label": "Work/HR"},
            ]
        }
        cfg_path = write_yaml(cfg, filename="suggestions.yaml")
        args = make_args(  # noqa: S106
            credentials="cred.json",
            token="tok.json",
            config=cfg_path,
            dry_run=True,
            sweep_days=None,
            pages=1,
            batch_size=2,
        )

        with patch("mail.gmail_api.GmailClient", ConstructableFakeGmailClient):
            from mail.labels.commands import run_labels_apply_suggestions

            with capture_stdout() as buf:
                rc = run_labels_apply_suggestions(args)
            out = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("Would create: from:(news@example.com)", out)
        self.assertIn("Would create: from:(hr@company.com)", out)


if __name__ == "__main__":
    unittest.main()
