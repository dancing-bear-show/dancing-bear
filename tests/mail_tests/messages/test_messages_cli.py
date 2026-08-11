import os
import tempfile
import unittest
from unittest.mock import patch

from tests.fixtures import capture_stdout
from tests.mail_tests.fixtures import FakeGmailClient, make_args
from mail.messages_cli.commands import (
    run_messages_search,
    run_messages_summarize,
    run_messages_get,
)
from mail.messages_cli.commands_reply import run_messages_reply


def _make_messages_client():
    """Create a FakeGmailClient configured for messages CLI tests."""
    msg_id = "MSG1"
    thread_id = "THREAD1"
    return FakeGmailClient(
        messages={
            msg_id: {
                "id": msg_id,
                "threadId": thread_id,
                "snippet": "Snippet here",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Sender <sender@example.com>"},
                        {"name": "Subject", "value": "Hello"},
                        {"name": "Message-Id", "value": "<abc@id>"},
                        {"name": "References", "value": "<prev@id>"},
                    ]
                },
                "text": "This is the body of the email. It has some content.",
            }
        },
        message_ids_by_query={"": [msg_id]},  # Return msg_id for any query
    )


class MessagesCLITests(unittest.TestCase):
    def test_messages_search_lists_candidates(self):
        client = _make_messages_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client), \
             patch("mail.utils.cli_helpers.is_outlook_profile", return_value=False):

            args = make_args(
                query="from:sender@example.com",
                days=None,
                only_inbox=False,
                max_results=3,
                json=False,
            )
            with capture_stdout() as buf:
                rc = run_messages_search(args)
            out = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("Hello", out)
        self.assertIn("sender@example.com", out)

    def test_messages_summarize_writes_file(self):
        client = _make_messages_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):

            with tempfile.TemporaryDirectory() as td:
                outp = os.path.join(td, "sum.txt")
                args = make_args(
                    id=None,
                    query="from:sender@example.com",
                    latest=True,
                    days=None,
                    only_inbox=False,
                    out=outp,
                    max_words=30,
                )
                with capture_stdout():
                    rc = run_messages_summarize(args)

                self.assertEqual(rc, 0)
                self.assertTrue(os.path.exists(outp))
                with open(outp, "r", encoding="utf-8") as fh:
                    self.assertIn("Summary", fh.read() or "")

    def test_messages_reply_dry_run_writes_eml(self):
        client = _make_messages_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):

            with tempfile.TemporaryDirectory() as td:
                eml = os.path.join(td, "reply.eml")
                args = make_args(
                    id="MSG1",
                    query=None,
                    days=None,
                    only_inbox=False,
                    latest=False,
                    points="Please confirm receipt.",
                    points_file=None,
                    tone="friendly",
                    signoff="Thanks, Brian",
                    include_summary=False,
                    include_quote=False,
                    cc=[],
                    bcc=[],
                    subject=None,
                    draft_out=eml,
                    apply=False,
                )
                with capture_stdout():
                    rc = run_messages_reply(args)

                self.assertEqual(rc, 0)
                self.assertTrue(os.path.exists(eml))
                self.assertEqual(len(client.sent_messages), 0)

    def test_messages_reply_plan_only(self):
        client = _make_messages_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):

            args = make_args(
                id="MSG1",
                query=None,
                days=None,
                only_inbox=False,
                latest=False,
                points="Plan it",
                points_file=None,
                tone="friendly",
                signoff="Thanks",
                include_summary=False,
                include_quote=False,
                cc=["cc@example.com"],
                bcc=[],
                subject=None,
                draft_out=None,
                apply=False,
                plan=True,
                create_draft=False,
                send_at=None,
                send_in=None,
            )
            with capture_stdout() as buf:
                rc = run_messages_reply(args)
            out = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("Plan: reply", out)
        self.assertIn("to:", out)

    def test_messages_reply_create_draft(self):
        client = _make_messages_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):

            args = make_args(
                id="MSG1",
                query=None,
                days=None,
                only_inbox=False,
                latest=False,
                points="Create a draft",
                points_file=None,
                tone="friendly",
                signoff="Thanks",
                include_summary=False,
                include_quote=False,
                cc=[],
                bcc=[],
                subject=None,
                draft_out=None,
                apply=False,
                plan=False,
                create_draft=True,
                send_at=None,
                send_in=None,
            )
            with capture_stdout() as buf:
                rc = run_messages_reply(args)
            out = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("Created Gmail draft", out)


class MessagesGetCLITests(unittest.TestCase):
    def _make_client(self):
        """FakeGmailClient with one message that has headers and a plain-text body."""
        msg_id = "MSG_GET_1"
        return FakeGmailClient(
            messages={
                msg_id: {
                    "id": msg_id,
                    "threadId": "T1",
                    "snippet": "Short snippet",
                    "payload": {
                        "headers": [
                            {"name": "Date", "value": "Mon, 10 Aug 2026 12:00:00 +0000"},
                            {"name": "From", "value": "Alice <alice@example.com>"},
                            {"name": "To", "value": "Bob <bob@example.com>"},
                            {"name": "Subject", "value": "Hello from Alice"},
                        ]
                    },
                    "text": "Hello Bob, this is the full body.",
                }
            }
        )

    def test_messages_get_format_text(self):
        """get with --format text prints headers then body."""
        client = self._make_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(id="MSG_GET_1", format="text")
            with capture_stdout() as buf:
                rc = run_messages_get(args)
            out = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("From: Alice <alice@example.com>", out)
        self.assertIn("Subject: Hello from Alice", out)
        self.assertIn("Hello Bob, this is the full body.", out)

    def test_messages_get_fetches_headers_as_metadata_only(self):
        """get must not pull the full payload twice.

        The body comes from get_message_text(), which does its own full fetch,
        so the header fetch here should request fmt="metadata".
        """
        client = self._make_client()
        seen_fmts = []
        real_get_message = client.get_message

        def recording_get_message(msg_id, fmt="full"):
            seen_fmts.append(fmt)
            return real_get_message(msg_id, fmt=fmt)

        client.get_message = recording_get_message
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(id="MSG_GET_1", format="text")
            with capture_stdout():
                rc = run_messages_get(args)

        self.assertEqual(rc, 0)
        self.assertEqual(seen_fmts, ["metadata"])

    def test_messages_get_format_json(self):
        """get with --format json emits a JSON object with required fields."""
        import json as _json
        client = self._make_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(id="MSG_GET_1", format="json")
            with capture_stdout() as buf:
                rc = run_messages_get(args)
            out = buf.getvalue()

        self.assertEqual(rc, 0)
        data = _json.loads(out)
        self.assertEqual(data["id"], "MSG_GET_1")
        self.assertEqual(data["subject"], "Hello from Alice")
        self.assertEqual(data["from_header"], "Alice <alice@example.com>")
        self.assertEqual(data["to_header"], "Bob <bob@example.com>")
        self.assertIn("Hello Bob", data["body"])

    def test_messages_get_missing_id_returns_error(self):
        """get without --id exits with rc=1."""
        client = self._make_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(id=None, format="text")
            with capture_stdout():
                rc = run_messages_get(args)

        self.assertEqual(rc, 1)


class MessagesSummarizeRegressionTests(unittest.TestCase):
    """Regression: summarize must use get_message_text, not bodyPreview."""

    def test_summarize_uses_get_message_text_not_body_preview(self):
        """Summarize should return real content, not CSS, for HTML-only messages.

        This test guards against the regression where the summarize pipeline
        read msg.get('bodyPreview') which returns the CSS stylesheet block on
        HTML-only messages (e.g., clinic receipts).  The processor must call
        get_message_text() so plain-text is preferred and HTML is stripped.
        """
        css_body = "/* Client-specific Styles */ #outlook a{padding:0;} body{margin:0;}"
        real_text = "Appointment confirmed: Balance Family Chiropractic. Total: $90.00."
        msg_id = "MSG_HTML_ONLY"
        client = FakeGmailClient(
            messages={
                msg_id: {
                    "id": msg_id,
                    "threadId": "T2",
                    "bodyPreview": css_body,  # what the old code (incorrectly) read
                    "snippet": css_body,
                    "payload": {"headers": []},
                    "text": real_text,  # what get_message_text() returns
                }
            },
            message_ids_by_query={"": [msg_id]},
        )
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(
                id=msg_id,
                query=None,
                days=None,
                only_inbox=False,
                out=None,
                max_words=120,
            )
            with capture_stdout() as buf:
                rc = run_messages_summarize(args)
            out = buf.getvalue()

        self.assertEqual(rc, 0)
        # Must NOT contain CSS — that would mean bodyPreview was used
        self.assertNotIn("Client-specific Styles", out)
        self.assertNotIn("#outlook", out)
        # Must reflect content from get_message_text()
        self.assertIn("Balance Family", out)


class OutlookMessagesCLITests(unittest.TestCase):
    def test_outlook_search_lists_candidates(self):
        """Test Outlook message search via is_outlook_profile=True path."""
        fake_client = type("FakeOutlookClient", (), {
            "search_inbox_messages": lambda self, params: ["OLK1"],
            "get_message": lambda self, mid, select_body=False: {
                "subject": "Outlook Subject",
                "from": {"emailAddress": {"name": "Alice", "address": "alice@outlook.com"}},
                "bodyPreview": "Preview text",
            },
        })()

        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True), \
             patch("mail.utils.cli_helpers.outlook_client_from_args", return_value=fake_client):
            args = make_args(
                query="swim class",
                days=None,
                only_inbox=False,
                max_results=5,
                json=False,
                profile="outlook_vanesa",
            )
            with capture_stdout() as buf:
                rc = run_messages_search(args)
            out = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("Outlook Subject", out)
        self.assertIn("alice@outlook.com", out)

    def test_outlook_search_empty_query_returns_error(self):
        """Outlook search with empty query should fail cleanly."""
        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True):
            args = make_args(
                query="",
                days=None,
                only_inbox=False,
                max_results=5,
                json=False,
                profile="outlook_vanesa",
            )
            with capture_stdout() as buf:
                rc = run_messages_search(args)
            out = buf.getvalue()

        self.assertEqual(rc, 1)
        self.assertIn("non-empty", out)


if __name__ == "__main__":
    unittest.main()
