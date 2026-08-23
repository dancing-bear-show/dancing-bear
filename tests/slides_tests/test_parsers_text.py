"""Unit tests for slides shared text/regex/chunking helpers (_parse_text)."""

import unittest

from slides._parse_text import (
    _chunk_slides,
    _extract_highlights,
    _normalize_title,
    _parse_bullet_line,
)
from slides.schema import BulletItem, SlideContent, TableSlide


# ---------------------------------------------------------------------------
# _normalize_title
# ---------------------------------------------------------------------------

class TestNormalizeTitle(unittest.TestCase):
    """Tests for _normalize_title helper."""

    _CASES = [
        ("Slide 1: Introduction", "Introduction", "colon-prefix"),
        ("Slide 2 - Details", "Details", "dash-prefix"),
        ("Slide 10 \u2014 Summary", "Summary", "em-dash-prefix"),
        ("slide 3: lower", "lower", "case-insensitive"),
        ("  Slide 4:  Spaced  ", "Spaced", "whitespace"),
        ("Hello World", "Hello World", "no-prefix"),
        ("", "", "empty-string"),
        ("   ", "", "whitespace-only"),
    ]

    def test_normalize_title(self):
        """Verify all prefix-stripping and edge-case behaviors."""
        for title, expected, label in self._CASES:
            with self.subTest(label=label, title=title):
                self.assertEqual(_normalize_title(title), expected)


# ---------------------------------------------------------------------------
# _extract_highlights
# ---------------------------------------------------------------------------

class TestExtractHighlights(unittest.TestCase):
    """Tests for _extract_highlights helper."""

    def test_bold_text(self):
        """Bold markdown produces highlight and cleaned text."""
        cleaned, highlights = _extract_highlights("Use **kubectl** carefully")
        self.assertEqual(cleaned, "Use kubectl carefully")
        self.assertEqual(highlights, ["kubectl"])

    def test_code_text(self):
        """Inline code produces highlight and cleaned text."""
        cleaned, highlights = _extract_highlights("Run `terraform plan` first")
        self.assertEqual(cleaned, "Run terraform plan first")
        self.assertEqual(highlights, ["terraform plan"])

    def test_mixed_bold_and_code(self):
        """Both bold and code are extracted as highlights."""
        cleaned, highlights = _extract_highlights("The **API** uses `gRPC` calls")
        self.assertEqual(cleaned, "The API uses gRPC calls")
        self.assertIn("API", highlights)
        self.assertIn("gRPC", highlights)

    def test_no_markdown(self):
        """Plain text returns unchanged with empty highlights."""
        cleaned, highlights = _extract_highlights("Plain text here")
        self.assertEqual(cleaned, "Plain text here")
        self.assertEqual(highlights, [])

    def test_multiple_bold(self):
        """Multiple bold segments are all captured."""
        cleaned, highlights = _extract_highlights("**A** and **B** items")
        self.assertEqual(cleaned, "A and B items")
        self.assertEqual(highlights, ["A", "B"])

    def test_empty_string(self):
        """Empty string returns empty string and no highlights."""
        cleaned, highlights = _extract_highlights("")
        self.assertEqual(cleaned, "")
        self.assertEqual(highlights, [])


# ---------------------------------------------------------------------------
# _parse_bullet_line
# ---------------------------------------------------------------------------

class TestParseBulletLine(unittest.TestCase):
    """Tests for _parse_bullet_line helper."""

    _BULLET_PREFIX_CASES = [
        ("- Item one", "Item one", "dash"),
        ("* Item two", "Item two", "asterisk"),
        ("\u2022 Item three", "Item three", "unicode"),
        ("1. Numbered item", "Numbered item", "numbered"),
        ("12. Double digit", "Double digit", "double-digit"),
    ]

    def test_bullet_prefixes(self):
        """All supported bullet prefixes are parsed correctly."""
        for line, expected_text, label in self._BULLET_PREFIX_CASES:
            with self.subTest(label=label, line=line):
                bullet = _parse_bullet_line(line)
                self.assertIsNotNone(bullet)
                self.assertEqual(bullet.text, expected_text)

    def test_indented_level_1(self):
        """Two-space indent maps to level 1."""
        bullet = _parse_bullet_line("  - Sub-item")
        self.assertIsNotNone(bullet)
        self.assertEqual(bullet.level, 1)
        self.assertEqual(bullet.text, "Sub-item")

    def test_indented_level_2(self):
        """Four-space indent maps to level 2."""
        bullet = _parse_bullet_line("    - Deep item")
        self.assertIsNotNone(bullet)
        self.assertEqual(bullet.level, 2)
        self.assertEqual(bullet.text, "Deep item")

    def test_deep_indent_capped_at_2(self):
        """Very deep indentation is capped at level 2."""
        bullet = _parse_bullet_line("        - Very deep")
        self.assertIsNotNone(bullet)
        self.assertEqual(bullet.level, 2)

    def test_non_bullet_line_returns_none(self):
        """Non-bullet line returns None."""
        self.assertIsNone(_parse_bullet_line("Just text"))
        self.assertIsNone(_parse_bullet_line(""))
        self.assertIsNone(_parse_bullet_line("# Heading"))

    def test_empty_bullet_text_returns_none(self):
        """Bullet with no text after prefix returns None."""
        self.assertIsNone(_parse_bullet_line("-   "))

    def test_bullet_with_highlights(self):
        """Inline markdown in bullets is extracted as highlights."""
        bullet = _parse_bullet_line("- Use **bold** here")
        self.assertIsNotNone(bullet)
        self.assertEqual(bullet.text, "Use bold here")
        self.assertEqual(bullet.highlight, ["bold"])


# ---------------------------------------------------------------------------
# _chunk_slides
# ---------------------------------------------------------------------------

class TestChunkSlides(unittest.TestCase):
    """Tests for _chunk_slides helper."""

    def _make_slide(self, title: str, bullet_count: int) -> SlideContent:
        """Factory to create a slide with N bullets."""
        bullets = [BulletItem(text=f"Bullet {i}") for i in range(bullet_count)]
        return SlideContent(title=title, subtitle="Sub", bullets=bullets, notes="Notes")

    def test_under_limit_unchanged(self):
        """Slides within the limit are returned unchanged."""
        slides = [self._make_slide("A", 3)]
        result = _chunk_slides(slides, bullet_limit=8)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "A")

    def test_exact_limit_unchanged(self):
        """Slide at exactly the limit is not split."""
        slides = [self._make_slide("A", 8)]
        result = _chunk_slides(slides, bullet_limit=8)
        self.assertEqual(len(result), 1)

    def test_over_limit_splits(self):
        """Slide exceeding limit is split into continuation slides."""
        slides = [self._make_slide("Long", 10)]
        result = _chunk_slides(slides, bullet_limit=4)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].title, "Long")
        self.assertEqual(result[1].title, "Long (cont.)")
        self.assertEqual(result[2].title, "Long (cont.)")
        self.assertEqual(len(result[0].bullets), 4)
        self.assertEqual(len(result[1].bullets), 4)
        self.assertEqual(len(result[2].bullets), 2)

    def test_continuation_loses_subtitle_and_notes(self):
        """Continuation slides do not carry subtitle or notes."""
        slides = [self._make_slide("S", 6)]
        result = _chunk_slides(slides, bullet_limit=3)
        self.assertEqual(result[0].subtitle, "Sub")
        self.assertEqual(result[0].notes, "Notes")
        self.assertIsNone(result[1].subtitle)
        self.assertIsNone(result[1].notes)

    def test_mixed_slides(self):
        """A mix of short and long slides is handled correctly."""
        slides = [
            self._make_slide("Short", 2),
            self._make_slide("Long", 5),
        ]
        result = _chunk_slides(slides, bullet_limit=3)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].title, "Short")
        self.assertEqual(result[1].title, "Long")
        self.assertEqual(result[2].title, "Long (cont.)")

    def test_table_slide_passed_through(self):
        """TableSlide instances are passed through without chunking."""
        table = TableSlide(title="Data", headers=["A", "B"], rows=[["1", "2"]])
        bullet = self._make_slide("Bullets", 3)
        result = _chunk_slides([table, bullet], bullet_limit=8)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], TableSlide)
        self.assertEqual(result[0].title, "Data")
        self.assertEqual(result[1].title, "Bullets")

    def test_empty_list(self):
        """Empty input returns empty output."""
        self.assertEqual(_chunk_slides([]), [])

    def test_zero_bullet_limit_returns_slides_unchanged(self):
        """bullet_limit=0 returns slides unchanged instead of raising ValueError."""
        slides = [self._make_slide("A", 5), self._make_slide("B", 3)]
        result = _chunk_slides(slides, bullet_limit=0)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].title, "A")
        self.assertEqual(len(result[0].bullets), 5)
        self.assertEqual(result[1].title, "B")
        self.assertEqual(len(result[1].bullets), 3)

    def test_negative_bullet_limit_returns_slides_unchanged(self):
        """Negative bullet_limit returns slides unchanged."""
        slides = [self._make_slide("X", 4)]
        result = _chunk_slides(slides, bullet_limit=-1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "X")

if __name__ == "__main__":
    unittest.main()
