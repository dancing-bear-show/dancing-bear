"""Tests for `messages threads-get` and the `messages get` selector flags."""
import json
import unittest
from unittest.mock import patch

from tests.fixtures import capture_stdout
from tests.mail_tests.fixtures import FakeGmailClient, make_args
from mail.messages_cli.commands import parse_id_list, run_messages_get
from mail.messages_cli.commands_threads import (
    ThreadMessage,
    ThreadResult,
    resolve_thread_id,
    run_messages_threads_get,
)
from mail.messages import Candidate
from mail.providers.base import BaseProvider


def _thread_message(msg_id: str, subject: str, *, thread_id: str = "T1") -> dict:
    """One thread message in Gmail's threads().get(format="metadata") shape."""
    return {
        "id": msg_id,
        "threadId": thread_id,
        "snippet": f"snippet for {msg_id}",
        # Epoch ms for 2026-08-10T12:00:00Z, matching the Date header below.
        "internalDate": "1786363200000",
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "headers": [
                {"name": "Date", "value": "Mon, 10 Aug 2026 12:00:00 +0000"},
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "To", "value": "Bob <bob@example.com>"},
                {"name": "Subject", "value": subject},
            ]
        },
        "text": f"body of {msg_id}",
    }


def _threads_client() -> FakeGmailClient:
    """FakeGmailClient with a two-message thread T1."""
    first = _thread_message("M1", "Original")
    second = _thread_message("M2", "Re: Original")
    return FakeGmailClient(
        messages={"M1": first, "M2": second},
        threads={"T1": {"id": "T1", "messages": [first, second]}},
        message_ids_by_query={"": ["M1"]},
    )


class ThreadsGetCLITests(unittest.TestCase):
    def test_threads_get_lists_all_messages_in_thread(self):
        """threads-get prints every message in the conversation."""
        client = _threads_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(thread_id="T1", include_body=False, json=False)
            with capture_stdout() as buf:
                rc = run_messages_threads_get(args)
            out = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("Thread: T1", out)
        self.assertIn("Messages: 2", out)
        self.assertIn("Original", out)
        self.assertIn("Re: Original", out)

    def test_threads_get_json_reuses_candidate_fields(self):
        """JSON output carries the widened Candidate fields (date/to/labels/unread)."""
        client = _threads_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(thread_id="T1", include_body=False, json=True)
            with capture_stdout() as buf:
                rc = run_messages_threads_get(args)
            data = json.loads(buf.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(data["thread_id"], "T1")
        self.assertEqual(data["message_count"], 2)
        first = data["messages"][0]
        self.assertEqual(first["to_header"], "Bob <bob@example.com>")
        self.assertEqual(first["date"], "2026-08-10T12:00:00Z")
        self.assertIn("INBOX", first["labels"])
        self.assertTrue(first["unread"])
        self.assertNotIn("body", first)

    def test_threads_get_include_body_adds_bodies(self):
        """--include-body pulls each message body."""
        client = _threads_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(thread_id="T1", include_body=True, json=True)
            with capture_stdout() as buf:
                rc = run_messages_threads_get(args)
            data = json.loads(buf.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(data["messages"][0]["body"], "body of M1")
        self.assertEqual(data["messages"][1]["body"], "body of M2")

    def test_threads_get_resolves_thread_from_message_id(self):
        """--id resolves to the owning thread."""
        client = _threads_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(thread_id=None, id="M1", include_body=False, json=True)
            with capture_stdout() as buf:
                rc = run_messages_threads_get(args)
            data = json.loads(buf.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(data["thread_id"], "T1")

    def test_threads_get_resolves_thread_from_query(self):
        """--query resolves to the first matching message's thread."""
        client = _threads_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(
                thread_id=None, id=None, query="from:alice", days=None,
                only_inbox=False, include_body=False, json=True,
            )
            with capture_stdout() as buf:
                rc = run_messages_threads_get(args)
            data = json.loads(buf.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(data["thread_id"], "T1")

    def test_threads_get_without_selector_returns_error(self):
        """No thread-id/id/query exits 1."""
        client = _threads_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(thread_id=None, id=None, query=None, include_body=False, json=False)
            with capture_stdout():
                rc = run_messages_threads_get(args)

        self.assertEqual(rc, 1)

    def test_threads_get_not_found_returns_one_not_six(self):
        """Thread-not-found collapses to exit 1, matching the rest of the group."""
        client = _threads_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(thread_id="NOPE", include_body=False, json=False)
            with capture_stdout():
                rc = run_messages_threads_get(args)

        self.assertEqual(rc, 1)

    def test_threads_get_rejects_outlook_profile(self):
        """Outlook profiles are unsupported -> exit 1."""
        client = _threads_client()
        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True), \
                patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(profile="outlook_personal", thread_id="T1", include_body=False, json=False)
            with capture_stdout():
                rc = run_messages_threads_get(args)

        self.assertEqual(rc, 1)

    def test_resolve_thread_id_prefers_explicit_thread_id(self):
        """An explicit --thread-id short-circuits message lookup."""
        client = _threads_client()
        args = make_args(thread_id="T_EXPLICIT", id="M1")
        self.assertEqual(resolve_thread_id(args, client), "T_EXPLICIT")


class BaseProviderThreadTests(unittest.TestCase):
    def test_get_thread_is_not_abstract(self):
        """get_thread must stay non-abstract so OutlookProvider can instantiate."""
        self.assertNotIn("get_thread", BaseProvider.__abstractmethods__)

    def test_outlook_provider_still_instantiates(self):
        """Regression: adding get_thread must not break OutlookProvider construction."""
        from mail.providers.outlook import OutlookProvider

        # token_path is never read: the test only constructs the provider and
        # calls get_thread, neither of which authenticates.
        provider = OutlookProvider(client_id="fake-client-id", token_path="")  # nosec B106 - empty path, not a credential
        with self.assertRaises(NotImplementedError):
            provider.get_thread("T1")


class ThreadDataclassTests(unittest.TestCase):
    def test_thread_message_wraps_candidate_without_dropping_fields(self):
        """ThreadMessage composes Candidate rather than re-declaring its fields."""
        cand = Candidate(
            id="M1", thread_id="T1", from_header="a@b.c", subject="S",
            snippet="snip", to_header="d@e.f", date="2026-08-10T12:00:00Z",
            labels=["INBOX"], unread=True,
        )
        payload = ThreadMessage(candidate=cand, body="hi").to_dict(include_body=True)
        self.assertEqual(payload["to_header"], "d@e.f")
        self.assertEqual(payload["date"], "2026-08-10T12:00:00Z")
        self.assertEqual(payload["labels"], ["INBOX"])
        self.assertTrue(payload["unread"])
        self.assertEqual(payload["body"], "hi")

    def test_thread_result_counts_messages(self):
        result = ThreadResult(thread_id="T1", messages=[])
        self.assertEqual(result.to_dict(include_body=False)["message_count"], 0)


class ParseIdListTests(unittest.TestCase):
    def test_splits_strips_and_drops_empties(self):
        self.assertEqual(parse_id_list("A, B ,, C "), ["A", "B", "C"])

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(parse_id_list(None), [])
        self.assertEqual(parse_id_list(""), [])
        self.assertEqual(parse_id_list("  ,  "), [])

    def test_single_id_returns_one_element(self):
        self.assertEqual(parse_id_list("ONLY"), ["ONLY"])


class MessagesGetSelectorTests(unittest.TestCase):
    def _client(self):
        return FakeGmailClient(
            messages={
                "A": _thread_message("A", "Subject A"),
                "B": _thread_message("B", "Subject B"),
            },
            message_ids_by_query={"": ["A"]},
        )

    def test_ids_never_reach_select_message_id_as_a_list(self):
        """Regression: --ids must be normalized before resolution runs.

        A list handed to select_message_id is truthy, gets passed to
        client.get_message, and the swallowed exception makes it return the list
        object itself as the message id -- a silent wrong answer. --ids must
        therefore bypass select_message_id entirely.
        """
        client = self._client()
        seen_ids = []
        real_get_message = client.get_message

        def recording_get_message(msg_id, fmt="full"):
            seen_ids.append(msg_id)
            return real_get_message(msg_id, fmt=fmt)

        client.get_message = recording_get_message

        with patch("mail.messages_cli.commands.select_message_id") as sel, \
                patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(id=None, ids="A,B", query=None, format="json")
            with capture_stdout():
                rc = run_messages_get(args)

        self.assertEqual(rc, 0)
        sel.assert_not_called()
        self.assertEqual(seen_ids, ["A", "B"])
        for seen in seen_ids:
            self.assertIsInstance(seen, str)

    def test_ids_multi_emits_json_list(self):
        """Multiple ids produce a JSON array."""
        client = self._client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(id=None, ids="A,B", query=None, format="json")
            with capture_stdout() as buf:
                rc = run_messages_get(args)
            data = json.loads(buf.getvalue())

        self.assertEqual(rc, 0)
        self.assertIsInstance(data, list)
        self.assertEqual([d["id"] for d in data], ["A", "B"])

    def test_single_id_still_emits_bare_json_object(self):
        """Backwards compatibility: one id keeps the object shape, not a list."""
        client = self._client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(id="A", ids=None, query=None, format="json")
            with capture_stdout() as buf:
                rc = run_messages_get(args)
            data = json.loads(buf.getvalue())

        self.assertEqual(rc, 0)
        self.assertIsInstance(data, dict)
        self.assertEqual(data["id"], "A")

    def test_get_resolves_message_from_query(self):
        """--query resolves a single message when --id/--ids are absent."""
        client = self._client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(
                id=None, ids=None, query="from:alice", days=None,
                only_inbox=False, format="json",
            )
            with capture_stdout() as buf:
                rc = run_messages_get(args)
            data = json.loads(buf.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(data["id"], "A")

    def test_no_selector_returns_one(self):
        """Dropping required=True must not lose the missing-selector guard."""
        client = self._client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(id=None, ids=None, query=None, format="text")
            with capture_stdout():
                rc = run_messages_get(args)

        self.assertEqual(rc, 1)

    def test_ids_text_output_separates_messages(self):
        """Text output for multiple ids prints both, separated."""
        client = self._client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(id=None, ids="A,B", query=None, format="text")
            with capture_stdout() as buf:
                rc = run_messages_get(args)
            out = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("Subject: Subject A", out)
        self.assertIn("Subject: Subject B", out)
        self.assertIn("---", out)


if __name__ == "__main__":
    unittest.main()
