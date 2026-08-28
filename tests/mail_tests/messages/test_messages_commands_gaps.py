"""Gap coverage for mail.messages_cli.commands.

Covers paths not exercised by existing tests:
- _fetch_id_and_thread exception fallback
- _outlook_search_processor RuntimeError path
- _run_outlook_summarize: no-id/no-query, query-search, fetch-failure, summary prefix
- _fetch_message_record: get_message failure, get_message_text failure
- run_messages_get: Outlook RuntimeError, empty resolution after selector
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from tests.fixtures import capture_stdout
from tests.mail_tests.fixtures import make_args
from mail.messages_cli.commands import (
    _fetch_id_and_thread,
    _fetch_message_record,
    run_messages_get,
    run_messages_summarize,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _outlook_get_args(**overrides):
    """Build args that force the Outlook dispatch path."""
    defaults = {
        "id": "OLK1",
        "ids": None,
        "query": None,
        "days": None,
        "only_inbox": False,
        "format": "text",
        "profile": "outlook_personal",
    }
    defaults.update(overrides)
    return make_args(**defaults)


def _gmail_get_args(**overrides):
    """Build args for the Gmail dispatch path."""
    defaults = {
        "id": "MSG1",
        "ids": None,
        "query": None,
        "days": None,
        "only_inbox": False,
        "format": "text",
        "profile": None,
    }
    defaults.update(overrides)
    return make_args(**defaults)


def _outlook_summarize_args(**overrides):
    """Build args for the Outlook summarize path."""
    defaults = {
        "id": None,
        "query": None,
        "days": None,
        "only_inbox": False,
        "max_words": 40,
        "out": None,
        "profile": "outlook_personal",
    }
    defaults.update(overrides)
    return make_args(**defaults)


# ---------------------------------------------------------------------------
# _fetch_id_and_thread
# ---------------------------------------------------------------------------


class FetchIdAndThreadTests(unittest.TestCase):
    """The exception fallback in _fetch_id_and_thread returns (message_id, None)."""

    def test_happy_path_returns_id_and_thread(self):
        client = MagicMock()
        client.get_message.return_value = {"id": "MSG1", "threadId": "THREAD1"}
        mid, tid = _fetch_id_and_thread(client, "MSG1")
        self.assertEqual(mid, "MSG1")
        self.assertEqual(tid, "THREAD1")

    def test_exception_falls_back_to_bare_id(self):
        """When get_message raises, return (message_id, None) not crash."""
        client = MagicMock()
        client.get_message.side_effect = Exception("network error")
        mid, tid = _fetch_id_and_thread(client, "MSG1")
        self.assertEqual(mid, "MSG1")
        self.assertIsNone(tid)


# ---------------------------------------------------------------------------
# _fetch_message_record (Gmail) error paths
# ---------------------------------------------------------------------------


class FetchMessageRecordErrorTests(unittest.TestCase):
    """Error paths in _fetch_message_record write to stderr and return None."""

    def test_get_message_failure_returns_none(self):
        """If client.get_message raises, _fetch_message_record returns None."""
        client = MagicMock()
        client.get_message.side_effect = Exception("metadata fetch failed")

        result = _fetch_message_record(client, "MSG1")

        self.assertIsNone(result)

    def test_get_message_text_failure_returns_none(self):
        """If client.get_message_text raises, _fetch_message_record returns None."""
        client = MagicMock()
        client.get_message.return_value = {
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Hi"},
                    {"name": "From", "value": "a@b.com"},
                ]
            }
        }
        client.get_message_text.side_effect = Exception("decode error")

        result = _fetch_message_record(client, "MSG1")

        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# run_messages_get — Outlook branch error paths
# ---------------------------------------------------------------------------


class MessagesGetOutlookErrorTests(unittest.TestCase):
    """`run_messages_get` Outlook error paths not covered by test_messages_get_outlook."""

    def test_outlook_client_build_failure_returns_1(self):
        """RuntimeError from outlook_client_from_args returns exit code 1."""
        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True), \
             patch("mail.utils.cli_helpers.outlook_client_from_args",
                   side_effect=RuntimeError("MSAL config missing")):
            with capture_stdout():
                rc = run_messages_get(_outlook_get_args())
        self.assertEqual(rc, 1)

    def test_empty_resolution_after_selector_returns_1(self):
        """When the resolved id list is empty (e.g. query found nothing), return 1."""
        client = MagicMock()
        # get_message raises so _fetch_outlook_message_record returns None
        client.get_message.side_effect = Exception("not found")

        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True), \
             patch("mail.utils.cli_helpers.outlook_client_from_args", return_value=client):
            with capture_stdout():
                rc = run_messages_get(_outlook_get_args(id="MISSING_ID"))
        # record list is empty → return 1
        self.assertEqual(rc, 1)

    def test_no_selector_returns_1_for_gmail_path(self):
        """No --id, --ids, or --query on Gmail path returns 1 immediately."""
        client = MagicMock()
        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=False), \
             patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            with capture_stdout():
                rc = run_messages_get(_gmail_get_args(id=None, ids=None, query=None))
        self.assertEqual(rc, 1)

    def test_query_resolves_to_no_id_returns_1(self):
        """When --query resolves to nothing, the second empty-ids guard fires."""
        client = MagicMock()
        client.authenticate.return_value = None
        # list_message_ids returns nothing, so select_message_id yields (None, None)
        client.list_message_ids.return_value = []

        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=False), \
             patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            with capture_stdout():
                rc = run_messages_get(_gmail_get_args(id=None, ids=None, query="subject:nothing"))
        self.assertEqual(rc, 1)


# ---------------------------------------------------------------------------
# run_messages_summarize — Outlook branch
# ---------------------------------------------------------------------------


class OutlookSummarizePathTests(unittest.TestCase):
    """`_run_outlook_summarize` paths beyond the happy path already in test_messages_get_outlook."""

    def test_no_id_no_query_returns_1(self):
        """Missing both --id and --query prints an error and returns 1."""
        client = MagicMock()

        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True), \
             patch("mail.utils.cli_helpers.outlook_client_from_args", return_value=client):
            with capture_stdout():
                rc = run_messages_summarize(_outlook_summarize_args(id=None, query=None))

        self.assertEqual(rc, 1)

    def test_query_with_no_results_returns_1(self):
        """When a query search returns no messages, return 1."""
        client = MagicMock()
        client.search_inbox_message_dicts.return_value = []

        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True), \
             patch("mail.utils.cli_helpers.outlook_client_from_args", return_value=client):
            with capture_stdout():
                rc = run_messages_summarize(_outlook_summarize_args(id=None, query="orphan query"))

        self.assertEqual(rc, 1)

    def test_query_resolves_and_summarizes(self):
        """When a query finds a message, summarize it and return 0."""
        client = MagicMock()
        client.search_inbox_message_dicts.return_value = [{"id": "OLK2"}]
        client.get_message.return_value = {
            "id": "OLK2",
            "subject": "Found",
            "body": {"contentType": "text", "content": "Plain text body."},
        }

        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True), \
             patch("mail.utils.cli_helpers.outlook_client_from_args", return_value=client), \
             patch("mail.llm_adapter.summarize_text", return_value="Plain text body."):
            with capture_stdout() as buf:
                rc = run_messages_summarize(_outlook_summarize_args(id=None, query="report"))

        self.assertEqual(rc, 0)
        self.assertIn("Summary", buf.getvalue())
        client.search_inbox_message_dicts.assert_called_once()

    def test_get_message_failure_returns_1(self):
        """If get_message raises after id is resolved, return 1."""
        client = MagicMock()
        client.get_message.side_effect = Exception("fetch failed")

        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True), \
             patch("mail.utils.cli_helpers.outlook_client_from_args", return_value=client):
            with capture_stdout():
                rc = run_messages_summarize(_outlook_summarize_args(id="OLK_BAD"))

        self.assertEqual(rc, 1)

    def test_summary_already_prefixed_not_doubled(self):
        """If summarize_text returns a string starting with 'Summary:', don't prepend again."""
        client = MagicMock()
        client.get_message.return_value = {
            "id": "OLK3",
            "subject": "Test",
            "body": {"contentType": "text", "content": "Details."},
        }

        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True), \
             patch("mail.utils.cli_helpers.outlook_client_from_args", return_value=client), \
             patch("mail.llm_adapter.summarize_text", return_value="Summary: already prefixed"):
            with capture_stdout() as buf:
                rc = run_messages_summarize(_outlook_summarize_args(id="OLK3"))

        self.assertEqual(rc, 0)
        out = buf.getvalue()
        # Should not appear as "Summary: Summary: already prefixed"
        self.assertNotIn("Summary: Summary:", out)
        self.assertIn("Summary: already prefixed", out)

    def test_outlook_client_build_failure_returns_1(self):
        """RuntimeError from outlook_client_from_args in summarize path returns 1."""
        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True), \
             patch("mail.utils.cli_helpers.outlook_client_from_args",
                   side_effect=RuntimeError("MSAL config error")):
            with capture_stdout():
                rc = run_messages_summarize(_outlook_summarize_args(id="OLK1"))
        self.assertEqual(rc, 1)


# ---------------------------------------------------------------------------
# _outlook_search_processor error path
# ---------------------------------------------------------------------------


class OutlookSearchProcessorErrorTests(unittest.TestCase):
    """_outlook_search_processor returns None when client construction fails."""

    def test_runtime_error_from_client_returns_none(self):
        """When outlook_client_from_args raises RuntimeError, processor is None."""
        from mail.messages_cli.commands import _outlook_search_processor

        args = make_args(query="swim", profile="outlook_personal")

        with patch("mail.utils.cli_helpers.outlook_client_from_args",
                   side_effect=RuntimeError("missing config")):
            with capture_stdout() as buf:
                processor = _outlook_search_processor(args, query="swim")

        self.assertIsNone(processor)
        # RuntimeError message is printed
        self.assertIn("missing config", buf.getvalue())

    def test_empty_query_returns_none(self):
        """When query is blank, _outlook_search_processor prints and returns None."""
        from mail.messages_cli.commands import _outlook_search_processor

        args = make_args(query="", profile="outlook_personal")

        with capture_stdout() as buf:
            processor = _outlook_search_processor(args, query="   ")

        self.assertIsNone(processor)
        self.assertIn("non-empty", buf.getvalue())

    def test_runtime_error_with_empty_message_does_not_print(self):
        """RuntimeError with an empty message string does not print a blank line."""
        from mail.messages_cli.commands import _outlook_search_processor

        args = make_args(query="test", profile="outlook_personal")

        with patch("mail.utils.cli_helpers.outlook_client_from_args",
                   side_effect=RuntimeError("")):
            with capture_stdout() as buf:
                processor = _outlook_search_processor(args, query="test")

        self.assertIsNone(processor)
        self.assertEqual(buf.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
