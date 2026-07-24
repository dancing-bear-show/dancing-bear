"""Tests for OutlookMailListProcessor and OutlookMailListProducer.

Covers happy paths (single page, multi-page pagination, empty list),
sad paths (None service, client exception), and producer output format.
"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock

from calendars.outlook_pipelines.mail import (
    OutlookMailListProcessor,
    OutlookMailListProducer,
    OutlookMailListRequest,
    OutlookMailListRequestConsumer,
    OutlookMailListResult,
)


def _make_message(
    subject: str = "Test Subject",
    received: str = "2025-06-01T09:00:00Z",
    from_address: str = "sender@example.com",
) -> dict:
    """Factory for Outlook mail message dicts used in tests."""
    return {
        "subject": subject,
        "receivedDateTime": received,
        "from": {"emailAddress": {"address": from_address}},
    }


def _make_request(svc, folder: str = "inbox", top: int = 5, pages: int = 1) -> OutlookMailListRequest:
    return OutlookMailListRequest(service=svc, folder=folder, top=top, pages=pages)


def _process(request: OutlookMailListRequest):
    consumer = OutlookMailListRequestConsumer(request)
    return OutlookMailListProcessor().process(consumer.consume())


class OutlookMailListProcessorHappyPathTests(unittest.TestCase):
    def test_returns_success_envelope_with_messages(self):
        svc = MagicMock()
        msg = _make_message()
        svc.list_messages.return_value = [msg]

        env = _process(_make_request(svc, folder="inbox", top=5, pages=1))

        self.assertTrue(env.ok())
        self.assertIsInstance(env.payload, OutlookMailListResult)
        self.assertEqual(len(env.payload.messages), 1)
        self.assertEqual(env.payload.folder, "inbox")
        svc.list_messages.assert_called_once_with(folder="inbox", top=5, pages=1)

    def test_passes_folder_and_top_to_client(self):
        svc = MagicMock()
        svc.list_messages.return_value = []

        _process(_make_request(svc, folder="SentItems", top=25, pages=1))

        svc.list_messages.assert_called_once_with(folder="SentItems", top=25, pages=1)

    def test_paginates_with_pages_parameter(self):
        svc = MagicMock()
        page1 = [_make_message(subject="Page1 msg A"), _make_message(subject="Page1 msg B")]
        page2 = [_make_message(subject="Page2 msg A")]
        # The real client aggregates pages and returns a flat list; we simulate that.
        svc.list_messages.return_value = page1 + page2

        env = _process(_make_request(svc, folder="inbox", top=10, pages=2))

        self.assertTrue(env.ok())
        self.assertEqual(len(env.payload.messages), 3)
        svc.list_messages.assert_called_once_with(folder="inbox", top=10, pages=2)

    def test_returns_correct_folder_in_result(self):
        svc = MagicMock()
        svc.list_messages.return_value = [_make_message()]

        env = _process(_make_request(svc, folder="Drafts", top=5, pages=1))

        self.assertTrue(env.ok())
        self.assertEqual(env.payload.folder, "Drafts")

    def test_empty_list_returns_success_with_no_messages(self):
        svc = MagicMock()
        svc.list_messages.return_value = []

        env = _process(_make_request(svc))

        self.assertTrue(env.ok())
        self.assertEqual(env.payload.messages, [])
        self.assertEqual(env.payload.folder, "inbox")

    def test_none_response_treated_as_empty(self):
        # Client returns None (defensive guard: msgs = msgs or [])
        svc = MagicMock()
        svc.list_messages.return_value = None

        env = _process(_make_request(svc))

        self.assertTrue(env.ok())
        self.assertEqual(env.payload.messages, [])


class OutlookMailListProcessorSadPathTests(unittest.TestCase):
    def test_none_service_returns_error_envelope(self):
        env = _process(_make_request(svc=None))

        self.assertFalse(env.ok())
        self.assertIn("service", (env.diagnostics or {}).get("message", "").lower())

    def test_client_exception_returns_error_envelope(self):
        svc = MagicMock()
        svc.list_messages.side_effect = RuntimeError("network failure")

        env = _process(_make_request(svc))

        self.assertFalse(env.ok())
        self.assertIn("network failure", (env.diagnostics or {}).get("message", ""))

    def test_client_exception_does_not_raise(self):
        svc = MagicMock()
        svc.list_messages.side_effect = ValueError("bad token")

        # Must not raise — SafeProcessor absorbs it.
        try:
            env = _process(_make_request(svc))
        except Exception as exc:  # nosec B110 - verifying no exception propagates
            self.fail(f"process() raised unexpectedly: {exc}")
        self.assertFalse(env.ok())


class OutlookMailListProducerTests(unittest.TestCase):
    def _produce(self, env) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookMailListProducer().produce(env)
        return buf.getvalue()

    def _ok_env(self, messages: list, folder: str = "inbox"):
        from core.pipeline import ResultEnvelope
        payload = OutlookMailListResult(messages=messages, folder=folder)
        return ResultEnvelope(status="success", payload=payload)

    def _err_env(self, message: str = "something went wrong"):
        from core.pipeline import ResultEnvelope
        return ResultEnvelope(status="error", diagnostics={"message": message})

    # --- success paths ---

    def test_produce_success_prints_message_count(self):
        msgs = [_make_message(subject="Hello"), _make_message(subject="World")]
        out = self._produce(self._ok_env(msgs))

        self.assertIn("Listed 2 message(s).", out)

    def test_produce_success_prints_subject(self):
        msgs = [_make_message(subject="Invoice #42")]
        out = self._produce(self._ok_env(msgs))

        self.assertIn("Invoice #42", out)

    def test_produce_success_prints_received_datetime(self):
        msgs = [_make_message(received="2025-06-01T09:30:00Z")]
        out = self._produce(self._ok_env(msgs))

        # receivedDateTime is truncated to 19 chars
        self.assertIn("2025-06-01T09:30:00", out)

    def test_produce_success_prints_from_address(self):
        msgs = [_make_message(from_address="alice@example.com")]
        out = self._produce(self._ok_env(msgs))

        self.assertIn("alice@example.com", out)

    def test_produce_success_truncates_subject_at_80_chars(self):
        long_subject = "X" * 90
        msgs = [_make_message(subject=long_subject)]
        out = self._produce(self._ok_env(msgs))

        # The printed line should NOT contain the full 90-char subject
        self.assertNotIn(long_subject, out)
        self.assertIn("X" * 80, out)

    def test_produce_empty_messages_prints_no_messages(self):
        out = self._produce(self._ok_env([]))

        self.assertIn("No messages.", out)

    def test_produce_empty_messages_does_not_print_count(self):
        out = self._produce(self._ok_env([]))

        self.assertNotIn("Listed", out)

    # --- error path ---

    def test_produce_error_envelope_prints_error_message(self):
        out = self._produce(self._err_env("Outlook service is required"))

        self.assertIn("Outlook service is required", out)

    def test_produce_error_envelope_does_not_print_count(self):
        out = self._produce(self._err_env("boom"))

        self.assertNotIn("Listed", out)

    # --- defensive: missing fields in message dict ---

    def test_produce_tolerates_missing_subject(self):
        msgs = [{"receivedDateTime": "2025-06-01T09:00:00Z", "from": {"emailAddress": {"address": "a@b.com"}}}]
        out = self._produce(self._ok_env(msgs))

        self.assertIn("Listed 1 message(s).", out)

    def test_produce_tolerates_missing_from(self):
        msgs = [{"subject": "No From", "receivedDateTime": "2025-06-01T09:00:00Z"}]
        out = self._produce(self._ok_env(msgs))

        self.assertIn("Listed 1 message(s).", out)

    def test_produce_tolerates_missing_received_datetime(self):
        msgs = [{"subject": "No Date", "from": {"emailAddress": {"address": "a@b.com"}}}]
        out = self._produce(self._ok_env(msgs))

        self.assertIn("Listed 1 message(s).", out)

    def test_produce_multiple_messages_prints_one_line_each(self):
        msgs = [
            _make_message(subject="First"),
            _make_message(subject="Second"),
            _make_message(subject="Third"),
        ]
        out = self._produce(self._ok_env(msgs))

        self.assertIn("First", out)
        self.assertIn("Second", out)
        self.assertIn("Third", out)
        self.assertIn("Listed 3 message(s).", out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
