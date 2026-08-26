"""Tests for OutlookMailMixin.search_messages and run_outlook_messages_search core behavior."""

from __future__ import annotations

import argparse
import json
import unittest
from io import StringIO
from unittest.mock import MagicMock, Mock, patch


from tests.mail_tests.outlook.fixtures import make_graph_message, make_response


class TestSearchMessages(unittest.TestCase):
    """Unit tests for OutlookMailMixin.search_messages URL construction and result parsing."""

    def _make_client(self):
        from core.outlook.mail import OutlookMailMixin
        client = MagicMock()
        client._headers_search.return_value = {"Authorization": "Bearer token", "ConsistencyLevel": "eventual"}
        client.GRAPH = "https://graph.microsoft.com/v1.0"
        client.search_messages = OutlookMailMixin.search_messages.__get__(client)
        return client

    @patch("core.outlook.mail._requests")
    def test_query_wraps_in_kql_quotes(self, mock_requests):
        """query param should produce $search=%22<query>%22."""
        client = self._make_client()
        mock_requests.return_value.get.return_value = make_response([])

        client.search_messages(query="brightchamps", top=10, pages=1)

        url = mock_requests.return_value.get.call_args[0][0]
        self.assertIn("%22brightchamps%22", url)

    @patch("core.outlook.mail._requests")
    def test_sender_uses_kql_from_prefix(self, mock_requests):
        """sender param should produce $search=%22from:<sender>%22."""
        client = self._make_client()
        mock_requests.return_value.get.return_value = make_response([])

        client.search_messages(query="", sender="brightchamps.com", top=10, pages=1)

        url = mock_requests.return_value.get.call_args[0][0]
        self.assertIn("from%3Abrightchamps.com", url)

    @patch("core.outlook.mail._requests")
    def test_result_fields_mapped_correctly(self, mock_requests):
        client = self._make_client()
        msg = make_graph_message(
            id="abc", subject="Test", received="2026-03-01T21:00:00Z",
            from_name="BrightCHAMPS", from_addr="noreply@brightchamps.com",
            preview="Hello", has_attachments=True,
        )
        mock_requests.return_value.get.return_value = make_response([msg])

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
        old_msg = make_graph_message(id="old", received="2025-12-31T20:00:00Z")
        new_msg = make_graph_message(id="new", received="2026-01-15T20:00:00Z")
        mock_requests.return_value.get.return_value = make_response([old_msg, new_msg])

        results = client.search_messages(query="test", top=10, pages=1, after="2026-01-01")

        ids = [r["id"] for r in results]
        self.assertNotIn("old", ids)
        self.assertIn("new", ids)

    @patch("core.outlook.mail._requests")
    def test_after_filter_applied_when_sender_set(self, mock_requests):
        """after filter applies client-side even when sender is set."""
        client = self._make_client()
        old_msg = make_graph_message(id="old", received="2025-12-31T20:00:00Z")
        new_msg = make_graph_message(id="new", received="2026-01-15T20:00:00Z")
        mock_requests.return_value.get.return_value = make_response([old_msg, new_msg])

        results = client.search_messages(query="", sender="example.com", top=10, pages=1, after="2026-01-01")

        ids = [r["id"] for r in results]
        self.assertNotIn("old", ids)
        self.assertIn("new", ids)

    @patch("core.outlook.mail._requests")
    def test_pagination_follows_next_link(self, mock_requests):
        """Should follow @odata.nextLink up to pages limit."""
        client = self._make_client()
        page1_msg = make_graph_message(id="p1")
        page2_msg = make_graph_message(id="p2")

        mock_get = mock_requests.return_value.get
        mock_get.side_effect = [
            make_response([page1_msg], next_link="https://graph.microsoft.com/v1.0/me/messages?$skip=10"),
            make_response([page2_msg]),
        ]

        results = client.search_messages(query="test", top=10, pages=2)

        self.assertEqual(len(results), 2)
        self.assertEqual(mock_get.call_count, 2)

    @patch("core.outlook.mail._requests")
    def test_pagination_stops_at_pages_limit(self, mock_requests):
        """Should not fetch more pages than specified."""
        client = self._make_client()
        msg = make_graph_message(id="p1")

        mock_get = mock_requests.return_value.get
        mock_get.return_value = make_response([msg], next_link="https://graph.microsoft.com/next")

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
        mock_requests.return_value.get.return_value = make_response([])

        results = client.search_messages(query="nothing", top=10, pages=1)

        self.assertEqual(results, [])

    @patch("core.outlook.mail._requests")
    def test_top_included_in_url(self, mock_requests):
        client = self._make_client()
        mock_requests.return_value.get.return_value = make_response([])

        client.search_messages(query="test", top=25, pages=1)

        url = mock_requests.return_value.get.call_args[0][0]
        self.assertIn("$top=25", url)

    @patch("core.outlook.mail._requests")
    def test_uses_search_headers(self, mock_requests):
        """Should use _headers_search() (includes ConsistencyLevel: eventual)."""
        client = self._make_client()
        mock_requests.return_value.get.return_value = make_response([])

        client.search_messages(query="test", top=10, pages=1)

        headers = mock_requests.return_value.get.call_args[1]["headers"]
        self.assertIn("ConsistencyLevel", headers)


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


if __name__ == "__main__":
    unittest.main()
