import unittest

from mail.utils.filters import build_gmail_query, action_to_label_changes
from tests.mail_tests.fixtures import FakeGmailClient, make_user_label, make_system_label


class TestBuildGmailQuery(unittest.TestCase):
    def test_negated_and_attach(self):
        q = build_gmail_query(
            {"query": "x", "negatedQuery": "y", "hasAttachment": True},
            days=None,
            only_inbox=False,
        )
        self.assertIn("x", q)
        self.assertIn("-(y)", q)
        self.assertIn("has:attachment", q)


class TestActionToLabelChanges(unittest.TestCase):
    def test_resolution(self):
        client = FakeGmailClient(labels=[
            make_user_label("Lists/Newsletters", "L1"),
            make_system_label("INBOX"),
        ])
        add, rem = action_to_label_changes(
            client,
            {"add": ["Lists/Newsletters"], "remove": ["INBOX"]},
        )
        self.assertEqual(add, ["L1"])
        self.assertEqual(rem, ["INBOX"])


if __name__ == "__main__":
    unittest.main()
