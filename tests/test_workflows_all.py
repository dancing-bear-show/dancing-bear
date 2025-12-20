import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from tests.fixtures import has_pyyaml


class FakeGmailClient:
    def __init__(self):
        self._labels = [
            {"id": "LBL_X", "name": "X"},
            {"id": "INBOX", "name": "INBOX"},
        ]
        self._name_to_id = {d["name"]: d["id"] for d in self._labels}
        self._filters = []

    def authenticate(self):
        return None

    def list_labels(self, *_, **__):
        return list(self._labels)

    def get_label_id_map(self):
        return dict(self._name_to_id)

    def list_filters(self, *_, **__):
        return list(self._filters)


@unittest.skipUnless(has_pyyaml(), "requires PyYAML")
class WorkflowAllProvidersTests(unittest.TestCase):
    def _write_unified(self, data) -> str:
        import yaml
        td = tempfile.mkdtemp()
        p = os.path.join(td, "filters_unified.yaml")
        with open(p, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False)
        return p

    def test_workflow_from_unified_runs_gmail_and_skips_outlook_when_unset(self):
        unified = {"filters": [{"match": {"from": "a@b.com"}, "action": {"add": ["X"]}}]}
        cfg_path = self._write_unified(unified)
        out_dir = tempfile.mkdtemp()

        fake = FakeGmailClient()

        # Patch Gmail provider construction inside plan/sync path
        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", new=lambda _args: fake):
            import mail_assistant.__main__ as m
            # Force Gmail detection by pointing credentials to a temp file that exists
            from mail_assistant import config_resolver as cr
            td = tempfile.mkdtemp()
            cred = os.path.join(td, "cred.json")
            with open(cred, "w", encoding="utf-8") as fh:
                fh.write("{}")
            tok = os.path.join(td, "tok.json")
            with open(tok, "w", encoding="utf-8") as fh:
                fh.write("{}")
            with patch.object(cr, "resolve_paths_profile", new=lambda **kwargs: (cred, tok)), \
                 patch.object(m, "_resolve_outlook_args", new=lambda _args: (None, None, None, None)):
                buf = io.StringIO()
                args = SimpleNamespace(config=cfg_path, out_dir=out_dir, delete_missing=False, apply=False, providers=None, profile=None, accounts_config=None, account=None)
                with redirect_stdout(buf):
                    rc = m._cmd_workflows_from_unified(args)
                out = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("[Gmail] Plan:", out)
        # Likely skip Outlook due to no client_id configured
        self.assertIn("[Outlook] Skipping", out)


if __name__ == "__main__":
    unittest.main()
