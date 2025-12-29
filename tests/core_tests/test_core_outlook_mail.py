"""Tests for core/outlook/mail.py mail operations."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.outlook.mail import OutlookMailMixin


# -------------------- Fixtures --------------------

CATEGORY_WORK = {"id": "cat-1", "displayName": "Work", "color": "preset0"}
CATEGORY_PERSONAL = {"id": "cat-2", "displayName": "Personal", "color": "preset1"}
CATEGORIES_LIST = [CATEGORY_WORK, CATEGORY_PERSONAL]

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

MESSAGE_BASIC = {"id": "msg-1", "subject": "Test Subject", "bodyPreview": "Preview..."}
MESSAGE_LIST = [
    {"id": "msg-1", "subject": "First"},
    {"id": "msg-2", "subject": "Second"},
]

FOLDER_INBOX = {"id": "inbox-id", "displayName": "Inbox", "parentFolderId": None}
FOLDER_ARCHIVE = {"id": "archive-id", "displayName": "Archive", "parentFolderId": None}
FOLDER_SUBFOLDER = {"id": "sub-id", "displayName": "SubFolder", "parentFolderId": "inbox-id"}
FOLDERS_LIST = [FOLDER_INBOX, FOLDER_ARCHIVE]


def make_mock_response(json_data=None, status_code=200, text=None):
    """Create a mock HTTP response object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text if text is not None else (str(json_data) if json_data else "")
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


# -------------------- Label (Category) Tests --------------------

class TestListLabels(OutlookMailTestBase):
    """Tests for list_labels method."""

    @patch("core.outlook.mail._requests")
    def test_list_labels_no_cache(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": CATEGORIES_LIST})

        result = FakeMailClient().list_labels()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Work")
        self.assertEqual(result[0]["id"], "cat-1")
        self.assertEqual(result[0]["color"]["name"], "preset0")
        self.assertEqual(result[0]["type"], "user")

    @patch("core.outlook.mail._requests")
    def test_list_labels_with_cache_miss(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": CATEGORIES_LIST})

        client = FakeMailClient(cache_dir="/tmp/test")  # nosec B108 - test fixture
        result = client.list_labels(use_cache=True)

        self.assertEqual(len(result), 2)
        mock_requests.get.assert_called_once()
        # Verify cache was populated
        self.assertIsNotNone(client._cfg_cache.get("categories"))

    @patch("core.outlook.mail._requests")
    def test_list_labels_with_cache_hit(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)

        client = FakeMailClient(cache_dir="/tmp/test")  # nosec B108 - test fixture
        client._cfg_cache["categories"] = CATEGORIES_LIST
        result = client.list_labels(use_cache=True)

        self.assertEqual(len(result), 2)
        mock_requests.get.assert_not_called()

    @patch("core.outlook.mail._requests")
    def test_list_labels_empty(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": []})

        result = FakeMailClient().list_labels()

        self.assertEqual(result, [])


class TestCreateLabel(OutlookMailTestBase):
    """Tests for create_label method."""

    @patch("core.outlook.mail._requests")
    def test_create_label_basic(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "new-cat", "displayName": "NewLabel"})

        result = FakeMailClient().create_label("NewLabel")

        self.assertEqual(result["id"], "new-cat")
        self.assertEqual(result["name"], "NewLabel")
        mock_requests.post.assert_called_once()

    @patch("core.outlook.mail._requests")
    def test_create_label_with_color(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "new-cat", "displayName": "ColorLabel"})

        FakeMailClient().create_label("ColorLabel", color={"name": "preset5"})

        call_json = mock_requests.post.call_args.kwargs["json"]
        self.assertEqual(call_json["displayName"], "ColorLabel")
        self.assertEqual(call_json["color"], "preset5")

    @patch("core.outlook.mail._requests")
    def test_create_label_without_color(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "new-cat", "displayName": "NoColor"})

        FakeMailClient().create_label("NoColor")

        call_json = mock_requests.post.call_args.kwargs["json"]
        self.assertNotIn("color", call_json)


class TestUpdateLabel(OutlookMailTestBase):
    """Tests for update_label method."""

    @patch("core.outlook.mail._requests")
    def test_update_label_name(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.patch.return_value = make_mock_response({"id": "cat-1"}, text='{"id": "cat-1"}')

        result = FakeMailClient().update_label("cat-1", {"name": "Updated"})

        call_json = mock_requests.patch.call_args.kwargs["json"]
        self.assertEqual(call_json["displayName"], "Updated")
        self.assertIsNotNone(result)

    @patch("core.outlook.mail._requests")
    def test_update_label_color(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.patch.return_value = make_mock_response({"id": "cat-1"}, text='{"id": "cat-1"}')

        FakeMailClient().update_label("cat-1", {"color": {"name": "preset3"}})

        call_json = mock_requests.patch.call_args.kwargs["json"]
        self.assertEqual(call_json["color"], "preset3")

    @patch("core.outlook.mail._requests")
    def test_update_label_empty_body_returns_empty(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)

        result = FakeMailClient().update_label("cat-1", {})

        self.assertEqual(result, {})
        mock_requests.patch.assert_not_called()

    @patch("core.outlook.mail._requests")
    def test_update_label_empty_response(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.patch.return_value = make_mock_response(None, text="")

        result = FakeMailClient().update_label("cat-1", {"name": "Test"})

        self.assertEqual(result, {})


class TestDeleteLabel(OutlookMailTestBase):
    """Tests for delete_label method."""

    @patch("core.outlook.mail._requests")
    def test_delete_label(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.delete.return_value = make_mock_response(status_code=204, text="")

        FakeMailClient().delete_label("cat-1")

        mock_requests.delete.assert_called_once()
        self.assertIn("cat-1", mock_requests.delete.call_args[0][0])


class TestGetLabelIdMap(OutlookMailTestBase):
    """Tests for get_label_id_map method."""

    @patch("core.outlook.mail._requests")
    def test_get_label_id_map(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": CATEGORIES_LIST})

        result = FakeMailClient().get_label_id_map()

        self.assertEqual(result["Work"], "cat-1")
        self.assertEqual(result["Personal"], "cat-2")

    @patch("core.outlook.mail._requests")
    def test_get_label_id_map_empty(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": []})

        result = FakeMailClient().get_label_id_map()

        self.assertEqual(result, {})


class TestEnsureLabel(OutlookMailTestBase):
    """Tests for ensure_label method."""

    @patch("core.outlook.mail._requests")
    def test_ensure_label_exists(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": CATEGORIES_LIST})

        result = FakeMailClient().ensure_label("Work")

        self.assertEqual(result, "cat-1")
        mock_requests.post.assert_not_called()

    @patch("core.outlook.mail._requests")
    def test_ensure_label_creates_new(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": []})
        mock_requests.post.return_value = make_mock_response({"id": "new-id", "displayName": "NewLabel"})

        result = FakeMailClient().ensure_label("NewLabel")

        self.assertEqual(result, "new-id")
        mock_requests.post.assert_called_once()


# -------------------- Filter (Rule) Tests --------------------

class TestListFilters(OutlookMailTestBase):
    """Tests for list_filters method."""

    @patch("core.outlook.mail._requests")
    def test_list_filters_basic(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": RULES_LIST})

        result = FakeMailClient().list_filters()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], "rule-1")
        self.assertEqual(result[0]["criteria"]["from"], "sender@example.com")
        self.assertEqual(result[0]["action"]["addLabelIds"], ["Work"])

    @patch("core.outlook.mail._requests")
    def test_list_filters_with_forward_action(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": [RULE_WITH_FORWARD]})

        result = FakeMailClient().list_filters()

        self.assertEqual(result[0]["criteria"]["subject"], "urgent")
        self.assertEqual(result[0]["action"]["forward"], "forward@example.com")
        self.assertEqual(result[0]["action"]["moveToFolderId"], "folder-123")

    @patch("core.outlook.mail._requests")
    def test_list_filters_with_cache_miss(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": RULES_LIST})

        client = FakeMailClient(cache_dir="/tmp/test")  # nosec B108 - test fixture
        result = client.list_filters(use_cache=True)

        self.assertEqual(len(result), 2)
        self.assertIsNotNone(client._cfg_cache.get("rules_inbox"))

    @patch("core.outlook.mail._requests")
    def test_list_filters_with_cache_hit(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)

        client = FakeMailClient(cache_dir="/tmp/test")  # nosec B108 - test fixture
        client._cfg_cache["rules_inbox"] = RULES_LIST
        result = client.list_filters(use_cache=True)

        self.assertEqual(len(result), 2)
        mock_requests.get.assert_not_called()

    @patch("core.outlook.mail._requests")
    def test_list_filters_multiple_conditions(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        rule = {
            "id": "rule-multi",
            "conditions": {
                "senderContains": ["a@test.com", "b@test.com"],
                "recipientContains": ["to@test.com"],
            },
            "actions": {},
        }
        mock_requests.get.return_value = make_mock_response({"value": [rule]})

        result = FakeMailClient().list_filters()

        self.assertEqual(result[0]["criteria"]["from"], "a@test.com OR b@test.com")
        self.assertEqual(result[0]["criteria"]["to"], "to@test.com")


class TestCreateFilter(OutlookMailTestBase):
    """Tests for create_filter method."""

    @patch("core.outlook.mail._requests")
    def test_create_filter_with_from(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "new-rule"})

        result = FakeMailClient().create_filter(
            criteria={"from": "sender@example.com"},
            action={"addLabelIds": ["Work"]}
        )

        self.assertEqual(result["id"], "new-rule")
        call_json = mock_requests.post.call_args.kwargs["json"]
        self.assertEqual(call_json["conditions"]["senderContains"], ["sender@example.com"])
        self.assertEqual(call_json["actions"]["assignCategories"], ["Work"])

    @patch("core.outlook.mail._requests")
    def test_create_filter_with_multiple_from(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "new-rule"})

        FakeMailClient().create_filter(
            criteria={"from": "a@test.com OR b@test.com"},
            action={}
        )

        call_json = mock_requests.post.call_args.kwargs["json"]
        self.assertEqual(call_json["conditions"]["senderContains"], ["a@test.com", "b@test.com"])

    @patch("core.outlook.mail._requests")
    def test_create_filter_with_forward(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "new-rule"})

        FakeMailClient().create_filter(
            criteria={"subject": "urgent"},
            action={"forward": "a@test.com, b@test.com"}
        )

        call_json = mock_requests.post.call_args.kwargs["json"]
        self.assertEqual(call_json["conditions"]["subjectContains"], ["urgent"])
        self.assertEqual(len(call_json["actions"]["forwardTo"]), 2)

    @patch("core.outlook.mail._requests")
    def test_create_filter_with_move(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "new-rule"})

        FakeMailClient().create_filter(
            criteria={"to": "me@test.com"},
            action={"moveToFolderId": "folder-123"}
        )

        call_json = mock_requests.post.call_args.kwargs["json"]
        self.assertEqual(call_json["actions"]["moveToFolder"], "folder-123")

    @patch("core.outlook.mail._requests")
    def test_create_filter_has_required_fields(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.post.return_value = make_mock_response({"id": "new-rule"})

        FakeMailClient().create_filter(criteria={}, action={})

        call_json = mock_requests.post.call_args.kwargs["json"]
        self.assertIn("displayName", call_json)
        self.assertEqual(call_json["sequence"], 1)
        self.assertTrue(call_json["isEnabled"])
        self.assertTrue(call_json["stopProcessingRules"])


class TestDeleteFilter(OutlookMailTestBase):
    """Tests for delete_filter method."""

    @patch("core.outlook.mail._requests")
    def test_delete_filter(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.delete.return_value = make_mock_response(status_code=204, text="")

        FakeMailClient().delete_filter("rule-1")

        mock_requests.delete.assert_called_once()
        self.assertIn("rule-1", mock_requests.delete.call_args[0][0])
        self.assertIn("messageRules", mock_requests.delete.call_args[0][0])


# -------------------- Message Tests --------------------

class TestSearchInboxMessages(OutlookMailTestBase):
    """Tests for search_inbox_messages method."""

    @patch("core.outlook.mail._requests")
    def test_search_inbox_basic(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": MESSAGE_LIST})

        result = FakeMailClient().search_inbox_messages("test query", use_cache=False)

        self.assertEqual(result, ["msg-1", "msg-2"])

    @patch("core.outlook.mail._requests")
    def test_search_inbox_with_days_filter(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": MESSAGE_LIST})

        FakeMailClient().search_inbox_messages("test", days=7, use_cache=False)

        call_url = mock_requests.get.call_args[0][0]
        self.assertIn("$filter=receivedDateTime", call_url)

    @patch("core.outlook.mail._requests")
    def test_search_inbox_pagination(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": [{"id": "msg-1"}], "@odata.nextLink": "http://next"}),
            make_mock_response({"value": [{"id": "msg-2"}]}),
        ]

        result = FakeMailClient().search_inbox_messages("test", pages=2, use_cache=False)

        self.assertEqual(result, ["msg-1", "msg-2"])
        self.assertEqual(mock_requests.get.call_count, 2)

    @patch("core.outlook.mail._requests")
    def test_search_inbox_with_cache(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": MESSAGE_LIST})

        client = FakeMailClient(cache_dir="/tmp/test")  # nosec B108 - test fixture
        result = client.search_inbox_messages("test", use_cache=True)

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


# -------------------- Folder Tests --------------------

class TestListFolders(OutlookMailTestBase):
    """Tests for list_folders method."""

    @patch("core.outlook.mail._requests")
    def test_list_folders(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": FOLDERS_LIST})

        result = FakeMailClient().list_folders()

        self.assertEqual(len(result), 2)

    @patch("core.outlook.mail._requests")
    def test_list_folders_pagination(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": [FOLDER_INBOX], "@odata.nextLink": "http://next"}),
            make_mock_response({"value": [FOLDER_ARCHIVE]}),
        ]

        result = FakeMailClient().list_folders()

        self.assertEqual(len(result), 2)
        self.assertEqual(mock_requests.get.call_count, 2)


class TestGetFolderIdMap(OutlookMailTestBase):
    """Tests for get_folder_id_map method."""

    @patch("core.outlook.mail._requests")
    def test_get_folder_id_map(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": FOLDERS_LIST})

        result = FakeMailClient().get_folder_id_map()

        self.assertEqual(result["Inbox"], "inbox-id")
        self.assertEqual(result["Archive"], "archive-id")


class TestEnsureFolder(OutlookMailTestBase):
    """Tests for ensure_folder method."""

    @patch("core.outlook.mail._requests")
    def test_ensure_folder_exists(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": FOLDERS_LIST})

        result = FakeMailClient().ensure_folder("Inbox")

        self.assertEqual(result, "inbox-id")
        mock_requests.post.assert_not_called()

    @patch("core.outlook.mail._requests")
    def test_ensure_folder_creates_new(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": []})
        mock_requests.post.return_value = make_mock_response({"id": "new-folder-id"})

        result = FakeMailClient().ensure_folder("NewFolder")

        self.assertEqual(result, "new-folder-id")

    @patch("core.outlook.mail._requests")
    def test_ensure_folder_conflict_returns_existing(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        # First get returns empty, second returns the folder after conflict
        mock_requests.get.side_effect = [
            make_mock_response({"value": []}),
            make_mock_response({"value": []}),
            make_mock_response({"value": [{"id": "existing-id", "displayName": "Test"}]}),
        ]
        mock_requests.post.return_value = make_mock_response(status_code=409)

        result = FakeMailClient().ensure_folder("Test")

        self.assertEqual(result, "existing-id")


class TestListAllFolders(OutlookMailTestBase):
    """Tests for list_all_folders method."""

    @patch("core.outlook.mail._requests")
    def test_list_all_folders_flat(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": FOLDERS_LIST}),  # Root folders
            make_mock_response({"value": []}),  # Children of inbox
            make_mock_response({"value": []}),  # Children of archive
        ]

        client = FakeMailClient()
        result = client.list_all_folders()

        self.assertEqual(len(result), 2)

    @patch("core.outlook.mail._requests")
    def test_list_all_folders_with_children(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": [FOLDER_INBOX]}),  # Root folders
            make_mock_response({"value": [FOLDER_SUBFOLDER]}),  # Children of inbox
            make_mock_response({"value": []}),  # Children of subfolder
        ]

        result = FakeMailClient().list_all_folders()

        self.assertEqual(len(result), 2)

    @patch("core.outlook.mail._requests")
    def test_list_all_folders_with_cache(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)

        client = FakeMailClient()
        client._cfg_cache["folders_all"] = FOLDERS_LIST
        result = client.list_all_folders()

        self.assertEqual(len(result), 2)
        mock_requests.get.assert_not_called()

    @patch("core.outlook.mail._requests")
    def test_list_all_folders_clear_cache(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": FOLDERS_LIST}),
            make_mock_response({"value": []}),
            make_mock_response({"value": []}),
        ]

        client = FakeMailClient()
        client._cfg_cache["folders_all"] = []  # Stale cache
        result = client.list_all_folders(clear_cache=True)

        self.assertEqual(len(result), 2)


class TestGetFolderPathMap(OutlookMailTestBase):
    """Tests for get_folder_path_map method."""

    @patch("core.outlook.mail._requests")
    def test_get_folder_path_map_flat(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": FOLDERS_LIST}),
            make_mock_response({"value": []}),
            make_mock_response({"value": []}),
        ]

        result = FakeMailClient().get_folder_path_map()

        self.assertEqual(result["Inbox"], "inbox-id")
        self.assertEqual(result["Archive"], "archive-id")

    @patch("core.outlook.mail._requests")
    def test_get_folder_path_map_nested(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": [FOLDER_INBOX]}),
            make_mock_response({"value": [FOLDER_SUBFOLDER]}),
            make_mock_response({"value": []}),
        ]

        result = FakeMailClient().get_folder_path_map()

        self.assertIn("Inbox", result)
        self.assertIn("Inbox/SubFolder", result)


class TestEnsureFolderPath(OutlookMailTestBase):
    """Tests for ensure_folder_path method."""

    @patch("core.outlook.mail._requests")
    def test_ensure_folder_path_single_level(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.return_value = make_mock_response({"value": FOLDERS_LIST})

        result = FakeMailClient().ensure_folder_path("Inbox")

        self.assertEqual(result, "inbox-id")

    @patch("core.outlook.mail._requests")
    def test_ensure_folder_path_nested_exists(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": [FOLDER_INBOX]}),  # get_folder_id_map
            make_mock_response({"value": [FOLDER_SUBFOLDER]}),  # Children
        ]

        result = FakeMailClient().ensure_folder_path("Inbox/SubFolder")

        self.assertEqual(result, "sub-id")

    @patch("core.outlook.mail._requests")
    def test_ensure_folder_path_creates_nested(self, mock_requests_fn):
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": [FOLDER_INBOX]}),  # get_folder_id_map
            make_mock_response({"value": []}),  # No children
        ]
        mock_requests.post.return_value = make_mock_response({"id": "new-sub-id"})

        result = FakeMailClient().ensure_folder_path("Inbox/NewSub")

        self.assertEqual(result, "new-sub-id")
        mock_requests.post.assert_called_once()

    def test_ensure_folder_path_empty_raises(self):
        with self.assertRaises(ValueError) as ctx:
            FakeMailClient().ensure_folder_path("")
        self.assertIn("empty", str(ctx.exception).lower())


# -------------------- Signature Tests --------------------

class TestSignatures(unittest.TestCase):
    """Tests for signature methods (NotImplementedError expected)."""

    def test_list_signatures_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            FakeMailClient().list_signatures()

    def test_update_signature_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            FakeMailClient().update_signature("<html>Signature</html>")


if __name__ == "__main__":
    unittest.main()
