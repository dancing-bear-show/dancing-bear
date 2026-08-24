"""Tests for Outlook $search URL construction: encoding contract and $filter incompatibility.

Covers two pre-existing bugs in ``core.outlook.mail``:

Defect 1 -- Microsoft Graph rejects ``$search`` combined with ``$filter``. The inbox
search must not emit ``$filter``; the ``days`` window is applied client-side
instead (the same approach ``_build_kql_search_url`` already takes).

Defect 2 -- the raw search term was interpolated into the URL unencoded. The
encoding contract is now: **callers pass RAW, unquoted terms**; ``_build_search_url``
owns both the KQL quote-wrapping and the percent-encoding.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from core.outlook.models import SearchParams

from tests.core_tests.outlook_helpers import (
    FakeMailClient,
    iso_days_ago,
    make_mock_response,
)


class SearchUrlTestBase(unittest.TestCase):
    """Shared helpers for inspecting the generated search URL."""

    def _build(self, **kwargs) -> str:
        params = SearchParams(**kwargs)
        return FakeMailClient()._build_search_url(params)

    def _query_params(self, url: str) -> dict[str, list[str]]:
        """Parse the URL query string without decoding surprises."""
        return parse_qs(urlparse(url).query, keep_blank_values=True)


class TestSearchFilterIncompatibility(SearchUrlTestBase):
    """Defect 1: $search and $filter must never appear together."""

    def test_no_filter_when_days_set(self):
        """days must NOT produce a $filter -- Graph 400s on $search+$filter."""
        url = self._build(search_query="invoice", days=7)

        self.assertNotIn("$filter", url)

    def test_search_present_when_days_set(self):
        """Dropping $filter must not drop $search."""
        url = self._build(search_query="invoice", days=7)

        self.assertIn("$search=", url)

    def test_selects_received_date_for_client_side_filtering(self):
        """$select must include receivedDateTime so the client-side filter has data."""
        url = self._build(search_query="invoice", days=7)

        select = self._query_params(url).get("$select", [""])[0]
        self.assertIn("receivedDateTime", select)

    def test_no_filter_when_days_absent(self):
        url = self._build(search_query="invoice")

        self.assertNotIn("$filter", url)


class TestClientSideDateFiltering(unittest.TestCase):
    """Defect 1: the days window is enforced client-side after fetching."""

    @patch("core.outlook.mail._requests")
    def test_drops_messages_older_than_days_window(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests
        mock_requests.get.return_value = make_mock_response({
            "value": [
                {"id": "recent", "receivedDateTime": iso_days_ago(1)},
                {"id": "stale", "receivedDateTime": iso_days_ago(90)},
            ]
        })

        result = FakeMailClient().search_inbox_messages(
            SearchParams(search_query="invoice", days=7, use_cache=False)
        )

        self.assertEqual(result, ["recent"])

    @patch("core.outlook.mail._requests")
    def test_keeps_all_messages_when_days_absent(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests
        mock_requests.get.return_value = make_mock_response({
            "value": [
                {"id": "recent", "receivedDateTime": iso_days_ago(1)},
                {"id": "stale", "receivedDateTime": iso_days_ago(900)},
            ]
        })

        result = FakeMailClient().search_inbox_messages(
            SearchParams(search_query="invoice", use_cache=False)
        )

        self.assertEqual(result, ["recent", "stale"])

    @patch("core.outlook.mail._requests")
    def test_keeps_message_with_missing_received_date(self, mock_requests_fn):
        """A message Graph returned without receivedDateTime must not be silently dropped."""
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests
        mock_requests.get.return_value = make_mock_response({
            "value": [{"id": "no-date"}]
        })

        result = FakeMailClient().search_inbox_messages(
            SearchParams(search_query="invoice", days=7, use_cache=False)
        )

        self.assertEqual(result, ["no-date"])


class TestSearchQueryEncoding(SearchUrlTestBase):
    """Defect 2: raw terms are quote-wrapped and percent-encoded by the builder."""

    def test_plain_term_is_kql_quoted_and_encoded(self):
        """A raw term becomes %22term%22 -- the builder owns the quoting."""
        url = self._build(search_query="invoice")

        self.assertIn("$search=%22invoice%22", url)

    def test_spaces_are_encoded_not_literal(self):
        """A space must never reach the URL literally."""
        url = self._build(search_query="order confirmation")

        self.assertNotIn(" ", url)
        self.assertIn("%22order%20confirmation%22", url)

    def test_ampersand_cannot_inject_extra_query_param(self):
        """& in a term must be encoded, not split the query string."""
        url = self._build(search_query="a&$top=999")

        self.assertEqual(self._query_params(url).get("$top"), ["25"])

    def test_embedded_quote_is_encoded(self):
        """A double quote in the raw term must be percent-encoded."""
        url = self._build(search_query='say "hi"')

        self.assertNotIn('"', url)

    def test_non_ascii_term_is_encoded(self):
        url = self._build(search_query="café")

        self.assertNotIn("é", url)
        self.assertIn("caf%C3%A9", url)

    def test_caller_passes_raw_terms_not_pre_quoted(self):
        """Contract check: a pre-quoted term would double-wrap.

        Callers pass RAW terms. Passing '"x"' must therefore produce an
        encoded double-quote inside the KQL quotes, which is the visible
        symptom of a caller violating the contract.
        """
        url = self._build(search_query="Confirmation for order 123")

        self.assertIn("$search=%22Confirmation%20for%20order%20123%22", url)
        self.assertNotIn("%22%22", url)


class TestSearchUrlStructure(SearchUrlTestBase):
    """Structural invariants that must survive the fix."""

    def test_top_is_included(self):
        url = self._build(search_query="invoice", top=50)

        self.assertEqual(self._query_params(url).get("$top"), ["50"])

    def test_targets_inbox_folder(self):
        url = self._build(search_query="invoice")

        self.assertIn("/me/mailFolders/inbox/messages", url)


if __name__ == "__main__":
    unittest.main()
