import unittest

from tests.mail.fixtures import FakeGmailClient


class TestUtilsFiltersMore(unittest.TestCase):
    def test_build_criteria_from_match(self):
        from mail.utils.filters import build_criteria_from_match

        crit = build_criteria_from_match({
            "from": "a@b", "to": "c@d", "subject": "Hello",
            "query": "newsletter", "negatedQuery": "-spam",
            "hasAttachment": True, "size": 1024, "sizeComparison": "larger"
        })
        self.assertEqual(crit["from"], "a@b")
        self.assertEqual(crit["to"], "c@d")
        self.assertEqual(crit["subject"], "Hello")
        self.assertEqual(crit["query"], "newsletter")
        self.assertEqual(crit["negatedQuery"], "-spam")
        self.assertTrue(crit["hasAttachment"])
        self.assertEqual(crit["size"], 1024)
        self.assertEqual(crit["sizeComparison"], "larger")

    def test_build_gmail_query(self):
        from mail.utils.filters import build_gmail_query

        q = build_gmail_query({
            "from": "a@b", "to": "c@d", "subject": "hi there",
            "query": "list:news", "negatedQuery": "promo",
            "hasAttachment": True
        }, days=7, only_inbox=True)
        self.assertIn("from:(a@b)", q)
        self.assertIn("to:(c@d)", q)
        self.assertIn('subject:"hi there"', q)
        self.assertIn("list:news", q)
        self.assertIn("-(promo)", q)
        self.assertIn("has:attachment", q)
        self.assertIn("newer_than:7d", q)
        self.assertIn("in:inbox", q)

    def test_action_to_label_changes(self):
        from mail.utils.filters import action_to_label_changes

        client = FakeGmailClient(labels=[
            {"id": "L1", "name": "Work"},
            {"id": "INBOX", "name": "INBOX"},
        ])
        add_ids, rem_ids = action_to_label_changes(
            client,
            {"add": ["Work", "CATEGORY_PROMOTIONS"], "remove": ["INBOX", "Archive"]}
        )
        self.assertIn("L1", add_ids)
        self.assertIn("CATEGORY_PROMOTIONS", add_ids)
        self.assertIn("INBOX", rem_ids)
        # "Archive" gets ensured and mapped
        self.assertTrue(any("Archive" in x or "LBL_" in x for x in rem_ids))


if __name__ == "__main__":
    unittest.main()
