"""Tests for per-slide layout selection via layout_map.

Covers:
- layout_map parsing from YAML and dict
- Per-slide layout selection in generation
- Fallback to template_slide_index when layout_map is None
- Invalid layout_map indices produce clear errors
- CLI --layout-map flag parsing
- Backward compatibility
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from slides.cli import _parse_layout_map_flag
from slides.constants import RESERVED_LAYOUT_KEY
from slides.generator import SlideGenerator, load_deck_from_yaml
from slides.parsers import _parse_layout_map, load_deck_from_dict
from slides.schema import (
    DeckMetadata,
    SlideContent,
    SlideDeck,
)


class TestParseLayoutMap(unittest.TestCase):
    """Tests for _parse_layout_map validation."""

    def test_none_returns_none(self) -> None:
        """None input returns None."""
        self.assertIsNone(_parse_layout_map(None))

    def test_valid_map(self) -> None:
        """Valid integer values are accepted."""
        result = _parse_layout_map({"section": 0, "bullet": 1, "table": 1})
        self.assertEqual(result, {"section": 0, "bullet": 1, "table": 1})

    def test_negative_index_raises(self) -> None:
        """Negative index raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            _parse_layout_map({"section": -1})
        self.assertIn("non-negative integer", str(ctx.exception))
        self.assertIn("section", str(ctx.exception))

    def test_string_index_raises(self) -> None:
        """Non-integer value raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            _parse_layout_map({"bullet": "zero"})
        self.assertIn("non-negative integer", str(ctx.exception))

    def test_float_index_raises(self) -> None:
        """Float value raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            _parse_layout_map({"bullet": 1.5})
        self.assertIn("non-negative integer", str(ctx.exception))

    def test_empty_map_returns_empty(self) -> None:
        """Empty dict returns empty dict (not None)."""
        result = _parse_layout_map({})
        self.assertEqual(result, {})

    def test_non_dict_raises(self) -> None:
        """Non-mapping input raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            _parse_layout_map(["section", 0])
        self.assertIn("must be a mapping", str(ctx.exception))

    def test_reserved_key_raises(self) -> None:
        """Reserved key __fallback__ raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            _parse_layout_map({"__fallback__": 0})
        self.assertIn("reserved", str(ctx.exception))


class TestLoadDeckFromYamlWithLayoutMap(unittest.TestCase):
    """Tests for layout_map parsing from YAML files."""

    def test_yaml_with_layout_map(self) -> None:
        """YAML with layout_map populates DeckMetadata.layout_map."""
        yaml_content = """
title: Branded Deck
template_slide_index: 1
layout_map:
  section: 0
  bullet: 1
  table: 1
slides:
  - title: Section Break
    layout: section
  - title: Content
    layout: bullet
    bullets:
      - First point
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as f:
            f.write(yaml_content)
        self.addCleanup(Path(f.name).unlink, missing_ok=True)

        deck = load_deck_from_yaml(f.name)

        self.assertEqual(
            deck.metadata.layout_map,
            {"section": 0, "bullet": 1, "table": 1},
        )
        self.assertEqual(len(deck.slides), 2)
        self.assertEqual(deck.slides[0].layout, "section")
        self.assertEqual(deck.slides[1].layout, "bullet")

    def test_yaml_without_layout_map(self) -> None:
        """YAML without layout_map leaves field as None (backward compat)."""
        yaml_content = """
title: Legacy Deck
template_slide_index: 11
slides: []
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as f:
            f.write(yaml_content)
        self.addCleanup(Path(f.name).unlink, missing_ok=True)

        deck = load_deck_from_yaml(f.name)

        self.assertIsNone(deck.metadata.layout_map)
        self.assertEqual(deck.metadata.template_slide_index, 11)

    def test_yaml_invalid_layout_map_value(self) -> None:
        """YAML with non-integer layout_map value raises ValueError."""
        yaml_content = """
title: Bad Deck
layout_map:
  section: "not_a_number"
slides: []
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as f:
            f.write(yaml_content)
        self.addCleanup(Path(f.name).unlink, missing_ok=True)

        with self.assertRaises(ValueError) as ctx:
            load_deck_from_yaml(f.name)
        self.assertIn("non-negative integer", str(ctx.exception))


class TestLoadDeckFromDictWithLayoutMap(unittest.TestCase):
    """Tests for layout_map parsing via load_deck_from_dict."""

    def test_dict_with_layout_map(self) -> None:
        """Dict with layout_map populates DeckMetadata.layout_map."""
        data = {
            "title": "Dict Deck",
            "layout_map": {"section": 0, "bullet": 1},
            "slides": [
                {"title": "Intro", "layout": "section"},
            ],
        }
        deck = load_deck_from_dict(data)
        self.assertEqual(deck.metadata.layout_map, {"section": 0, "bullet": 1})

    def test_dict_without_layout_map(self) -> None:
        """Dict without layout_map leaves field as None."""
        data = {"title": "Simple", "slides": []}
        deck = load_deck_from_dict(data)
        self.assertIsNone(deck.metadata.layout_map)


class TestPrepareWithLayoutMap(unittest.TestCase):
    """Tests for _prepare_presentation with layout_map."""

    def setUp(self) -> None:
        self.generator = SlideGenerator(template_path="/fake/template.pptx")

    @patch("slides.generator.Presentation")
    def test_layout_map_extracts_layouts_and_deletes_slides(
        self, mock_prs_class: MagicMock,
    ) -> None:
        """With layout_map, layouts are extracted and all slides deleted."""
        mock_prs = MagicMock()
        mock_prs_class.return_value = mock_prs

        # Simulate 3 template slides with distinct layouts
        mock_layout_0 = MagicMock(name="SectionLayout")
        mock_layout_1 = MagicMock(name="BulletLayout")
        mock_slide_0 = MagicMock(slide_layout=mock_layout_0)
        mock_slide_1 = MagicMock(slide_layout=mock_layout_1)
        mock_slide_2 = MagicMock(slide_layout=mock_layout_1)

        slides_list = [mock_slide_0, mock_slide_1, mock_slide_2]
        mock_slides = MagicMock()
        mock_slides.__len__ = MagicMock(return_value=3)
        mock_slides.__getitem__ = lambda self_inner, idx: slides_list[idx]

        # Simulate _sldIdLst for deletion; __len__ must track the live list
        mock_sld_ids = []
        for i in range(3):
            entry = MagicMock()
            entry.get.return_value = f"rId{i}"
            entry.rId = f"rId{i}"
            mock_sld_ids.append(entry)
        mock_slides._sldIdLst = mock_sld_ids
        mock_slides.__len__ = lambda self_inner: len(mock_sld_ids)
        mock_prs.slides = mock_slides
        mock_prs.part = MagicMock()

        deck = SlideDeck(
            metadata=DeckMetadata(
                title="Test",
                template_slide_index=1,
                layout_map={"section": 0, "bullet": 1},
            ),
            slides=[],
        )

        prs, first_slide, layouts, theme_color = self.generator._prepare_presentation(deck)

        # first_slide should be None in layout_map mode
        self.assertIsNone(first_slide)
        # layouts should be a dict
        self.assertIsInstance(layouts, dict)
        self.assertIs(layouts["section"], mock_layout_0)
        self.assertIs(layouts["bullet"], mock_layout_1)
        # Should have fallback key
        self.assertIn(RESERVED_LAYOUT_KEY, layouts)

    @patch("slides.generator.Presentation")
    def test_layout_map_out_of_bounds_raises(
        self, mock_prs_class: MagicMock,
    ) -> None:
        """layout_map index exceeding template slide count raises ValueError."""
        mock_prs = MagicMock()
        mock_prs_class.return_value = mock_prs
        mock_slides = MagicMock()
        mock_slides.__len__ = MagicMock(return_value=2)
        mock_prs.slides = mock_slides

        deck = SlideDeck(
            metadata=DeckMetadata(
                title="Test",
                layout_map={"section": 5},
            ),
            slides=[],
        )

        with self.assertRaises(ValueError) as ctx:
            self.generator._prepare_presentation(deck)

        self.assertIn("layout_map['section']", str(ctx.exception))
        self.assertIn("out of bounds", str(ctx.exception))
        self.assertIn("2 slides", str(ctx.exception))

    @patch("slides.generator.Presentation")
    def test_layout_map_fallback_to_first_entry(
        self, mock_prs_class: MagicMock,
    ) -> None:
        """When template_slide_index is out of bounds, fallback uses first layout_map entry."""
        mock_prs = MagicMock()
        mock_prs_class.return_value = mock_prs

        mock_layout_0 = MagicMock(name="SectionLayout")
        mock_slide_0 = MagicMock(slide_layout=mock_layout_0)
        slides_list = [mock_slide_0]
        mock_slides = MagicMock()
        mock_slides.__len__ = lambda self_inner: len(mock_sld_ids)
        mock_slides.__getitem__ = lambda self_inner, idx: slides_list[idx]

        mock_sld_ids = []
        entry = MagicMock()
        entry.get.return_value = "rId0"
        entry.rId = "rId0"
        mock_sld_ids.append(entry)
        mock_slides._sldIdLst = mock_sld_ids
        mock_prs.slides = mock_slides
        mock_prs.part = MagicMock()

        deck = SlideDeck(
            metadata=DeckMetadata(
                title="Test",
                template_slide_index=99,  # out of bounds
                layout_map={"section": 0},
            ),
            slides=[],
        )

        prs, first_slide, layouts, theme_color = self.generator._prepare_presentation(deck)

        # Fallback should come from the first layout_map entry
        self.assertIn(RESERVED_LAYOUT_KEY, layouts)
        self.assertEqual(layouts[RESERVED_LAYOUT_KEY], mock_layout_0)


class TestResolveLayout(unittest.TestCase):
    """Tests for _resolve_layout method."""

    def setUp(self) -> None:
        self.generator = SlideGenerator(template_path="/fake/template.pptx")

    def test_single_layout_passthrough(self) -> None:
        """When layouts is a single object (legacy), it is returned as-is."""
        layout = MagicMock(name="SingleLayout")
        content = SlideContent(title="Test", layout="section")
        result = self.generator._resolve_layout(layout, content)
        self.assertIs(result, layout)

    def test_dict_layout_exact_match(self) -> None:
        """When content.layout matches a key in the dict, that layout is used."""
        section_layout = MagicMock(name="SectionLayout")
        bullet_layout = MagicMock(name="BulletLayout")
        fallback = MagicMock(name="Fallback")
        layouts = {
            "section": section_layout,
            "bullet": bullet_layout,
            RESERVED_LAYOUT_KEY: fallback,
        }
        content = SlideContent(title="Break", layout="section")
        result = self.generator._resolve_layout(layouts, content)
        self.assertIs(result, section_layout)

    def test_dict_layout_falls_back_to_default(self) -> None:
        """When content.layout is not in the dict, fallback layout is used."""
        bullet_layout = MagicMock(name="BulletLayout")
        fallback = MagicMock(name="Fallback")
        layouts = {
            "bullet": bullet_layout,
            RESERVED_LAYOUT_KEY: fallback,
        }
        content = SlideContent(title="Unknown", layout="custom_unknown")
        result = self.generator._resolve_layout(layouts, content)
        self.assertIs(result, fallback)


class TestGenerateWithLayoutMap(unittest.TestCase):
    """Tests for generate() with layout_map mode."""

    @patch("slides.generator.Presentation")
    def test_generate_uses_per_slide_layouts(
        self, mock_prs_class: MagicMock,
    ) -> None:
        """Each slide uses the layout from layout_map based on its layout field."""
        mock_prs = MagicMock()
        mock_prs_class.return_value = mock_prs

        mock_section_layout = MagicMock(name="SectionLayout")
        mock_bullet_layout = MagicMock(name="BulletLayout")

        mock_slide_0 = MagicMock(slide_layout=mock_section_layout)
        mock_slide_1 = MagicMock(slide_layout=mock_bullet_layout)

        slides_list = [mock_slide_0, mock_slide_1]
        mock_slides = MagicMock()
        mock_slides.__len__ = MagicMock(return_value=2)
        mock_slides.__getitem__ = lambda self_inner, idx: slides_list[idx]

        # _sldIdLst for deletion; __len__ must track the live list
        mock_sld_ids = []
        for i in range(2):
            entry = MagicMock()
            entry.get.return_value = f"rId{i}"
            entry.rId = f"rId{i}"
            mock_sld_ids.append(entry)
        mock_slides._sldIdLst = mock_sld_ids
        mock_slides.__len__ = lambda self_inner: len(mock_sld_ids)

        # New slides added by generate()
        new_slide_1 = MagicMock()
        new_slide_1.shapes = MagicMock()
        new_slide_1.shapes.__iter__ = MagicMock(return_value=iter([]))
        new_slide_2 = MagicMock()
        new_slide_2.shapes = MagicMock()
        new_slide_2.shapes.__iter__ = MagicMock(return_value=iter([]))

        mock_slides.add_slide = MagicMock(side_effect=[new_slide_1, new_slide_2])
        mock_prs.slides = mock_slides
        mock_prs.part = MagicMock()

        deck = SlideDeck(
            metadata=DeckMetadata(
                title="Branded",
                template_slide_index=1,
                layout_map={"section": 0, "bullet": 1},
            ),
            slides=[
                SlideContent(title="Section Break", layout="section"),
                SlideContent(title="Content", layout="bullet", bullets=[]),
            ],
        )

        generator = SlideGenerator(template_path="/fake/template.pptx")
        generator.generate(deck, "/tmp/test_output.pptx")

        # Verify add_slide was called with correct layouts
        calls = mock_slides.add_slide.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertIs(calls[0][0][0], mock_section_layout)
        self.assertIs(calls[1][0][0], mock_bullet_layout)

        # Verify save was called
        mock_prs.save.assert_called_once_with("/tmp/test_output.pptx")


class TestBackwardCompatibility(unittest.TestCase):
    """Verify existing behavior is preserved when layout_map is None."""

    def test_deck_metadata_layout_map_defaults_none(self) -> None:
        """DeckMetadata without layout_map has None default."""
        meta = DeckMetadata(title="Test")
        self.assertIsNone(meta.layout_map)

    @patch("slides.generator.Presentation")
    def test_legacy_mode_first_slide_reused(
        self, mock_prs_class: MagicMock,
    ) -> None:
        """Without layout_map, first_slide is reused from template (legacy)."""
        mock_prs = MagicMock()
        mock_prs_class.return_value = mock_prs

        mock_first_slide = MagicMock()
        mock_first_slide.slide_layout = MagicMock()

        mock_slides = MagicMock()
        mock_slides.__len__ = MagicMock(return_value=12)
        mock_slides.__getitem__ = MagicMock(return_value=mock_first_slide)

        mock_sld_ids = [MagicMock(rId=f"rId{i}") for i in range(12)]
        for entry in mock_sld_ids:
            entry.get = MagicMock(return_value=None)
        mock_slides._sldIdLst = mock_sld_ids
        mock_prs.slides = mock_slides
        mock_prs.part = MagicMock()

        deck = SlideDeck(
            metadata=DeckMetadata(title="Legacy", template_slide_index=11),
            slides=[],
        )

        generator = SlideGenerator(template_path="/fake/template.pptx")
        prs, first_slide, layouts, theme_color = generator._prepare_presentation(deck)

        # In legacy mode, first_slide is returned and layouts is a single layout
        self.assertIs(first_slide, mock_first_slide)
        self.assertNotIsInstance(layouts, dict)


class TestParseLayoutMapFlag(unittest.TestCase):
    """Tests for CLI --layout-map flag parsing."""

    def test_none_returns_none(self) -> None:
        self.assertIsNone(_parse_layout_map_flag(None))

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(_parse_layout_map_flag(""))

    def test_valid_single_entry(self) -> None:
        result = _parse_layout_map_flag("bullet=1")
        self.assertEqual(result, {"bullet": 1})

    def test_valid_multiple_entries(self) -> None:
        result = _parse_layout_map_flag("section=0,bullet=1,table=1")
        self.assertEqual(result, {"section": 0, "bullet": 1, "table": 1})

    def test_spaces_are_trimmed(self) -> None:
        result = _parse_layout_map_flag(" section = 0 , bullet = 1 ")
        self.assertEqual(result, {"section": 0, "bullet": 1})

    def test_missing_equals_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _parse_layout_map_flag("section0")
        self.assertIn("expected name=index", str(ctx.exception))

    def test_non_integer_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _parse_layout_map_flag("section=abc")
        self.assertIn("must be an integer", str(ctx.exception))

    def test_negative_index_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _parse_layout_map_flag("section=-1")
        self.assertIn("non-negative", str(ctx.exception))

    def test_empty_name_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _parse_layout_map_flag("=0")
        self.assertIn("cannot be empty", str(ctx.exception))


class TestDeleteAllSlides(unittest.TestCase):
    """Tests for _delete_all_slides static method."""

    def test_deletes_all_entries(self) -> None:
        """All slides are removed from _sldIdLst."""
        mock_prs = MagicMock()
        entries = []
        for i in range(3):
            entry = MagicMock()
            entry.get.return_value = f"rId{i}"
            entry.rId = f"rId{i}"
            entries.append(entry)
        mock_prs.slides._sldIdLst = list(entries)
        mock_prs.slides.__len__ = lambda self: len(mock_prs.slides._sldIdLst)
        mock_prs.part = MagicMock()

        SlideGenerator._delete_all_slides(mock_prs)

        self.assertEqual(len(mock_prs.slides._sldIdLst), 0)
        self.assertEqual(mock_prs.part.drop_rel.call_count, 3)
