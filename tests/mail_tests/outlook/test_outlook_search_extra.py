"""Tests for outlook messages search extra — new flags, summarize, and rules prune."""

from __future__ import annotations

import argparse
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

from core.outlook.mail import OutlookMailMixin


from tests.mail_tests.outlook.fixtures import make_response


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
        client = MagicMock()
        client._headers_search.return_value = {"Authorization": "Bearer token", "ConsistencyLevel": "eventual"}
        client.search_messages = OutlookMailMixin.search_messages.__get__(client)

        mock_requests.return_value.get.return_value = make_response([])

        client.search_messages(query="test", top=10, pages=1, only_inbox=True)

        url = mock_requests.return_value.get.call_args[0][0]
        self.assertIn("mailFolders/inbox/messages", url)
        self.assertNotIn("/me/messages", url)

    @patch("core.outlook.mail._requests")
    def test_without_only_inbox_uses_all_messages_path(self, mock_requests):
        """only_inbox=False (default) should use /me/messages URL."""
        client = MagicMock()
        client._headers_search.return_value = {"Authorization": "Bearer token", "ConsistencyLevel": "eventual"}
        client.search_messages = OutlookMailMixin.search_messages.__get__(client)

        mock_requests.return_value.get.return_value = make_response([])

        client.search_messages(query="test", top=10, pages=1)

        url = mock_requests.return_value.get.call_args[0][0]
        self.assertIn("/me/messages", url)
        self.assertNotIn("mailFolders/inbox", url)


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
    unittest.main()
