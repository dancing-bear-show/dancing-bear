"""Tests for outlook messages.search — search_messages mixin and CLI command."""

from __future__ import annotations

import argparse
import json
import unittest
from io import StringIO
from unittest.mock import MagicMock, Mock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_graph_message(
    *,
    id: str = "msg-1",
    subject: str = "Hello",
    received: str = "2026-01-15T20:00:00Z",
    from_name: str = "Sender",
    from_addr: str = "sender@example.com",
    preview: str = "Body preview",
    has_attachments: bool = False,
) -> dict:
    return {
        "id": id,
        "subject": subject,
        "receivedDateTime": received,
        "from": {"emailAddress": {"name": from_name, "address": from_addr}},
        "bodyPreview": preview,
        "hasAttachments": has_attachments,
    }


def _make_response(messages: list, next_link: str = None) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    data = {"value": messages}
    if next_link:
        data["@odata.nextLink"] = next_link
    resp.json.return_value = data
    return resp


# ---------------------------------------------------------------------------
# Tests: OutlookMailMixin.search_messages
# ---------------------------------------------------------------------------

class TestSearchMessages(unittest.TestCase):
    """Unit tests for OutlookMailMixin.search_messages URL construction and result parsing."""

    def _make_client(self):
        from core.outlook.mail import OutlookMailMixin
        client = MagicMock()
        client._headers_search.return_value = {"Authorization": "Bearer token", "ConsistencyLevel": "eventual"}
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        # Bind the real method
        client.search_messages = OutlookMailMixin.search_messages.__get__(client)
        return client

    @patch("core.outlook.mail._requests")
    def test_query_wraps_in_kql_quotes(self, mock_requests):
        """query param should produce $search=%22<query>%22."""
        client = self._make_client()
        mock_requests.return_value.get.return_value = _make_response([])

        client.search_messages(query="brightchamps", top=10, pages=1)

        url = mock_requests.return_value.get.call_args[0][0]
        self.assertIn("%22brightchamps%22", url)

    @patch("core.outlook.mail._requests")
    def test_sender_uses_kql_from_prefix(self, mock_requests):
        """sender param should produce $search=%22from:<sender>%22."""
        client = self._make_client()
        mock_requests.return_value.get.return_value = _make_response([])

        client.search_messages(query="", sender="brightchamps.com", top=10, pages=1)

        url = mock_requests.return_value.get.call_args[0][0]
        self.assertIn("from%3Abrightchamps.com", url)

    @patch("core.outlook.mail._requests")
    def test_result_fields_mapped_correctly(self, mock_requests):
        client = self._make_client()
        msg = _make_graph_message(
            id="abc", subject="Test", received="2026-03-01T21:00:00Z",
            from_name="BrightCHAMPS", from_addr="noreply@brightchamps.com",
            preview="Hello", has_attachments=True,
        )
        mock_requests.return_value.get.return_value = _make_response([msg])

        results = client.search_messages(query="test", top=10, pages=1)

        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["id"], "abc")
        self.assertEqual(r["subject"], "Test")
        self.assertEqual(r["received"], "2026-03-01T21:00:00Z")
        self.assertEqual(r["from"], "BrightCHAMPS <noreply@brightchamps.com>")
        self.assertEqual(r["snippet"], "Hello")
        self.assertTrue(r["has_attachments"])

    @patch("core.outlook.mail._requests")
    def test_after_filter_excludes_old_messages(self, mock_requests):
        """Messages before --after date should be excluded (client-side filter)."""
        client = self._make_client()
        old_msg = _make_graph_message(id="old", received="2025-12-31T20:00:00Z")
        new_msg = _make_graph_message(id="new", received="2026-01-15T20:00:00Z")
        mock_requests.return_value.get.return_value = _make_response([old_msg, new_msg])

        results = client.search_messages(query="test", top=10, pages=1, after="2026-01-01")

        ids = [r["id"] for r in results]
        self.assertNotIn("old", ids)
        self.assertIn("new", ids)

    @patch("core.outlook.mail._requests")
    def test_after_filter_applied_when_sender_set(self, mock_requests):
        """after filter applies client-side even when sender is set."""
        client = self._make_client()
        old_msg = _make_graph_message(id="old", received="2025-12-31T20:00:00Z")
        new_msg = _make_graph_message(id="new", received="2026-01-15T20:00:00Z")
        mock_requests.return_value.get.return_value = _make_response([old_msg, new_msg])

        results = client.search_messages(query="", sender="example.com", top=10, pages=1, after="2026-01-01")

        ids = [r["id"] for r in results]
        self.assertNotIn("old", ids)
        self.assertIn("new", ids)

    @patch("core.outlook.mail._requests")
    def test_pagination_follows_next_link(self, mock_requests):
        """Should follow @odata.nextLink up to pages limit."""
        client = self._make_client()
        page1_msg = _make_graph_message(id="p1")
        page2_msg = _make_graph_message(id="p2")

        mock_get = mock_requests.return_value.get
        mock_get.side_effect = [
            _make_response([page1_msg], next_link="https://graph.microsoft.com/v1.0/me/messages?$skip=10"),
            _make_response([page2_msg]),
        ]

        results = client.search_messages(query="test", top=10, pages=2)

        self.assertEqual(len(results), 2)
        self.assertEqual(mock_get.call_count, 2)

    @patch("core.outlook.mail._requests")
    def test_pagination_stops_at_pages_limit(self, mock_requests):
        """Should not fetch more pages than specified."""
        client = self._make_client()
        msg = _make_graph_message(id="p1")

        mock_get = mock_requests.return_value.get
        mock_get.return_value = _make_response([msg], next_link="https://graph.microsoft.com/next")

        client.search_messages(query="test", top=10, pages=1)

        self.assertEqual(mock_get.call_count, 1)

    def test_empty_query_and_sender_returns_empty_list(self):
        """When both query and sender are empty, return [] without calling the API."""
        client = self._make_client()

        results = client.search_messages(query="", sender=None, top=10, pages=1)

        self.assertEqual(results, [])

    @patch("core.outlook.mail._requests")
    def test_empty_results_returned(self, mock_requests):
        client = self._make_client()
        mock_requests.return_value.get.return_value = _make_response([])

        results = client.search_messages(query="nothing", top=10, pages=1)

        self.assertEqual(results, [])

    @patch("core.outlook.mail._requests")
    def test_top_included_in_url(self, mock_requests):
        client = self._make_client()
        mock_requests.return_value.get.return_value = _make_response([])

        client.search_messages(query="test", top=25, pages=1)

        url = mock_requests.return_value.get.call_args[0][0]
        self.assertIn("$top=25", url)

    @patch("core.outlook.mail._requests")
    def test_uses_search_headers(self, mock_requests):
        """Should use _headers_search() (includes ConsistencyLevel: eventual)."""
        client = self._make_client()
        mock_requests.return_value.get.return_value = _make_response([])

        client.search_messages(query="test", top=10, pages=1)

        headers = mock_requests.return_value.get.call_args[1]["headers"]
        self.assertIn("ConsistencyLevel", headers)


# ---------------------------------------------------------------------------
# Tests: run_outlook_messages_search command
# ---------------------------------------------------------------------------

class TestRunOutlookMessagesSearch(unittest.TestCase):
    """Tests for the run_outlook_messages_search CLI handler."""

    def _make_args(self, **kwargs):
        defaults = dict(
            query="test",
            top=10,
            pages=1,
            after=None,
            sender=None,
            json=False,
            client_id="client-123",
            tenant="common",
            token=None,
            accounts_config=None,
            account=None,
            profile=None,
            cache_dir=None,
            cache=None,
        )
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def _mock_client(self, messages=None):
        client = MagicMock()
        client.search_messages.return_value = messages or []
        return client

    @patch("mail.outlook.commands.get_outlook_client")
    def test_passes_query_and_sender_to_search(self, mock_get_client):
        from mail.outlook.commands import run_outlook_messages_search
        client = self._mock_client()
        mock_get_client.return_value = (client, 0)

        args = self._make_args(query="hello", sender="example.com", top=5, pages=2, after="2026-01-01")
        run_outlook_messages_search(args)

        client.search_messages.assert_called_once_with(
            query="hello", top=5, pages=2, after="2026-01-01", sender="example.com", only_inbox=False
        )

    @patch("mail.outlook.commands.get_outlook_client")
    def test_plain_output_formats_messages(self, mock_get_client):
        from mail.outlook.commands import run_outlook_messages_search
        msgs = [{
            "id": "1", "subject": "Class reminder", "from": "BC <noreply@brightchamps.com>",
            "received": "2026-03-01T20:00:00Z", "snippet": "Class in 1 hour", "has_attachments": False,
        }]
        mock_get_client.return_value = (self._mock_client(msgs), 0)

        with patch("sys.stdout", new_callable=StringIO) as out:
            run_outlook_messages_search(self._make_args())

        output = out.getvalue()
        self.assertIn("Class reminder", output)
        self.assertIn("2026-03-01", output)
        self.assertIn("Class in 1 hour", output)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_json_output(self, mock_get_client):
        from mail.outlook.commands import run_outlook_messages_search
        msgs = [{"id": "1", "subject": "Test", "from": "X <x@x.com>",
                 "received": "2026-01-01T00:00:00Z", "snippet": "", "has_attachments": False}]
        mock_get_client.return_value = (self._mock_client(msgs), 0)

        with patch("sys.stdout", new_callable=StringIO) as out:
            run_outlook_messages_search(self._make_args(json=True))

        parsed = json.loads(out.getvalue())
        self.assertEqual(parsed[0]["id"], "1")

    @patch("mail.outlook.commands.get_outlook_client")
    def test_attachment_indicator_in_plain_output(self, mock_get_client):
        from mail.outlook.commands import run_outlook_messages_search
        msgs = [{"id": "1", "subject": "With attachment", "from": "X <x@x.com>",
                 "received": "2026-01-01T00:00:00Z", "snippet": "", "has_attachments": True}]
        mock_get_client.return_value = (self._mock_client(msgs), 0)

        with patch("sys.stdout", new_callable=StringIO) as out:
            run_outlook_messages_search(self._make_args())

        self.assertIn("📎", out.getvalue())

    @patch("mail.outlook.commands.get_outlook_client")
    def test_returns_nonzero_on_client_error(self, mock_get_client):
        from mail.outlook.commands import run_outlook_messages_search
        mock_get_client.return_value = (None, 2)

        result = run_outlook_messages_search(self._make_args())

        self.assertEqual(result, 2)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_returns_zero_on_success(self, mock_get_client):
        from mail.outlook.commands import run_outlook_messages_search
        mock_get_client.return_value = (self._mock_client(), 0)

        result = run_outlook_messages_search(self._make_args())

        self.assertEqual(result, 0)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_returns_one_when_no_query_or_sender(self, mock_get_client):
        """Both --query and --sender absent should return exit code 1."""
        from mail.outlook.commands import run_outlook_messages_search
        mock_get_client.return_value = (self._mock_client(), 0)

        result = run_outlook_messages_search(self._make_args(query="", sender=None))

        self.assertEqual(result, 1)


# ---------------------------------------------------------------------------
# Tests: resolve_outlook_args — account falls back to profile
# ---------------------------------------------------------------------------

class TestResolveOutlookArgsAccountFallback(unittest.TestCase):
    """Tests for the account -> profile fallback in resolve_outlook_args."""

    def test_account_used_as_profile_when_profile_not_set(self):
        """--account should be used as the credentials.ini profile name."""
        from mail.outlook.helpers import resolve_outlook_args

        args = Mock()
        args.profile = None
        args.account = "outlook_vanesa"
        args.client_id = None
        args.tenant = None
        args.token = None
        args.cache_dir = None
        args.cache = None
        args.accounts_config = None

        with patch("mail.outlook.helpers.resolve_outlook_credentials") as mock_resolve:
            mock_resolve.return_value = ("client-xyz", "common", "/path/token.json")
            resolve_outlook_args(args)

        mock_resolve.assert_called_once_with(
            "outlook_vanesa",
            None,
            None,
            None,
        )

    def test_profile_takes_precedence_over_account(self):
        """Explicit --profile should win over --account."""
        from mail.outlook.helpers import resolve_outlook_args

        args = Mock()
        args.profile = "explicit_profile"
        args.account = "outlook_vanesa"
        args.client_id = None
        args.tenant = None
        args.token = None
        args.cache_dir = None
        args.cache = None
        args.accounts_config = None

        with patch("mail.outlook.helpers.resolve_outlook_credentials") as mock_resolve:
            mock_resolve.return_value = (None, None, None)
            resolve_outlook_args(args)

        mock_resolve.assert_called_once_with("explicit_profile", None, None, None)

    def test_both_none_passes_none_as_profile(self):
        """When both profile and account are None, profile=None is passed."""
        from mail.outlook.helpers import resolve_outlook_args

        args = Mock()
        args.profile = None
        args.account = None
        args.client_id = None
        args.tenant = None
        args.token = None
        args.cache_dir = None
        args.cache = None
        args.accounts_config = None

        with patch("mail.outlook.helpers.resolve_outlook_credentials") as mock_resolve:
            mock_resolve.return_value = (None, None, None)
            resolve_outlook_args(args)

        mock_resolve.assert_called_once_with(None, None, None, None)


# ---------------------------------------------------------------------------
# Tests: --days and --only-inbox flags on run_outlook_messages_search
# ---------------------------------------------------------------------------

class TestRunOutlookMessagesSearchNewFlags(unittest.TestCase):
    """Tests for --days and --only-inbox flags added to messages.search."""

    def _make_args(self, **kwargs):
        defaults = dict(
            query="test",
            top=10,
            pages=1,
            after=None,
            days=None,
            sender=None,
            only_inbox=False,
            json=False,
            client_id="client-123",
            tenant="common",
            token=None,
            accounts_config=None,
            account=None,
            profile=None,
            cache_dir=None,
            cache=None,
        )
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def _mock_client(self, messages=None):
        client = MagicMock()
        client.search_messages.return_value = messages or []
        return client

    @patch("mail.outlook.commands.get_outlook_client")
    def test_days_converts_to_after(self, mock_get_client):
        """--days N should compute --after as today minus N days."""
        import datetime
        from mail.outlook.commands import run_outlook_messages_search
        client = self._mock_client()
        mock_get_client.return_value = (client, 0)

        args = self._make_args(days=7)
        run_outlook_messages_search(args)

        call_kwargs = client.search_messages.call_args[1]
        expected_after = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        self.assertEqual(call_kwargs["after"], expected_after)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_days_ignored_when_after_already_set(self, mock_get_client):
        """--after takes precedence over --days."""
        from mail.outlook.commands import run_outlook_messages_search
        client = self._mock_client()
        mock_get_client.return_value = (client, 0)

        args = self._make_args(days=7, after="2026-01-01")
        run_outlook_messages_search(args)

        call_kwargs = client.search_messages.call_args[1]
        self.assertEqual(call_kwargs["after"], "2026-01-01")

    @patch("mail.outlook.commands.get_outlook_client")
    def test_only_inbox_passed_to_search(self, mock_get_client):
        """--only-inbox should be forwarded to search_messages."""
        from mail.outlook.commands import run_outlook_messages_search
        client = self._mock_client()
        mock_get_client.return_value = (client, 0)

        args = self._make_args(only_inbox=True)
        run_outlook_messages_search(args)

        call_kwargs = client.search_messages.call_args[1]
        self.assertTrue(call_kwargs["only_inbox"])

    @patch("core.outlook.mail._requests")
    def test_only_inbox_uses_inbox_folder_path(self, mock_requests):
        """only_inbox=True should target mailFolders/inbox/messages URL."""
        from core.outlook.mail import OutlookMailMixin
        client = MagicMock()
        client._headers_search.return_value = {"Authorization": "Bearer token", "ConsistencyLevel": "eventual"}
        client.search_messages = OutlookMailMixin.search_messages.__get__(client)

        mock_requests.return_value.get.return_value = _make_response([])

        client.search_messages(query="test", top=10, pages=1, only_inbox=True)

        url = mock_requests.return_value.get.call_args[0][0]
        self.assertIn("mailFolders/inbox/messages", url)
        self.assertNotIn("/me/messages", url)

    @patch("core.outlook.mail._requests")
    def test_without_only_inbox_uses_all_messages_path(self, mock_requests):
        """only_inbox=False (default) should use /me/messages URL."""
        from core.outlook.mail import OutlookMailMixin
        client = MagicMock()
        client._headers_search.return_value = {"Authorization": "Bearer token", "ConsistencyLevel": "eventual"}
        client.search_messages = OutlookMailMixin.search_messages.__get__(client)

        mock_requests.return_value.get.return_value = _make_response([])

        client.search_messages(query="test", top=10, pages=1)

        url = mock_requests.return_value.get.call_args[0][0]
        self.assertIn("/me/messages", url)
        self.assertNotIn("mailFolders/inbox", url)


# ---------------------------------------------------------------------------
# Tests: run_outlook_messages_summarize
# ---------------------------------------------------------------------------

class TestRunOutlookMessagesSummarize(unittest.TestCase):
    """Tests for the run_outlook_messages_summarize CLI handler."""

    def _make_args(self, **kwargs):
        defaults = dict(
            id=None,
            query=None,
            top=5,
            pages=1,
            max_words=120,
            out=None,
            client_id="client-123",
            tenant="common",
            token=None,
            accounts_config=None,
            account=None,
            profile=None,
            cache_dir=None,
            cache=None,
        )
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def _mock_client(self, message=None, search_results=None):
        client = MagicMock()
        client.get_message.return_value = message or {
            "id": "msg-1",
            "subject": "Test Subject",
            "receivedDateTime": "2026-03-01T12:00:00Z",
            "from": {"emailAddress": {"name": "Sender", "address": "sender@example.com"}},
            "body": {"content": "<p>Hello world. This is a test message.</p>"},
        }
        client.search_messages.return_value = search_results if search_results is not None else [{"id": "msg-1"}]
        return client

    @patch("mail.outlook.commands.get_outlook_client")
    def test_returns_nonzero_on_client_error(self, mock_get_client):
        from mail.outlook.commands import run_outlook_messages_summarize
        mock_get_client.return_value = (None, 2)

        result = run_outlook_messages_summarize(self._make_args())
        self.assertEqual(result, 2)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_returns_one_without_id_or_query(self, mock_get_client):
        from mail.outlook.commands import run_outlook_messages_summarize
        mock_get_client.return_value = (self._mock_client(), 0)

        with patch("sys.stdout", new_callable=StringIO):
            result = run_outlook_messages_summarize(self._make_args(id=None, query=None))
        self.assertEqual(result, 1)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_summarizes_by_id(self, mock_get_client):
        from mail.outlook.commands import run_outlook_messages_summarize
        client = self._mock_client()
        mock_get_client.return_value = (client, 0)

        with patch("sys.stdout", new_callable=StringIO) as out:
            result = run_outlook_messages_summarize(self._make_args(id="msg-1"))

        self.assertEqual(result, 0)
        client.get_message.assert_called_once_with("msg-1", select_body=True)
        self.assertIn("Test Subject", out.getvalue())

    @patch("mail.outlook.commands.get_outlook_client")
    def test_summarizes_by_query(self, mock_get_client):
        from mail.outlook.commands import run_outlook_messages_summarize
        client = self._mock_client()
        mock_get_client.return_value = (client, 0)

        with patch("sys.stdout", new_callable=StringIO) as out:
            result = run_outlook_messages_summarize(self._make_args(query="test subject"))

        self.assertEqual(result, 0)
        client.search_messages.assert_called_once()
        client.get_message.assert_called_once_with("msg-1", select_body=True)
        self.assertIn("Test Subject", out.getvalue())

    @patch("mail.outlook.commands.get_outlook_client")
    def test_returns_one_when_no_search_results(self, mock_get_client):
        from mail.outlook.commands import run_outlook_messages_summarize
        client = self._mock_client(search_results=[])
        mock_get_client.return_value = (client, 0)

        with patch("sys.stdout", new_callable=StringIO):
            result = run_outlook_messages_summarize(self._make_args(query="nothing"))
        self.assertEqual(result, 1)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_strips_html_from_body(self, mock_get_client):
        from mail.outlook.commands import run_outlook_messages_summarize
        client = self._mock_client(message={
            "id": "m1", "subject": "HTML Test", "receivedDateTime": "2026-01-01T00:00:00Z",
            "from": {"emailAddress": {"name": "A", "address": "a@b.com"}},
            "body": {"content": "<html><body><p>Plain text content here.</p></body></html>"},
        })
        mock_get_client.return_value = (client, 0)

        with patch("sys.stdout", new_callable=StringIO) as out:
            run_outlook_messages_summarize(self._make_args(id="m1"))

        output = out.getvalue()
        self.assertNotIn("<html>", output)
        self.assertIn("Plain text content", output)


# ---------------------------------------------------------------------------
# Tests: run_outlook_rules_prune_empty
# ---------------------------------------------------------------------------

class TestRunOutlookRulesPruneEmpty(unittest.TestCase):
    """Tests for the run_outlook_rules_prune_empty CLI handler."""

    def _make_args(self, **kwargs):
        defaults = dict(
            dry_run=False,
            client_id="client-123",
            tenant="common",
            token=None,
            accounts_config=None,
            account=None,
            profile=None,
            cache_dir=None,
            cache=None,
        )
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_returns_nonzero_on_client_error(self, mock_get_client):
        from mail.outlook.commands import run_outlook_rules_prune_empty
        mock_get_client.return_value = (None, 2)

        result = run_outlook_rules_prune_empty(self._make_args())
        self.assertEqual(result, 2)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_no_empty_rules_reports_zero_deleted(self, mock_get_client):
        from mail.outlook.commands import run_outlook_rules_prune_empty
        client = MagicMock()
        client.list_filters.return_value = [
            {"id": "r1", "criteria": {"from": "x@y.com"}, "action": {"addLabelIds": ["Label"]}},
        ]
        mock_get_client.return_value = (client, 0)

        with patch("sys.stdout", new_callable=StringIO) as out:
            result = run_outlook_rules_prune_empty(self._make_args())

        self.assertEqual(result, 0)
        self.assertIn("No empty rules found", out.getvalue())
        client.delete_filter.assert_not_called()

    @patch("mail.outlook.commands.get_outlook_client")
    def test_deletes_empty_rules(self, mock_get_client):
        from mail.outlook.commands import run_outlook_rules_prune_empty
        client = MagicMock()
        client.list_filters.return_value = [
            {"id": "r1", "criteria": {}, "action": {}},
            {"id": "r2", "criteria": {"from": "x@y.com"}, "action": {"addLabelIds": ["Label"]}},
        ]
        mock_get_client.return_value = (client, 0)

        with patch("sys.stdout", new_callable=StringIO) as out:
            result = run_outlook_rules_prune_empty(self._make_args())

        self.assertEqual(result, 0)
        client.delete_filter.assert_called_once_with("r1")
        self.assertIn("Deleted 1 empty rule", out.getvalue())

    @patch("mail.outlook.commands.get_outlook_client")
    def test_dry_run_does_not_delete(self, mock_get_client):
        from mail.outlook.commands import run_outlook_rules_prune_empty
        client = MagicMock()
        client.list_filters.return_value = [
            {"id": "r1", "criteria": {}, "action": {}},
        ]
        mock_get_client.return_value = (client, 0)

        with patch("sys.stdout", new_callable=StringIO) as out:
            result = run_outlook_rules_prune_empty(self._make_args(dry_run=True))

        self.assertEqual(result, 0)
        client.delete_filter.assert_not_called()
        self.assertIn("Would delete", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
