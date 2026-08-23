"""Unit tests for slides parsers module."""

import tempfile
import unittest
from pathlib import Path

from slides.constants import (
    DEFAULT_TEMPLATE_SLIDE_INDEX,
    DEFAULT_THEME_COLOR,
    LAYOUT_BULLET,
    LAYOUT_SECTION,
)
from slides.parsers import (
    _body_to_bullets,
    _chunk_slides,
    _extract_highlights,
    _normalize_title,
    _parse_bullet_line,
    _parse_bullets,
    _parse_markdown_section,
    _parse_slide,
    load_deck_from_csv,
    load_deck_from_dict,
    load_deck_from_markdown,
    load_deck_from_outline,
)
from slides.schema import (
    BulletItem,
    SlideContent,
    SlideDeck,
    TableSlide,
)

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
# _parse_bullets
# ---------------------------------------------------------------------------

class TestParseBullets(unittest.TestCase):
    """Tests for _parse_bullets helper — dict bold, list/tuple shorthand."""

    def test_string_bullet(self):
        result = _parse_bullets(["hello"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "hello")
        self.assertEqual(result[0].level, 0)
        self.assertFalse(result[0].bold)

    def test_dict_bullet_with_bold_true(self):
        result = _parse_bullets([{"text": "important", "bold": True}])
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].bold)

    def test_dict_bullet_with_bold_false(self):
        result = _parse_bullets([{"text": "normal", "bold": False}])
        self.assertFalse(result[0].bold)

    def test_dict_bullet_bold_default(self):
        result = _parse_bullets([{"text": "no bold key"}])
        self.assertFalse(result[0].bold)

    def test_dict_bullet_bold_string_false_rejected(self):
        """bold: 'false' (string) should NOT be treated as True."""
        result = _parse_bullets([{"text": "tricky", "bold": "false"}])
        self.assertFalse(result[0].bold)

    def test_dict_bullet_bold_one_rejected(self):
        """bold: 1 (int) should NOT be treated as True — only bool True."""
        result = _parse_bullets([{"text": "tricky", "bold": 1}])
        self.assertFalse(result[0].bold)

    def test_list_bullet_text_only(self):
        result = _parse_bullets([["just text"]])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "just text")
        self.assertEqual(result[0].level, 0)

    def test_list_bullet_with_level(self):
        result = _parse_bullets([["indented", 1]])
        self.assertEqual(result[0].text, "indented")
        self.assertEqual(result[0].level, 1)

    def test_tuple_bullet_with_level(self):
        result = _parse_bullets([("sub-item", 2)])
        self.assertEqual(result[0].text, "sub-item")
        self.assertEqual(result[0].level, 2)

    def test_list_bullet_negative_level_raises(self):
        with self.assertRaisesRegex(ValueError, "non-negative"):
            _parse_bullets([["bad", -1]])

    def test_list_bullet_empty_raises(self):
        with self.assertRaisesRegex(ValueError, "1 or 2 elements"):
            _parse_bullets([[]])

    def test_list_bullet_too_many_elements_raises(self):
        with self.assertRaisesRegex(ValueError, "1 or 2 elements"):
            _parse_bullets([["text", 1, "extra"]])

    def test_mixed_bullet_types(self):
        result = _parse_bullets([
            "plain",
            {"text": "bold line", "bold": True},
            ["indented", 1],
        ])
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].text, "plain")
        self.assertFalse(result[0].bold)
        self.assertTrue(result[1].bold)
        self.assertEqual(result[2].level, 1)

    def test_dict_bullet_with_url(self):
        """Dict bullet with explicit url field sets url on BulletItem."""
        result = _parse_bullets([{"text": "Dashboard", "url": "https://grafana.example.com"}])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "Dashboard")
        self.assertEqual(result[0].url, "https://grafana.example.com")

    def test_dict_bullet_without_url(self):
        """Dict bullet without url field defaults to None."""
        result = _parse_bullets([{"text": "No link"}])
        self.assertIsNone(result[0].url)

    def test_string_bullet_url_autodetect_https(self):
        """String bullet starting with https:// auto-sets url."""
        result = _parse_bullets(["https://example.com/dashboard"])
        self.assertEqual(result[0].text, "https://example.com/dashboard")
        self.assertEqual(result[0].url, "https://example.com/dashboard")

    def test_string_bullet_url_autodetect_http(self):
        """String bullet starting with http:// auto-sets url."""
        result = _parse_bullets(["http://internal.example.com"])
        self.assertEqual(result[0].url, "http://internal.example.com")

    def test_string_bullet_no_url_autodetect(self):
        """Plain string bullet does not auto-detect url."""
        result = _parse_bullets(["Plain text bullet"])
        self.assertIsNone(result[0].url)

    def test_string_bullet_url_not_at_start(self):
        """String with URL in the middle does not auto-detect."""
        result = _parse_bullets(["Visit https://example.com for details"])
        self.assertIsNone(result[0].url)

    def test_list_bullet_no_url(self):
        """List/tuple bullets do not support url field."""
        result = _parse_bullets([["some text", 1]])
        self.assertIsNone(result[0].url)


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


# ---------------------------------------------------------------------------
# _parse_markdown_section
# ---------------------------------------------------------------------------

class TestParseMarkdownSection(unittest.TestCase):
    """Tests for _parse_markdown_section helper."""

    def test_heading_with_bullets(self):
        """Heading followed by bullets produces a slide."""
        lines = ["# My Title", "- Point A", "- Point B"]
        slide = _parse_markdown_section(lines)
        self.assertIsNotNone(slide)
        self.assertEqual(slide.title, "My Title")
        self.assertEqual(len(slide.bullets), 2)

    def test_title_directive_overrides_heading(self):
        """**Title:** directive overrides heading."""
        lines = ["# Heading", "**Title:** Override Title", "- Bullet"]
        slide = _parse_markdown_section(lines)
        self.assertEqual(slide.title, "Override Title")

    def test_subtitle_directive(self):
        """**Subtitle:** directive sets subtitle."""
        lines = ["# Title", "**Subtitle:** My Subtitle", "- Bullet"]
        slide = _parse_markdown_section(lines)
        self.assertEqual(slide.subtitle, "My Subtitle")

    def test_layout_section_variants(self):
        """All section layout values map to LAYOUT_SECTION."""
        for layout_value in ("section", "section_header", "Section Header", "section-header"):
            with self.subTest(layout_value=layout_value):
                lines = ["# Title", f"**Layout:** {layout_value}"]
                slide = _parse_markdown_section(lines)
                self.assertEqual(slide.layout, LAYOUT_SECTION)

    def test_layout_table_directive_ignored(self):
        """**Layout: table** is ignored in markdown parser (table only works via CSV)."""
        lines = ["# Table Title", "**Layout:** table"]
        slide = _parse_markdown_section(lines)
        self.assertEqual(slide.layout, LAYOUT_BULLET)

    def test_h2_without_bullets_becomes_section(self):
        """H2 heading with no bullets defaults to section layout."""
        lines = ["## Section Break"]
        slide = _parse_markdown_section(lines)
        self.assertIsNotNone(slide)
        self.assertEqual(slide.title, "Section Break")
        self.assertEqual(slide.layout, LAYOUT_SECTION)

    def test_h2_with_bullets_stays_bullet(self):
        """H2 heading with bullets stays as bullet layout."""
        lines = ["## Topic", "- Point"]
        slide = _parse_markdown_section(lines)
        self.assertEqual(slide.layout, LAYOUT_BULLET)

    def test_empty_lines_returns_none(self):
        """Section with no title or bullets returns None."""
        self.assertIsNone(_parse_markdown_section([]))

    def test_title_normalization(self):
        """Slide prefix is stripped from heading titles."""
        lines = ["# Slide 1: Introduction", "- Bullet"]
        slide = _parse_markdown_section(lines)
        self.assertEqual(slide.title, "Introduction")

    def test_bullets_only_gets_untitled(self):
        """Section with bullets but no heading gets 'Untitled' title."""
        lines = ["- Just a bullet"]
        slide = _parse_markdown_section(lines)
        self.assertEqual(slide.title, "Untitled")


# ---------------------------------------------------------------------------
# load_deck_from_markdown
# ---------------------------------------------------------------------------

class TestLoadDeckFromMarkdown(unittest.TestCase):
    """Tests for load_deck_from_markdown."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, name: str, content: str) -> Path:
        """Write a temp file and return its path."""
        p = self.tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_single_slide(self):
        """Single section markdown produces one slide."""
        md = self._write("single.md", "# Hello World\n- Bullet one\n- Bullet two\n")

        deck = load_deck_from_markdown(md)
        self.assertIsInstance(deck, SlideDeck)
        self.assertEqual(deck.metadata.title, "Hello World")
        self.assertEqual(len(deck.slides), 1)
        self.assertEqual(len(deck.slides[0].bullets), 2)

    def test_multiple_sections(self):
        """Sections separated by --- produce multiple slides."""
        md = self._write("multi.md", "# Slide A\n- A1\n---\n# Slide B\n- B1\n")

        deck = load_deck_from_markdown(md)
        self.assertEqual(len(deck.slides), 2)
        self.assertEqual(deck.slides[0].title, "Slide A")
        self.assertEqual(deck.slides[1].title, "Slide B")

    def test_empty_sections_skipped(self):
        """Empty sections between separators are skipped."""
        md = self._write("empty.md", "# First\n- A\n---\n\n---\n# Last\n- B\n")

        deck = load_deck_from_markdown(md)
        self.assertEqual(len(deck.slides), 2)

    def test_auto_pagination(self):
        """Slides exceeding bullet_limit are split."""
        bullets = "\n".join(f"- Item {i}" for i in range(12))
        md = self._write("long.md", f"# Big Slide\n{bullets}\n")

        deck = load_deck_from_markdown(md, bullet_limit=5)
        self.assertEqual(len(deck.slides), 3)
        self.assertEqual(deck.slides[0].title, "Big Slide")
        self.assertEqual(deck.slides[1].title, "Big Slide (cont.)")

    def test_custom_title_overrides_first_slide(self):
        """Explicit title parameter overrides first slide title as deck title."""
        md = self._write("titled.md", "# Slide Title\n- A\n")

        deck = load_deck_from_markdown(md, title="Custom Deck Title")
        self.assertEqual(deck.metadata.title, "Custom Deck Title")

    def test_metadata_passthrough(self):
        """Author, template_path, theme_color, template_slide_index pass through."""
        md = self._write("meta.md", "# Slide\n- A\n")

        deck = load_deck_from_markdown(
            md,
            author="Alice",
            template_path="/tmp/t.pptx",  # nosec B108 - mock path arg, no file read
            template_slide_index=5,
            theme_color="ACCENT_1",
        )
        self.assertEqual(deck.metadata.author, "Alice")
        self.assertEqual(deck.template_path, "/tmp/t.pptx")  # nosec B108 - asserting on mock data value
        self.assertEqual(deck.metadata.template_slide_index, 5)
        self.assertEqual(deck.metadata.theme_color, "ACCENT_1")

    def test_default_metadata(self):
        """Without explicit args, defaults from constants are used."""
        md = self._write("defaults.md", "# Title\n- A\n")

        deck = load_deck_from_markdown(md)
        self.assertEqual(deck.metadata.template_slide_index, DEFAULT_TEMPLATE_SLIDE_INDEX)
        self.assertEqual(deck.metadata.theme_color, DEFAULT_THEME_COLOR)
        self.assertIsNone(deck.metadata.author)
        self.assertIsNone(deck.template_path)

    def test_inline_markdown_highlights(self):
        """Bold and code in bullets produce BulletItem.highlight entries."""
        md = self._write("highlights.md", "# Title\n- Use **kubectl** and `helm`\n")

        deck = load_deck_from_markdown(md)
        bullet = deck.slides[0].bullets[0]
        self.assertIsInstance(bullet, BulletItem)
        self.assertIn("kubectl", bullet.highlight)
        self.assertIn("helm", bullet.highlight)

    def test_sub_bullets(self):
        """Indented bullets produce BulletItems with higher levels."""
        md = self._write("indent.md", "# Title\n- Top\n  - Sub\n    - Deep\n")

        deck = load_deck_from_markdown(md)
        bullets = deck.slides[0].bullets
        self.assertEqual(len(bullets), 3)
        self.assertEqual(bullets[0].level, 0)
        self.assertEqual(bullets[1].level, 1)
        self.assertEqual(bullets[2].level, 2)

    def test_numbered_list(self):
        """Numbered list items are parsed as bullets."""
        md = self._write("numbered.md", "# Steps\n1. First\n2. Second\n3. Third\n")

        deck = load_deck_from_markdown(md)
        self.assertEqual(len(deck.slides[0].bullets), 3)

    def test_empty_file(self):
        """Empty markdown file produces deck with 'Untitled' title and no slides."""
        md = self._write("empty.md", "")

        deck = load_deck_from_markdown(md)
        self.assertEqual(deck.metadata.title, "Untitled")
        self.assertEqual(len(deck.slides), 0)

    def test_directives_in_markdown(self):
        """Title, Subtitle directives work in markdown sections."""
        md = self._write(
            "directives.md",
            "**Title:** Custom Title\n"
            "**Subtitle:** My Subtitle\n"
            "- Bullet\n",
        )

        deck = load_deck_from_markdown(md)
        slide = deck.slides[0]
        self.assertEqual(slide.title, "Custom Title")
        self.assertEqual(slide.subtitle, "My Subtitle")


# ---------------------------------------------------------------------------
# load_deck_from_outline
# ---------------------------------------------------------------------------

class TestLoadDeckFromOutline(unittest.TestCase):
    """Tests for load_deck_from_outline."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, name: str, content: str) -> Path:
        p = self.tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_basic_outline(self):
        """Basic outline with one slide and prompts."""
        outline = self._write(
            "outline.md",
            "- Slide 1 \u2014 Introduction\n"
            "- Prompt (on slide): Welcome everyone\n"
            "- Prompt (on slide): Today we cover X\n",
        )

        deck = load_deck_from_outline(outline)
        self.assertIsInstance(deck, SlideDeck)
        self.assertEqual(deck.metadata.title, "Introduction")
        self.assertEqual(len(deck.slides), 1)
        self.assertEqual(len(deck.slides[0].bullets), 2)
        self.assertEqual(deck.slides[0].bullets[0].text, "Welcome everyone")

    def test_multiple_slides(self):
        """Multiple slide definitions in the outline."""
        outline = self._write(
            "multi.md",
            "- Slide 1 \u2014 Intro\n"
            "- Prompt (on slide): Hello\n"
            "- Slide 2 \u2014 Details\n"
            "- Prompt (on slide): More info\n",
        )

        deck = load_deck_from_outline(outline)
        self.assertEqual(len(deck.slides), 2)
        self.assertEqual(deck.slides[0].title, "Intro")
        self.assertEqual(deck.slides[1].title, "Details")

    def test_slide_without_prompts(self):
        """Slide with no prompts gets empty bullets list."""
        outline = self._write("no_prompts.md", "- Slide 1 \u2014 Title Only\n")

        deck = load_deck_from_outline(outline)
        self.assertEqual(len(deck.slides), 1)
        self.assertEqual(deck.slides[0].bullets, [])

    def test_empty_outline(self):
        """Empty outline produces deck with 'Untitled' and no slides."""
        outline = self._write("empty.md", "")

        deck = load_deck_from_outline(outline)
        self.assertEqual(deck.metadata.title, "Untitled")
        self.assertEqual(len(deck.slides), 0)

    def test_custom_title_override(self):
        """Explicit title parameter overrides first slide title."""
        outline = self._write("titled.md", "- Slide 1 \u2014 First\n")

        deck = load_deck_from_outline(outline, title="My Deck")
        self.assertEqual(deck.metadata.title, "My Deck")

    def test_metadata_passthrough(self):
        """Author, template_path, theme_color pass through."""
        outline = self._write("meta.md", "- Slide 1 \u2014 First\n")

        deck = load_deck_from_outline(
            outline,
            author="Bob",
            template_path="/tmp/t.pptx",  # nosec B108 - mock path arg, no file read
            template_slide_index=3,
            theme_color="DARK_1",
        )
        self.assertEqual(deck.metadata.author, "Bob")
        self.assertEqual(deck.template_path, "/tmp/t.pptx")  # nosec B108 - asserting on mock data value
        self.assertEqual(deck.metadata.template_slide_index, 3)
        self.assertEqual(deck.metadata.theme_color, "DARK_1")

    def test_outline_with_optional_tag(self):
        """Slide definitions with [optional tag] are parsed correctly."""
        outline = self._write(
            "tagged.md",
            "- Slide 1 \u2014 Overview [intro]\n- Prompt (on slide): Hello\n",
        )

        deck = load_deck_from_outline(outline)
        self.assertEqual(deck.slides[0].title, "Overview")

    def test_prompt_with_markdown(self):
        """Bold text in prompts produces highlights."""
        outline = self._write(
            "bold.md",
            "- Slide 1 \u2014 Title\n"
            "- Prompt (on slide): Use **kubectl** wisely\n",
        )

        deck = load_deck_from_outline(outline)
        bullet = deck.slides[0].bullets[0]
        self.assertIsInstance(bullet, BulletItem)
        self.assertIn("kubectl", bullet.highlight)

    def test_empty_prompt_text_skipped(self):
        """Prompt with no text after colon is skipped."""
        outline = self._write(
            "empty_prompt.md",
            "- Slide 1 \u2014 Title\n"
            "- Prompt (on slide): \n",
        )

        deck = load_deck_from_outline(outline)
        self.assertEqual(len(deck.slides[0].bullets), 0)


# ---------------------------------------------------------------------------
# load_deck_from_csv
# ---------------------------------------------------------------------------

class TestLoadDeckFromCsv(unittest.TestCase):
    """Tests for load_deck_from_csv."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, name: str, content: str) -> Path:
        p = self.tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_bullet_mode(self):
        """CSV with slide_title/summary columns groups into bullet slides."""
        csv_file = self._write(
            "bullets.csv",
            "slide_title,summary\n"
            "Intro,Welcome\n"
            "Intro,Overview\n"
            "Details,Point A\n",
        )

        deck = load_deck_from_csv(csv_file, title="CSV Deck")
        self.assertEqual(deck.metadata.title, "CSV Deck")
        self.assertEqual(len(deck.slides), 2)
        self.assertEqual(deck.slides[0].title, "Intro")
        self.assertEqual(len(deck.slides[0].bullets), 2)
        self.assertEqual(deck.slides[1].title, "Details")
        self.assertEqual(len(deck.slides[1].bullets), 1)

    def test_table_mode(self):
        """CSV without title column creates a table slide."""
        csv_file = self._write(
            "table.csv",
            "name,value,status\n"
            "SvcA,99.9%,OK\n"
            "SvcB,98.5%,WARN\n",
        )

        deck = load_deck_from_csv(csv_file, title="Table Deck")
        self.assertEqual(len(deck.slides), 1)
        slide = deck.slides[0]
        self.assertIsInstance(slide, TableSlide)
        self.assertEqual(slide.headers, ["name", "value", "status"])
        self.assertEqual(len(slide.rows), 2)
        self.assertEqual(slide.rows[0], ["SvcA", "99.9%", "OK"])

    def test_empty_csv(self):
        """Empty CSV produces deck with no slides."""
        csv_file = self._write("empty.csv", "slide_title,summary\n")

        deck = load_deck_from_csv(csv_file, title="Empty")
        self.assertEqual(len(deck.slides), 0)
        self.assertEqual(deck.metadata.title, "Empty")

    def test_custom_column_names(self):
        """Custom title_column and text_column parameters work."""
        csv_file = self._write(
            "custom.csv",
            "heading,body\n"
            "Topic A,Content 1\n"
            "Topic A,Content 2\n",
        )

        deck = load_deck_from_csv(
            csv_file,
            title_column="heading",
            text_column="body",
        )
        self.assertEqual(len(deck.slides), 1)
        self.assertEqual(deck.slides[0].title, "Topic A")
        self.assertEqual(len(deck.slides[0].bullets), 2)

    def test_auto_pagination_csv(self):
        """CSV bullet mode respects bullet_limit for auto-pagination."""
        rows = "\n".join(f"Topic,Bullet {i}" for i in range(10))
        csv_file = self._write("long.csv", f"slide_title,summary\n{rows}\n")

        deck = load_deck_from_csv(csv_file, bullet_limit=4)
        self.assertGreater(len(deck.slides), 2)
        self.assertIn("(cont.)", deck.slides[1].title)

    def test_metadata_passthrough(self):
        """Author, template_path, theme_color pass through."""
        csv_file = self._write("meta.csv", "slide_title,summary\nA,B\n")

        deck = load_deck_from_csv(
            csv_file,
            author="Charlie",
            template_path="/tmp/t.pptx",  # nosec B108 - mock path arg, no file read
            template_slide_index=7,
            theme_color="ACCENT_3",
        )
        self.assertEqual(deck.metadata.author, "Charlie")
        self.assertEqual(deck.template_path, "/tmp/t.pptx")  # nosec B108 - asserting on mock data value
        self.assertEqual(deck.metadata.template_slide_index, 7)
        self.assertEqual(deck.metadata.theme_color, "ACCENT_3")

    def test_empty_text_rows_skipped(self):
        """Rows with empty summary text are skipped."""
        csv_file = self._write(
            "gaps.csv",
            "slide_title,summary\n"
            "Topic,Content\n"
            "Topic,\n"
            "Topic,More content\n",
        )

        deck = load_deck_from_csv(csv_file)
        self.assertEqual(len(deck.slides[0].bullets), 2)

    def test_table_mode_no_crash(self):
        """CSV table-data path (no title_column/text_column) does not crash in _chunk_slides."""
        csv_file = self._write(
            "table_only.csv",
            "host,cpu,memory\n"
            "web-1,45%,2GB\n"
            "web-2,78%,4GB\n"
            "web-3,12%,1GB\n",
        )

        deck = load_deck_from_csv(csv_file, title="Table Test")
        self.assertEqual(len(deck.slides), 1)
        slide = deck.slides[0]
        self.assertIsInstance(slide, TableSlide)
        self.assertEqual(slide.title, "Table Test")
        self.assertEqual(slide.headers, ["host", "cpu", "memory"])
        self.assertEqual(len(slide.rows), 3)

    def test_highlights_in_csv_text(self):
        """Bold markdown in CSV summary text produces highlights."""
        csv_file = self._write(
            "highlights.csv",
            "slide_title,summary\n"
            "Topic,Use **terraform** carefully\n",
        )

        deck = load_deck_from_csv(csv_file)
        bullet = deck.slides[0].bullets[0]
        self.assertIsInstance(bullet, BulletItem)
        self.assertIn("terraform", bullet.highlight)


# ---------------------------------------------------------------------------
# load_deck_from_dict
# ---------------------------------------------------------------------------

class TestLoadDeckFromDict(unittest.TestCase):
    """Tests for load_deck_from_dict."""

    def test_basic_dict(self):
        """Basic dict with slides produces a SlideDeck."""
        data = {
            "title": "Dict Deck",
            "author": "Test",
            "slides": [
                {"title": "Slide 1", "bullets": ["A", "B"]},
            ],
        }
        deck = load_deck_from_dict(data)
        self.assertIsInstance(deck, SlideDeck)
        self.assertEqual(deck.metadata.title, "Dict Deck")
        self.assertEqual(deck.metadata.author, "Test")
        self.assertEqual(len(deck.slides), 1)
        self.assertEqual(deck.slides[0].title, "Slide 1")

    def test_template_path_override(self):
        """template_path parameter overrides dict value."""
        data = {
            "title": "T",
            "template_path": "/dict/path.pptx",
            "slides": [],
        }
        deck = load_deck_from_dict(data, template_path="/override.pptx")
        self.assertEqual(deck.template_path, "/override.pptx")

    def test_template_path_from_dict(self):
        """template_path falls back to dict value when not overridden."""
        data = {
            "title": "T",
            "template_path": "/dict/path.pptx",
            "slides": [],
        }
        deck = load_deck_from_dict(data)
        self.assertEqual(deck.template_path, "/dict/path.pptx")

    def test_table_slide_in_dict(self):
        """Dict with layout=table creates a TableSlide."""
        data = {
            "title": "T",
            "slides": [
                {
                    "title": "Data",
                    "layout": "table",
                    "headers": ["Name", "Value"],
                    "rows": [["A", "1"]],
                },
            ],
        }
        deck = load_deck_from_dict(data)
        self.assertEqual(len(deck.slides), 1)
        self.assertIsInstance(deck.slides[0], TableSlide)
        self.assertEqual(deck.slides[0].headers, ["Name", "Value"])

    def test_defaults_for_missing_fields(self):
        """Missing fields in dict get sensible defaults."""
        data = {"slides": []}
        deck = load_deck_from_dict(data)
        self.assertEqual(deck.metadata.title, "Untitled")
        self.assertIsNone(deck.metadata.author)
        self.assertEqual(deck.metadata.template_slide_index, DEFAULT_TEMPLATE_SLIDE_INDEX)
        self.assertEqual(deck.metadata.theme_color, DEFAULT_THEME_COLOR)

    def test_date_field(self):
        """Date field from dict is converted to string."""
        data = {"title": "T", "date": "2026-01-15", "slides": []}
        deck = load_deck_from_dict(data)
        self.assertEqual(deck.metadata.date, "2026-01-15")

    def test_date_none(self):
        """Missing date field results in None."""
        data = {"title": "T", "slides": []}
        deck = load_deck_from_dict(data)
        self.assertIsNone(deck.metadata.date)

    def test_empty_slides_list(self):
        """Dict with empty slides list produces deck with no slides."""
        data = {"title": "Empty", "slides": []}
        deck = load_deck_from_dict(data)
        self.assertEqual(len(deck.slides), 0)

    def test_full_metadata(self):
        """All metadata fields are preserved."""
        data = {
            "title": "Full",
            "author": "Alice",
            "date": "2026-03-13",
            "template_slide_index": 5,
            "theme_color": "DARK_2",
            "slides": [],
        }
        deck = load_deck_from_dict(data)
        self.assertEqual(deck.metadata.title, "Full")
        self.assertEqual(deck.metadata.author, "Alice")
        self.assertEqual(deck.metadata.date, "2026-03-13")
        self.assertEqual(deck.metadata.template_slide_index, 5)
        self.assertEqual(deck.metadata.theme_color, "DARK_2")


# ---------------------------------------------------------------------------
# _body_to_bullets
# ---------------------------------------------------------------------------

class TestBodyToBullets(unittest.TestCase):
    """Tests for _body_to_bullets helper — multiline body string to BulletItem list."""

    def test_plain_lines_level_zero(self):
        """Plain text lines become level-0 bullets."""
        result = _body_to_bullets("Line one\nLine two")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].text, "Line one")
        self.assertEqual(result[0].level, 0)
        self.assertEqual(result[1].text, "Line two")
        self.assertEqual(result[1].level, 0)

    def test_dash_bullet_level_one(self):
        """Lines starting with '- ' become level-1 bullets."""
        result = _body_to_bullets("- First item\n- Second item")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].text, "First item")
        self.assertEqual(result[0].level, 1)
        self.assertEqual(result[1].text, "Second item")
        self.assertEqual(result[1].level, 1)

    def test_indented_dash_bullet_level_two(self):
        """Lines with 2+ spaces before '- ' become level-2 bullets."""
        # Note: body.strip("\n") only strips newlines (not spaces), but the
        # first line still has no leading indent — use a plain line first
        # to test that indentation on subsequent lines is preserved.
        result = _body_to_bullets("Header\n  - Sub-item\n    - Deep sub-item")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].text, "Header")
        self.assertEqual(result[0].level, 0)
        self.assertEqual(result[1].text, "Sub-item")
        self.assertEqual(result[1].level, 2)
        self.assertEqual(result[2].text, "Deep sub-item")
        self.assertEqual(result[2].level, 2)

    def test_mixed_levels(self):
        """Mix of plain, dash, and indented dash lines."""
        body = "Overview\n- Point one\n  - Detail\nConclusion"
        result = _body_to_bullets(body)
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0].level, 0)
        self.assertEqual(result[1].level, 1)
        self.assertEqual(result[2].level, 2)
        self.assertEqual(result[3].level, 0)

    def test_blank_lines_skipped(self):
        """Blank lines are skipped."""
        result = _body_to_bullets("Line one\n\n\nLine two")
        self.assertEqual(len(result), 2)

    def test_leading_trailing_whitespace_stripped(self):
        """Leading/trailing blank lines from body.strip() are handled."""
        result = _body_to_bullets("\n\nContent here\n\n")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "Content here")

    def test_empty_string(self):
        """Empty string returns empty list."""
        result = _body_to_bullets("")
        self.assertEqual(result, [])

    def test_whitespace_only(self):
        """Whitespace-only string returns empty list."""
        result = _body_to_bullets("   \n  \n  ")
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# _parse_slide with body: field
# ---------------------------------------------------------------------------

class TestParseSlideBodyField(unittest.TestCase):
    """Tests for body: field support in _parse_slide."""

    def test_body_field_produces_bullets(self):
        """body: multiline string is converted to BulletItem list."""
        slide_data = {
            "title": "Summary",
            "body": "Overview\n- Key point\n  - Detail",
        }
        result = _parse_slide(slide_data)
        self.assertEqual(len(result.bullets), 3)
        self.assertEqual(result.bullets[0].level, 0)
        self.assertEqual(result.bullets[1].level, 1)
        self.assertEqual(result.bullets[2].level, 2)

    def test_body_field_ignored_when_bullets_present(self):
        """body: is ignored when bullets: is also specified."""
        slide_data = {
            "title": "Has Both",
            "bullets": ["Explicit bullet"],
            "body": "This should be ignored",
        }
        result = _parse_slide(slide_data)
        self.assertEqual(len(result.bullets), 1)
        self.assertEqual(result.bullets[0].text, "Explicit bullet")

    def test_body_field_none_uses_empty_bullets(self):
        """body: None falls through to empty bullets."""
        slide_data = {"title": "No body", "body": None}
        result = _parse_slide(slide_data)
        self.assertEqual(result.bullets, [])

    def test_body_field_non_string_ignored(self):
        """body: with non-string value (e.g. int) falls through to empty bullets."""
        slide_data = {"title": "Bad body", "body": 42}
        result = _parse_slide(slide_data)
        self.assertEqual(result.bullets, [])


if __name__ == "__main__":
    unittest.main()
