import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch


def _has_pyyaml() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("yaml") is not None
    except Exception:
        return False


class FakeLabelClient:
    def __init__(self):
        # Existing labels include a system label, a user label to update, and an extra to delete
        self._labels = [
            {"id": "SYS_INBOX", "name": "INBOX", "type": "system"},
            {
                "id": "LBL_REPORTS",
                "name": "Reports",
                "type": "user",
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
            {"id": "LBL_OLD", "name": "OldLabel", "type": "user"},
        ]

    # Provider-like surface used by CLI
    def authenticate(self):
        return None

    def list_labels(self, *_, **__):
        return list(self._labels)


@unittest.skipUnless(_has_pyyaml(), "requires PyYAML")
class CLILabelPlanTests(unittest.TestCase):
    def _write_yaml(self, data) -> str:
        import yaml

        td = tempfile.mkdtemp()
        p = os.path.join(td, "labels.yaml")
        with open(p, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False)
        return p

    def test_labels_plan_create_update_delete(self):
        desired = {
            "labels": [
                {"name": "Reports", "labelListVisibility": "labelHide"},  # update
                {"name": "NewLabel"},  # create
            ]
        }
        cfg_path = self._write_yaml(desired)
        fake = FakeLabelClient()
        args = SimpleNamespace(config=cfg_path, delete_missing=True, credentials=None, token=None, cache=None)
        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", new=lambda _args: fake):
            import mail_assistant.__main__ as m

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = m._cmd_labels_plan(args)
            out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Plan: create=1 update=1 delete=1", out)
        self.assertIn("Would create:", out)
        self.assertIn("Would update:", out)
        self.assertIn("Would delete:", out)


if __name__ == "__main__":
    unittest.main()

