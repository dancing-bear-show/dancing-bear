"""Tests for messages search pagination and structured query flags.

Covers the pagination fix (max_pages=0 cursor exhaustion, page_size decoupled
from max_results), the structured criteria flags that feed build_gmail_query,
the Outlook rejection path, and the FROZEN text/JSON output contracts.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tests.fixtures import capture_stdout
from tests.mail_tests.fixtures import make_args
from mail.messages_cli.commands import run_messages_search
from mail.messages_cli.pipeline import (
    MessagesSearchRequest,
    search_request_to_criteria,
)


class RecordingGmailClient:
    """Gmail client fake that records list_message_ids kwargs verbatim.

    The shared FakeGmailClient swallows pagination kwargs via **kwargs, so
    pagination assertions need a fake that preserves them.
    """

    def __init__(self, ids=None, messages=None):
        self._ids = list(ids or [])
        self._messages = messages or {}
        self.calls: list[dict] = []

    def authenticate(self) -> None:
        """No-op: tests do not authenticate."""

    def list_message_ids(self, query=None, label_ids=None, max_pages=1, page_size=500):
        self.calls.append({
            "query": query,
            "label_ids": label_ids,
            "max_pages": max_pages,
            "page_size": page_size,
        })
        return list(self._ids)

    def get_messages_metadata(self, ids, use_cache=True):
        return [self._messages.get(mid, {"id": mid}) for mid in ids]


def _message(mid: str, *, subject="Subject", sender="s@example.com", to="r@example.com",
             snippet="Snippet", labels=None, internal_date="1700000000000"):
    return {
        "id": mid,
        "threadId": f"T{mid}",
        "snippet": snippet,
        "internalDate": internal_date,
        "labelIds": list(labels or ["INBOX"]),
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "To", "value": to},
                {"name": "Subject", "value": subject},
            ]
        },
    }


def _search_args(**kwargs):
    """Build search args with all structured flags defaulted off."""
    defaults = {
        "query": "",
        "days": None,
        "only_inbox": False,
        "max_results": 5,
        "json": False,
        "from_": None,
        "to": None,
        "subject_contains": None,
        "not_query": None,
        "has_attachment": False,
        "unread": False,
    }
    defaults.update(kwargs)
    return make_args(**defaults)


def _run_gmail_search(client, **arg_overrides):
    """Run a Gmail search against the given client, returning (rc, stdout)."""
    with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client), \
         patch("mail.utils.cli_helpers.is_outlook_profile", return_value=False):
        with capture_stdout() as buf:
            rc = run_messages_search(_search_args(**arg_overrides))
    return rc, buf.getvalue()


class SearchCriteriaTests(unittest.TestCase):
    """search_request_to_criteria maps request fields onto build_gmail_query keys."""

    def test_empty_request_yields_no_criteria(self):
        crit = search_request_to_criteria(MessagesSearchRequest(query=""))
        self.assertEqual(crit, {})

    def test_maps_each_flag_to_its_criteria_key(self):
        crit = search_request_to_criteria(MessagesSearchRequest(
            query="report",
            from_="a@example.com",
            to="b@example.com",
            subject_contains="invoice",
            not_query="spam",
            has_attachment=True,
        ))
        self.assertEqual(crit, {
            "query": "report",
            "from": "a@example.com",
            "to": "b@example.com",
            "subject": "invoice",
            "negatedQuery": "spam",
            "hasAttachment": True,
        })

    def test_false_has_attachment_is_omitted(self):
        crit = search_request_to_criteria(
            MessagesSearchRequest(query="x", has_attachment=False)
        )
        self.assertNotIn("hasAttachment", crit)

    def test_unread_is_not_a_criteria_key(self):
        """unread is appended as is:unread, never passed to build_gmail_query."""
        crit = search_request_to_criteria(MessagesSearchRequest(query="x", unread=True))
        self.assertNotIn("unread", crit)


class SearchPaginationTests(unittest.TestCase):
    def test_exhausts_cursor_and_decouples_page_size(self):
        client = RecordingGmailClient(ids=["M1"], messages={"M1": _message("M1")})
        rc, _ = _run_gmail_search(client, query="hello", max_results=5)

        self.assertEqual(rc, 0)
        call = client.calls[0]
        # max_pages=0 is falsy, so gather_pages never breaks -> full exhaustion.
        self.assertEqual(call["max_pages"], 0)
        # page_size floors at 100 rather than tracking a small max_results.
        self.assertEqual(call["page_size"], 100)

    def test_large_max_results_raises_page_size_to_cap(self):
        client = RecordingGmailClient(ids=["M1"], messages={"M1": _message("M1")})
        _run_gmail_search(client, query="hello", max_results=900)
        self.assertEqual(client.calls[0]["page_size"], 500)

    def test_results_are_truncated_to_max_results(self):
        ids = [f"M{i}" for i in range(10)]
        messages = {mid: _message(mid) for mid in ids}
        client = RecordingGmailClient(ids=ids, messages=messages)

        rc, out = _run_gmail_search(client, query="hello", max_results=3, json=True)

        self.assertEqual(rc, 0)
        self.assertEqual(len(json.loads(out)), 3)


class SearchQueryBuildingTests(unittest.TestCase):
    def _query_for(self, **overrides) -> str:
        client = RecordingGmailClient(ids=[])
        _run_gmail_search(client, **overrides)
        return client.calls[0]["query"]

    def test_structured_flags_become_gmail_operators(self):
        q = self._query_for(
            query="report",
            from_="a@example.com",
            to="b@example.com",
            subject_contains="invoice",
            not_query="spam",
            has_attachment=True,
        )
        self.assertIn("from:(a@example.com)", q)
        self.assertIn("to:(b@example.com)", q)
        self.assertIn("subject:invoice", q)
        self.assertIn("-(spam)", q)
        self.assertIn("has:attachment", q)
        self.assertIn("report", q)

    def test_multiword_subject_is_quoted(self):
        q = self._query_for(subject_contains="quarterly report")
        self.assertIn('subject:"quarterly report"', q)

    def test_unread_appends_is_unread(self):
        self.assertIn("is:unread", self._query_for(query="hello", unread=True))

    def test_unread_alone_does_not_leave_leading_space(self):
        self.assertEqual(self._query_for(unread=True), "is:unread")

    def test_no_flags_yields_empty_query(self):
        self.assertEqual(self._query_for(), "")

    def test_days_and_only_inbox_still_apply(self):
        q = self._query_for(query="hello", days=7, only_inbox=True)
        self.assertIn("newer_than:7d", q)
        self.assertIn("in:inbox", q)


class SearchOutputContractTests(unittest.TestCase):
    """The text shape is FROZEN; new fields are JSON-only and JSON stays a bare array."""

    def _run(self, *, json_output: bool) -> str:
        client = RecordingGmailClient(
            ids=["M1"],
            messages={"M1": _message(
                "M1",
                subject="Hello",
                sender="Sender <sender@example.com>",
                to="Me <me@example.com>",
                snippet="Snippet here",
                labels=["INBOX", "UNREAD"],
            )},
        )
        _, out = _run_gmail_search(client, query="hello", json=json_output)
        return out

    def test_text_output_is_four_tab_separated_columns(self):
        line = self._run(json_output=False).strip()
        self.assertEqual(
            line, "M1\tHello\tSender <sender@example.com>\tSnippet here"
        )
        self.assertEqual(len(line.split("\t")), 4)

    def test_text_output_omits_new_fields(self):
        out = self._run(json_output=False)
        for leaked in ("me@example.com", "UNREAD", "2023-"):
            self.assertNotIn(leaked, out)

    def test_json_output_is_a_bare_array(self):
        payload = json.loads(self._run(json_output=True))
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 1)

    def test_json_output_carries_new_fields(self):
        row = json.loads(self._run(json_output=True))[0]
        self.assertEqual(row["id"], "M1")
        self.assertEqual(row["to_header"], "Me <me@example.com>")
        self.assertTrue(row["unread"])
        self.assertIn("UNREAD", row["labels"])
        self.assertTrue(row["date"].endswith("Z"))


class SearchOutlookGuardTests(unittest.TestCase):
    def _run_outlook(self, **overrides):
        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True):
            with capture_stdout() as buf:
                rc = run_messages_search(
                    _search_args(profile="outlook_vanesa", **overrides)
                )
        return rc, buf.getvalue()

    def test_structured_flag_rejected_for_outlook(self):
        rc, out = self._run_outlook(query="swim", from_="a@example.com")
        self.assertEqual(rc, 1)
        self.assertIn("--from", out)
        self.assertIn("Gmail-only", out)

    def test_every_structured_flag_is_rejected(self):
        for override in (
            {"from_": "a@example.com"},
            {"to": "b@example.com"},
            {"subject_contains": "invoice"},
            {"not_query": "spam"},
            {"has_attachment": True},
            {"unread": True},
        ):
            with self.subTest(flag=next(iter(override))):
                rc, _ = self._run_outlook(query="swim", **override)
                self.assertEqual(rc, 1)

    def test_outlook_search_single_api_call(self):
        """End-to-end N+1 guard: one search call, zero per-message fetches.

        TestOutlookSearchAvoidsNPlusOne covers this at the processor level by
        calling _process_safe directly. This asserts the same contract through
        run_messages_search, so a revert that reintroduces a per-message fetch
        in the COMMAND path (not the processor) still fails.
        """
        from unittest.mock import MagicMock

        client = MagicMock()
        client.search_inbox_message_dicts.return_value = [
            {
                "id": f"OLK{i}",
                "subject": f"Subject {i}",
                "from": {"emailAddress": {"name": "Alice", "address": "alice@outlook.com"}},
                "bodyPreview": "Preview text",
            }
            # More rows than max_results, so the ceiling slice is exercised too.
            for i in range(5)
        ]

        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True), \
             patch("mail.utils.cli_helpers.outlook_client_from_args", return_value=client):
            with capture_stdout() as buf:
                rc = run_messages_search(
                    _search_args(query="swim", profile="outlook_vanesa", max_results=3)
                )

        self.assertEqual(rc, 0)
        # Negative side: no per-message round trip, under any name.
        self.assertEqual(client.get_message.call_count, 0)
        self.assertEqual(client.get_messages_metadata.call_count, 0)
        # Positive side: exactly one search, so a different N+1 cannot pass.
        self.assertEqual(client.search_inbox_message_dicts.call_count, 1)
        self.assertEqual(len(buf.getvalue().strip().splitlines()), 3)

    def test_plain_outlook_search_is_unaffected(self):
        """Without structured flags, Outlook search proceeds to the normal path."""
        # search_inbox_message_dicts returns fully-$selected rows, so the
        # processor builds candidates without any per-message get_message.
        fake_client = type("FakeOutlookClient", (), {
            "search_inbox_message_dicts": lambda self, params: [{
                "id": "OLK1",
                "subject": "Outlook Subject",
                "from": {"emailAddress": {"name": "Alice", "address": "alice@outlook.com"}},
                "bodyPreview": "Preview text",
            }],
        })()
        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True), \
             patch("mail.utils.cli_helpers.outlook_client_from_args", return_value=fake_client):
            with capture_stdout() as buf:
                rc = run_messages_search(_search_args(query="swim", profile="outlook_vanesa"))
        self.assertEqual(rc, 0)
        self.assertIn("Outlook Subject", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
