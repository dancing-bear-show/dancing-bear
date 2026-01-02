"""Tests for resume/docx_styles.py styling utilities."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from tests.resume_tests.fixtures import mock_docx_modules


@mock_docx_modules
class TestStyleManagerColorUtils(unittest.TestCase):
    """Tests for StyleManager color utilities."""

    def test_parse_hex_color_valid(self):
        """Test parsing valid hex color."""
        from resume.docx_styles import StyleManager
        result = StyleManager.parse_hex_color("#FF0000")
        self.assertEqual(result, (255, 0, 0))

    def test_parse_hex_color_no_hash(self):
        """Test parsing hex color without hash."""
        from resume.docx_styles import StyleManager
        result = StyleManager.parse_hex_color("00FF00")
        self.assertEqual(result, (0, 255, 0))

    def test_parse_hex_color_invalid_length(self):
        """Test parsing invalid hex color length."""
        from resume.docx_styles import StyleManager
        result = StyleManager.parse_hex_color("#FFF")
        self.assertIsNone(result)

    def test_parse_hex_color_none(self):
        """Test parsing None returns None."""
        from resume.docx_styles import StyleManager
        result = StyleManager.parse_hex_color(None)
        self.assertIsNone(result)

    def test_parse_hex_color_empty(self):
        """Test parsing empty string returns None."""
        from resume.docx_styles import StyleManager
        result = StyleManager.parse_hex_color("")
        self.assertIsNone(result)

    def test_hex_fill(self):
        """Test converting RGB to hex fill string."""
        from resume.docx_styles import StyleManager
        result = StyleManager.hex_fill((255, 128, 0))
        self.assertEqual(result, "FF8000")

    def test_is_dark_dark_color(self):
        """Test is_dark with dark color."""
        from resume.docx_styles import StyleManager
        self.assertTrue(StyleManager.is_dark((0, 0, 0)))
        self.assertTrue(StyleManager.is_dark((50, 50, 50)))

    def test_is_dark_light_color(self):
        """Test is_dark with light color."""
        from resume.docx_styles import StyleManager
        self.assertFalse(StyleManager.is_dark((255, 255, 255)))
        self.assertFalse(StyleManager.is_dark((200, 200, 200)))

    def test_auto_contrast_color_dark_bg(self):
        """Test auto contrast for dark background."""
        from resume.docx_styles import StyleManager
        result = StyleManager.auto_contrast_color((0, 0, 0))
        self.assertEqual(result, "#FFFFFF")

    def test_auto_contrast_color_light_bg(self):
        """Test auto contrast for light background."""
        from resume.docx_styles import StyleManager
        result = StyleManager.auto_contrast_color((255, 255, 255))
        self.assertEqual(result, "#000000")


@mock_docx_modules
class TestStyleManagerParagraphFormatting(unittest.TestCase):
    """Tests for StyleManager paragraph formatting methods."""

    def _get_fake_paragraph(self):
        """Create a fake paragraph object."""
        p = MagicMock()
        p.paragraph_format = MagicMock()
        return p

    def test_tight_paragraph(self):
        """Test tight paragraph formatting."""
        from resume.docx_styles import StyleManager
        p = self._get_fake_paragraph()

        StyleManager.tight_paragraph(p, before_pt=6, after_pt=2)

        # Verify spacing was set
        self.assertIsNotNone(p.paragraph_format)

    def test_compact_bullet(self):
        """Test compact bullet formatting."""
        from resume.docx_styles import StyleManager
        p = self._get_fake_paragraph()

        StyleManager.compact_bullet(p)

        # Should not raise
        self.assertIsNotNone(p.paragraph_format)

    def test_flush_left(self):
        """Test flush left alignment."""
        from resume.docx_styles import StyleManager
        p = self._get_fake_paragraph()

        StyleManager.flush_left(p)

        self.assertIsNotNone(p.paragraph_format)

    def test_center_paragraph(self):
        """Test center paragraph alignment."""
        from resume.docx_styles import StyleManager
        p = self._get_fake_paragraph()

        StyleManager.center_paragraph(p)

        self.assertIsNotNone(p.paragraph_format)


@mock_docx_modules
class TestStyleManagerRunFormatting(unittest.TestCase):
    """Tests for StyleManager run formatting methods."""

    def _get_fake_run(self):
        """Create a fake run object."""
        run = MagicMock()
        run.font = MagicMock()
        run.font.color = MagicMock()
        return run

    def test_apply_run_color_valid(self):
        """Test applying valid color to run."""
        from resume.docx_styles import StyleManager
        run = self._get_fake_run()

        StyleManager.apply_run_color(run, "#FF0000")

        # Should not raise

    def test_apply_run_color_none(self):
        """Test applying None color is no-op."""
        from resume.docx_styles import StyleManager
        run = self._get_fake_run()

        StyleManager.apply_run_color(run, None)

        # Should not raise

    def test_apply_run_size(self):
        """Test applying font size to run."""
        from resume.docx_styles import StyleManager
        run = self._get_fake_run()

        StyleManager.apply_run_size(run, 12.0)

        # Should not raise

    def test_apply_run_size_none(self):
        """Test applying None size is no-op."""
        from resume.docx_styles import StyleManager
        run = self._get_fake_run()

        StyleManager.apply_run_size(run, None)

        # Should not raise


@mock_docx_modules
class TestTextFormatter(unittest.TestCase):
    """Tests for TextFormatter class."""

    def test_normalize_present_variants(self):
        """Test normalizing present-like values."""
        from resume.docx_styles import TextFormatter
        self.assertEqual(TextFormatter.normalize_present("now"), "Present")
        self.assertEqual(TextFormatter.normalize_present("present"), "Present")
        self.assertEqual(TextFormatter.normalize_present("current"), "Present")
        self.assertEqual(TextFormatter.normalize_present("to date"), "Present")
        self.assertEqual(TextFormatter.normalize_present("today"), "Present")

    def test_normalize_present_regular_date(self):
        """Test normalizing regular date values."""
        from resume.docx_styles import TextFormatter
        self.assertEqual(TextFormatter.normalize_present("2023"), "2023")
        self.assertEqual(TextFormatter.normalize_present("Dec 2023"), "Dec 2023")

    def test_normalize_present_empty(self):
        """Test normalizing empty value."""
        from resume.docx_styles import TextFormatter
        self.assertEqual(TextFormatter.normalize_present(""), "")
        self.assertEqual(TextFormatter.normalize_present("  "), "")

    def test_format_date_span_start_end(self):
        """Test formatting date span with start and end."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.format_date_span("2020", "2023")
        self.assertEqual(result, "2020 – 2023")

    def test_format_date_span_start_only(self):
        """Test formatting date span with start only."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.format_date_span("2020", "")
        self.assertEqual(result, "2020 – Present")

    def test_format_date_span_end_only(self):
        """Test formatting date span with end only."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.format_date_span("", "2023")
        self.assertEqual(result, "2023")

    def test_format_date_span_empty(self):
        """Test formatting date span with neither."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.format_date_span("", "")
        self.assertEqual(result, "")

    def test_format_date_span_normalizes_present(self):
        """Test format_date_span normalizes present values."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.format_date_span("2020", "now")
        self.assertEqual(result, "2020 – Present")

    def test_format_date_location(self):
        """Test formatting date and location together."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.format_date_location("2020", "2023", "New York")
        self.assertEqual(result, "2020 – 2023 · New York")

    def test_format_date_location_no_location(self):
        """Test formatting date without location."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.format_date_location("2020", "2023", "")
        self.assertEqual(result, "2020 – 2023")

    def test_format_phone_10_digits(self):
        """Test formatting 10-digit phone number."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.format_phone("5551234567")
        self.assertEqual(result, "(555) 123-4567")

    def test_format_phone_11_digits(self):
        """Test formatting 11-digit phone number."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.format_phone("15551234567")
        self.assertEqual(result, "+1 (555) 123-4567")

    def test_format_phone_already_formatted(self):
        """Test phone that's already formatted."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.format_phone("(555) 123-4567")
        self.assertEqual(result, "(555) 123-4567")

    def test_format_phone_international(self):
        """Test international phone number passthrough."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.format_phone("+54 9 1167929561")
        self.assertEqual(result, "+54 9 1167929561")

    def test_format_link_strips_scheme(self):
        """Test format_link strips http/https."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.format_link("https://example.com/path")
        self.assertEqual(result, "example.com/path")

    def test_format_link_strips_www(self):
        """Test format_link strips www."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.format_link("https://www.example.com")
        self.assertEqual(result, "example.com")

    def test_format_link_strips_trailing_slash(self):
        """Test format_link strips trailing slash."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.format_link("https://example.com/")
        self.assertEqual(result, "example.com")

    def test_clean_inline_removes_bullets(self):
        """Test clean_inline removes bullet characters."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.clean_inline("• First point • Second point")
        self.assertEqual(result, "First point Second point")

    def test_clean_inline_collapses_whitespace(self):
        """Test clean_inline collapses whitespace."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.clean_inline("Multiple   spaces   here")
        self.assertEqual(result, "Multiple spaces here")

    def test_normalize_bullet_strips_period(self):
        """Test normalize_bullet strips terminal period."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.normalize_bullet("This is a sentence.")
        self.assertEqual(result, "This is a sentence")

    def test_normalize_bullet_keeps_period(self):
        """Test normalize_bullet can keep period."""
        from resume.docx_styles import TextFormatter
        result = TextFormatter.normalize_bullet("This is a sentence.", strip_terminal_period=False)
        self.assertEqual(result, "This is a sentence.")


@mock_docx_modules
class TestBackwardCompatAliases(unittest.TestCase):
    """Tests for backward-compatible function aliases."""

    def test_parse_hex_color_alias(self):
        """Test _parse_hex_color alias works."""
        from resume.docx_styles import _parse_hex_color
        result = _parse_hex_color("#FF0000")
        self.assertEqual(result, (255, 0, 0))

    def test_is_dark_alias(self):
        """Test _is_dark alias works."""
        from resume.docx_styles import _is_dark
        self.assertTrue(_is_dark((0, 0, 0)))

    def test_format_phone_display_alias(self):
        """Test _format_phone_display alias works."""
        from resume.docx_styles import _format_phone_display
        result = _format_phone_display("5551234567")
        self.assertEqual(result, "(555) 123-4567")

    def test_format_link_display_alias(self):
        """Test _format_link_display alias works."""
        from resume.docx_styles import _format_link_display
        result = _format_link_display("https://example.com")
        self.assertEqual(result, "example.com")


if __name__ == "__main__":
    unittest.main()
