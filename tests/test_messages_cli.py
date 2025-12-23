import os
import tempfile
import unittest
from unittest.mock import patch

from tests.fixtures import FakeGmailClient, capture_stdout, make_args


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
        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            import mail_assistant.__main__ as m

            args = make_args(
                query="from:sender@example.com",
                days=None,
                only_inbox=False,
                max_results=3,
                json=False,
            )
            with capture_stdout() as buf:
                rc = m._cmd_messages_search(args)
            out = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("Hello", out)
        self.assertIn("sender@example.com", out)

    def test_messages_summarize_writes_file(self):
        client = _make_messages_client()
        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            import mail_assistant.__main__ as m

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
                with capture_stdout() as buf:
                    rc = m._cmd_messages_summarize(args)

                self.assertEqual(rc, 0)
                self.assertTrue(os.path.exists(outp))
                with open(outp, "r", encoding="utf-8") as fh:
                    self.assertIn("Summary", fh.read() or "")

    def test_messages_reply_dry_run_writes_eml(self):
        client = _make_messages_client()
        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            import mail_assistant.__main__ as m

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
                with capture_stdout() as buf:
                    rc = m._cmd_messages_reply(args)

                self.assertEqual(rc, 0)
                self.assertTrue(os.path.exists(eml))
                self.assertEqual(len(client.sent_messages), 0)

    def test_messages_reply_plan_only(self):
        client = _make_messages_client()
        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            import mail_assistant.__main__ as m

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
                rc = m._cmd_messages_reply(args)
            out = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("Plan: reply", out)
        self.assertIn("to:", out)

    def test_messages_reply_create_draft(self):
        client = _make_messages_client()
        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            import mail_assistant.__main__ as m

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
                rc = m._cmd_messages_reply(args)
            out = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("Created Gmail draft", out)


if __name__ == "__main__":
    unittest.main()
