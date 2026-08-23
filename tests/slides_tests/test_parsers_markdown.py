"""Unit tests for slides markdown and outline loaders."""

import tempfile
import unittest
from pathlib import Path

from slides.constants import (
    DEFAULT_TEMPLATE_SLIDE_INDEX,
    DEFAULT_THEME_COLOR,
    LAYOUT_BULLET,
    LAYOUT_SECTION,
)
from slides.parsers_markdown import (
    _parse_markdown_section,
    load_deck_from_markdown,
    load_deck_from_outline,
)
from slides.schema import BulletItem, SlideDeck


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

if __name__ == "__main__":
    unittest.main()
