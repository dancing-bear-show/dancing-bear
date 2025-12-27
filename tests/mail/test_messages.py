"""Tests for mail/messages.py email parsing and composition utilities."""

import unittest
from email.message import EmailMessage

from mail.messages import (
    _parse_addr,
    _compose_reply,
    Candidate,
    candidates_from_metadata,
    encode_email_message,
)


class ParseAddrTests(unittest.TestCase):
    def test_empty_string(self):
        name, email = _parse_addr("")
        self.assertEqual(name, "")
        self.assertEqual(email, "")

    def test_none_input(self):
        name, email = _parse_addr(None)
        self.assertEqual(name, "")
        self.assertEqual(email, "")

    def test_email_only(self):
        name, email = _parse_addr("user@example.com")
        self.assertEqual(email, "user@example.com")

    def test_name_and_email(self):
        name, email = _parse_addr("John Doe <john@example.com>")
        self.assertEqual(name, "John Doe")
        self.assertEqual(email, "john@example.com")

    def test_quoted_name(self):
        name, email = _parse_addr('"Doe, John" <john@example.com>')
        self.assertEqual(name, "Doe, John")
        self.assertEqual(email, "john@example.com")

    def test_angle_brackets_only(self):
        name, email = _parse_addr("<user@example.com>")
        self.assertEqual(name, "")
        self.assertEqual(email, "user@example.com")


class ComposeReplyTests(unittest.TestCase):
    def test_basic_reply(self):
        msg = _compose_reply(
            from_email="me@example.com",
            to_email="you@example.com",
            subject="Test Subject",
            body_text="Reply body",
        )
        self.assertIsInstance(msg, EmailMessage)
        self.assertEqual(msg["From"], "me@example.com")
        self.assertEqual(msg["To"], "you@example.com")
        self.assertEqual(msg["Subject"], "Re: Test Subject")

    def test_subject_already_has_re(self):
        msg = _compose_reply(
            from_email="me@example.com",
            to_email="you@example.com",
            subject="Re: Already a reply",
            body_text="Body",
        )
        self.assertEqual(msg["Subject"], "Re: Already a reply")

    def test_subject_re_case_insensitive(self):
        msg = _compose_reply(
            from_email="me@example.com",
            to_email="you@example.com",
            subject="RE: Uppercase Re",
            body_text="Body",
        )
        self.assertEqual(msg["Subject"], "RE: Uppercase Re")

    def test_with_cc(self):
        msg = _compose_reply(
            from_email="me@example.com",
            to_email="you@example.com",
            subject="Subject",
            body_text="Body",
            cc=["cc1@example.com", "cc2@example.com"],
        )
        self.assertEqual(msg["Cc"], "cc1@example.com, cc2@example.com")

    def test_with_in_reply_to(self):
        msg = _compose_reply(
            from_email="me@example.com",
            to_email="you@example.com",
            subject="Subject",
            body_text="Body",
            in_reply_to="<original-msg-id@example.com>",
        )
        self.assertEqual(msg["In-Reply-To"], "<original-msg-id@example.com>")

    def test_with_references(self):
        msg = _compose_reply(
            from_email="me@example.com",
            to_email="you@example.com",
            subject="Subject",
            body_text="Body",
            references="<ref1@example.com> <ref2@example.com>",
        )
        self.assertEqual(msg["References"], "<ref1@example.com> <ref2@example.com>")

    def test_include_quote(self):
        msg = _compose_reply(
            from_email="me@example.com",
            to_email="you@example.com",
            subject="Subject",
            body_text="My reply",
            include_quote=True,
            original_text="Original line 1\nOriginal line 2",
        )
        content = msg.get_content()
        self.assertIn("My reply", content)
        self.assertIn("> Original line 1", content)
        self.assertIn("> Original line 2", content)

    def test_include_quote_without_original(self):
        msg = _compose_reply(
            from_email="me@example.com",
            to_email="you@example.com",
            subject="Subject",
            body_text="Reply only",
            include_quote=True,
            original_text="",
        )
        content = msg.get_content()
        self.assertEqual(content.strip(), "Reply only")

    def test_empty_body(self):
        msg = _compose_reply(
            from_email="me@example.com",
            to_email="you@example.com",
            subject="Subject",
            body_text="",
        )
        self.assertIsInstance(msg, EmailMessage)


class CandidateTests(unittest.TestCase):
    def test_create_candidate(self):
        c = Candidate(
            id="msg123",
            thread_id="thread456",
            from_header="sender@example.com",
            subject="Test Subject",
            snippet="Preview text...",
        )
        self.assertEqual(c.id, "msg123")
        self.assertEqual(c.thread_id, "thread456")
        self.assertEqual(c.from_header, "sender@example.com")
        self.assertEqual(c.subject, "Test Subject")
        self.assertEqual(c.snippet, "Preview text...")

    def test_candidate_optional_thread_id(self):
        c = Candidate(
            id="msg123",
            thread_id=None,
            from_header="sender@example.com",
            subject="Subject",
            snippet="",
        )
        self.assertIsNone(c.thread_id)


class CandidatesFromMetadataTests(unittest.TestCase):
    def test_empty_list(self):
        result = candidates_from_metadata([])
        self.assertEqual(result, [])

    def test_single_message(self):
        msgs = [
            {
                "id": "msg1",
                "threadId": "thread1",
                "snippet": "  Preview text  ",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "Subject", "value": "Test Subject"},
                    ]
                },
            }
        ]
        result = candidates_from_metadata(msgs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "msg1")
        self.assertEqual(result[0].thread_id, "thread1")
        self.assertEqual(result[0].from_header, "sender@example.com")
        self.assertEqual(result[0].subject, "Test Subject")
        self.assertEqual(result[0].snippet, "Preview text")

    def test_multiple_messages(self):
        msgs = [
            {"id": "msg1", "payload": {"headers": []}},
            {"id": "msg2", "payload": {"headers": []}},
        ]
        result = candidates_from_metadata(msgs)
        self.assertEqual(len(result), 2)

    def test_missing_payload(self):
        msgs = [{"id": "msg1"}]
        result = candidates_from_metadata(msgs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].from_header, "")
        self.assertEqual(result[0].subject, "")

    def test_missing_headers(self):
        msgs = [{"id": "msg1", "payload": {}}]
        result = candidates_from_metadata(msgs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].from_header, "")

    def test_missing_id(self):
        msgs = [{"threadId": "thread1", "payload": {"headers": []}}]
        result = candidates_from_metadata(msgs)
        self.assertEqual(result[0].id, "")

    def test_header_case_insensitive(self):
        msgs = [
            {
                "id": "msg1",
                "payload": {
                    "headers": [
                        {"name": "FROM", "value": "sender@example.com"},
                        {"name": "SUBJECT", "value": "CAPS Subject"},
                    ]
                },
            }
        ]
        result = candidates_from_metadata(msgs)
        # Headers are normalized to lowercase keys
        self.assertEqual(result[0].from_header, "sender@example.com")
        self.assertEqual(result[0].subject, "CAPS Subject")

    def test_snippet_whitespace_stripped(self):
        msgs = [{"id": "msg1", "snippet": "  \n  Text with spaces  \n  ", "payload": {}}]
        result = candidates_from_metadata(msgs)
        self.assertEqual(result[0].snippet, "Text with spaces")


class EncodeEmailMessageTests(unittest.TestCase):
    def test_encode_simple_message(self):
        msg = EmailMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Test"
        msg.set_content("Body text")

        result = encode_email_message(msg)
        self.assertIsInstance(result, bytes)
        self.assertIn(b"From: sender@example.com", result)
        self.assertIn(b"To: recipient@example.com", result)

    def test_encode_unicode_content(self):
        msg = EmailMessage()
        msg["Subject"] = "Test émojis 🎉"
        msg.set_content("Hello été")

        result = encode_email_message(msg)
        self.assertIsInstance(result, bytes)


if __name__ == "__main__":
    unittest.main()
