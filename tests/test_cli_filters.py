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


class FakeClient:
    def __init__(self):
        # Define a stable label set and ID mapping
        self._labels = [
            {"id": "LBL_X", "name": "X"},
            {"id": "LBL_REPORTS", "name": "Reports"},
            {"id": "INBOX", "name": "INBOX"},
            {"id": "UNREAD", "name": "UNREAD"},
        ]
        self._name_to_id = {d["name"]: d["id"] for d in self._labels}
        # Existing filter set contains one rule equivalent to desired "Reports" rule
        self._filters = [
            {
                "id": "F_EXIST_1",
                "criteria": {"from": None, "to": None, "subject": "Weekly report", "query": None, "negatedQuery": None},
                "action": {"addLabelIds": [self._name_to_id["Reports"]]},
            }
        ]

    # Provider-like surface used by CLI
    def authenticate(self):
        return None

    def list_labels(self):
        return list(self._labels)

    def get_label_id_map(self):
        return dict(self._name_to_id)

    def list_filters(self, use_cache: bool = False, ttl: int = 300):
        return list(self._filters)

    def list_message_ids(self, query=None, label_ids=None, max_pages: int = 1, page_size: int = 500):
        q = query or ""
        # Deterministic fake counts based on query content
        if "from:(a@b.com)" in q:
            return ["m" + str(i) for i in range(5)]  # 5 matches
        if "subject:\"Weekly report\"" in q:
            return ["n" + str(i) for i in range(3)]  # 3 matches
        return []


@unittest.skipUnless(_has_pyyaml(), "requires PyYAML")
class CLIFilterPlanImpactTests(unittest.TestCase):
    def _write_yaml(self, data) -> str:
        import yaml

        td = tempfile.mkdtemp()
        p = os.path.join(td, "filters.yaml")
        with open(p, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False)
        return p

    def test_filters_plan_shows_create_for_missing(self):
        # Desired has two rules; one already exists (Reports), one new (X)
        desired = {
            "filters": [
                {"match": {"from": "a@b.com"}, "action": {"add": ["X"], "remove": ["INBOX"]}},
                {"match": {"subject": "Weekly report"}, "action": {"add": ["Reports"]}},
            ]
        }
        cfg_path = self._write_yaml(desired)
        fake = FakeClient()
        args = SimpleNamespace(config=cfg_path, delete_missing=False, credentials=None, token=None, cache=None)
        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", new=lambda _args: fake):
            import mail_assistant.__main__ as m

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = m._cmd_filters_plan(args)
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
        cfg_path = self._write_yaml(desired)
        fake = FakeClient()
        # Provide days and only_inbox to exercise query builder
        args = SimpleNamespace(config=cfg_path, days=7, only_inbox=True, pages=2, credentials=None, token=None, cache=None)
        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", new=lambda _args: fake):
            import mail_assistant.__main__ as m
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = m._cmd_filters_impact(args)
            out = buf.getvalue().splitlines()
        self.assertEqual(rc, 0)
        # Expect two lines of counts and a total
        counts = [ln for ln in out if ln.strip() and not ln.startswith("Total ")]
        self.assertTrue(any("  5" in ln for ln in counts), msg=f"output: {out}")
        self.assertTrue(any("  3" in ln for ln in counts), msg=f"output: {out}")
        self.assertTrue(any("Total impacted: 8" in ln for ln in out), msg=f"output: {out}")


if __name__ == "__main__":
    unittest.main()

