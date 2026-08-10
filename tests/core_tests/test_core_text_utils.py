"""Tests for core.text_utils.strip_css_boilerplate."""

import unittest

from core.text_utils import strip_css_boilerplate


class TestStripCssBoilerplate(unittest.TestCase):
    def test_strips_leading_css_block_and_keeps_content(self):
        body = (
            "/* Client-specific Styles */\n"
            "#outlook a{padding:0;} /* Force Outlook to provide a view in browser button. */\n"
            "body{width:100% !important;}\n"
            ".ReadMsgBody{width:100%;}\n"
            ".ExternalClass{width:100%;}\n"
            ".td-txlineitems-right { width: 40%; }\n"
            "Dear Brian,\n\n"
            "Thank you for choosing Massage Addict Richmond Hill\n\n"
            "** RECEIPT OF SALE **\n\n"
            "Grand Total $90.00\n"
            "---- Payments ----\n"
            "REQUESTED - Sun Life $90.00\n"
        )

        result = strip_css_boilerplate(body)

        # CSS is gone.
        self.assertNotIn("/*", result)
        self.assertNotIn("ReadMsgBody", result)
        self.assertNotIn("ExternalClass", result)
        self.assertNotIn("td-txlineitems-right", result)
        # Real content survives.
        self.assertIn("Dear Brian,", result)
        self.assertIn("Massage Addict Richmond Hill", result)
        self.assertIn("RECEIPT OF SALE", result)
        self.assertIn("Grand Total $90.00", result)
        self.assertIn("REQUESTED - Sun Life $90.00", result)

    def test_plain_text_without_css_is_byte_identical(self):
        body = "Hi there,\n\nYour balance due is $0.00. Thanks!\n\nBest,\nTeam"
        self.assertEqual(strip_css_boilerplate(body), body)

    def test_prose_with_braces_is_not_mangled(self):
        body = "Note: { see attached } for details. Balance Due { $0.00 } as of today."
        self.assertEqual(strip_css_boilerplate(body), body)

    def test_style_tag_survives_html_to_text_is_stripped(self):
        body = "<style>body{color:red;} .foo{font-weight:bold;}</style>Hello there"
        result = strip_css_boilerplate(body)
        self.assertNotIn("<style>", result)
        self.assertNotIn("color:red", result)
        self.assertIn("Hello there", result)

    def test_comma_separated_selector_list_stripped(self):
        body = "h1, h2, .title, #header {\n  font-family: Arial;\n  color: #333;\n}\nWelcome to our newsletter."
        result = strip_css_boilerplate(body)
        self.assertNotIn("font-family", result)
        self.assertIn("Welcome to our newsletter.", result)

    def test_media_query_with_nested_rule_stripped(self):
        body = (
            "@media only screen and (max-width:480px) {\n"
            "  .container { width: 100% !important; }\n"
            "}\n"
            "Hello world"
        )
        result = strip_css_boilerplate(body)
        self.assertNotIn("container", result)
        self.assertNotIn("max-width", result)
        self.assertIn("Hello world", result)

    def test_empty_string_returns_empty(self):
        self.assertEqual(strip_css_boilerplate(""), "")

    def test_store_hours_style_braces_not_mistaken_for_css(self):
        body = "Store hours: { Mon-Fri 9-5 }"
        self.assertEqual(strip_css_boilerplate(body), body)


if __name__ == "__main__":
    unittest.main()
