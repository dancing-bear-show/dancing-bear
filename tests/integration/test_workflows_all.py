import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from tests.fixtures import has_pyyaml, write_yaml
from tests.mail_tests.fixtures import FakeGmailClient


@unittest.skipUnless(has_pyyaml(), "requires PyYAML")
class WorkflowAllProvidersTests(unittest.TestCase):

    def test_workflow_from_unified_runs_gmail_and_skips_outlook_when_unset(self):
        unified = {"filters": [{"match": {"from": "a@b.com"}, "action": {"add": ["X"]}}]}
        cfg_path = write_yaml(unified, filename="filters_unified.yaml")
        out_dir = tempfile.mkdtemp()

        fake = FakeGmailClient(
            labels=[
                {"id": "LBL_X", "name": "X"},
                {"id": "INBOX", "name": "INBOX"},
            ],
            filters=[],
        )

        # Patch Gmail provider construction inside plan/sync path
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", new=lambda _args: fake):
            from mail.config_cli.commands import run_workflows_from_unified
            from mail.outlook import helpers as outlook_helpers
            # Force Gmail detection by pointing credentials to a temp file that exists
            from mail import config_resolver as cr
            td = tempfile.mkdtemp()
            cred = os.path.join(td, "cred.json")
            with open(cred, "w", encoding="utf-8") as fh:
                fh.write("{}")
            tok = os.path.join(td, "tok.json")
            with open(tok, "w", encoding="utf-8") as fh:
                fh.write("{}")
            with patch.object(cr, "resolve_paths_profile", new=lambda **kwargs: (cred, tok)), \
                 patch.object(outlook_helpers, "resolve_outlook_args", new=lambda _args: (None, None, None, None)):
                buf = io.StringIO()
                args = SimpleNamespace(config=cfg_path, out_dir=out_dir, delete_missing=False, apply=False, providers=None, profile=None, accounts_config=None, account=None)
                with redirect_stdout(buf):
                    rc = run_workflows_from_unified(args)
                out = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("[Gmail] Plan:", out)
        # Likely skip Outlook due to no client_id configured
        self.assertIn("[Outlook] Skipping", out)


if __name__ == "__main__":
    unittest.main()
