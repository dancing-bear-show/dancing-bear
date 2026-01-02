import base64
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from tests.mail_tests.fixtures import FakeGmailClient, capture_stdout, make_args
from mail.messages_cli.commands import (
    run_messages_reply,
    run_messages_apply_scheduled,
)


def _make_messages_client():
    """Create a FakeGmailClient configured for messages tests."""
    msg_id = "MSG1"
    return FakeGmailClient(
        messages={
            msg_id: {
                "id": msg_id,
                "threadId": "THREAD1",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Sender <sender@example.com>"},
                        {"name": "Subject", "value": "Hello"},
                        {"name": "Message-Id", "value": "<abc@id>"},
                        {"name": "References", "value": "<prev@id>"},
                    ]
                },
                "text": "Body text.",
            }
        },
    )


class MessagesScheduleTests(unittest.TestCase):
    def test_reply_with_send_in_queues(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"] = os.path.join(td, "scheduled.json")
            client = _make_messages_client()

            with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):

                args = make_args(
                    id="MSG1",
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
                    profile="gmail_personal",
                )

                with capture_stdout():
                    rc = run_messages_reply(args)

                self.assertEqual(rc, 0)
                # Queue should contain one item
                with open(os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"], "r", encoding="utf-8") as fh:
                    data = json.loads(fh.read())
                self.assertEqual(len(data), 1)

    def test_apply_scheduled_sends_due(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"] = os.path.join(td, "scheduled.json")
            # Pre-populate queue with one due item
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

            client = _make_messages_client()

            with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):

                args = make_args(max=5, profile="gmail_personal")

                with capture_stdout():
                    rc = run_messages_apply_scheduled(args)

                self.assertEqual(rc, 0)
                self.assertEqual(len(client.sent_messages), 1)


if __name__ == "__main__":
    unittest.main()
