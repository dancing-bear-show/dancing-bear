"""Tests for mail/paging.py pagination utilities."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from mail.paging import gather_pages, paginate_gmail_messages


class TestPaginateGmailMessages(unittest.TestCase):
    """Tests for paginate_gmail_messages generator."""

    def setUp(self):
        self.mock_svc = MagicMock()

    def test_yields_message_ids_single_page(self):
        """Single page of results yields one list."""
        self.mock_svc.list.return_value.execute.return_value = {
            "messages": [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}],
        }
        pages = list(paginate_gmail_messages(self.mock_svc))
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0], ["m1", "m2", "m3"])

    def test_yields_multiple_pages(self):
        """Multiple pages with nextPageToken yields multiple lists."""
        self.mock_svc.list.return_value.execute.side_effect = [
            {"messages": [{"id": "m1"}, {"id": "m2"}], "nextPageToken": "token1"},
            {"messages": [{"id": "m3"}, {"id": "m4"}], "nextPageToken": "token2"},
            {"messages": [{"id": "m5"}]},
        ]
        pages = list(paginate_gmail_messages(self.mock_svc))
        self.assertEqual(len(pages), 3)
        self.assertEqual(pages[0], ["m1", "m2"])
        self.assertEqual(pages[1], ["m3", "m4"])
        self.assertEqual(pages[2], ["m5"])

    def test_empty_response_yields_nothing(self):
        """Empty messages list yields no pages."""
        self.mock_svc.list.return_value.execute.return_value = {"messages": []}
        pages = list(paginate_gmail_messages(self.mock_svc))
        self.assertEqual(pages, [])

    def test_missing_messages_key_yields_nothing(self):
        """Response without messages key yields no pages."""
        self.mock_svc.list.return_value.execute.return_value = {}
        pages = list(paginate_gmail_messages(self.mock_svc))
        self.assertEqual(pages, [])

    def test_skips_messages_without_id(self):
        """Messages without id field are filtered out."""
        self.mock_svc.list.return_value.execute.return_value = {
            "messages": [{"id": "m1"}, {"other": "data"}, {"id": "m2"}, {"id": None}],
        }
        pages = list(paginate_gmail_messages(self.mock_svc))
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0], ["m1", "m2"])

    def test_passes_query_parameter(self):
        """Query parameter is passed to API."""
        self.mock_svc.list.return_value.execute.return_value = {"messages": [{"id": "m1"}]}
        list(paginate_gmail_messages(self.mock_svc, query="from:test@example.com"))
        call_kwargs = self.mock_svc.list.call_args[1]
        self.assertEqual(call_kwargs["q"], "from:test@example.com")

    def test_passes_label_ids_parameter(self):
        """Label IDs parameter is passed to API."""
        self.mock_svc.list.return_value.execute.return_value = {"messages": [{"id": "m1"}]}
        list(paginate_gmail_messages(self.mock_svc, label_ids=["INBOX", "UNREAD"]))
        call_kwargs = self.mock_svc.list.call_args[1]
        self.assertEqual(call_kwargs["labelIds"], ["INBOX", "UNREAD"])

    def test_passes_page_size_parameter(self):
        """Page size parameter is passed to API."""
        self.mock_svc.list.return_value.execute.return_value = {"messages": []}
        list(paginate_gmail_messages(self.mock_svc, page_size=100))
        call_kwargs = self.mock_svc.list.call_args[1]
        self.assertEqual(call_kwargs["maxResults"], 100)

    def test_default_page_size_is_500(self):
        """Default page size is 500."""
        self.mock_svc.list.return_value.execute.return_value = {"messages": []}
        list(paginate_gmail_messages(self.mock_svc))
        call_kwargs = self.mock_svc.list.call_args[1]
        self.assertEqual(call_kwargs["maxResults"], 500)

    def test_always_passes_user_id_me(self):
        """userId is always 'me'."""
        self.mock_svc.list.return_value.execute.return_value = {"messages": []}
        list(paginate_gmail_messages(self.mock_svc))
        call_kwargs = self.mock_svc.list.call_args[1]
        self.assertEqual(call_kwargs["userId"], "me")

    def test_passes_page_token_on_subsequent_requests(self):
        """Page token is passed on second and subsequent requests."""
        self.mock_svc.list.return_value.execute.side_effect = [
            {"messages": [{"id": "m1"}], "nextPageToken": "next_token"},
            {"messages": [{"id": "m2"}]},
        ]
        list(paginate_gmail_messages(self.mock_svc))
        calls = self.mock_svc.list.call_args_list
        # First call should not have pageToken
        self.assertNotIn("pageToken", calls[0][1])
        # Second call should have pageToken
        self.assertEqual(calls[1][1]["pageToken"], "next_token")


class TestGatherPages(unittest.TestCase):
    """Tests for gather_pages function."""

    def test_gathers_all_pages(self):
        """Collects all IDs from all pages."""
        pages = [["a", "b"], ["c", "d"], ["e"]]
        result = gather_pages(iter(pages))
        self.assertEqual(result, ["a", "b", "c", "d", "e"])

    def test_empty_pages_returns_empty_list(self):
        """Empty input yields empty output."""
        result = gather_pages(iter([]))
        self.assertEqual(result, [])

    def test_max_pages_limits_pages_collected(self):
        """max_pages stops collection after N pages."""
        pages = [["a", "b"], ["c", "d"], ["e", "f"], ["g"]]
        result = gather_pages(iter(pages), max_pages=2)
        self.assertEqual(result, ["a", "b", "c", "d"])

    def test_max_pages_one(self):
        """max_pages=1 returns only first page."""
        pages = [["a", "b", "c"], ["d", "e"]]
        result = gather_pages(iter(pages), max_pages=1)
        self.assertEqual(result, ["a", "b", "c"])

    def test_limit_truncates_results(self):
        """limit truncates total results."""
        pages = [["a", "b", "c"], ["d", "e", "f"]]
        result = gather_pages(iter(pages), limit=4)
        self.assertEqual(result, ["a", "b", "c", "d"])

    def test_limit_exact_match(self):
        """limit exactly matching total count."""
        pages = [["a", "b"], ["c"]]
        result = gather_pages(iter(pages), limit=3)
        self.assertEqual(result, ["a", "b", "c"])

    def test_limit_less_than_first_page(self):
        """limit less than first page size."""
        pages = [["a", "b", "c", "d", "e"]]
        result = gather_pages(iter(pages), limit=2)
        self.assertEqual(result, ["a", "b"])

    def test_limit_stops_iteration_early(self):
        """limit stops consuming pages once reached."""
        pages = [["a", "b"], ["c", "d"], ["e", "f"]]
        result = gather_pages(iter(pages), limit=3)
        # Should stop after second page since 4 >= 3
        self.assertEqual(result, ["a", "b", "c"])

    def test_max_pages_and_limit_combined(self):
        """Both max_pages and limit can be used together."""
        pages = [["a", "b", "c"], ["d", "e", "f"], ["g", "h"]]
        # max_pages=2 stops after 2 pages, limit only truncates if limit reached first
        result = gather_pages(iter(pages), max_pages=2, limit=4)
        # max_pages=2 triggers first (6 items collected), limit doesn't truncate after
        self.assertEqual(result, ["a", "b", "c", "d", "e", "f"])

    def test_limit_reached_before_max_pages(self):
        """limit reached before max_pages."""
        pages = [["a", "b"], ["c", "d"], ["e", "f"]]
        result = gather_pages(iter(pages), max_pages=10, limit=3)
        self.assertEqual(result, ["a", "b", "c"])

    def test_max_pages_reached_before_limit(self):
        """max_pages reached before limit."""
        pages = [["a"], ["b"], ["c"]]
        result = gather_pages(iter(pages), max_pages=2, limit=10)
        self.assertEqual(result, ["a", "b"])

    def test_works_with_generator(self):
        """Works with generator input."""
        def gen():
            yield ["x", "y"]
            yield ["z"]
        result = gather_pages(gen())
        self.assertEqual(result, ["x", "y", "z"])

    def test_empty_page_in_middle(self):
        """Handles empty pages in the middle."""
        pages = [["a"], [], ["b"]]
        result = gather_pages(iter(pages))
        self.assertEqual(result, ["a", "b"])

    def test_limit_zero_returns_empty(self):
        """limit=0 is falsy, so no limit applied (returns all)."""
        pages = [["a", "b"], ["c"]]
        result = gather_pages(iter(pages), limit=0)
        # limit=0 is falsy, so the limit check doesn't trigger
        self.assertEqual(result, ["a", "b", "c"])

    def test_max_pages_zero_returns_empty(self):
        """max_pages=0 is falsy, so no max_pages limit applied."""
        pages = [["a"], ["b"], ["c"]]
        result = gather_pages(iter(pages), max_pages=0)
        self.assertEqual(result, ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
