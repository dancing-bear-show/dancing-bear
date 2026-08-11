"""Tests for ``search_inbox_message_dicts``: the N+1-avoiding dict search.

This method returns full message dicts so callers no longer need a per-ID
``get_message`` round trip. It reuses the query contract established for
``_build_search_url``: callers pass RAW terms, no ``$filter`` is emitted, and
the ``days`` window is applied client-side.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from core.outlook.mail import OutlookMailMixin
from core.outlook.models import SearchParams


def make_mock_response(json_data=None):
    """Create a mock HTTP response object."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    return resp


def iso_days_ago(days: int) -> str:
    """Return an ISO-8601 Z timestamp ``days`` before now."""
    stamp = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def graph_message(mid: str, **overrides) -> dict:
    """Build a Graph message payload with sensible defaults."""
    msg = {
        "id": mid,
        "subject": f"Subject {mid}",
        "receivedDateTime": iso_days_ago(1),
        "from": {"emailAddress": {"name": "Sender", "address": "s@example.com"}},
        "bodyPreview": "preview",
        "hasAttachments": False,
        "conversationId": f"conv-{mid}",
        "isRead": True,
    }
    msg.update(overrides)
    return msg


class FakeMailClient(OutlookMailMixin):
    """Fake client exercising the mixin without network or credentials."""

    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir
        self._cfg_cache = {}

    def _headers(self):
        return {"Authorization": "Bearer fake-token", "Content-Type": "application/json"}

    def _headers_search(self):
        headers = self._headers()
        headers["ConsistencyLevel"] = "eventual"
        return headers

    def cfg_get_json(self, key, ttl=300):
        return self._cfg_cache.get(key)

    def cfg_put_json(self, key, data):
        self._cfg_cache[key] = data

    def cfg_clear(self):
        self._cfg_cache.clear()


class DictSearchTestBase(unittest.TestCase):
    """Shared setup for dict-search tests."""

    def _run(self, response, **kwargs):
        """Run a search against a canned response, returning (result, url)."""
        with patch("core.outlook.mail._requests") as mock_requests_fn:
            mock_requests = MagicMock()
            mock_requests_fn.return_value = mock_requests
            mock_requests.get.return_value = make_mock_response(response)
            kwargs.setdefault("search_query", "invoice")
            kwargs.setdefault("use_cache", False)
            client = kwargs.pop("client", None) or FakeMailClient()
            result = client.search_inbox_message_dicts(SearchParams(**kwargs))
            url = mock_requests.get.call_args[0][0]
        return result, url


class TestDictSearchUrl(DictSearchTestBase):
    """URL construction: $select breadth, no $filter, encoding."""

    def _url(self, **kwargs) -> str:
        _result, url = self._run({"value": []}, **kwargs)
        return url

    def test_selects_all_required_fields(self):
        select = parse_qs(urlparse(self._url()).query).get("$select", [""])[0]

        for field in (
            "id", "subject", "receivedDateTime", "from", "toRecipients",
            "bodyPreview", "hasAttachments", "conversationId", "isRead",
        ):
            self.assertIn(field, select)

    def test_emits_no_filter_even_with_days(self):
        """Graph rejects $search+$filter; the window is client-side."""
        self.assertNotIn("$filter", self._url(days=7))

    def test_query_is_kql_quoted_and_encoded(self):
        self.assertIn("$search=%22invoice%22", self._url())

    def test_special_chars_cannot_inject_query_params(self):
        url = self._url(search_query="a&$top=999")

        self.assertEqual(parse_qs(urlparse(url).query).get("$top"), ["25"])

    def test_top_is_honoured(self):
        url = self._url(top=50)

        self.assertEqual(parse_qs(urlparse(url).query).get("$top"), ["50"])

    def test_targets_inbox(self):
        self.assertIn("/me/mailFolders/inbox/messages", self._url())


class TestDictSearchResults(DictSearchTestBase):
    """Result shape: full dicts, not bare IDs."""

    def test_returns_dicts_not_ids(self):
        result, _url = self._run({"value": [graph_message("m1")]})

        self.assertIsInstance(result[0], dict)
        self.assertEqual(result[0]["id"], "m1")

    def test_preserves_graph_fields(self):
        msg = graph_message("m1", subject="Receipt", hasAttachments=True, isRead=False)
        result, _url = self._run({"value": [msg]})

        self.assertEqual(result[0]["subject"], "Receipt")
        self.assertTrue(result[0]["hasAttachments"])
        self.assertFalse(result[0]["isRead"])

    def test_skips_entries_without_id(self):
        result, _url = self._run({"value": [{"subject": "no id"}, graph_message("m1")]})

        self.assertEqual([m["id"] for m in result], ["m1"])

    def test_empty_response_returns_empty_list(self):
        result, _url = self._run({"value": []})

        self.assertEqual(result, [])


class TestDictSearchClientSideDateFilter(DictSearchTestBase):
    """The days window is enforced client-side."""

    def test_drops_out_of_window_messages(self):
        result, _url = self._run(
            {"value": [
                graph_message("recent", receivedDateTime=iso_days_ago(1)),
                graph_message("stale", receivedDateTime=iso_days_ago(90)),
            ]},
            days=7,
        )

        self.assertEqual([m["id"] for m in result], ["recent"])

    def test_keeps_all_when_no_days(self):
        result, _url = self._run(
            {"value": [
                graph_message("recent", receivedDateTime=iso_days_ago(1)),
                graph_message("stale", receivedDateTime=iso_days_ago(900)),
            ]},
        )

        self.assertEqual([m["id"] for m in result], ["recent", "stale"])

    def test_keeps_message_missing_received_date(self):
        """A missing receivedDateTime must not silently drop the message."""
        msg = graph_message("no-date")
        del msg["receivedDateTime"]
        result, _url = self._run({"value": [msg]}, days=7)

        self.assertEqual([m["id"] for m in result], ["no-date"])


class TestDictSearchPagination(unittest.TestCase):
    """Pagination follows @odata.nextLink up to params.pages."""

    @patch("core.outlook.mail._requests")
    def test_follows_next_link(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests
        mock_requests.get.side_effect = [
            make_mock_response({"value": [graph_message("m1")], "@odata.nextLink": "http://next"}),
            make_mock_response({"value": [graph_message("m2")]}),
        ]

        result = FakeMailClient().search_inbox_message_dicts(
            SearchParams(search_query="invoice", pages=2, use_cache=False)
        )

        self.assertEqual([m["id"] for m in result], ["m1", "m2"])
        self.assertEqual(mock_requests.get.call_count, 2)


class TestDictSearchCache(unittest.TestCase):
    """Cache isolation: the dict cache must not collide with the ID cache."""

    def _client(self):
        return FakeMailClient(cache_dir="/tmp/outlook-cache-test")  # nosec B108 - fake, never written

    @patch("core.outlook.mail._requests")
    def test_uses_distinct_cache_key_prefix(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests
        mock_requests.get.return_value = make_mock_response({"value": [graph_message("m1")]})
        client = self._client()

        client.search_inbox_message_dicts(SearchParams(search_query="invoice"))

        self.assertTrue(any(k.startswith("searchdicts_") for k in client._cfg_cache))
        self.assertFalse(any(k.startswith("search_") and not k.startswith("searchdicts_")
                             for k in client._cfg_cache))

    @patch("core.outlook.mail._requests")
    def test_rejects_cached_id_list_shape(self, mock_requests_fn):
        """A stale list-of-str cache entry must be ignored, not returned as dicts."""
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests
        mock_requests.get.return_value = make_mock_response({"value": [graph_message("m1")]})
        client = self._client()
        params = SearchParams(search_query="invoice")
        # Poison every cache slot with the old ID-list shape.
        client.cfg_get_json = lambda key, ttl=300: ["stale-id-1", "stale-id-2"]

        result = client.search_inbox_message_dicts(params)

        self.assertEqual([m["id"] for m in result], ["m1"])

    @patch("core.outlook.mail._requests")
    def test_returns_cached_dicts_without_refetch(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests
        client = self._client()
        client.cfg_get_json = lambda key, ttl=300: [{"id": "cached"}]

        result = client.search_inbox_message_dicts(SearchParams(search_query="invoice"))

        self.assertEqual([m["id"] for m in result], ["cached"])
        mock_requests.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
