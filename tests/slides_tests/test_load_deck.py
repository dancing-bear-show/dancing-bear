"""Tests for slides.generator.load_deck_from_yaml function."""

import tempfile
import unittest
from pathlib import Path

from slides.generator import load_deck_from_yaml
from slides.schema import BulletItem, SlideContent, TableSlide


class TestLoadDeckFromYaml(unittest.TestCase):
    """Tests for load_deck_from_yaml function."""

    def test_load_minimal_yaml(self):
        """Load YAML with minimal required fields."""
        yaml_content = """
title: Test Deck
slides: []
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()

            deck = load_deck_from_yaml(f.name)

            self.assertEqual(deck.metadata.title, "Test Deck")
            self.assertEqual(deck.slides, [])
            self.assertIsNone(deck.metadata.author)
            self.assertIsNone(deck.metadata.date)
            self.assertEqual(deck.metadata.template_slide_index, 0)
            self.assertEqual(deck.metadata.theme_color, "LIGHT_2")

            Path(f.name).unlink()

    def test_load_with_all_metadata(self):
        """Load YAML with all metadata fields populated."""
        yaml_content = """
title: Complete Deck
author: Test Author
date: 2024-01-15
template_slide_index: 5
theme_color: ACCENT_1
template_path: /path/to/template.pptx
slides: []
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()

            deck = load_deck_from_yaml(f.name)

            self.assertEqual(deck.metadata.title, "Complete Deck")
            self.assertEqual(deck.metadata.author, "Test Author")
            # YAML date is coerced to string
            self.assertEqual(deck.metadata.date, "2024-01-15")
            self.assertEqual(deck.metadata.template_slide_index, 5)
            self.assertEqual(deck.metadata.theme_color, "ACCENT_1")
            self.assertEqual(deck.template_path, "/path/to/template.pptx")

            Path(f.name).unlink()

    def test_load_bullet_slides(self):
        """Load YAML with bullet-style slides."""
        yaml_content = """
title: Bullet Deck
slides:
  - title: Slide 1
    bullets:
      - First bullet
      - Second bullet
      - Third bullet
  - title: Slide 2
    layout: bullet
    bullets:
      - Another bullet
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()

            deck = load_deck_from_yaml(f.name)

            self.assertEqual(len(deck.slides), 2)

            slide1 = deck.slides[0]
            self.assertIsInstance(slide1, SlideContent)
            self.assertEqual(slide1.title, "Slide 1")
            self.assertEqual(len(slide1.bullets), 3)
            self.assertEqual(slide1.bullets[0].text, "First bullet")
            self.assertEqual(slide1.bullets[1].text, "Second bullet")
            self.assertEqual(slide1.bullets[2].text, "Third bullet")

            slide2 = deck.slides[1]
            self.assertEqual(slide2.layout, "bullet")
            self.assertEqual(len(slide2.bullets), 1)

            Path(f.name).unlink()

    def test_load_table_slides(self):
        """Load YAML with table-style slides."""
        yaml_content = """
title: Table Deck
slides:
  - title: Data Table
    layout: table
    headers:
      - Name
      - Value
      - Status
    rows:
      - [Item 1, 100, Active]
      - [Item 2, 200, Inactive]
    first_col_width: 2.5
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()

            deck = load_deck_from_yaml(f.name)

            self.assertEqual(len(deck.slides), 1)

            table_slide = deck.slides[0]
            self.assertIsInstance(table_slide, TableSlide)
            self.assertEqual(table_slide.title, "Data Table")
            self.assertEqual(table_slide.layout, "table")
            self.assertEqual(table_slide.headers, ["Name", "Value", "Status"])
            self.assertEqual(len(table_slide.rows), 2)
            self.assertEqual(table_slide.rows[0], ["Item 1", 100, "Active"])
            self.assertEqual(table_slide.first_col_width, 2.5)

            Path(f.name).unlink()

    def test_load_mixed_bullets_strings_and_dicts(self):
        """Load YAML with bullets that are both strings and dicts."""
        yaml_content = """
title: Mixed Bullets
slides:
  - title: Mixed Slide
    bullets:
      - Simple string bullet
      - text: Dict-style bullet
        level: 1
      - text: Highlighted bullet
        level: 0
        highlight:
          - important
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()

            deck = load_deck_from_yaml(f.name)

            slide = deck.slides[0]
            self.assertEqual(len(slide.bullets), 3)

            # String bullet (now wrapped in BulletItem)
            self.assertIsInstance(slide.bullets[0], BulletItem)
            self.assertEqual(slide.bullets[0].text, "Simple string bullet")

            # Dict bullet with level
            self.assertIsInstance(slide.bullets[1], BulletItem)
            self.assertEqual(slide.bullets[1].text, "Dict-style bullet")
            self.assertEqual(slide.bullets[1].level, 1)

            # Dict bullet with highlight
            self.assertIsInstance(slide.bullets[2], BulletItem)
            self.assertEqual(slide.bullets[2].text, "Highlighted bullet")
            self.assertEqual(slide.bullets[2].highlight, ["important"])

            Path(f.name).unlink()

    def test_load_highlights_as_string(self):
        """Load YAML with highlights specified as a single string."""
        yaml_content = """
title: Single Highlight
slides:
  - title: Highlight Slide
    bullets:
      - text: This is a test bullet
        highlight: test
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()

            deck = load_deck_from_yaml(f.name)

            bullet = deck.slides[0].bullets[0]
            self.assertIsInstance(bullet, BulletItem)
            # Single string highlight should be converted to list
            self.assertEqual(bullet.highlight, ["test"])

            Path(f.name).unlink()

    def test_load_highlights_as_list(self):
        """Load YAML with highlights specified as a list."""
        yaml_content = """
title: Multiple Highlights
slides:
  - title: Multi Highlight Slide
    bullets:
      - text: Multiple words highlighted here
        highlight:
          - Multiple
          - highlighted
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()

            deck = load_deck_from_yaml(f.name)

            bullet = deck.slides[0].bullets[0]
            self.assertIsInstance(bullet, BulletItem)
            self.assertEqual(bullet.highlight, ["Multiple", "highlighted"])

            Path(f.name).unlink()

    def test_default_values_applied(self):
        """Verify default values are applied when fields are missing."""
        yaml_content = """
slides:
  - bullets:
      - text: Minimal bullet
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()

            deck = load_deck_from_yaml(f.name)

            # Metadata defaults
            self.assertEqual(deck.metadata.title, "Untitled")
            self.assertIsNone(deck.metadata.author)
            self.assertEqual(deck.metadata.template_slide_index, 0)
            self.assertEqual(deck.metadata.theme_color, "LIGHT_2")

            # Slide defaults
            slide = deck.slides[0]
            self.assertEqual(slide.title, "")
            self.assertEqual(slide.layout, "bullet")

            # Bullet defaults
            bullet = slide.bullets[0]
            self.assertIsInstance(bullet, BulletItem)
            self.assertEqual(bullet.level, 0)
            self.assertEqual(bullet.highlight, [])

            Path(f.name).unlink()


if __name__ == "__main__":
    unittest.main()
