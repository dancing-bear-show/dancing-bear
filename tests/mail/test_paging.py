"""Tests for mail/paging.py Gmail pagination utilities."""

import unittest
from unittest.mock import MagicMock

from mail.paging import paginate_gmail_messages, gather_pages


class GatherPagesTests(unittest.TestCase):
    def test_empty_pages(self):
        result = gather_pages([])
        self.assertEqual(result, [])

    def test_single_page(self):
        pages = [["id1", "id2", "id3"]]
        result = gather_pages(pages)
        self.assertEqual(result, ["id1", "id2", "id3"])

    def test_multiple_pages(self):
        pages = [["id1", "id2"], ["id3", "id4"], ["id5"]]
        result = gather_pages(pages)
        self.assertEqual(result, ["id1", "id2", "id3", "id4", "id5"])

    def test_max_pages_limit(self):
        pages = [["id1"], ["id2"], ["id3"], ["id4"]]
        result = gather_pages(pages, max_pages=2)
        self.assertEqual(result, ["id1", "id2"])

    def test_limit_truncates_results(self):
        pages = [["id1", "id2", "id3"], ["id4", "id5"]]
        result = gather_pages(pages, limit=4)
        self.assertEqual(result, ["id1", "id2", "id3", "id4"])

    def test_limit_exact(self):
        pages = [["id1", "id2"], ["id3", "id4"]]
        result = gather_pages(pages, limit=4)
        self.assertEqual(result, ["id1", "id2", "id3", "id4"])

    def test_limit_smaller_than_first_page(self):
        pages = [["id1", "id2", "id3", "id4", "id5"]]
        result = gather_pages(pages, limit=2)
        self.assertEqual(result, ["id1", "id2"])

    def test_max_pages_and_limit_combined(self):
        pages = [["id1", "id2"], ["id3", "id4"], ["id5", "id6"]]
        # max_pages is checked after each full page is added; with max_pages=2
        # we consume exactly 2 full pages (4 items) and then break, before
        # the limit=3 check can truncate the accumulated results.
        result = gather_pages(pages, max_pages=2, limit=3)
        # In this case max_pages stops iteration after a full page, so limit
        # does not apply and the final output contains 4 items.
        self.assertEqual(result, ["id1", "id2", "id3", "id4"])

    def test_works_with_generator(self):
        def page_gen():
            yield ["id1", "id2"]
            yield ["id3"]
        result = gather_pages(page_gen())
        self.assertEqual(result, ["id1", "id2", "id3"])

    def test_preserves_order(self):
        pages = [["a", "b"], ["c", "d"], ["e"]]
        result = gather_pages(pages)
        self.assertEqual(result, ["a", "b", "c", "d", "e"])


class PaginateGmailMessagesTests(unittest.TestCase):
    def _make_mock_svc(self, pages):
        """Create a mock Gmail messages service that returns given pages.

        pages: list of lists of message dicts, e.g. [[{"id": "1"}], [{"id": "2"}]]
        """
        svc = MagicMock()
        responses = []
        for i, page in enumerate(pages):
            resp = {"messages": page}
            if i < len(pages) - 1:
                resp["nextPageToken"] = f"token_{i+1}"
            responses.append(resp)

        # Chain the responses
        call_count = [0]
        def execute():
            idx = call_count[0]
            call_count[0] += 1
            return responses[idx] if idx < len(responses) else {"messages": []}

        svc.list.return_value.execute = execute
        return svc

    def test_empty_results(self):
        svc = self._make_mock_svc([[]])
        result = list(paginate_gmail_messages(svc))
        self.assertEqual(result, [])

    def test_single_page(self):
        svc = self._make_mock_svc([[{"id": "msg1"}, {"id": "msg2"}]])
        result = list(paginate_gmail_messages(svc))
        self.assertEqual(result, [["msg1", "msg2"]])

    def test_multiple_pages(self):
        svc = self._make_mock_svc([
            [{"id": "msg1"}, {"id": "msg2"}],
            [{"id": "msg3"}],
        ])
        result = list(paginate_gmail_messages(svc))
        self.assertEqual(result, [["msg1", "msg2"], ["msg3"]])

    def test_passes_query(self):
        svc = self._make_mock_svc([[{"id": "msg1"}]])
        list(paginate_gmail_messages(svc, query="from:test@example.com"))
        call_args = svc.list.call_args
        self.assertEqual(call_args.kwargs.get("q"), "from:test@example.com")

    def test_passes_label_ids(self):
        svc = self._make_mock_svc([[{"id": "msg1"}]])
        list(paginate_gmail_messages(svc, label_ids=["INBOX", "UNREAD"]))
        call_args = svc.list.call_args
        self.assertEqual(call_args.kwargs.get("labelIds"), ["INBOX", "UNREAD"])

    def test_passes_page_size(self):
        svc = self._make_mock_svc([[{"id": "msg1"}]])
        list(paginate_gmail_messages(svc, page_size=100))
        call_args = svc.list.call_args
        self.assertEqual(call_args.kwargs.get("maxResults"), 100)

    def test_skips_messages_without_id(self):
        svc = self._make_mock_svc([[{"id": "msg1"}, {"threadId": "no-id"}, {"id": "msg2"}]])
        result = list(paginate_gmail_messages(svc))
        self.assertEqual(result, [["msg1", "msg2"]])

    def test_yields_lists(self):
        svc = self._make_mock_svc([[{"id": "msg1"}], [{"id": "msg2"}]])
        for page in paginate_gmail_messages(svc):
            self.assertIsInstance(page, list)


if __name__ == "__main__":
    unittest.main()
