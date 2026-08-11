"""Tests for provider-agnostic ``messages get`` / ``messages summarize``.

Both commands dispatch on ``is_outlook_profile`` the way ``messages search``
already does. The Gmail path must be unchanged; the Outlook path builds its
record from Graph fields and extracts body text via ``outlook_message_text``.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from mail.messages_cli.commands import run_messages_get, run_messages_summarize
from tests.fixtures import capture_stdout
from tests.mail_tests.fixtures import make_args


def graph_message(mid: str = "OLK1", **overrides) -> dict:
    """Build a Graph message payload as get_message would return it."""
    msg = {
        "id": mid,
        "subject": "Order receipt",
        "receivedDateTime": "2026-03-01T21:00:00Z",
        "from": {"emailAddress": {"name": "Store", "address": "no-reply@store.com"}},
        "toRecipients": [{"emailAddress": {"name": "Me", "address": "me@example.com"}}],
        "body": {"contentType": "html", "content": "<p>Your order shipped.</p>"},
        "bodyPreview": "Your order shipped.",
        "isRead": True,
        "conversationId": "conv-1",
    }
    msg.update(overrides)
    return msg


class OutlookGetTestBase(unittest.TestCase):
    """Shared harness: force the Outlook branch with a fake client."""

    def _run_get(self, client, **arg_overrides):
        arg_overrides.setdefault("id", "OLK1")
        arg_overrides.setdefault("format", "text")
        arg_overrides.setdefault("profile", "outlook_personal")
        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True), \
             patch("mail.utils.cli_helpers.outlook_client_from_args", return_value=client):
            with capture_stdout() as buf:
                rc = run_messages_get(make_args(**arg_overrides))
        return rc, buf.getvalue()


class TestOutlookGet(OutlookGetTestBase):
    """`messages get` against an Outlook profile."""

    def _client(self, msg=None):
        client = MagicMock()
        client.get_message.return_value = msg if msg is not None else graph_message()
        return client

    def test_text_format_prints_headers_and_body(self):
        rc, out = self._run_get(self._client())

        self.assertEqual(rc, 0)
        self.assertIn("Subject: Order receipt", out)
        self.assertIn("From: Store <no-reply@store.com>", out)
        self.assertIn("Your order shipped.", out)

    def test_body_html_is_converted_to_text(self):
        _rc, out = self._run_get(self._client())

        self.assertNotIn("<p>", out)

    def test_json_format_emits_expected_fields(self):
        rc, out = self._run_get(self._client(), format="json")
        data = json.loads(out)

        self.assertEqual(rc, 0)
        self.assertEqual(data["id"], "OLK1")
        self.assertEqual(data["subject"], "Order receipt")
        self.assertEqual(data["from_header"], "Store <no-reply@store.com>")
        self.assertIn("me@example.com", data["to_header"])
        self.assertIn("Your order shipped.", data["body"])

    def test_date_is_iso_utc(self):
        _rc, out = self._run_get(self._client(), format="json")

        self.assertEqual(json.loads(out)["date"], "2026-03-01T21:00:00Z")

    def test_does_not_call_gmail_provider(self):
        """The Outlook branch must not build a Gmail client."""
        client = self._client()
        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True), \
             patch("mail.utils.cli_helpers.outlook_client_from_args", return_value=client), \
             patch("mail.utils.cli_helpers.gmail_provider_from_args") as gmail:
            with capture_stdout():
                run_messages_get(make_args(id="OLK1", format="text", profile="outlook_personal"))

        gmail.assert_not_called()

    def test_missing_selector_returns_error(self):
        rc, _out = self._run_get(self._client(), id=None)

        self.assertEqual(rc, 1)

    def test_fetch_failure_returns_error(self):
        client = MagicMock()
        client.get_message.side_effect = RuntimeError("graph down")

        rc, _out = self._run_get(client)

        self.assertEqual(rc, 1)


class TestOutlookSummarize(unittest.TestCase):
    """`messages summarize` against an Outlook profile."""

    def _run(self, client, **arg_overrides):
        arg_overrides.setdefault("id", "OLK1")
        arg_overrides.setdefault("profile", "outlook_personal")
        arg_overrides.setdefault("max_words", 40)
        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True), \
             patch("mail.utils.cli_helpers.outlook_client_from_args", return_value=client), \
             patch("mail.llm_adapter.summarize_text", side_effect=lambda t, max_words=120: t[:60]):
            with capture_stdout() as buf:
                rc = run_messages_summarize(make_args(**arg_overrides))
        return rc, buf.getvalue()

    def test_summarizes_outlook_body(self):
        client = MagicMock()
        client.get_message.return_value = graph_message()

        rc, out = self._run(client)

        self.assertEqual(rc, 0)
        self.assertIn("Your order shipped", out)

    def test_uses_body_not_css_boilerplate(self):
        """Regression guard mirroring the Gmail-side bodyPreview bug."""
        css = "/* Client-specific Styles */ #outlook a{padding:0;}"
        client = MagicMock()
        client.get_message.return_value = graph_message(
            body={"contentType": "html", "content": f"<style>{css}</style><p>Total: $90.00</p>"},
            bodyPreview=css,
        )

        _rc, out = self._run(client)

        self.assertIn("Total: $90.00", out)
        self.assertNotIn("padding:0", out)

    def test_does_not_call_gmail_provider(self):
        client = MagicMock()
        client.get_message.return_value = graph_message()
        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=True), \
             patch("mail.utils.cli_helpers.outlook_client_from_args", return_value=client), \
             patch("mail.llm_adapter.summarize_text", side_effect=lambda t, max_words=120: t[:60]), \
             patch("mail.utils.cli_helpers.gmail_provider_from_args") as gmail:
            with capture_stdout():
                run_messages_summarize(make_args(id="OLK1", profile="outlook_personal", max_words=40))

        gmail.assert_not_called()


class TestGmailPathUnchanged(unittest.TestCase):
    """The Gmail branch must be untouched by the dispatch."""

    def test_gmail_get_still_uses_gmail_provider(self):
        client = MagicMock()
        client.get_message.return_value = {
            "payload": {"headers": [
                {"name": "Subject", "value": "Hi"},
                {"name": "From", "value": "a@b.com"},
            ]}
        }
        client.get_message_text.return_value = "body text"

        with patch("mail.utils.cli_helpers.is_outlook_profile", return_value=False), \
             patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            with capture_stdout() as buf:
                rc = run_messages_get(make_args(id="G1", format="text"))

        self.assertEqual(rc, 0)
        self.assertIn("body text", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
