"""Tests for messages list-attachments and download-attachment commands."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from tests.fixtures import capture_stdout
from tests.mail_tests.fixtures import FakeGmailClient, make_args
from mail.messages_cli.commands import (
    AttachmentInfo,
    list_message_attachments,
    _sanitize_filename,
    run_messages_list_attachments,
    run_messages_download_attachment,
)


def _make_attachment_msg(msg_id: str = "MSG1") -> dict:
    """Build a fake Gmail message dict with one attachment."""
    return {
        msg_id: {
            "id": msg_id,
            "threadId": "T1",
            "payload": {
                "mimeType": "multipart/mixed",
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "filename": "",
                        "body": {"data": "aGVsbG8="},
                    },
                    {
                        "mimeType": "application/pdf",
                        "filename": "report.pdf",
                        "body": {"attachmentId": "ATT1", "size": 1234},
                    },
                ],
            },
            "_attachments": {
                "ATT1": b"%PDF-1.4 fake",
            },
        }
    }


def _make_multi_attachment_msg(msg_id: str = "MSG2") -> dict:
    """Build a fake Gmail message dict with two attachments."""
    return {
        msg_id: {
            "id": msg_id,
            "threadId": "T2",
            "payload": {
                "mimeType": "multipart/mixed",
                "parts": [
                    {
                        "mimeType": "application/pdf",
                        "filename": "doc1.pdf",
                        "body": {"attachmentId": "ATT_A", "size": 100},
                    },
                    {
                        "mimeType": "image/png",
                        "filename": "image.png",
                        "body": {"attachmentId": "ATT_B", "size": 200},
                    },
                ],
            },
            "_attachments": {
                "ATT_A": b"pdf-content",
                "ATT_B": b"png-content",
            },
        }
    }


def _make_nested_attachment_msg(msg_id: str = "MSG3") -> dict:
    """Build a Gmail message dict with nested parts containing an attachment."""
    return {
        msg_id: {
            "id": msg_id,
            "threadId": "T3",
            "payload": {
                "mimeType": "multipart/mixed",
                "parts": [
                    {
                        "mimeType": "multipart/alternative",
                        "filename": "",
                        "body": {},
                        "parts": [
                            {
                                "mimeType": "text/plain",
                                "filename": "",
                                "body": {"data": "aGVsbG8="},
                            },
                            {
                                "mimeType": "application/zip",
                                "filename": "nested.zip",
                                "body": {"attachmentId": "ATT_NESTED", "size": 999},
                            },
                        ],
                    },
                ],
            },
            "_attachments": {
                "ATT_NESTED": b"PK fake zip content",
            },
        }
    }


class TestListMessageAttachments(unittest.TestCase):
    def test_returns_attachment_info_for_part_with_filename(self):
        msg_data = _make_attachment_msg()
        msg = msg_data["MSG1"]
        result = list_message_attachments(msg)
        self.assertEqual(len(result), 1)
        att = result[0]
        self.assertIsInstance(att, AttachmentInfo)
        self.assertEqual(att.filename, "report.pdf")
        self.assertEqual(att.mime_type, "application/pdf")
        self.assertEqual(att.attachment_id, "ATT1")
        self.assertEqual(att.size, 1234)

    def test_returns_empty_for_message_with_no_attachments(self):
        msg = {
            "id": "MSG_NOATT",
            "payload": {
                "mimeType": "text/plain",
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "filename": "",
                        "body": {"data": "aGVsbG8="},
                    }
                ],
            },
        }
        result = list_message_attachments(msg)
        self.assertEqual(result, [])

    def test_walks_nested_parts_recursively(self):
        msg_data = _make_nested_attachment_msg()
        msg = msg_data["MSG3"]
        result = list_message_attachments(msg)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].filename, "nested.zip")
        self.assertEqual(result[0].attachment_id, "ATT_NESTED")


class TestSanitizeFilename(unittest.TestCase):
    def test_strips_unix_path_separators(self):
        self.assertEqual(_sanitize_filename("some/path/file.pdf"), "file.pdf")

    def test_strips_windows_path_separators(self):
        self.assertEqual(_sanitize_filename("some\\path\\file.pdf"), "file.pdf")

    def test_passthrough_plain_filename(self):
        self.assertEqual(_sanitize_filename("report.pdf"), "report.pdf")

    def test_path_traversal_attempt(self):
        self.assertEqual(_sanitize_filename("../../etc/passwd"), "passwd")


class TestRunMessagesListAttachments(unittest.TestCase):
    def _client_with_msg(self, msg_id: str = "MSG1") -> FakeGmailClient:
        return FakeGmailClient(messages=_make_attachment_msg(msg_id))

    def test_table_output(self):
        client = self._client_with_msg()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(id="MSG1", json=False)
            with capture_stdout() as buf:
                rc = run_messages_list_attachments(args)
            out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("report.pdf", out)
        self.assertIn("application/pdf", out)
        self.assertIn("1234 bytes", out)
        self.assertIn("ATT1", out)

    def test_json_output(self):
        import json
        client = self._client_with_msg()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(id="MSG1", json=True)
            with capture_stdout() as buf:
                rc = run_messages_list_attachments(args)
            out = buf.getvalue()
        self.assertEqual(rc, 0)
        parsed = json.loads(out)
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["filename"], "report.pdf")
        self.assertEqual(parsed[0]["attachmentId"], "ATT1")
        self.assertEqual(parsed[0]["size"], 1234)

    def test_missing_id_returns_exit_1(self):
        client = self._client_with_msg()
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(id=None, json=False)
            rc = run_messages_list_attachments(args)
        self.assertEqual(rc, 1)

    def test_no_attachments_exits_0(self):
        client = FakeGmailClient(messages={
            "MSG_EMPTY": {
                "id": "MSG_EMPTY",
                "payload": {
                    "mimeType": "text/plain",
                    "parts": [],
                },
            }
        })
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = make_args(id="MSG_EMPTY", json=False)
            with capture_stdout() as buf:
                rc = run_messages_list_attachments(args)
            out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("No attachments", out)


class TestRunMessagesDownloadAttachment(unittest.TestCase):
    def test_single_attachment_auto_select_writes_file(self):
        client = FakeGmailClient(messages=_make_attachment_msg("MSG1"))
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            with tempfile.TemporaryDirectory() as td:
                args = make_args(
                    id="MSG1",
                    attachment_id=None,
                    filename=None,
                    out=None,
                    out_dir=td,
                )
                with capture_stdout() as buf:
                    rc = run_messages_download_attachment(args)
                out = buf.getvalue()
                written = os.path.join(td, "report.pdf")
                self.assertEqual(rc, 0)
                self.assertTrue(os.path.exists(written))
                with open(written, "rb") as fh:
                    self.assertEqual(fh.read(), b"%PDF-1.4 fake")
                self.assertIn("report.pdf", out)

    def test_multi_attachment_without_selector_exits_1(self):
        client = FakeGmailClient(messages=_make_multi_attachment_msg("MSG2"))
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            with tempfile.TemporaryDirectory() as td:
                args = make_args(
                    id="MSG2",
                    attachment_id=None,
                    filename=None,
                    out=None,
                    out_dir=td,
                )
                rc = run_messages_download_attachment(args)
        self.assertEqual(rc, 1)

    def test_attachment_id_selects_correct_attachment(self):
        client = FakeGmailClient(messages=_make_multi_attachment_msg("MSG2"))
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            with tempfile.TemporaryDirectory() as td:
                args = make_args(
                    id="MSG2",
                    attachment_id="ATT_B",
                    filename=None,
                    out=None,
                    out_dir=td,
                )
                with capture_stdout() as buf:
                    rc = run_messages_download_attachment(args)
                out = buf.getvalue()
                written = os.path.join(td, "image.png")
                self.assertEqual(rc, 0)
                self.assertTrue(os.path.exists(written))
                with open(written, "rb") as fh:
                    self.assertEqual(fh.read(), b"png-content")
                self.assertIn("image.png", out)

    def test_filename_filter_selects_by_name(self):
        client = FakeGmailClient(messages=_make_multi_attachment_msg("MSG2"))
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            with tempfile.TemporaryDirectory() as td:
                args = make_args(
                    id="MSG2",
                    attachment_id=None,
                    filename="doc1.pdf",
                    out=None,
                    out_dir=td,
                )
                with capture_stdout() as buf:
                    rc = run_messages_download_attachment(args)
                out = buf.getvalue()
                written = os.path.join(td, "doc1.pdf")
                self.assertEqual(rc, 0)
                self.assertTrue(os.path.exists(written))
                with open(written, "rb") as fh:
                    self.assertEqual(fh.read(), b"pdf-content")
                self.assertIn("doc1.pdf", out)

    def test_out_flag_as_directory_writes_filename_inside(self):
        client = FakeGmailClient(messages=_make_attachment_msg("MSG1"))
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            with tempfile.TemporaryDirectory() as td:
                args = make_args(
                    id="MSG1",
                    attachment_id=None,
                    filename=None,
                    out=td,  # td is a directory
                    out_dir=".",
                )
                with capture_stdout():
                    rc = run_messages_download_attachment(args)
                self.assertEqual(rc, 0)
                self.assertTrue(os.path.exists(os.path.join(td, "report.pdf")))

    def test_filename_filter_not_found_exits_1(self):
        client = FakeGmailClient(messages=_make_attachment_msg("MSG1"))
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            with tempfile.TemporaryDirectory() as td:
                args = make_args(
                    id="MSG1",
                    attachment_id=None,
                    filename="nonexistent.txt",
                    out=None,
                    out_dir=td,
                )
                rc = run_messages_download_attachment(args)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
