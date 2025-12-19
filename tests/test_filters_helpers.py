import types

import mail_assistant.__main__ as cli


class StubClient:
    def __init__(self, name_to_id):
        self._m = name_to_id

    def get_label_id_map(self):
        return self._m


def test_build_gmail_query_negated_and_attach():
    q = cli._build_gmail_query({"query": "x", "negatedQuery": "y", "hasAttachment": True}, days=None, only_inbox=False)
    assert "x" in q and "-(y)" in q and "has:attachment" in q


def test_action_to_label_changes_resolution():
    client = StubClient({"Lists/Newsletters": "L1", "INBOX": "INBOX"})
    add, rem = cli._action_to_label_changes(client, {"add": ["Lists/Newsletters"], "remove": ["INBOX"]})
    assert add == ["L1"] and rem == ["INBOX"]

