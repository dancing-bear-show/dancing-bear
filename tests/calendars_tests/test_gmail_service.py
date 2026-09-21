"""Tests for GmailService.query_and_list_ids delegation.

Every pipeline test mocks ``query_and_list_ids`` on the service, so none of
them exercise the method itself: they assert what the mock was told to return.
This file drives the real method through a fake provider, so the query the
helper builds and the paging arguments it forwards are actually asserted.
"""

from __future__ import annotations

import unittest

from calendars.gmail_service import GmailService, QueryParams


class _RecordingProvider:
    """Records the kwargs list_message_ids was called with."""

    def __init__(self, ids: list[str] | None = None) -> None:
        self.ids = ids if ids is not None else ["m1", "m2"]
        self.calls: list[dict] = []

    def list_message_ids(self, *, query: str, max_pages: int, page_size: int) -> list[str]:
        self.calls.append({"query": query, "max_pages": max_pages, "page_size": page_size})
        return self.ids


class TestQueryAndListIdsDelegation(unittest.TestCase):
    """query_and_list_ids must build the query and forward the paging args."""

    def setUp(self) -> None:
        self.provider = _RecordingProvider()
        self.svc = GmailService(provider=self.provider)

    def test_returns_provider_ids(self):
        ids = self.svc.query_and_list_ids(
            QueryParams(from_text="richmondhill.ca", days=30),
            max_pages=2,
            page_size=50,
        )
        self.assertEqual(ids, ["m1", "m2"])

    def test_forwards_paging_arguments(self):
        self.svc.query_and_list_ids(
            QueryParams(from_text="richmondhill.ca", days=30),
            max_pages=3,
            page_size=25,
        )
        call = self.provider.calls[0]
        self.assertEqual(call["max_pages"], 3)
        self.assertEqual(call["page_size"], 25)

    def test_passes_built_query_not_raw_params(self):
        """The provider receives the assembled query string, not the dataclass."""
        self.svc.query_and_list_ids(
            QueryParams(from_text="richmondhill.ca", days=30, inbox_only=True),
            max_pages=1,
            page_size=10,
        )
        query = self.provider.calls[0]["query"]
        self.assertIn('from:"richmondhill.ca"', query)
        self.assertIn("newer_than:30d", query)
        self.assertIn("in:inbox", query)

    def test_explicit_query_passes_through_unchanged(self):
        """An explicit query bypasses assembly, matching build_query_from_params."""
        self.svc.query_and_list_ids(
            QueryParams(explicit="subject:enrollment", from_text="ignored", days=99),
            max_pages=1,
            page_size=10,
        )
        self.assertEqual(self.provider.calls[0]["query"], "subject:enrollment")

    def test_matches_build_query_from_params(self):
        """The query built inline must equal the public builder's output.

        Pins the two together: if query_and_list_ids ever stops delegating to
        build_query_from_params, the callers that were consolidated onto this
        helper would silently change behaviour.
        """
        params = QueryParams(from_text="a@b.com", days=7, inbox_only=True)
        self.svc.query_and_list_ids(params, max_pages=1, page_size=10)
        self.assertEqual(
            self.provider.calls[0]["query"],
            GmailService.build_query_from_params(params),
        )

    def test_empty_result_is_returned_as_is(self):
        """A provider returning no ids is passed through, not coerced."""
        svc = GmailService(provider=_RecordingProvider(ids=[]))
        self.assertEqual(
            svc.query_and_list_ids(QueryParams(days=1), max_pages=1, page_size=10), []
        )


if __name__ == "__main__":
    unittest.main()
