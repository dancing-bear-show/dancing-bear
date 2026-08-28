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
    _outline_prompt_bullet,
    _parse_markdown_section,
    _parse_outline_slides,
    load_deck_from_markdown,
    load_deck_from_outline,
)
from slides.schema import BulletItem, DeckOptions, SlideDeck
from tests.slides_tests.fixtures import assert_metadata_passthrough


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

    def test_explicit_empty_title_falls_back_to_first_slide(self):
        """An empty title falls back to the first slide title, unlike the CSV loader.

        Deliberate asymmetry, and it predates DeckOptions: this loader has always
        taken `title: str | None = None` with a truthiness check, while the CSV
        loader took `title: str = DEFAULT_TITLE` and let "" through. Pinned here
        so the difference is asserted rather than merely documented — see
        test_explicit_empty_title_is_preserved in test_parsers_csv.py.
        """
        md = self._write("blank.md", "# First Heading\n- Bullet\n")

        deck = load_deck_from_markdown(md, options=DeckOptions(title=""))
        self.assertEqual(deck.metadata.title, "First Heading")

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

        deck = load_deck_from_markdown(md, options=DeckOptions(title="Custom Deck Title"))
        self.assertEqual(deck.metadata.title, "Custom Deck Title")

    def test_metadata_passthrough(self):
        """Author, template_path, theme_color, template_slide_index pass through."""
        md = self._write("meta.md", "# Slide\n- A\n")

        deck = load_deck_from_markdown(
            md,
            options=DeckOptions(
                author="Alice",
                template_path="/tmp/t.pptx",  # nosec B108 - mock path arg, no file read
                template_slide_index=5,
                theme_color="ACCENT_1",
            ),
        )
        assert_metadata_passthrough(
            self,
            deck,
            author="Alice",
            template_path="/tmp/t.pptx",  # nosec B108 - asserting on mock data value
            template_slide_index=5,
            theme_color="ACCENT_1",
        )

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
            "- Slide 1 — Introduction\n"
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
            "- Slide 1 — Intro\n"
            "- Prompt (on slide): Hello\n"
            "- Slide 2 — Details\n"
            "- Prompt (on slide): More info\n",
        )

        deck = load_deck_from_outline(outline)
        self.assertEqual(len(deck.slides), 2)
        self.assertEqual(deck.slides[0].title, "Intro")
        self.assertEqual(deck.slides[1].title, "Details")

    def test_slide_without_prompts(self):
        """Slide with no prompts gets empty bullets list."""
        outline = self._write("no_prompts.md", "- Slide 1 — Title Only\n")

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
        outline = self._write("titled.md", "- Slide 1 — First\n")

        deck = load_deck_from_outline(outline, options=DeckOptions(title="My Deck"))
        self.assertEqual(deck.metadata.title, "My Deck")

    def test_metadata_passthrough(self):
        """Author, template_path, theme_color pass through."""
        outline = self._write("meta.md", "- Slide 1 — First\n")

        deck = load_deck_from_outline(
            outline,
            options=DeckOptions(
                author="Bob",
                template_path="/tmp/t.pptx",  # nosec B108 - mock path arg, no file read
                template_slide_index=3,
                theme_color="DARK_1",
            ),
        )
        assert_metadata_passthrough(
            self,
            deck,
            author="Bob",
            template_path="/tmp/t.pptx",  # nosec B108 - asserting on mock data value
            template_slide_index=3,
            theme_color="DARK_1",
        )

    def test_outline_with_optional_tag(self):
        """Slide definitions with [optional tag] are parsed correctly."""
        outline = self._write(
            "tagged.md",
            "- Slide 1 — Overview [intro]\n- Prompt (on slide): Hello\n",
        )

        deck = load_deck_from_outline(outline)
        self.assertEqual(deck.slides[0].title, "Overview")

    def test_prompt_with_markdown(self):
        """Bold text in prompts produces highlights."""
        outline = self._write(
            "bold.md",
            "- Slide 1 — Title\n"
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
            "- Slide 1 — Title\n"
            "- Prompt (on slide): \n",
        )

        deck = load_deck_from_outline(outline)
        self.assertEqual(len(deck.slides[0].bullets), 0)

# ---------------------------------------------------------------------------
# _parse_markdown_section: non-bullet, non-directive line skips bullet append
# (partial branch 189->182)
# ---------------------------------------------------------------------------

class TestParseSectionNonBulletLines(unittest.TestCase):
    """Cover the branch where a line is not a directive and not a bullet (branch 189->182)."""

    def test_non_bullet_non_directive_line_does_not_add_bullet(self):
        """A plain line with no heading marker or bullet prefix is skipped."""
        # "Some plain text" is neither a heading (#) nor a bullet (- text)
        result = _parse_markdown_section(["# A Title", "Some plain text that is not a bullet"])
        # Slide should exist (has a title) but have zero bullets
        self.assertIsNotNone(result)
        self.assertEqual(result.title, "A Title")
        self.assertEqual(result.bullets, [])

    def test_section_with_only_non_bullet_lines_returns_slide(self):
        """A section with a heading and only non-bullet content creates a slide."""
        result = _parse_markdown_section(["# My Slide", "just a sentence"])
        self.assertIsNotNone(result)
        self.assertEqual(result.bullets, [])


# ---------------------------------------------------------------------------
# _outline_prompt_bullet: non-matching line returns None (line 210, branch 98->91)
# ---------------------------------------------------------------------------

class TestOutlinePromptBullet(unittest.TestCase):
    """Tests for _outline_prompt_bullet — covers the non-match branch."""

    def test_non_matching_line_returns_none(self):
        """A line that does not match the prompt pattern returns None (line 210)."""
        result = _outline_prompt_bullet("Just a plain comment line")
        self.assertIsNone(result)

    def test_matching_line_returns_bullet(self):
        """A matching prompt line returns a BulletItem."""
        result = _outline_prompt_bullet("- Prompt (on slide): Key point")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, BulletItem)
        self.assertIn("Key point", result.text)


# ---------------------------------------------------------------------------
# _parse_outline_slides: lines before any slide header skip the body branch
# (partial branch 243->233)
# ---------------------------------------------------------------------------

class TestParseOutlineSlides(unittest.TestCase):
    """Tests for _parse_outline_slides partial branches."""

    def test_lines_before_first_slide_header_are_ignored(self):
        """Content lines before the first slide header are silently ignored (branch 243->233)."""
        text = (
            "preamble line — no slide yet\n"
            "- Slide 1 — Real Title\n"
            "- Prompt (on slide): Included bullet\n"
        )
        slides = _parse_outline_slides(text)
        self.assertEqual(len(slides), 1)
        self.assertEqual(slides[0].title, "Real Title")
        self.assertEqual(len(slides[0].bullets), 1)

    def test_non_prompt_line_inside_slide_does_not_add_bullet(self):
        """A non-prompt line inside a slide does not produce a bullet (branch 189->182)."""
        text = (
            "- Slide 1 — Title\n"
            "this line is not a prompt\n"
        )
        slides = _parse_outline_slides(text)
        self.assertEqual(len(slides), 1)
        self.assertEqual(slides[0].bullets, [])


# ---------------------------------------------------------------------------
# _parse_markdown_section: None returned when section has no title or bullets
# (partial branch 98->91 in load_deck_from_markdown)
# ---------------------------------------------------------------------------

class TestParseSectionNoneResult(unittest.TestCase):
    """Cover the branch where _parse_markdown_section returns None (partial 98->91)."""

    def test_empty_section_skipped_in_markdown_load(self):
        """Sections that parse to None are skipped; deck slide count excludes them."""
        import tempfile
        import os
        md = "# Valid Title\n- bullet one\n\n---\n\n\n---\n\n# Another\n- point\n"
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(md)
            path = f.name
        try:
            deck = load_deck_from_markdown(path)
            # Exactly the two real sections survive; the blank middle section
            # parses to None and is skipped. A >= assertion would not catch a
            # regression that stopped skipping it.
            self.assertEqual(len(deck.slides), 2)
            self.assertEqual(
                [s.title for s in deck.slides], ["Valid Title", "Another"]
            )
        finally:
            os.unlink(path)

    def test_plain_text_only_section_produces_no_slide(self):
        """A section with only plain text (no heading, no bullets) is skipped (branch 98->91)."""
        import tempfile
        import os
        # First section: valid. Second section: plain text only (no # title, no - bullet)
        # _parse_markdown_section returns None for it; load_deck skips it.
        md = "# Real Slide\n- valid bullet\n\n---\n\njust plain prose no heading no bullet\n"
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(md)
            path = f.name
        try:
            deck = load_deck_from_markdown(path)
            # Only the first (real) section becomes a slide; prose section is None and skipped
            self.assertEqual(len(deck.slides), 1)
            self.assertEqual(deck.slides[0].title, "Real Slide")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
