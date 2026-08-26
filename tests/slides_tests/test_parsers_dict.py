"""Unit tests for the slides dict/YAML deck parser."""

import unittest

from slides.constants import (
    DEFAULT_TEMPLATE_SLIDE_INDEX,
    DEFAULT_THEME_COLOR,
)
from slides.parsers_dict import _parse_slide, load_deck_from_dict
from slides.schema import SlideDeck, TableSlide


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

# ---------------------------------------------------------------------------
# load_deck_from_dict: slides key absent defaults to empty list (line 182)
# ---------------------------------------------------------------------------

class TestLoadDeckFromDictNoSlidesKey(unittest.TestCase):
    """Tests for load_deck_from_dict when the 'slides' key is entirely absent."""

    def test_no_slides_key_produces_empty_deck(self):
        """When 'slides' key is absent, deck has zero slides (not a KeyError)."""
        deck = load_deck_from_dict({})
        self.assertEqual(deck.slides, [])

    def test_slides_key_none_produces_empty_deck(self):
        """When slides is explicitly None, deck has zero slides."""
        deck = load_deck_from_dict({"slides": None})
        self.assertEqual(deck.slides, [])


# ---------------------------------------------------------------------------
# _parse_slide: bullets: not-a-list ValueError (lines 56-60)
# ---------------------------------------------------------------------------

class TestParseSlideValueErrors(unittest.TestCase):
    """Tests for _parse_slide error paths on invalid field types."""

    def test_bullets_not_list_with_title_raises(self):
        """bullets: as a non-list with a slide title includes title in message."""
        with self.assertRaises(ValueError) as ctx:
            _parse_slide({"title": "My Slide", "bullets": "not a list"})
        self.assertIn("My Slide", str(ctx.exception))
        self.assertIn("bullets", str(ctx.exception))

    def test_bullets_not_list_without_title_raises(self):
        """bullets: as a non-list without a slide title still raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            _parse_slide({"bullets": 42})
        self.assertIn("bullets", str(ctx.exception))


# ---------------------------------------------------------------------------
# load_deck_from_dict: slides: not-a-list ValueError (lines 183-188)
# ---------------------------------------------------------------------------

class TestLoadDeckFromDictValueErrors(unittest.TestCase):
    """Tests for load_deck_from_dict error paths on invalid slides field."""

    def test_slides_not_list_with_deck_title_raises(self):
        """slides: as a scalar with a deck title includes deck title in message."""
        with self.assertRaises(ValueError) as ctx:
            load_deck_from_dict({"title": "My Deck", "slides": "not a list"})
        self.assertIn("My Deck", str(ctx.exception))
        self.assertIn("slides", str(ctx.exception))

    def test_slides_not_list_without_deck_title_raises(self):
        """slides: as a scalar without deck title still raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            load_deck_from_dict({"slides": 99})
        self.assertIn("slides", str(ctx.exception))

    def test_slides_not_list_dict_value_raises(self):
        """slides: as a dict (mapping not wrapped in a list) raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            load_deck_from_dict({"slides": {"title": "Orphan"}})
        self.assertIn("slides", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
