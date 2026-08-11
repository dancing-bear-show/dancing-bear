"""Tests for the Outlook search path: single-fetch results and field mapping.

Covers the N+1 removal (one ``search_inbox_message_dicts`` call instead of a
``get_message`` per ID) and the Graph -> MessageCandidate field mapping,
including the deliberate ``has_attachment`` provider asymmetry.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from mail.messages_cli.pipeline import (
    MessageCandidate,
    MessagesSearchRequest,
    MessagesSearchResult,
    MessagesSearchProducer,
    OutlookMessagesSearchProcessor,
    _outlook_msg_to_candidate,
)


def graph_message(mid: str = "m1", **overrides) -> dict:
    """Build a Graph message payload with sensible defaults."""
    msg = {
        "id": mid,
        "subject": "Receipt",
        "receivedDateTime": "2026-03-01T21:00:00Z",
        "from": {"emailAddress": {"name": "Store", "address": "no-reply@store.com"}},
        "toRecipients": [{"emailAddress": {"name": "Me", "address": "me@example.com"}}],
        "bodyPreview": "  your order  ",
        "hasAttachments": True,
        "conversationId": "conv-1",
        "isRead": False,
    }
    msg.update(overrides)
    return msg


class TestOutlookSearchAvoidsNPlusOne(unittest.TestCase):
    """The processor must fetch dicts once, never get_message per ID."""

    def _run(self, messages, max_results=5):
        client = MagicMock()
        client.search_inbox_message_dicts.return_value = messages
        request = MessagesSearchRequest(query="receipt", max_results=max_results)
        result = OutlookMessagesSearchProcessor(client)._process_safe(request)
        return result, client

    def test_does_not_call_get_message(self):
        _result, client = self._run([graph_message("m1"), graph_message("m2")])

        client.get_message.assert_not_called()

    def test_issues_a_single_search_call(self):
        _result, client = self._run([graph_message("m1"), graph_message("m2")])

        client.search_inbox_message_dicts.assert_called_once()

    def test_passes_raw_query_to_search_params(self):
        """Contract: the term reaches SearchParams raw, unquoted."""
        _result, client = self._run([])

        params = client.search_inbox_message_dicts.call_args[0][0]
        self.assertEqual(params.search_query, "receipt")

    def test_returns_one_candidate_per_message(self):
        result, _client = self._run([graph_message("m1"), graph_message("m2")])

        self.assertEqual([c.id for c in result.candidates], ["m1", "m2"])

    def test_respects_max_results_ceiling(self):
        msgs = [graph_message(f"m{i}") for i in range(10)]
        result, _client = self._run(msgs, max_results=3)

        self.assertEqual(len(result.candidates), 3)


class TestOutlookCandidateMapping(unittest.TestCase):
    """Graph fields must reach MessageCandidate, not silently default."""

    def test_maps_subject_and_snippet(self):
        cand = _outlook_msg_to_candidate("m1", graph_message())

        self.assertEqual(cand.subject, "Receipt")
        self.assertEqual(cand.snippet, "your order")

    def test_maps_from_header_with_name(self):
        cand = _outlook_msg_to_candidate("m1", graph_message())

        self.assertEqual(cand.from_header, "Store <no-reply@store.com>")

    def test_from_header_without_name_is_bare_address(self):
        msg = graph_message(**{"from": {"emailAddress": {"address": "a@b.com"}}})
        cand = _outlook_msg_to_candidate("m1", msg)

        self.assertEqual(cand.from_header, "a@b.com")

    def test_maps_to_header(self):
        cand = _outlook_msg_to_candidate("m1", graph_message())

        self.assertIn("me@example.com", cand.to_header)

    def test_joins_multiple_recipients(self):
        msg = graph_message(toRecipients=[
            {"emailAddress": {"address": "a@x.com"}},
            {"emailAddress": {"address": "b@x.com"}},
        ])
        cand = _outlook_msg_to_candidate("m1", msg)

        self.assertIn("a@x.com", cand.to_header)
        self.assertIn("b@x.com", cand.to_header)

    def test_maps_date_as_iso_utc(self):
        cand = _outlook_msg_to_candidate("m1", graph_message())

        self.assertEqual(cand.date, "2026-03-01T21:00:00Z")

    def test_normalizes_fractional_seconds_to_iso_utc(self):
        """Graph may return sub-second precision; match the Gmail-side format."""
        msg = graph_message(receivedDateTime="2026-03-01T21:00:00.1234567Z")
        cand = _outlook_msg_to_candidate("m1", msg)

        self.assertEqual(cand.date, "2026-03-01T21:00:00Z")

    def test_missing_date_is_empty_string(self):
        msg = graph_message()
        del msg["receivedDateTime"]

        self.assertEqual(_outlook_msg_to_candidate("m1", msg).date, "")

    def test_unread_is_true_when_not_read(self):
        cand = _outlook_msg_to_candidate("m1", graph_message(isRead=False))

        self.assertTrue(cand.unread)

    def test_unread_is_false_when_read(self):
        cand = _outlook_msg_to_candidate("m1", graph_message(isRead=True))

        self.assertFalse(cand.unread)

    def test_has_attachment_is_populated_on_outlook(self):
        cand = _outlook_msg_to_candidate("m1", graph_message(hasAttachments=True))

        self.assertIs(cand.has_attachment, True)

    def test_has_attachment_false_is_preserved_on_outlook(self):
        """False means 'genuinely none' on Outlook, unlike Gmail's unknown."""
        cand = _outlook_msg_to_candidate("m1", graph_message(hasAttachments=False))

        self.assertIs(cand.has_attachment, False)


class TestHasAttachmentProviderAsymmetry(unittest.TestCase):
    """has_attachment is emitted for Outlook and omitted for Gmail."""

    def _json_for(self, candidate) -> dict:
        producer = MessagesSearchProducer(output_json=True)
        printed = []
        producer._write = printed.append  # not used by _produce_success; kept harmless
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            producer._produce_success(MessagesSearchResult(candidates=[candidate]), None)
        return json.loads(buf.getvalue())[0]

    def test_outlook_candidate_includes_key(self):
        cand = _outlook_msg_to_candidate("m1", graph_message(hasAttachments=True))

        self.assertIn("has_attachment", self._json_for(cand))

    def test_gmail_candidate_omits_key_entirely(self):
        """Gmail's format=metadata lacks payload.parts; false would be a lie."""
        cand = MessageCandidate(id="g1", subject="s", from_header="f", snippet="x")

        self.assertNotIn("has_attachment", self._json_for(cand))

    def test_gmail_candidate_still_emits_other_fields(self):
        cand = MessageCandidate(id="g1", subject="s", from_header="f", snippet="x")
        payload = self._json_for(cand)

        self.assertEqual(payload["id"], "g1")
        self.assertIn("unread", payload)


if __name__ == "__main__":
    unittest.main()
