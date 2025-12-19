import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch


class FakeClient:
    def __init__(self):
        self.sent = False
        self._id = "MSG1"
        self._thread = "THREAD1"

    # Lifecycle
    def authenticate(self):
        return None

    # Search/list
    def list_message_ids(self, query=None, max_pages=1, page_size=5):
        return [self._id]

    def get_messages_metadata(self, ids, use_cache=True):
        return [
            {
                "id": self._id,
                "threadId": self._thread,
                "snippet": "Snippet here",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Sender <sender@example.com>"},
                        {"name": "Subject", "value": "Hello"},
                    ]
                },
            }
        ]

    def get_message_text(self, msg_id: str) -> str:
        return "This is the body of the email. It has some content."

    def get_message(self, msg_id: str, fmt: str = "full"):
        return {
            "id": self._id,
            "threadId": self._thread,
            "payload": {
                "headers": [
                    {"name": "From", "value": "Sender <sender@example.com>"},
                    {"name": "Subject", "value": "Hello"},
                    {"name": "Message-Id", "value": "<abc@id>"},
                    {"name": "References", "value": "<prev@id>"},
                ]
            },
        }

    def get_profile(self):
        return {"emailAddress": "me@example.com"}

    # Send/draft
    def send_message_raw(self, raw_bytes: bytes, thread_id=None):
        self.sent = True
        return {"id": "SENT"}

    def create_draft_raw(self, raw_bytes: bytes, thread_id=None):
        self.draft = True
        return {"id": "DRAFT1"}


class MessagesCLITests(unittest.TestCase):
    def test_messages_search_lists_candidates(self):
        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", new=lambda _args: FakeClient()):
            import mail_assistant.__main__ as m
            args = SimpleNamespace(query="from:sender@example.com", days=None, only_inbox=False, max_results=3, json=False, credentials=None, token=None, cache=None)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = m._cmd_messages_search(args)
            out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Hello", out)
        self.assertIn("sender@example.com", out)

    def test_messages_summarize_writes_file(self):
        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", new=lambda _args: FakeClient()):
            import mail_assistant.__main__ as m
            with tempfile.TemporaryDirectory() as td:
                outp = os.path.join(td, "sum.txt")
                args = SimpleNamespace(id=None, query="from:sender@example.com", latest=True, days=None, only_inbox=False, out=outp, max_words=30, credentials=None, token=None, cache=None)
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = m._cmd_messages_summarize(args)
                self.assertEqual(rc, 0)
                self.assertTrue(os.path.exists(outp))
                with open(outp, "r", encoding="utf-8") as fh:
                    self.assertIn("Summary", fh.read() or "")

    def test_messages_reply_dry_run_writes_eml(self):
        fake = FakeClient()
        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", new=lambda _args: fake):
            import mail_assistant.__main__ as m
            with tempfile.TemporaryDirectory() as td:
                eml = os.path.join(td, "reply.eml")
                args = SimpleNamespace(
                    id=fake._id,
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
                    credentials=None,
                    token=None,
                    cache=None,
                )
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = m._cmd_messages_reply(args)
                self.assertEqual(rc, 0)
                self.assertTrue(os.path.exists(eml))
                self.assertFalse(fake.sent)

    def test_messages_reply_plan_only(self):
        fake = FakeClient()
        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", new=lambda _args: fake):
            import mail_assistant.__main__ as m
            args = SimpleNamespace(
                id=fake._id,
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
                credentials=None,
                token=None,
                cache=None,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = m._cmd_messages_reply(args)
            out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Plan: reply", out)
        self.assertIn("to:", out)

    def test_messages_reply_create_draft(self):
        fake = FakeClient()
        with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", new=lambda _args: fake):
            import mail_assistant.__main__ as m
            args = SimpleNamespace(
                id=fake._id,
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
                credentials=None,
                token=None,
                cache=None,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = m._cmd_messages_reply(args)
            out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Created Gmail draft", out)


if __name__ == "__main__":
    unittest.main()
