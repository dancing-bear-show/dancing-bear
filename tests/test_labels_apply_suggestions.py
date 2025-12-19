import io
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace


class FakeGmailClient:
    def __init__(self, credentials_path: str, token_path: str, cache_dir=None):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.cache_dir = cache_dir
        self.auth = False
        self.created = []

    def authenticate(self):
        self.auth = True

    def get_label_id_map(self):
        return {}

    def ensure_label(self, name: str, **kwargs):
        return f"ID_{name}"

    def create_filter(self, criteria, action):
        self.created.append((criteria, action))


class LabelsApplySuggestionsTests(unittest.TestCase):
    def test_dry_run_apply_suggestions(self):
        import mail_assistant.__main__ as cli

        # Patch lazy loader to return our fake client class
        original_lazy = cli._lazy_gmail_client
        cli._lazy_gmail_client = lambda: FakeGmailClient
        try:
            with tempfile.TemporaryDirectory() as td:
                cfg = {
                    "suggestions": [
                        {"domain": "news@example.com", "label": "Lists/Newsletters"},
                        {"domain": "hr@company.com", "label": "Work/HR"},
                    ]
                }
                import yaml
                p = tempfile.NamedTemporaryFile(dir=td, suffix=".yaml", delete=False)
                p.close()
                with open(p.name, "w", encoding="utf-8") as fh:
                    yaml.safe_dump(cfg, fh, sort_keys=False)

                args = SimpleNamespace(
                    credentials="cred.json",
                    token="tok.json",
                    cache=None,
                    config=p.name,
                    dry_run=True,
                    sweep_days=None,
                    pages=1,
                    batch_size=2,
                )
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = cli._cmd_labels_apply_suggestions(args)
                out = buf.getvalue()
                self.assertEqual(rc, 0)
                self.assertIn("Would create: from:(news@example.com)", out)
                self.assertIn("Would create: from:(hr@company.com)", out)
        finally:
            cli._lazy_gmail_client = original_lazy

