import unittest
from unittest.mock import patch

from tests.fixtures import (
    FakeGmailClient,
    capture_stdout,
    has_pyyaml,
    make_args,
    write_yaml,
)


@unittest.skipUnless(has_pyyaml(), "requires PyYAML")
class CLILabelPlanTests(unittest.TestCase):
    def test_labels_plan_create_update_delete(self):
        # Existing labels include a system label, a user label to update, and an extra to delete
        client = FakeGmailClient(labels=[
            {"id": "SYS_INBOX", "name": "INBOX", "type": "system"},
            {"id": "LBL_REPORTS", "name": "Reports", "type": "user",
             "labelListVisibility": "labelShow", "messageListVisibility": "show"},
            {"id": "LBL_OLD", "name": "OldLabel", "type": "user"},
        ])

        desired = {
            "labels": [
                {"name": "Reports", "labelListVisibility": "labelHide"},  # update
                {"name": "NewLabel"},  # create
            ]
        }
        cfg_path = write_yaml(desired, filename="labels.yaml")
        args = make_args(config=cfg_path, delete_missing=True)

        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            from mail_assistant.labels.commands import run_labels_plan

            with capture_stdout() as buf:
                rc = run_labels_plan(args)
            out = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("Plan: create=1 update=1 delete=1", out)
        self.assertIn("Would create:", out)
        self.assertIn("Would update:", out)
        self.assertIn("Would delete:", out)


if __name__ == "__main__":
    unittest.main()
