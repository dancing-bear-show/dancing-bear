"""Unit tests for slides schema dataclasses."""

import unittest

from slides.constants import (
    DEFAULT_BULLET_LEVEL,
    DEFAULT_TEMPLATE_SLIDE_INDEX,
    DEFAULT_THEME_COLOR,
    LAYOUT_BULLET,
    LAYOUT_TABLE,
)
from slides.schema import (
    BulletItem,
    DeckMetadata,
    ResolvedBullet,
    SlideContent,
    SlideDeck,
    TableSlide,
)


class TestBulletItem(unittest.TestCase):
    """Tests for BulletItem dataclass."""

    def test_create_with_defaults(self):
        """BulletItem should have default level=0 and empty highlights."""
        bullet = BulletItem(text="Test bullet")

        self.assertEqual(bullet.text, "Test bullet")
        self.assertEqual(bullet.level, DEFAULT_BULLET_LEVEL)
        self.assertEqual(bullet.highlight, [])

    def test_create_with_level(self):
        """BulletItem should accept custom level values."""
        bullet = BulletItem(text="Sub-bullet", level=1)

        self.assertEqual(bullet.text, "Sub-bullet")
        self.assertEqual(bullet.level, 1)

        # Test sub-sub-bullet level
        deep_bullet = BulletItem(text="Deep bullet", level=2)
        self.assertEqual(deep_bullet.level, 2)

    def test_create_with_highlights(self):
        """BulletItem should accept highlight text segments."""
        bullet = BulletItem(
            text="Important text with highlights",
            highlight=["Important", "highlights"],
        )

        self.assertEqual(bullet.text, "Important text with highlights")
        self.assertEqual(bullet.highlight, ["Important", "highlights"])

    def test_highlights_is_list(self):
        """BulletItem highlights field should always be a list."""
        bullet = BulletItem(text="Test")

        self.assertIsInstance(bullet.highlight, list)
        self.assertEqual(len(bullet.highlight), 0)

        # Verify highlight is mutable list (not tuple)
        bullet.highlight.append("new_highlight")
        self.assertEqual(bullet.highlight, ["new_highlight"])

    def test_url_default_none(self):
        """BulletItem url should default to None."""
        bullet = BulletItem(text="No link")
        self.assertIsNone(bullet.url)

    def test_url_with_value(self):
        """BulletItem url should accept a string URL."""
        bullet = BulletItem(text="Dashboard", url="https://grafana.example.com")
        self.assertEqual(bullet.url, "https://grafana.example.com")


class TestSlideContent(unittest.TestCase):
    """Tests for SlideContent dataclass."""

    def test_create_with_title_only(self):
        """SlideContent should work with only a title."""
        slide = SlideContent(title="My Slide Title")

        self.assertEqual(slide.title, "My Slide Title")
        self.assertEqual(slide.bullets, [])
        self.assertIsNone(slide.notes)
        self.assertEqual(slide.layout, LAYOUT_BULLET)

    def test_create_with_bullets_strings(self):
        """SlideContent should accept bullets as plain strings."""
        slide = SlideContent(
            title="Bullet Slide",
            bullets=["First point", "Second point", "Third point"],
        )

        self.assertEqual(slide.title, "Bullet Slide")
        self.assertEqual(len(slide.bullets), 3)
        self.assertEqual(slide.bullets[0], "First point")
        self.assertEqual(slide.bullets[1], "Second point")
        self.assertEqual(slide.bullets[2], "Third point")

    def test_create_with_bullets_mixed(self):
        """SlideContent should accept mixed strings and BulletItem objects."""
        bullet_item = BulletItem(text="Formatted bullet", level=1)
        slide = SlideContent(
            title="Mixed Slide",
            bullets=["Plain string", bullet_item, "Another string"],
        )

        self.assertEqual(len(slide.bullets), 3)
        self.assertEqual(slide.bullets[0], "Plain string")
        self.assertIsInstance(slide.bullets[1], BulletItem)
        self.assertEqual(slide.bullets[1].text, "Formatted bullet")
        self.assertEqual(slide.bullets[1].level, 1)
        self.assertEqual(slide.bullets[2], "Another string")

    def test_default_layout_is_bullet(self):
        """SlideContent should default to 'bullet' layout."""
        slide = SlideContent(title="Test")

        self.assertEqual(slide.layout, LAYOUT_BULLET)
        self.assertEqual(slide.layout, "bullet")

    def test_notes_optional(self):
        """SlideContent notes should be optional and support string values."""
        # Without notes
        slide_no_notes = SlideContent(title="No Notes")
        self.assertIsNone(slide_no_notes.notes)

        # With notes
        slide_with_notes = SlideContent(
            title="With Notes",
            notes="Speaker notes for this slide",
        )
        self.assertEqual(slide_with_notes.notes, "Speaker notes for this slide")


class TestTableSlide(unittest.TestCase):
    """Tests for TableSlide dataclass."""

    def test_create_basic_table(self):
        """TableSlide should accept headers and rows."""
        table = TableSlide(
            title="Metrics Table",
            headers=["Metric", "Value", "Target"],
            rows=[
                ["Uptime", "99.9%", "99.5%"],
                ["Latency", "45ms", "100ms"],
            ],
        )

        self.assertEqual(table.title, "Metrics Table")
        self.assertEqual(table.headers, ["Metric", "Value", "Target"])
        self.assertEqual(len(table.rows), 2)
        self.assertEqual(table.rows[0], ["Uptime", "99.9%", "99.5%"])
        self.assertEqual(table.rows[1], ["Latency", "45ms", "100ms"])

    def test_inherits_from_slide_content(self):
        """TableSlide should inherit from SlideContent."""
        table = TableSlide(title="Test Table")

        self.assertIsInstance(table, SlideContent)
        self.assertTrue(hasattr(table, "title"))
        self.assertTrue(hasattr(table, "bullets"))
        self.assertTrue(hasattr(table, "notes"))
        self.assertTrue(hasattr(table, "layout"))

    def test_default_layout_is_table(self):
        """TableSlide should default to 'table' layout."""
        table = TableSlide(title="Test")

        self.assertEqual(table.layout, LAYOUT_TABLE)
        self.assertEqual(table.layout, "table")

    def test_first_col_width_optional(self):
        """TableSlide first_col_width should be optional."""
        # Without first_col_width
        table_default = TableSlide(title="Default Width")
        self.assertIsNone(table_default.first_col_width)

        # With first_col_width
        table_custom = TableSlide(title="Custom Width", first_col_width=2.5)
        self.assertEqual(table_custom.first_col_width, 2.5)

    def test_empty_headers_and_rows(self):
        """TableSlide should default to empty headers and rows."""
        table = TableSlide(title="Empty Table")

        self.assertEqual(table.headers, [])
        self.assertEqual(table.rows, [])
        self.assertIsInstance(table.headers, list)
        self.assertIsInstance(table.rows, list)


class TestDeckMetadata(unittest.TestCase):
    """Tests for DeckMetadata dataclass."""

    def test_create_with_title_only(self):
        """DeckMetadata should work with only a title."""
        metadata = DeckMetadata(title="My Presentation")

        self.assertEqual(metadata.title, "My Presentation")
        self.assertIsNone(metadata.author)
        self.assertIsNone(metadata.date)
        self.assertEqual(metadata.template_slide_index, DEFAULT_TEMPLATE_SLIDE_INDEX)
        self.assertEqual(metadata.theme_color, DEFAULT_THEME_COLOR)

    def test_create_with_all_fields(self):
        """DeckMetadata should accept all optional fields."""
        metadata = DeckMetadata(
            title="Complete Presentation",
            author="John Doe",
            date="2026-02-06",
            template_slide_index=5,
            theme_color="ACCENT_1",
        )

        self.assertEqual(metadata.title, "Complete Presentation")
        self.assertEqual(metadata.author, "John Doe")
        self.assertEqual(metadata.date, "2026-02-06")
        self.assertEqual(metadata.template_slide_index, 5)
        self.assertEqual(metadata.theme_color, "ACCENT_1")

    def test_default_template_slide_index(self):
        """DeckMetadata should default template_slide_index to 0."""
        metadata = DeckMetadata(title="Test")

        self.assertEqual(metadata.template_slide_index, 0)
        self.assertEqual(metadata.template_slide_index, DEFAULT_TEMPLATE_SLIDE_INDEX)

    def test_default_theme_color(self):
        """DeckMetadata should default theme_color to 'LIGHT_2'."""
        metadata = DeckMetadata(title="Test")

        self.assertEqual(metadata.theme_color, "LIGHT_2")
        self.assertEqual(metadata.theme_color, DEFAULT_THEME_COLOR)


class TestSlideDeck(unittest.TestCase):
    """Tests for SlideDeck dataclass."""

    def test_create_empty_deck(self):
        """SlideDeck should work with metadata and no slides."""
        metadata = DeckMetadata(title="Empty Deck")
        deck = SlideDeck(metadata=metadata)

        self.assertEqual(deck.metadata.title, "Empty Deck")
        self.assertEqual(deck.slides, [])
        self.assertIsNone(deck.template_path)

    def test_create_with_slides(self):
        """SlideDeck should accept a list of slides."""
        metadata = DeckMetadata(title="Full Deck")
        slides = [
            SlideContent(title="Introduction", bullets=["Welcome"]),
            SlideContent(title="Main Content", bullets=["Point 1", "Point 2"]),
            TableSlide(
                title="Data",
                headers=["A", "B"],
                rows=[["1", "2"]],
            ),
        ]
        deck = SlideDeck(metadata=metadata, slides=slides)

        self.assertEqual(deck.metadata.title, "Full Deck")
        self.assertEqual(len(deck.slides), 3)
        self.assertIsInstance(deck.slides[0], SlideContent)
        self.assertIsInstance(deck.slides[1], SlideContent)
        self.assertIsInstance(deck.slides[2], TableSlide)
        self.assertEqual(deck.slides[0].title, "Introduction")
        self.assertEqual(deck.slides[1].title, "Main Content")
        self.assertEqual(deck.slides[2].title, "Data")

    def test_template_path_optional(self):
        """SlideDeck template_path should be optional."""
        metadata = DeckMetadata(title="Test")

        # Without template_path
        deck_default = SlideDeck(metadata=metadata)
        self.assertIsNone(deck_default.template_path)

        # With template_path
        deck_custom = SlideDeck(
            metadata=metadata,
            template_path="/path/to/template.pptx",
        )
        self.assertEqual(deck_custom.template_path, "/path/to/template.pptx")


class TestResolvedBullet(unittest.TestCase):
    """Tests for ResolvedBullet.from_item normalization."""

    def test_from_bullet_item_copies_all_fields(self):
        item = BulletItem(text="hello", level=1, highlight=["hi"], bold=True, url="http://x.com")
        resolved = ResolvedBullet.from_item(item)
        self.assertEqual(resolved.text, "hello")
        self.assertEqual(resolved.level, 1)
        self.assertEqual(resolved.highlight, ["hi"])
        self.assertTrue(resolved.bold)
        self.assertEqual(resolved.url, "http://x.com")

    def test_from_plain_string_uses_defaults(self):
        resolved = ResolvedBullet.from_item("plain")
        self.assertEqual(resolved.text, "plain")
        self.assertEqual(resolved.level, DEFAULT_BULLET_LEVEL)
        self.assertEqual(resolved.highlight, [])
        self.assertFalse(resolved.bold)
        self.assertIsNone(resolved.url)

    def test_non_string_item_is_coerced_to_text(self):
        resolved = ResolvedBullet.from_item(42)
        self.assertEqual(resolved.text, "42")

    def test_is_frozen(self):
        resolved = ResolvedBullet.from_item("x")
        with self.assertRaises(AttributeError):
            resolved.text = "mutated"


if __name__ == "__main__":
    unittest.main()
