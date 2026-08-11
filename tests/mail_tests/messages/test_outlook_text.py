"""Tests for Outlook message body extraction."""
from __future__ import annotations

import unittest

from mail.messages_cli.outlook_text import outlook_message_text


def graph_message(content: str, content_type: str = "html", **extra) -> dict:
    """Build a Graph message with a body of the given content type."""
    msg = {"body": {"contentType": content_type, "content": content}}
    msg.update(extra)
    return msg


class TestOutlookMessageText(unittest.TestCase):
    """Body extraction across content types and fallbacks."""

    def test_html_body_is_converted_to_text(self):
        msg = graph_message("<p>Hello</p><p>World</p>")

        result = outlook_message_text(msg)

        self.assertIn("Hello", result)
        self.assertIn("World", result)
        self.assertNotIn("<p>", result)

    def test_html_entities_are_unescaped(self):
        msg = graph_message("<p>Tom &amp; Jerry</p>")

        self.assertIn("Tom & Jerry", outlook_message_text(msg))

    def test_text_body_passes_through(self):
        msg = graph_message("Plain body line", content_type="text")

        self.assertIn("Plain body line", outlook_message_text(msg))

    def test_css_boilerplate_is_stripped(self):
        """Transactional senders flatten CSS into the body; it must not survive."""
        msg = graph_message(
            "<style>.a { color: red; }</style><p>Real content</p>"
        )

        result = outlook_message_text(msg)

        self.assertIn("Real content", result)
        self.assertNotIn("color: red", result)

    def test_falls_back_to_body_preview(self):
        """With no body, bodyPreview is the best available text."""
        msg = {"bodyPreview": "Preview text only"}

        self.assertEqual(outlook_message_text(msg), "Preview text only")

    def test_empty_body_falls_back_to_preview(self):
        msg = graph_message("", content_type="html", bodyPreview="Fallback")

        self.assertEqual(outlook_message_text(msg), "Fallback")

    def test_missing_everything_returns_empty_string(self):
        self.assertEqual(outlook_message_text({}), "")

    def test_none_message_returns_empty_string(self):
        self.assertEqual(outlook_message_text(None), "")

    def test_unknown_content_type_is_treated_as_html(self):
        """Graph only documents html/text; anything else is safest as HTML."""
        msg = graph_message("<b>Bold</b>", content_type="richText")

        result = outlook_message_text(msg)

        self.assertIn("Bold", result)
        self.assertNotIn("<b>", result)

    def test_content_type_is_case_insensitive(self):
        msg = graph_message("Plain line", content_type="TEXT")

        self.assertIn("Plain line", outlook_message_text(msg))


if __name__ == "__main__":
    unittest.main()
