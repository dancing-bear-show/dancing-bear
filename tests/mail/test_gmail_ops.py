"""Tests for mail/utils/gmail_ops.py Gmail helper functions."""

import unittest
from typing import List, Optional

from mail.utils.gmail_ops import (
    list_message_ids,
    fetch_messages_with_metadata,
    _clip_ids,
)


class FakeGmailClient:
    """Fake Gmail client for testing."""

    def __init__(self, message_ids: List[str], messages: List[dict]):
        self.message_ids = message_ids
        self.messages = messages
        self.list_calls = []
        self.metadata_calls = []

    def list_message_ids(
        self,
        query: Optional[str] = None,
        label_ids: Optional[List[str]] = None,
        max_pages: int = 1,
        page_size: int = 500,
    ) -> List[str]:
        self.list_calls.append(
            {"query": query, "label_ids": label_ids, "max_pages": max_pages, "page_size": page_size}
        )
        return self.message_ids

    def get_messages_metadata(self, ids: List[str], use_cache: bool = True) -> List[dict]:
        self.metadata_calls.append({"ids": ids, "use_cache": use_cache})
        return [m for m in self.messages if m["id"] in ids]


class TestClipIds(unittest.TestCase):
    """Tests for _clip_ids helper function."""

    def test_clips_to_max(self):
        ids = ["m1", "m2", "m3", "m4", "m5"]
        result = _clip_ids(ids, max_msgs=3)
        self.assertEqual(result, ["m1", "m2", "m3"])

    def test_returns_all_when_below_max(self):
        ids = ["m1", "m2"]
        result = _clip_ids(ids, max_msgs=5)
        self.assertEqual(result, ["m1", "m2"])

    def test_returns_all_when_max_is_none(self):
        ids = ["m1", "m2", "m3"]
        result = _clip_ids(ids, max_msgs=None)
        self.assertEqual(result, ["m1", "m2", "m3"])

    def test_handles_empty_list(self):
        result = _clip_ids([], max_msgs=10)
        self.assertEqual(result, [])


class TestListMessageIds(unittest.TestCase):
    """Tests for list_message_ids function."""

    def test_lists_message_ids(self):
        client = FakeGmailClient(
            message_ids=["m1", "m2", "m3"],
            messages=[],
        )
        result = list_message_ids(client, query="in:inbox", pages=1)
        self.assertEqual(result, ["m1", "m2", "m3"])
        self.assertEqual(len(client.list_calls), 1)
        self.assertEqual(client.list_calls[0]["query"], "in:inbox")
        self.assertEqual(client.list_calls[0]["max_pages"], 1)

    def test_respects_max_msgs(self):
        client = FakeGmailClient(
            message_ids=["m1", "m2", "m3", "m4", "m5"],
            messages=[],
        )
        result = list_message_ids(client, query="in:inbox", pages=1, max_msgs=3)
        self.assertEqual(result, ["m1", "m2", "m3"])

    def test_uses_custom_page_size(self):
        client = FakeGmailClient(
            message_ids=["m1"],
            messages=[],
        )
        list_message_ids(client, query="test", pages=2, page_size=100)
        self.assertEqual(client.list_calls[0]["page_size"], 100)
        self.assertEqual(client.list_calls[0]["max_pages"], 2)

    def test_uses_default_page_size(self):
        client = FakeGmailClient(
            message_ids=["m1"],
            messages=[],
        )
        list_message_ids(client, query="test", pages=1)
        self.assertEqual(client.list_calls[0]["page_size"], 500)


class TestFetchMessagesWithMetadata(unittest.TestCase):
    """Tests for fetch_messages_with_metadata function."""

    def test_fetches_ids_and_metadata(self):
        messages = [
            {"id": "m1", "subject": "Test 1"},
            {"id": "m2", "subject": "Test 2"},
        ]
        client = FakeGmailClient(
            message_ids=["m1", "m2"],
            messages=messages,
        )
        ids, msgs = fetch_messages_with_metadata(client, query="in:inbox", pages=1)

        self.assertEqual(ids, ["m1", "m2"])
        self.assertEqual(msgs, messages)
        self.assertEqual(len(client.list_calls), 1)
        self.assertEqual(len(client.metadata_calls), 1)
        self.assertTrue(client.metadata_calls[0]["use_cache"])

    def test_respects_max_msgs_parameter(self):
        messages = [
            {"id": "m1", "subject": "Test 1"},
            {"id": "m2", "subject": "Test 2"},
            {"id": "m3", "subject": "Test 3"},
        ]
        client = FakeGmailClient(
            message_ids=["m1", "m2", "m3"],
            messages=messages,
        )
        ids, msgs = fetch_messages_with_metadata(client, query="test", pages=1, max_msgs=2)

        self.assertEqual(ids, ["m1", "m2"])
        self.assertEqual(len(msgs), 2)

    def test_passes_page_size(self):
        client = FakeGmailClient(
            message_ids=["m1"],
            messages=[{"id": "m1"}],
        )
        fetch_messages_with_metadata(client, query="test", pages=3, page_size=250)

        self.assertEqual(client.list_calls[0]["page_size"], 250)

    def test_handles_empty_results(self):
        client = FakeGmailClient(
            message_ids=[],
            messages=[],
        )
        ids, msgs = fetch_messages_with_metadata(client, query="nonexistent", pages=1)

        self.assertEqual(ids, [])
        self.assertEqual(msgs, [])


if __name__ == "__main__":
    unittest.main()
