import base64
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch


class FakeClient:
    def __init__(self):
        self.sent = []
        self._id = "MSG1"
        self._thread = "THREAD1"

    def authenticate(self):
        return None

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

    def get_message_text(self, msg_id: str) -> str:
        return "Body text."

    def get_profile(self):
        return {"emailAddress": "me@example.com"}

    def send_message_raw(self, raw_bytes: bytes, thread_id=None):
        self.sent.append((raw_bytes, thread_id))
        return {"id": "SENT"}


class MessagesScheduleTests(unittest.TestCase):
    def test_reply_with_send_in_queues(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"] = os.path.join(td, "scheduled.json")
            fake = FakeClient()
            with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", new=lambda _args: fake):
                import mail_assistant.__main__ as m
                args = SimpleNamespace(
                    id=fake._id,
                    query=None,
                    days=None,
                    only_inbox=False,
                    latest=False,
                    points="OK",
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
                    send_at=None,
                    send_in="1s",
                    credentials=None,
                    token=None,
                    cache=None,
                    profile="gmail_personal",
                )
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = m._cmd_messages_reply(args)
                self.assertEqual(rc, 0)
                # Queue should contain one item
                import json
                with open(os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"], "r", encoding="utf-8") as fh:
                    data = json.loads(fh.read())
                self.assertEqual(len(data), 1)

    def test_apply_scheduled_sends_due(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"] = os.path.join(td, "scheduled.json")
            # Pre-populate queue with one due item
            import json, time
            due = int(time.time()) - 1
            raw = base64.b64encode(b"From: a@b\nTo: c@d\n\nhi").decode("utf-8")
            queued = [{
                "provider": "gmail",
                "profile": "gmail_personal",
                "due_at": due,
                "raw_b64": raw,
                "thread_id": None,
                "to": "c@d",
                "subject": "hi",
                "created_at": due,
            }]
            with open(os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"], "w", encoding="utf-8") as fh:
                fh.write(json.dumps(queued))

            fake = FakeClient()
            with patch("mail_assistant.utils.cli_helpers.gmail_provider_from_args", new=lambda _args: fake):
                import mail_assistant.__main__ as m
                args = SimpleNamespace(max=5, profile="gmail_personal")
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = m._cmd_messages_apply_scheduled(args)
                self.assertEqual(rc, 0)
                self.assertEqual(len(fake.sent), 1)


if __name__ == "__main__":
    unittest.main()
