"""Tests for Outlook mail label (category) operations."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from tests.fixtures import test_path
from core.outlook.mail import OutlookMailMixin


# -------------------- Fixtures --------------------

CATEGORY_WORK = {"id": "cat-1", "displayName": "Work", "color": "preset0"}
CATEGORY_PERSONAL = {"id": "cat-2", "displayName": "Personal", "color": "preset1"}
CATEGORIES_LIST = [CATEGORY_WORK, CATEGORY_PERSONAL]


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


class TestListLabels(OutlookMailTestBase):
    """Tests for list_labels method."""

    @patch("core.outlook._mail_labels._requests")
    def test_list_labels_no_cache(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": CATEGORIES_LIST})

        result = FakeMailClient().list_labels()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Work")
        self.assertEqual(result[0]["id"], "cat-1")
        self.assertEqual(result[0]["color"]["name"], "preset0")
        self.assertEqual(result[0]["type"], "user")

    @patch("core.outlook._mail_labels._requests")
    def test_list_labels_with_cache_miss(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": CATEGORIES_LIST})

        client = FakeMailClient(cache_dir=test_path("test"))  # nosec B108 - test fixture
        result = client.list_labels(use_cache=True)

        self.assertEqual(len(result), 2)
        mock_requests.get.assert_called_once()
        self.assertIsNotNone(client._cfg_cache.get("categories"))

    @patch("core.outlook._mail_labels._requests")
    def test_list_labels_with_cache_hit(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)

        client = FakeMailClient(cache_dir=test_path("test"))  # nosec B108 - test fixture
        client._cfg_cache["categories"] = CATEGORIES_LIST
        result = client.list_labels(use_cache=True)

        self.assertEqual(len(result), 2)
        mock_requests.get.assert_not_called()

    @patch("core.outlook._mail_labels._requests")
    def test_list_labels_empty(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": []})

        result = FakeMailClient().list_labels()

        self.assertEqual(result, [])


class TestCreateLabel(OutlookMailTestBase):
    """Tests for create_label method."""

    @patch("core.outlook._mail_labels._requests")
    def test_create_label_basic(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "new-cat", "displayName": "NewLabel"})

        result = FakeMailClient().create_label("NewLabel")

        self.assertEqual(result["id"], "new-cat")
        self.assertEqual(result["name"], "NewLabel")
        mock_requests.post.assert_called_once()

    @patch("core.outlook._mail_labels._requests")
    def test_create_label_with_color(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "new-cat", "displayName": "ColorLabel"})

        FakeMailClient().create_label("ColorLabel", color={"name": "preset5"})

        call_json = mock_requests.post.call_args.kwargs["json"]
        self.assertEqual(call_json["displayName"], "ColorLabel")
        self.assertEqual(call_json["color"], "preset5")

    @patch("core.outlook._mail_labels._requests")
    def test_create_label_without_color(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "new-cat", "displayName": "NoColor"})

        FakeMailClient().create_label("NoColor")

        call_json = mock_requests.post.call_args.kwargs["json"]
        self.assertNotIn("color", call_json)


class TestUpdateLabel(OutlookMailTestBase):
    """Tests for update_label method."""

    @patch("core.outlook._mail_labels._requests")
    def test_update_label_name(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.patch.return_value = make_mock_response({"id": "cat-1"}, text='{"id": "cat-1"}')

        result = FakeMailClient().update_label("cat-1", {"name": "Updated"})

        call_json = mock_requests.patch.call_args.kwargs["json"]
        self.assertEqual(call_json["displayName"], "Updated")
        self.assertIsNotNone(result)

    @patch("core.outlook._mail_labels._requests")
    def test_update_label_color(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.patch.return_value = make_mock_response({"id": "cat-1"}, text='{"id": "cat-1"}')

        FakeMailClient().update_label("cat-1", {"color": {"name": "preset3"}})

        call_json = mock_requests.patch.call_args.kwargs["json"]
        self.assertEqual(call_json["color"], "preset3")

    @patch("core.outlook._mail_labels._requests")
    def test_update_label_empty_body_returns_empty(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)

        result = FakeMailClient().update_label("cat-1", {})

        self.assertEqual(result, {})
        mock_requests.patch.assert_not_called()

    @patch("core.outlook._mail_labels._requests")
    def test_update_label_empty_response(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.patch.return_value = make_mock_response(None, text="")

        result = FakeMailClient().update_label("cat-1", {"name": "Test"})

        self.assertEqual(result, {})


class TestDeleteLabel(OutlookMailTestBase):
    """Tests for delete_label method."""

    @patch("core.outlook._mail_labels._requests")
    def test_delete_label(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.delete.return_value = make_mock_response(status_code=204, text="")

        FakeMailClient().delete_label("cat-1")

        mock_requests.delete.assert_called_once()
        self.assertIn("cat-1", mock_requests.delete.call_args[0][0])


class TestGetLabelIdMap(OutlookMailTestBase):
    """Tests for get_label_id_map method."""

    @patch("core.outlook._mail_labels._requests")
    def test_get_label_id_map(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": CATEGORIES_LIST})

        result = FakeMailClient().get_label_id_map()

        self.assertEqual(result["Work"], "cat-1")
        self.assertEqual(result["Personal"], "cat-2")

    @patch("core.outlook._mail_labels._requests")
    def test_get_label_id_map_empty(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": []})

        result = FakeMailClient().get_label_id_map()

        self.assertEqual(result, {})


class TestEnsureLabel(OutlookMailTestBase):
    """Tests for ensure_label method."""

    @patch("core.outlook._mail_labels._requests")
    def test_ensure_label_exists(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": CATEGORIES_LIST})

        result = FakeMailClient().ensure_label("Work")

        self.assertEqual(result, "cat-1")
        mock_requests.post.assert_not_called()

    @patch("core.outlook._mail_labels._requests")
    def test_ensure_label_creates_new(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": []})
        mock_requests.post.return_value = make_mock_response({"id": "new-id", "displayName": "NewLabel"})

        result = FakeMailClient().ensure_label("NewLabel")

        self.assertEqual(result, "new-id")
        mock_requests.post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
