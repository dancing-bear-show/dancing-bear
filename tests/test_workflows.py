import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from tests.fixtures import has_pyyaml


class FakeClient:
    def __init__(self):
        # labels and existing filters mirror test_cli_filters FakeClient
        self._labels = [
            {"id": "LBL_X", "name": "X"},
            {"id": "LBL_REPORTS", "name": "Reports"},
            {"id": "INBOX", "name": "INBOX"},
        ]
        self._name_to_id = {d["name"]: d["id"] for d in self._labels}
        self._filters = [
            {
                "id": "F_EXIST_1",
                "criteria": {"from": None, "to": None, "subject": "Weekly report", "query": None, "negatedQuery": None},
                "action": {"addLabelIds": [self._name_to_id["Reports"]]},
            }
        ]

    def authenticate(self):
        return None

    def list_labels(self, *_, **__):
        return list(self._labels)

    def get_label_id_map(self):
        return dict(self._name_to_id)

    def list_filters(self, *_, **__):
        return list(self._filters)


@unittest.skipUnless(has_pyyaml(), "requires PyYAML")
class WorkflowTests(unittest.TestCase):
    def _write_unified(self, data) -> str:
        import yaml

        td = tempfile.mkdtemp()
        p = os.path.join(td, "filters_unified.yaml")
        with open(p, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False)
        return p

    def test_workflow_gmail_from_unified_plan_only(self):
        unified = {
            "filters": [
                {"match": {"from": "a@b.com"}, "action": {"add": ["X"]}},
            ]
        }
        cfg_path = self._write_unified(unified)
        out_dir = tempfile.mkdtemp()
        fake = FakeClient()
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
