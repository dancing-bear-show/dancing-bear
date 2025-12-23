import unittest
from unittest.mock import patch

from tests.fixtures import (
    FakeGmailClient,
    capture_stdout,
    has_pyyaml,
    make_args,
    write_yaml,
)


def _make_filters_client():
    """Create a FakeGmailClient configured for filters tests."""
    return FakeGmailClient(
        labels=[
            {"id": "LBL_X", "name": "X"},
            {"id": "LBL_REPORTS", "name": "Reports"},
            {"id": "INBOX", "name": "INBOX"},
            {"id": "UNREAD", "name": "UNREAD"},
        ],
        filters=[
            {
                "id": "F_EXIST_1",
                "criteria": {"from": None, "to": None, "subject": "Weekly report", "query": None, "negatedQuery": None},
                "action": {"addLabelIds": ["LBL_REPORTS"]},
            }
        ],
        message_ids_by_query={
            "from:(a@b.com)": ["m" + str(i) for i in range(5)],
            'subject:"Weekly report"': ["n" + str(i) for i in range(3)],
        },
    )


@unittest.skipUnless(has_pyyaml(), "requires PyYAML")
class CLIFilterPlanImpactTests(unittest.TestCase):
    def test_filters_plan_shows_create_for_missing(self):
        # Desired has two rules; one already exists (Reports), one new (X)
        desired = {
            "filters": [
                {"match": {"from": "a@b.com"}, "action": {"add": ["X"], "remove": ["INBOX"]}},
                {"match": {"subject": "Weekly report"}, "action": {"add": ["Reports"]}},
            ]
        }
        cfg_path = write_yaml(desired, filename="filters.yaml")
        client = _make_filters_client()
        args = make_args(config=cfg_path, delete_missing=False)

        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            from mail_assistant.filters.commands import run_filters_plan

            with capture_stdout() as buf:
                rc = run_filters_plan(args)
            out = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("Plan: create=1 delete=0", out)
        self.assertIn("Would create:", out)
        self.assertIn("from:a@b.com", out)

    def test_filters_impact_counts_use_provider(self):
        desired = {
            "filters": [
                {"match": {"from": "a@b.com"}, "action": {"add": ["X"]}},
                {"match": {"subject": "Weekly report"}, "action": {"add": ["Reports"]}},
            ]
        }
        cfg_path = write_yaml(desired, filename="filters.yaml")
        client = _make_filters_client()
        args = make_args(config=cfg_path, days=7, only_inbox=True, pages=2)

        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            from mail_assistant.filters.commands import run_filters_impact

            with capture_stdout() as buf:
                rc = run_filters_impact(args)
            out = buf.getvalue().splitlines()

        self.assertEqual(rc, 0)
        # Expect two lines of counts and a total
        counts = [ln for ln in out if ln.strip() and not ln.startswith("Total ")]
        self.assertTrue(any("  5" in ln for ln in counts), msg=f"output: {out}")
        self.assertTrue(any("  3" in ln for ln in counts), msg=f"output: {out}")
        self.assertTrue(any("Total impacted: 8" in ln for ln in out), msg=f"output: {out}")


if __name__ == "__main__":
    unittest.main()
