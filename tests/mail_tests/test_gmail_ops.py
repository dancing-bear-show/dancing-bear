"""Tests for mail/utils/gmail_ops.py."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock


class TestMessageQueryParams(unittest.TestCase):
    """Tests for MessageQueryParams dataclass."""

    def test_required_fields(self):
        from mail.utils.gmail_ops import MessageQueryParams
        params = MessageQueryParams(query="is:unread", pages=2)
        self.assertEqual(params.query, "is:unread")
        self.assertEqual(params.pages, 2)

    def test_optional_fields_default_to_none(self):
        from mail.utils.gmail_ops import MessageQueryParams
        params = MessageQueryParams(query="label:inbox", pages=1)
        self.assertIsNone(params.max_msgs)
        self.assertIsNone(params.page_size)

    def test_optional_fields_set(self):
        from mail.utils.gmail_ops import MessageQueryParams
        params = MessageQueryParams(query="from:me", pages=3, max_msgs=50, page_size=100)
        self.assertEqual(params.max_msgs, 50)
        self.assertEqual(params.page_size, 100)


class TestClipIds(unittest.TestCase):
    """Tests for _clip_ids()."""

    def _clip(self, ids, max_msgs):
        from mail.utils.gmail_ops import _clip_ids
        return _clip_ids(ids, max_msgs)

    def test_within_limit_returns_same_list(self):
        ids = ["a", "b", "c"]
        result = self._clip(ids, 5)
        self.assertEqual(result, ["a", "b", "c"])

    def test_none_max_msgs_returns_all(self):
        ids = ["a", "b", "c", "d", "e"]
        result = self._clip(ids, None)
        self.assertEqual(result, ["a", "b", "c", "d", "e"])

    def test_exceeds_limit_clips_to_max(self):
        ids = ["a", "b", "c", "d", "e"]
        result = self._clip(ids, 3)
        self.assertEqual(result, ["a", "b", "c"])

    def test_exact_limit_returns_all(self):
        ids = ["x", "y", "z"]
        result = self._clip(ids, 3)
        self.assertEqual(result, ["x", "y", "z"])

    def test_empty_list_returns_empty(self):
        result = self._clip([], 10)
        self.assertEqual(result, [])

    def test_clip_preserves_order(self):
        ids = ["first", "second", "third", "fourth"]
        result = self._clip(ids, 2)
        self.assertEqual(result, ["first", "second"])

    def test_zero_max_msgs_returns_empty(self):
        ids = ["a", "b", "c"]
        result = self._clip(ids, 0)
        self.assertEqual(result, [])


class TestListMessageIds(unittest.TestCase):
    """Tests for list_message_ids()."""

    def _make_client(self, ids):
        client = MagicMock()
        client.list_message_ids.return_value = ids
        return client

    def test_happy_path_returns_ids(self):
        from mail.utils.gmail_ops import MessageQueryParams, list_message_ids
        client = self._make_client(["m1", "m2", "m3"])
        params = MessageQueryParams(query="is:unread", pages=1)
        result = list_message_ids(client, params)
        self.assertEqual(result, ["m1", "m2", "m3"])

    def test_calls_client_with_correct_args(self):
        from mail.utils.gmail_ops import MessageQueryParams, list_message_ids
        client = self._make_client([])
        params = MessageQueryParams(query="label:work", pages=2, page_size=100)
        list_message_ids(client, params)
        client.list_message_ids.assert_called_once_with(
            query="label:work",
            max_pages=2,
            page_size=100,
        )

    def test_default_page_size_500_when_none(self):
        from mail.utils.gmail_ops import MessageQueryParams, list_message_ids
        client = self._make_client([])
        params = MessageQueryParams(query="from:me", pages=1)
        list_message_ids(client, params)
        client.list_message_ids.assert_called_once_with(
            query="from:me",
            max_pages=1,
            page_size=500,
        )

    def test_clips_to_max_msgs(self):
        from mail.utils.gmail_ops import MessageQueryParams, list_message_ids
        client = self._make_client(["a", "b", "c", "d", "e"])
        params = MessageQueryParams(query="is:read", pages=1, max_msgs=3)
        result = list_message_ids(client, params)
        self.assertEqual(result, ["a", "b", "c"])

    def test_no_clip_when_max_msgs_none(self):
        from mail.utils.gmail_ops import MessageQueryParams, list_message_ids
        ids = ["a", "b", "c", "d", "e"]
        client = self._make_client(ids)
        params = MessageQueryParams(query="label:all", pages=1)
        result = list_message_ids(client, params)
        self.assertEqual(result, ids)

    def test_empty_result_from_client(self):
        from mail.utils.gmail_ops import MessageQueryParams, list_message_ids
        client = self._make_client([])
        params = MessageQueryParams(query="nothing", pages=1)
        result = list_message_ids(client, params)
        self.assertEqual(result, [])


class TestFetchMessagesWithMetadata(unittest.TestCase):
    """Tests for fetch_messages_with_metadata()."""

    def _make_client(self, ids, metadata):
        client = MagicMock()
        client.list_message_ids.return_value = ids
        client.get_messages_metadata.return_value = metadata
        return client

    def test_returns_ids_and_metadata(self):
        from mail.utils.gmail_ops import MessageQueryParams, fetch_messages_with_metadata
        meta = [{"id": "m1", "snippet": "hello"}, {"id": "m2", "snippet": "world"}]
        client = self._make_client(["m1", "m2"], meta)
        params = MessageQueryParams(query="is:unread", pages=1)
        ids, messages = fetch_messages_with_metadata(client, params)
        self.assertEqual(ids, ["m1", "m2"])
        self.assertEqual(messages, meta)

    def test_calls_get_messages_metadata_with_ids(self):
        from mail.utils.gmail_ops import MessageQueryParams, fetch_messages_with_metadata
        client = self._make_client(["x1", "x2"], [])
        params = MessageQueryParams(query="from:test", pages=1)
        fetch_messages_with_metadata(client, params)
        client.get_messages_metadata.assert_called_once_with(["x1", "x2"], use_cache=True)

    def test_clips_before_fetching_metadata(self):
        from mail.utils.gmail_ops import MessageQueryParams, fetch_messages_with_metadata
        all_ids = ["a", "b", "c", "d", "e"]
        clipped_meta = [{"id": "a"}, {"id": "b"}]
        client = self._make_client(all_ids, clipped_meta)
        params = MessageQueryParams(query="label:inbox", pages=1, max_msgs=2)
        ids, _ = fetch_messages_with_metadata(client, params)
        # Only the first 2 IDs should be passed to get_messages_metadata
        client.get_messages_metadata.assert_called_once_with(["a", "b"], use_cache=True)
        self.assertEqual(ids, ["a", "b"])

    def test_empty_results(self):
        from mail.utils.gmail_ops import MessageQueryParams, fetch_messages_with_metadata
        client = self._make_client([], [])
        params = MessageQueryParams(query="nothing", pages=1)
        ids, messages = fetch_messages_with_metadata(client, params)
        self.assertEqual(ids, [])
        self.assertEqual(messages, [])


if __name__ == "__main__":
    unittest.main()
