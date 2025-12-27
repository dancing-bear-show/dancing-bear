import mail.__main__ as cli

from tests.mail.fixtures import FakeGmailClient


def test_build_gmail_query_negated_and_attach():
    q = cli._build_gmail_query(
        {"query": "x", "negatedQuery": "y", "hasAttachment": True},
        days=None,
        only_inbox=False,
    )
    assert "x" in q and "-(y)" in q and "has:attachment" in q


def test_action_to_label_changes_resolution():
    client = FakeGmailClient(labels=[
        {"id": "L1", "name": "Lists/Newsletters"},
        {"id": "INBOX", "name": "INBOX"},
    ])
    add, rem = cli._action_to_label_changes(
        client,
        {"add": ["Lists/Newsletters"], "remove": ["INBOX"]},
    )
    assert add == ["L1"] and rem == ["INBOX"]
