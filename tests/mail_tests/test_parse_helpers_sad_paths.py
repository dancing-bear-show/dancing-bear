"""Sad-path tests for mail parse/convert helpers.

These functions all swallow malformed input and return a default. That is the
right behaviour for provider data we do not control, but it means a regression
inside them is invisible: no exception, just a quietly wrong or empty value.
These tests pin the intended defaults so the silence stays deliberate.

Companion to the --send-in parser fix on this branch, which was the one case
in this sweep where malformed input produced a plausible WRONG value rather
than a default.
"""

from __future__ import annotations

import base64
import unittest


class TestHeadersToDict(unittest.TestCase):
    """GmailClient.headers_to_dict tolerates every shape of malformed payload."""

    def _call(self, msg):
        from mail.gmail_api import GmailClient
        return GmailClient.headers_to_dict(msg)

    def test_empty_message(self):
        self.assertEqual(self._call({}), {})

    def test_missing_and_null_payload(self):
        for msg in ({}, {"payload": None}, {"payload": {}}):
            with self.subTest(msg=msg):
                self.assertEqual(self._call(msg), {})

    def test_null_headers(self):
        self.assertEqual(self._call({"payload": {"headers": None}}), {})

    def test_non_list_headers_does_not_raise(self):
        """A string is iterable, so the guard must survive element access."""
        self.assertEqual(self._call({"payload": {"headers": "notalist"}}), {})

    def test_header_without_name_is_skipped(self):
        msg = {"payload": {"headers": [{"name": None, "value": "x"}]}}
        self.assertEqual(self._call(msg), {})

    def test_header_with_none_value_is_skipped(self):
        msg = {"payload": {"headers": [{"name": "To", "value": None}]}}
        self.assertEqual(self._call(msg), {})

    def test_empty_string_value_is_kept(self):
        """'' is a real header value; only None means absent."""
        msg = {"payload": {"headers": [{"name": "Subject", "value": ""}]}}
        self.assertEqual(self._call(msg), {"subject": ""})

    def test_names_are_lowercased(self):
        msg = {"payload": {"headers": [{"name": "SuBjEcT", "value": "hi"}]}}
        self.assertEqual(self._call(msg), {"subject": "hi"})

    def test_duplicate_header_last_wins(self):
        """Documents a real lossy behaviour: repeated headers collapse."""
        msg = {"payload": {"headers": [
            {"name": "To", "value": "first@example.com"},
            {"name": "To", "value": "second@example.com"},
        ]}}
        self.assertEqual(self._call(msg), {"to": "second@example.com"})


class TestDecodeMessageData(unittest.TestCase):
    """GmailClient._decode_message_data returns '' rather than raising."""

    def _call(self, data):
        from mail.gmail_api import GmailClient
        return GmailClient._decode_message_data(data)

    def test_valid_base64_round_trips(self):
        encoded = base64.urlsafe_b64encode(b"hello world").decode("utf-8")
        self.assertEqual(self._call(encoded), "hello world")

    def test_urlsafe_alphabet_is_used(self):
        """'-' and '_' must decode; standard-alphabet decoding would differ."""
        raw = b"\xfb\xff\xfe"
        self.assertEqual(self._call(base64.urlsafe_b64encode(raw).decode()), raw.decode("utf-8", "replace"))

    def test_invalid_base64_returns_empty(self):
        self.assertEqual(self._call("!!!notbase64!!!"), "")

    def test_wrong_padding_returns_empty(self):
        self.assertEqual(self._call("aGVsbG8"), "")

    def test_empty_input_returns_empty(self):
        self.assertEqual(self._call(""), "")

    def test_non_utf8_bytes_are_replaced_not_dropped(self):
        """errors='replace' keeps the message readable instead of returning ''."""
        encoded = base64.urlsafe_b64encode(b"\xff\xfe").decode("utf-8")
        self.assertNotEqual(self._call(encoded), "")


class TestGraphDatetimeToIso(unittest.TestCase):
    """_graph_datetime_to_iso normalises Graph timestamps to the Gmail format."""

    def _call(self, value):
        from mail.messages_cli.pipeline import _graph_datetime_to_iso
        return _graph_datetime_to_iso(value)

    def test_z_suffix_passthrough(self):
        self.assertEqual(self._call("2026-08-12T10:00:00Z"), "2026-08-12T10:00:00Z")

    def test_explicit_offset_normalised_to_z(self):
        self.assertEqual(self._call("2026-08-12T10:00:00+00:00"), "2026-08-12T10:00:00Z")

    def test_subsecond_precision_is_truncated(self):
        self.assertEqual(self._call("2026-08-12T10:00:00.1234567Z"), "2026-08-12T10:00:00Z")

    def test_non_utc_offset_is_converted(self):
        self.assertEqual(self._call("2026-08-12T12:00:00+02:00"), "2026-08-12T10:00:00Z")

    def test_naive_datetime_assumed_utc(self):
        self.assertEqual(self._call("2026-08-12 10:00:00"), "2026-08-12T10:00:00Z")

    def test_empty_and_none_return_empty(self):
        for value in ("", None, "   "):
            with self.subTest(value=value):
                self.assertEqual(self._call(value), "")

    def test_unparseable_value_passes_through_unchanged(self):
        """Deliberate: showing Graph's raw string beats showing nothing.

        Safe only because this field is display-only -- it is never used for
        sorting or comparison. If that changes, this fallback becomes a bug.
        """
        self.assertEqual(self._call("not-a-date"), "not-a-date")

    def test_matches_gmail_side_format(self):
        """Both providers must agree, or mixed listings sort inconsistently."""
        from mail.messages import _internal_date_to_iso
        gmail = _internal_date_to_iso(1786543200000)
        graph = self._call("2026-08-12T10:00:00Z")
        self.assertRegex(gmail, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertRegex(graph, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


if __name__ == "__main__":
    unittest.main()
