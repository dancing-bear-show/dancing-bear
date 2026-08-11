"""Tests for Outlook mail message operations: search, list, move, get."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from tests.fixtures import test_path
from core.outlook.mail import OutlookMailMixin


# -------------------- Fixtures --------------------

MESSAGE_BASIC = {"id": "msg-1", "subject": "Test Subject", "bodyPreview": "Preview..."}
MESSAGE_LIST = [
    {"id": "msg-1", "subject": "First"},
    {"id": "msg-2", "subject": "Second"},
]


def make_mock_response(json_data=None, status_code=200, text=None):
    """Create a mock HTTP response object."""
    resp = MagicMock()
    resp.status_code = status_code
    fallback_text = str(json_data) if json_data else ""
    resp.text = text if text is not None else fallback_text
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


class FakeMailClient(OutlookMailMixin):
    """Fake client for testing mixin methods."""

    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir
        self._cfg_cache = {}

    def _headers(self):
        return {"Authorization": "Bearer fake-token", "Content-Type": "application/json"}

    def _headers_search(self):
        h = self._headers()
        h["ConsistencyLevel"] = "eventual"
        return h

    def cfg_get_json(self, key, ttl=300):
        return self._cfg_cache.get(key)

    def cfg_put_json(self, key, data):
        self._cfg_cache[key] = data

    def cfg_clear(self):
        self._cfg_cache.clear()


class OutlookMailTestBase(unittest.TestCase):
    """Base class for Outlook mail tests with common helpers."""

    def _setup_mock_requests(self, mock_requests_fn):
        """Set up mock requests and return the mock object."""
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests
        return mock_requests


class TestSearchInboxMessages(OutlookMailTestBase):
    """Tests for search_inbox_messages method."""

    @patch("core.outlook.mail._requests")
    def test_search_inbox_basic(self, mock_requests_fn):
        from core.outlook.models import SearchParams
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": MESSAGE_LIST})

        result = FakeMailClient().search_inbox_messages(
            SearchParams(search_query="test query", use_cache=False)
        )

        self.assertEqual(result, ["msg-1", "msg-2"])

    @patch("core.outlook.mail._requests")
    def test_search_inbox_with_days_filter(self, mock_requests_fn):
        """days must NOT emit $filter -- Graph rejects $search+$filter.

        The window is applied client-side instead; see
        tests/core_tests/test_outlook_mail_search_query.py.
        """
        import datetime as _dt
        from core.outlook.models import SearchParams

        def _days_ago(days: int) -> str:
            stamp = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)
            return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")

        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({
            "value": [
                {"id": "in-window", "receivedDateTime": _days_ago(1)},
                {"id": "out-of-window", "receivedDateTime": _days_ago(90)},
            ]
        })

        result = FakeMailClient().search_inbox_messages(
            SearchParams(search_query="test", days=7, use_cache=False)
        )

        call_url = mock_requests.get.call_args[0][0]
        self.assertNotIn("$filter", call_url)
        self.assertIn("receivedDateTime", call_url)
        # Positive: the window is genuinely enforced client-side, so this would
        # fail against a function that simply returned nothing.
        self.assertEqual(result, ["in-window"])

    @patch("core.outlook.mail._requests")
    def test_search_inbox_pagination(self, mock_requests_fn):
        from core.outlook.models import SearchParams
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": [{"id": "msg-1"}], "@odata.nextLink": "http://next"}),
            make_mock_response({"value": [{"id": "msg-2"}]}),
        ]

        result = FakeMailClient().search_inbox_messages(
            SearchParams(search_query="test", pages=2, use_cache=False)
        )

        self.assertEqual(result, ["msg-1", "msg-2"])
        self.assertEqual(mock_requests.get.call_count, 2)

    @patch("core.outlook.mail._requests")
    def test_search_inbox_with_cache(self, mock_requests_fn):
        from core.outlook.models import SearchParams
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": MESSAGE_LIST})

        client = FakeMailClient(cache_dir=test_path("test"))  # nosec B108 - test fixture
        result = client.search_inbox_messages(
            SearchParams(search_query="test", use_cache=True)
        )

        self.assertEqual(len(result), 2)


class TestListMessages(OutlookMailTestBase):
    """Tests for list_messages method."""

    @patch("core.outlook.mail._requests")
    def test_list_messages_default(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": MESSAGE_LIST})

        result = FakeMailClient().list_messages()

        self.assertEqual(len(result), 2)
        self.assertIn("inbox", mock_requests.get.call_args[0][0])

    @patch("core.outlook.mail._requests")
    def test_list_messages_different_folder(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": []})

        FakeMailClient().list_messages(folder="sentitems")

        self.assertIn("sentitems", mock_requests.get.call_args[0][0])

    @patch("core.outlook.mail._requests")
    def test_list_messages_pagination(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": [{"id": "1"}], "@odata.nextLink": "http://next"}),
            make_mock_response({"value": [{"id": "2"}]}),
        ]

        result = FakeMailClient().list_messages(pages=2)

        self.assertEqual(len(result), 2)


class TestMoveMessage(OutlookMailTestBase):
    """Tests for move_message method."""

    @patch("core.outlook.mail._requests")
    def test_move_message(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "msg-1"})

        FakeMailClient().move_message("msg-1", "archive-folder-id")

        mock_requests.post.assert_called_once()
        self.assertIn("msg-1/move", mock_requests.post.call_args[0][0])
        call_json = mock_requests.post.call_args.kwargs["json"]
        self.assertEqual(call_json["destinationId"], "archive-folder-id")


class TestGetMessage(OutlookMailTestBase):
    """Tests for get_message method."""

    @patch("core.outlook.mail._requests")
    def test_get_message_with_body(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response(MESSAGE_BASIC)

        result = FakeMailClient().get_message("msg-1")

        self.assertEqual(result["subject"], "Test Subject")
        self.assertIn("body", mock_requests.get.call_args[0][0])

    @patch("core.outlook.mail._requests")
    def test_get_message_without_body(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response(MESSAGE_BASIC)

        FakeMailClient().get_message("msg-1", select_body=False)

        url = mock_requests.get.call_args[0][0]
        # Should not end with ,body (bodyPreview is ok)
        self.assertFalse(url.endswith(",body"))
        self.assertNotIn(",body,", url)


if __name__ == "__main__":
    unittest.main()
