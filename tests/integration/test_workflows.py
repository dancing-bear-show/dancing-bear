import io
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from tests.fixtures import has_pyyaml, write_yaml
from tests.mail_tests.fixtures import FakeGmailClient


@unittest.skipUnless(has_pyyaml(), "requires PyYAML")
class WorkflowTests(unittest.TestCase):

    def test_workflow_gmail_from_unified_plan_only(self):
        unified = {
            "filters": [
                {"match": {"from": "a@b.com"}, "action": {"add": ["X"]}},
            ]
        }
        cfg_path = write_yaml(unified, filename="filters_unified.yaml")
        out_dir = tempfile.mkdtemp()
        fake = FakeGmailClient(
            labels=[
                {"id": "LBL_X", "name": "X"},
                {"id": "LBL_REPORTS", "name": "Reports"},
                {"id": "INBOX", "name": "INBOX"},
            ],
            filters=[
                {
                    "id": "F_EXIST_1",
                    "criteria": {"from": None, "to": None, "subject": "Weekly report", "query": None, "negatedQuery": None},
                    "action": {"addLabelIds": ["LBL_REPORTS"]},
                }
            ],
        )
        args = SimpleNamespace(config=cfg_path, out_dir=out_dir, delete_missing=False, apply=False, credentials=None, token=None, cache=None)
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", new=lambda _args: fake):
            from mail.config_cli.commands import run_workflows_gmail_from_unified
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_workflows_gmail_from_unified(args)
            out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("[Plan] Gmail filters vs derived from unified:", out)
        self.assertIn("Plan: create=1", out)


if __name__ == "__main__":
    unittest.main()
