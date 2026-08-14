"""Tests for Outlook mail folder and filter operations — unique tests not covered by test_core_outlook_mail.py."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import requests

from core.outlook.mail import OutlookMailMixin


# -------------------- Fixtures --------------------

RULE_BASIC = {
    "id": "rule-1",
    "conditions": {"senderContains": ["sender@example.com"]},
    "actions": {"assignCategories": ["Work"]},
}
RULE_WITH_FORWARD = {
    "id": "rule-2",
    "conditions": {"subjectContains": ["urgent"]},
    "actions": {
        "forwardTo": [{"emailAddress": {"address": "forward@example.com"}}],
        "moveToFolder": "folder-123",
    },
}
RULES_LIST = [RULE_BASIC, RULE_WITH_FORWARD]

FOLDER_INBOX = {"id": "inbox-id", "displayName": "Inbox", "parentFolderId": None}
FOLDER_ARCHIVE = {"id": "archive-id", "displayName": "Archive", "parentFolderId": None}
FOLDER_SUBFOLDER = {"id": "sub-id", "displayName": "SubFolder", "parentFolderId": "inbox-id"}
FOLDERS_LIST = [FOLDER_INBOX, FOLDER_ARCHIVE]


def make_mock_response(json_data=None, status_code=200, text=None):
    """Create a mock HTTP response object."""
    resp = MagicMock()
    resp.status_code = status_code
    fallback_text = str(json_data) if json_data else ""
    resp.text = text if text is not None else fallback_text
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def make_error_response(status_code=500, text="Internal Server Error"):
    """Create a mock HTTP response object whose raise_for_status() raises HTTPError."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock(
        side_effect=requests.exceptions.HTTPError(f"{status_code} Error", response=resp)
    )
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


# -------------------- Filter (Rule) Tests --------------------

class TestListFilters(OutlookMailTestBase):
    """Tests for list_filters method."""

    @patch("core.outlook._mail_labels._requests")
    def test_list_filters_with_cache_miss(self, mock_requests_fn):
        from tests.fixtures import test_path
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": RULES_LIST})

        client = FakeMailClient(cache_dir=test_path("test"))  # nosec B108 - test fixture
        result = client.list_filters(use_cache=True)

        self.assertEqual(len(result), 2)
        self.assertIsNotNone(client._cfg_cache.get("rules_inbox"))

    @patch("core.outlook._mail_labels._requests")
    def test_list_filters_with_cache_hit(self, mock_requests_fn):
        from tests.fixtures import test_path
        mock_requests = self._setup_mock_requests(mock_requests_fn)

        client = FakeMailClient(cache_dir=test_path("test"))  # nosec B108 - test fixture
        client._cfg_cache["rules_inbox"] = RULES_LIST
        result = client.list_filters(use_cache=True)

        self.assertEqual(len(result), 2)
        mock_requests.get.assert_not_called()

    @patch("core.outlook._mail_labels._requests")
    def test_list_filters_raises_on_api_error(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_error_response(status_code=500)

        with self.assertRaises(requests.exceptions.HTTPError):
            FakeMailClient().list_filters()

    @patch("core.outlook._mail_labels._requests")
    def test_list_filters_raises_on_unauthorized(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_error_response(status_code=401, text="Unauthorized")

        with self.assertRaises(requests.exceptions.HTTPError):
            FakeMailClient().list_filters()


class TestCreateFilter(OutlookMailTestBase):
    """Tests for create_filter method."""

    @patch("core.outlook._mail_labels._requests")
    def test_create_filter_raises_on_api_error(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_error_response(status_code=400, text="Bad Request")

        with self.assertRaises(requests.exceptions.HTTPError):
            FakeMailClient().create_filter(criteria={"from": "sender@example.com"}, action={})

    @patch("core.outlook._mail_labels._requests")
    def test_create_filter_raises_on_server_error(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_error_response(status_code=503, text="Service Unavailable")

        with self.assertRaises(requests.exceptions.HTTPError):
            FakeMailClient().create_filter(criteria={}, action={"addLabelIds": ["Work"]})


class TestDeleteFilter(OutlookMailTestBase):
    """Tests for delete_filter method."""

    @patch("core.outlook._mail_labels._requests")
    def test_delete_filter_raises_on_not_found(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.delete.return_value = make_error_response(status_code=404, text="Not Found")

        with self.assertRaises(requests.exceptions.HTTPError):
            FakeMailClient().delete_filter("missing-rule")

    @patch("core.outlook._mail_labels._requests")
    def test_delete_filter_raises_on_server_error(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.delete.return_value = make_error_response(status_code=500)

        with self.assertRaises(requests.exceptions.HTTPError):
            FakeMailClient().delete_filter("rule-1")


# -------------------- Folder Tests --------------------

class TestListFolders(OutlookMailTestBase):
    """Tests for list_folders method."""

    @patch("core.outlook._mail_folders._requests")
    def test_list_folders_raises_on_api_error(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_error_response(status_code=500)

        with self.assertRaises(requests.exceptions.HTTPError):
            FakeMailClient().list_folders()

    @patch("core.outlook._mail_folders._requests")
    def test_list_folders_raises_on_pagination_error(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": [FOLDER_INBOX], "@odata.nextLink": "http://next"}),
            make_error_response(status_code=502, text="Bad Gateway"),
        ]

        with self.assertRaises(requests.exceptions.HTTPError):
            FakeMailClient().list_folders()


class TestListAllFolders(OutlookMailTestBase):
    """Tests for list_all_folders method."""

    @patch("core.outlook._mail_folders._requests")
    def test_list_all_folders_raises_on_root_fetch_error(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_error_response(status_code=500)

        with self.assertRaises(requests.exceptions.HTTPError):
            FakeMailClient().list_all_folders()

    @patch("core.outlook._mail_folders._requests")
    def test_list_all_folders_raises_on_child_fetch_error(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": FOLDERS_LIST}),  # Root folders succeed
            make_error_response(status_code=503, text="Service Unavailable"),  # Children of inbox fail
        ]

        with self.assertRaises(requests.exceptions.HTTPError):
            FakeMailClient().list_all_folders()


class TestGetFolderPathMap(OutlookMailTestBase):
    """Tests for get_folder_path_map method."""

    @patch("core.outlook._mail_folders._requests")
    def test_get_folder_path_map_raises_on_api_error(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_error_response(status_code=500)

        with self.assertRaises(requests.exceptions.HTTPError):
            FakeMailClient().get_folder_path_map()

    @patch("core.outlook._mail_folders._requests")
    def test_get_folder_path_map_handles_cyclic_parent_chain(self, mock_requests_fn):
        # Two folders whose parentFolderId fields point at each other, forming a
        # cycle. build_path()'s `seen` guard must terminate rather than recurse
        # forever, at the cost of producing a path rooted at whichever folder id
        # was resolved first (walk order-dependent, not a real parent chain).
        folder_a = {"id": "a-id", "displayName": "A", "parentFolderId": "b-id"}
        folder_b = {"id": "b-id", "displayName": "B", "parentFolderId": "a-id"}
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": [folder_a, folder_b]}),
            make_mock_response({"value": []}),
            make_mock_response({"value": []}),
        ]

        result = FakeMailClient().get_folder_path_map()

        self.assertEqual(result.get("B/A"), "a-id")
        self.assertEqual(result.get("A/B"), "b-id")


if __name__ == "__main__":
    unittest.main()
