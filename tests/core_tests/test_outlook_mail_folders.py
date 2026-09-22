"""Tests for Outlook mail folder and filter operations — unique tests not covered by test_core_outlook_mail.py."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import requests

from tests.core_tests.outlook_helpers import (
    FakeMailClient,
    OutlookMailTestBase,
    make_error_response,
    make_mock_response,
)


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


class TestResolveFolderPath(OutlookMailTestBase):
    """``resolve_folder_path``: look up a folder path WITHOUT creating anything.

    The non-mutating counterpart to ``ensure_folder_path``, added for callers that
    must not change the mailbox -- previews above all. ``rules.plan`` and
    ``rules.sync --dry-run`` previously fell back to the folder path string on a
    cache miss while the apply resolved the real Graph id, so the two keyed the
    same rule differently and the preview reported ``Would create`` for a rule the
    live run treated as a no-op.

    Tested against the real implementation rather than a stub: the parity tests in
    tests/mail_tests/outlook/ mock this method, which proves the wiring but says
    nothing about the method itself.
    """

    #: Archive/News nested under Archive, plus one top-level folder.
    FOLDERS = [
        {"id": "id-archive", "displayName": "Archive", "parentFolderId": None},
        {"id": "id-news", "displayName": "News", "parentFolderId": "id-archive"},
        {"id": "id-flat", "displayName": "Receipts", "parentFolderId": None},
    ]

    def _mock_tree(self, mock_requests_fn):
        """Serve the folder tree, then empty child listings for the BFS walk."""
        mock_requests = self._setup_mock_requests(mock_requests_fn)
        mock_requests.get.side_effect = [
            make_mock_response({"value": list(self.FOLDERS)}),
        ] + [make_mock_response({"value": []}) for _ in range(len(self.FOLDERS))]
        return mock_requests

    @patch("core.outlook._mail_folders._requests")
    def test_resolves_a_nested_path(self, mock_requests_fn):
        self._mock_tree(mock_requests_fn)

        self.assertEqual(FakeMailClient().resolve_folder_path("Archive/News"), "id-news")

    @patch("core.outlook._mail_folders._requests")
    def test_resolves_a_flat_path(self, mock_requests_fn):
        self._mock_tree(mock_requests_fn)

        self.assertEqual(FakeMailClient().resolve_folder_path("Receipts"), "id-flat")

    @patch("core.outlook._mail_folders._requests")
    def test_absent_path_returns_empty_string(self, mock_requests_fn):
        """A missing folder resolves to "" -- never a created folder, never a guess.

        Callers distinguish "" from an id to decide whether the apply would have to
        create the folder, which is what makes "Would create" honest.
        """
        self._mock_tree(mock_requests_fn)

        self.assertEqual(FakeMailClient().resolve_folder_path("Archive/Missing"), "")

    @patch("core.outlook._mail_folders._requests")
    def test_never_posts(self, mock_requests_fn):
        """The whole point: no POST, for a hit or a miss.

        ``ensure_folder_path`` reaches ``ensure_folder`` / ``_ensure_child_folder``,
        both of which POST to create. A preview calling those was a live defect on
        the sync dry-run path, so this asserts on the transport rather than trusting
        the call graph.
        """
        mock_requests = self._mock_tree(mock_requests_fn)

        FakeMailClient().resolve_folder_path("Archive/Missing")

        self.assertEqual(
            mock_requests.post.call_count, 0,
            "resolve_folder_path POSTed -- it must never create a folder",
        )

    @patch("core.outlook._mail_folders._requests")
    def test_bypasses_a_stale_cached_snapshot(self, mock_requests_fn):
        """It must read FRESH, not serve whatever is cached.

        Raised in review on this PR. The first cut passed ``ttl=0``, believing that
        forced a fresh listing. ``cfg_get_json`` documents 0 as "no expiry check"
        and guards on ``if ttl > 0``, so 0 serves an entry of ANY age -- the exact
        opposite. Probed with a 2-hour-old snapshot: zero Graph calls, and ``""``
        returned for a folder that exists, leaving the plan/apply parity gap this
        method was added to close exactly as it was.

        ``bypass_cache`` skips the cache READ outright. ``clear_cache`` would also
        work but wipes the whole provider cache, including unrelated rule caches.

        This test is the one whose absence let that through: the parity tests in
        tests/mail_tests/ mock this method, and the other tests here stub
        ``list_all_folders``, so nothing exercised the real cache path.
        """
        client = FakeMailClient()
        # Plant a stale snapshot that does NOT contain the folder.
        client._cfg_cache["folders_all"] = [
            {"id": "id-old", "displayName": "OldName", "parentFolderId": None},
        ]
        self._mock_tree(mock_requests_fn)

        got = client.resolve_folder_path("Archive/News")

        self.assertEqual(
            got, "id-news",
            "the stale cached snapshot was served instead of a fresh listing",
        )

    @patch("core.outlook._mail_folders._requests")
    def test_fresh_false_reuses_the_cache(self, mock_requests_fn):
        """Contrast: ``fresh=False`` deliberately reuses the cached map.

        Pins that the bypass is opt-out rather than unconditional, so a caller that
        wants the cheap cached read still has one.
        """
        client = FakeMailClient()
        client._cfg_cache["folders_all"] = [
            {"id": "id-cached", "displayName": "Cached", "parentFolderId": None},
        ]
        mock_requests = self._setup_mock_requests(mock_requests_fn)

        got = client.resolve_folder_path("Cached", fresh=False)

        self.assertEqual(got, "id-cached")
        self.assertEqual(
            mock_requests.get.call_count, 0,
            "fresh=False still hit Graph; the cache was not reused",
        )

    def test_empty_path_raises(self):
        """Matches ``ensure_folder_path``: an empty path is a caller error.

        Returning "" instead would be indistinguishable from "folder not found",
        hiding a malformed config behind a plausible-looking miss.
        """
        with self.assertRaises(ValueError):
            FakeMailClient().resolve_folder_path("")


if __name__ == "__main__":
    unittest.main()
