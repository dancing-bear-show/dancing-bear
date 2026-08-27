import base64
import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.fixtures import capture_stdout
from tests.mail_tests.fixtures import FakeGmailClient, make_args
from mail.messages_cli.commands_reply import (
    run_messages_reply,
    run_messages_apply_scheduled,
    _reply_show_plan,
    _format_points,
    _load_points_from_file,
    _reply_execute,
    _send_one_scheduled,
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


def _base_reply_args(**kwargs):
    """Make minimal args for run_messages_reply."""
    defaults = dict(
        id="MSG1",
        query=None,
        days=None,
        only_inbox=False,
        latest=False,
        points="",
        points_file=None,
        tone=None,
        signoff=None,
        include_summary=False,
        include_quote=False,
        cc=[],
        bcc=[],
        subject=None,
        draft_out=None,
        apply=False,
        send_at=None,
        send_in=None,
        plan=False,
        profile="gmail_personal",
    )
    defaults.update(kwargs)
    return make_args(**defaults)


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


# ---------------------------------------------------------------------------
# _reply_show_plan: branch coverage (lines 18-26)
# ---------------------------------------------------------------------------

class ReplyShowPlanTests(unittest.TestCase):
    """Tests for _reply_show_plan covering all optional branches."""

    def _make_args(self, **kwargs):
        defaults = dict(send_at=None, send_in=None, cc=[], bcc=[], subject=None)
        defaults.update(kwargs)
        return make_args(**defaults)

    def test_happy_path_minimal_args_returns_0(self):
        args = self._make_args()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _reply_show_plan(args, "to@example.com", "Original Subject")
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("Plan: reply", out)
        self.assertIn("to@example.com", out)

    def test_cc_line_printed_when_cc_present(self):
        # Line 18->20: cc is non-empty
        args = self._make_args(cc=["cc@example.com"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            _reply_show_plan(args, "to@example.com", "Subj")
        self.assertIn("cc: cc@example.com", buf.getvalue())

    def test_bcc_line_printed_when_bcc_present(self):
        # Line 21: bcc is non-empty
        args = self._make_args(bcc=["bcc@example.com"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            _reply_show_plan(args, "to@example.com", "Subj")
        self.assertIn("bcc: bcc@example.com", buf.getvalue())

    def test_when_line_printed_when_send_at_present(self):
        # Line 24: when is non-None
        args = self._make_args(send_at="2026-01-01 10:00")
        buf = io.StringIO()
        with redirect_stdout(buf):
            _reply_show_plan(args, "to@example.com", "Subj")
        self.assertIn("when:", buf.getvalue())

    def test_subject_shown_with_re_prefix_when_no_explicit_subject(self):
        args = self._make_args(subject=None)
        buf = io.StringIO()
        with redirect_stdout(buf):
            _reply_show_plan(args, "to@example.com", "Hello")
        self.assertIn("Re: Hello", buf.getvalue())

    def test_explicit_subject_used_instead_of_re_prefix(self):
        args = self._make_args(subject="Custom Subject")
        buf = io.StringIO()
        with redirect_stdout(buf):
            _reply_show_plan(args, "to@example.com", "Hello")
        self.assertIn("Custom Subject", buf.getvalue())
        self.assertNotIn("Re: Hello", buf.getvalue())


# ---------------------------------------------------------------------------
# _format_points: branch coverage (lines 83-88)
# ---------------------------------------------------------------------------

class FormatPointsTests(unittest.TestCase):
    """Tests for _format_points."""

    def test_empty_string_returns_empty_list(self):
        self.assertEqual([], _format_points(""))

    def test_none_equivalent_empty_string(self):
        self.assertEqual([], _format_points(""))

    def test_single_non_bullet_line_returned_as_is(self):
        # Line 84: single item, no leading dash
        result = _format_points("Just a sentence.")
        self.assertEqual(["Just a sentence."], result)

    def test_single_bullet_line_triggers_list_format(self):
        # Line 88: single item that starts with '-' uses multi-item format (len==1 but starts with -)
        result = _format_points("- A point")
        self.assertEqual(["Here are the points:", "- A point"], result)

    def test_multiple_lines_formatted_as_bulleted_list(self):
        result = _format_points("First\nSecond\nThird")
        self.assertIn("Here are the points:", result)
        self.assertIn("First", result[1])
        self.assertIn("Second", result[2])

    def test_whitespace_only_lines_stripped(self):
        result = _format_points("  A  \n   \n  B  ")
        self.assertNotIn("", result)


# ---------------------------------------------------------------------------
# _load_points_from_file: tests (lines 72-78)
# ---------------------------------------------------------------------------

class LoadPointsFromFileTests(unittest.TestCase):
    """Tests for _load_points_from_file."""

    def test_loads_goals_key(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "plan.yaml"
            p.write_text("goals:\n  - Do A\n  - Do B\n")
            args = make_args()
            result = _load_points_from_file(str(p), args)
            self.assertIn("Do A", result)
            self.assertIn("Do B", result)

    def test_loads_points_key_as_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "plan.yaml"
            p.write_text("points:\n  - Point X\n")
            args = make_args()
            result = _load_points_from_file(str(p), args)
            self.assertIn("Point X", result)

    def test_sets_signoff_from_file_when_arg_is_none(self):
        # Line 76: signoff in file, args.signoff is None
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "plan.yaml"
            p.write_text("goals:\n  - X\nsignoff: Best,\n")
            args = make_args(signoff=None)
            _load_points_from_file(str(p), args)
            self.assertEqual("Best,", args.signoff)

    def test_does_not_override_existing_signoff(self):
        # Line 76 branch: args.signoff already set — not overridden
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "plan.yaml"
            p.write_text("goals:\n  - X\nsignoff: New Signoff\n")
            args = make_args(signoff="Existing")
            _load_points_from_file(str(p), args)
            self.assertEqual("Existing", args.signoff)


# ---------------------------------------------------------------------------
# _reply_execute: branch coverage (lines 113-134)
# ---------------------------------------------------------------------------

class ReplyExecuteTests(unittest.TestCase):
    """Tests for _reply_execute."""

    def test_apply_true_sends_message(self):
        # Line 114-116: apply=True path
        client = FakeGmailClient()
        raw = b"From: a@b\nTo: c@d\n\nHi"
        args = make_args(apply=True, create_draft=False, draft_out=None)
        buf = io.StringIO()
        with redirect_stdout(buf):
            _reply_execute(args, client, raw, "THREAD1", "c@d")
        self.assertEqual(1, len(client.sent_messages))
        self.assertIn("Sent reply to c@d", buf.getvalue())

    def test_create_draft_true_creates_draft(self):
        # Happy path: create_draft=True
        client = FakeGmailClient()
        raw = b"From: a@b\nTo: c@d\n\nHi"
        args = make_args(apply=False, create_draft=True, draft_out=None)
        buf = io.StringIO()
        with redirect_stdout(buf):
            _reply_execute(args, client, raw, None, "c@d")
        self.assertEqual(1, len(client.created_drafts))
        self.assertIn("Created Gmail draft", buf.getvalue())

    def test_draft_out_writes_file(self):
        client = FakeGmailClient()
        raw = b"From: a@b\nTo: c@d\n\nHi"
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "reply.eml")
            args = make_args(apply=False, create_draft=False, draft_out=out)
            buf = io.StringIO()
            with redirect_stdout(buf):
                _reply_execute(args, client, raw, None, "c@d")
            self.assertTrue(os.path.exists(out))
            self.assertIn("Draft written to", buf.getvalue())

    def test_no_draft_out_prints_preview(self):
        # Lines 131-134: no draft_out, no apply, no create_draft — preview
        client = FakeGmailClient()
        raw = b"From: a@b\nTo: c@d\n\nHi there"
        args = make_args(apply=False, create_draft=False, draft_out=None)
        buf = io.StringIO()
        with redirect_stdout(buf):
            _reply_execute(args, client, raw, None, "c@d")
        self.assertIn("preview", buf.getvalue())
        self.assertIn("Hi there", buf.getvalue())


# ---------------------------------------------------------------------------
# run_messages_reply: error paths (lines 158-159, 165-166)
# ---------------------------------------------------------------------------

class RunMessagesReplyErrorTests(unittest.TestCase):
    """Tests for run_messages_reply sad paths."""

    def test_returns_1_when_no_message_id_found(self):
        # Lines 158-159: mid is None/empty
        client = FakeGmailClient()  # no messages
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = _base_reply_args(id=None, query="no_match")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_messages_reply(args)
        self.assertEqual(1, rc)
        self.assertIn("No message found", buf.getvalue())

    def test_returns_1_when_no_recipient_in_headers(self):
        # Lines 165-166: to_email is empty
        client = FakeGmailClient(
            messages={
                "MSG_NO_FROM": {
                    "id": "MSG_NO_FROM",
                    "threadId": "T1",
                    "payload": {"headers": [{"name": "Subject", "value": "Hi"}]},
                    "text": "",
                }
            },
        )
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = _base_reply_args(id="MSG_NO_FROM")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_messages_reply(args)
        self.assertEqual(1, rc)
        self.assertIn("Could not determine recipient", buf.getvalue())

    def test_plan_flag_returns_0_and_shows_plan(self):
        # Happy path with plan=True
        client = _make_messages_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = _base_reply_args(plan=True)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_messages_reply(args)
        self.assertEqual(0, rc)
        self.assertIn("Plan: reply", buf.getvalue())

    def test_include_summary_inserts_summary_line(self):
        # Lines 103-104: include_summary=True — summarize_text is called and prefixed
        client = _make_messages_client()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            # summarize_text is imported inside _build_reply_body from mail.llm_adapter
            with patch("mail.llm_adapter.summarize_text", return_value="A short summary") as mock_summ:
                args = _base_reply_args(include_summary=True, draft_out=None)
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = run_messages_reply(args)
        self.assertEqual(0, rc)
        mock_summ.assert_called_once()

    def test_points_file_path_triggers_load(self):
        # Line 98: plan_path is set
        client = _make_messages_client()
        with tempfile.TemporaryDirectory() as td:
            plan_file = Path(td) / "plan.yaml"
            plan_file.write_text("goals:\n  - Goal A\n")
            with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
                args = _base_reply_args(points_file=str(plan_file), draft_out=None)
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = run_messages_reply(args)
        self.assertEqual(0, rc)


# ---------------------------------------------------------------------------
# _reply_schedule: invalid due path (lines 44-45)
# ---------------------------------------------------------------------------

class ReplyScheduleTests(unittest.TestCase):
    """Tests for _reply_schedule covering the invalid due path."""

    def test_invalid_send_at_and_no_send_in_returns_1(self):
        # Lines 44-45: due is None after trying both send_at and send_in
        from mail.messages_cli.commands_reply import _reply_schedule
        args = make_args(send_at="not-a-date", send_in=None, profile=None, draft_out=None)
        raw = b"From: a@b\nTo: c@d\n\nHi"
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _reply_schedule(args, raw, None, "c@d", "subj")
        self.assertEqual(1, rc)
        self.assertIn("Invalid --send-at/--send-in", buf.getvalue())

    def test_invalid_send_in_delta_returns_1(self):
        # Line 41->43: send_in provided but parse_send_in returns None (delta is falsy)
        with tempfile.TemporaryDirectory() as td:
            os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"] = os.path.join(td, "sched.json")
            from mail.messages_cli.commands_reply import _reply_schedule
            args = make_args(send_at=None, send_in="gibberish", profile=None, draft_out=None)
            raw = b"From: a@b\nTo: c@d\n\nHi"
            with patch("mail.scheduler.parse_send_in", return_value=None):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = _reply_schedule(args, raw, None, "c@d", "subj")
            self.assertEqual(1, rc)
            self.assertIn("Invalid --send-at/--send-in", buf.getvalue())

    def test_draft_out_written_when_scheduled(self):
        # Lines 63-66: draft_out set on successful schedule
        with tempfile.TemporaryDirectory() as td:
            os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"] = os.path.join(td, "sched.json")
            from mail.messages_cli.commands_reply import _reply_schedule
            out_path = os.path.join(td, "reply.eml")
            args = make_args(send_at=None, send_in="1s", profile="default", draft_out=out_path)
            raw = b"From: a@b\nTo: c@d\n\nHi"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = _reply_schedule(args, raw, None, "c@d", "subj")
            self.assertEqual(0, rc)
            self.assertTrue(os.path.exists(out_path))
            self.assertIn("Draft written to", buf.getvalue())


# ---------------------------------------------------------------------------
# _send_one_scheduled: failure path (lines 215-217)
# ---------------------------------------------------------------------------

class SendOneScheduledTests(unittest.TestCase):
    """Tests for _send_one_scheduled failure path."""

    def test_returns_true_on_success(self):
        client = FakeGmailClient()
        raw = base64.b64encode(b"From: a@b\nTo: c@d\n\nHi").decode()
        item = {"to": "c@d", "subject": "Hi", "raw_b64": raw, "thread_id": None}
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = _send_one_scheduled(client, item, "gmail_personal")
        self.assertTrue(result)
        self.assertEqual(1, len(client.sent_messages))

    def test_returns_false_and_prints_on_send_failure(self):
        # Lines 215-217: exception caught, returns False
        client = FakeGmailClient()
        client.send_message_raw = MagicMock(side_effect=RuntimeError("network error"))
        raw = base64.b64encode(b"raw content").decode()
        item = {"to": "fail@d", "subject": "Fail", "raw_b64": raw, "thread_id": None}
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = _send_one_scheduled(client, item, "gmail_personal")
        self.assertFalse(result)
        self.assertIn("Failed to send to fail@d", buf.getvalue())
        client.send_message_raw.assert_called_once()


# ---------------------------------------------------------------------------
# run_messages_apply_scheduled: no-due path (lines 238-239)
# ---------------------------------------------------------------------------

class ApplyScheduledNoDueTests(unittest.TestCase):
    """Tests for run_messages_apply_scheduled when nothing is due."""

    def test_returns_0_and_prints_no_due_when_queue_empty(self):
        # Lines 238-239: pop_due returns []
        with tempfile.TemporaryDirectory() as td:
            os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"] = os.path.join(td, "empty.json")
            # Empty queue
            with open(os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"], "w") as f:
                f.write("[]")
            args = make_args(max=10, profile=None)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_messages_apply_scheduled(args)
        self.assertEqual(0, rc)
        self.assertIn("No scheduled messages due", buf.getvalue())

    def test_returns_1_on_send_errors(self):
        # Error case: items are due but sending fails
        with tempfile.TemporaryDirectory() as td:
            os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"] = os.path.join(td, "sched.json")
            due = int(time.time()) - 1
            raw = base64.b64encode(b"From: a@b\nTo: c@d\n\nhi").decode()
            queued = [{
                "provider": "gmail",
                "profile": "fail_profile",
                "due_at": due,
                "raw_b64": raw,
                "thread_id": None,
                "to": "c@d",
                "subject": "hi",
                "created_at": due,
            }]
            with open(os.environ["MAIL_ASSISTANT_SCHEDULE_PATH"], "w") as f:
                f.write(json.dumps(queued))

            client = _make_messages_client()
            client.send_message_raw = MagicMock(side_effect=RuntimeError("send fail"))
            with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
                args = make_args(max=10, profile=None)
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = run_messages_apply_scheduled(args)
            self.assertEqual(1, rc)


if __name__ == "__main__":
    unittest.main()
