"""Tests for slides.generator.SlideGenerator class — core generate() orchestration."""

import os
import subprocess  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B602/B603 review
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pptx.enum.dml import MSO_THEME_COLOR
from pptx.enum.shapes import MSO_SHAPE_TYPE

from slides.generator import (
    SlideGenerator,
    generate_from_yaml,
    generate_pptx,
)
from slides.schema import (
    DeckMetadata,
    SlideContent,
    SlideDeck,
    TableSlide,
)


class TestSlideGeneratorInit(unittest.TestCase):
    """Tests for SlideGenerator initialization."""

    def test_init_with_template_path(self):
        """SlideGenerator initializes with template path."""
        generator = SlideGenerator(template_path="/path/to/template.pptx")
        self.assertEqual(generator.template_path, "/path/to/template.pptx")

    def test_init_none_template_path(self):
        """SlideGenerator accepts None template_path."""
        generator = SlideGenerator(template_path=None)
        self.assertIsNone(generator.template_path)


class TestSlideGeneratorGenerateFromYaml(unittest.TestCase):
    """Tests for SlideGenerator.generate_from_yaml instance method."""

    @patch.object(SlideGenerator, 'generate')
    @patch('slides.generator.load_deck_from_yaml')
    def test_generate_from_yaml_instance_method(self, mock_load, mock_generate):
        """Test the instance method generate_from_yaml."""
        mock_deck = MagicMock()
        mock_load.return_value = mock_deck
        mock_generate.return_value = "/output/slides.pptx"

        generator = SlideGenerator(template_path="/template.pptx")
        result = generator.generate_from_yaml("/input/deck.yaml", "/output/slides.pptx")

        mock_load.assert_called_once_with("/input/deck.yaml")
        mock_generate.assert_called_once_with(mock_deck, "/output/slides.pptx")
        self.assertEqual(result, "/output/slides.pptx")


class TestSlideGeneratorGenerate(unittest.TestCase):
    """Tests for SlideGenerator.generate method."""

    def test_raises_without_template(self):
        """Raises ValueError when no template path provided."""
        # Create generator with None template path
        generator = SlideGenerator(template_path=None)

        deck = SlideDeck(
            metadata=DeckMetadata(title="Test"),
            slides=[],
            template_path=None,
        )

        with self.assertRaises(ValueError) as ctx:
            generator.generate(deck, "/tmp/output.pptx")  # nosec B108 - mock path arg, Presentation is patched

        self.assertIn("No template path provided", str(ctx.exception))

    @patch("slides.generator.Presentation")
    def test_generates_file(self, mock_presentation_class):
        """Generates PPTX file with mocked Presentation."""
        mock_prs = MagicMock()
        mock_presentation_class.return_value = mock_prs

        # Setup mock slides
        mock_slide = MagicMock()
        mock_slides_list = MagicMock()
        mock_slides_list.__len__ = MagicMock(return_value=1)
        mock_slides_list.__getitem__ = MagicMock(return_value=mock_slide)
        mock_slides_list._sldIdLst = [MagicMock(rId="rId1")]
        mock_prs.slides = mock_slides_list
        mock_prs.part = MagicMock()

        # Setup mock shapes
        mock_shape = MagicMock()
        mock_shape.is_placeholder = True
        mock_shape.has_text_frame = True
        mock_shape.text_frame = MagicMock()
        mock_shape.text_frame.paragraphs = [MagicMock()]
        mock_shape.text_frame.paragraphs[0].runs = []
        mock_slide.shapes = [mock_shape]
        mock_slide.slide_layout = MagicMock()

        generator = SlideGenerator(template_path="/path/to/template.pptx")
        deck = SlideDeck(
            metadata=DeckMetadata(title="Test Deck", template_slide_index=0),
            slides=[],
            template_path=None,  # Use generator's template
        )

        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            output_path = f.name

        result = generator.generate(deck, output_path)

        self.assertEqual(result, output_path)
        mock_presentation_class.assert_called_once_with("/path/to/template.pptx")
        mock_prs.save.assert_called_once_with(output_path)

        Path(output_path).unlink(missing_ok=True)

    @patch("slides.generator.Presentation")
    def test_bullet_slide_generation(self, mock_presentation_class):
        """Generates slide with bullet content."""
        mock_prs = MagicMock()
        mock_presentation_class.return_value = mock_prs

        # Create mock slide with proper structure
        mock_slide = MagicMock()
        mock_text_box = MagicMock()
        mock_text_box.is_placeholder = False
        mock_text_box.shape_type = MSO_SHAPE_TYPE.TEXT_BOX
        mock_text_box.has_text_frame = True
        mock_text_frame = MagicMock()
        mock_text_box.text_frame = mock_text_frame

        mock_title = MagicMock()
        mock_title.is_placeholder = True
        mock_title.has_text_frame = True
        mock_title.placeholder_format.idx = 0
        mock_title.text_frame = MagicMock()
        mock_title_para = MagicMock()
        mock_title_para.text = ""
        mock_title.text_frame.paragraphs = [mock_title_para]
        mock_title_para.runs = []

        mock_slide.shapes = [mock_title, mock_text_box]
        mock_slide.slide_layout = MagicMock()

        mock_slides_list = MagicMock()
        mock_slides_list.__len__ = MagicMock(return_value=12)
        mock_slides_list.__getitem__ = MagicMock(return_value=mock_slide)
        mock_slides_list._sldIdLst = [MagicMock(rId=f"rId{i}") for i in range(12)]
        mock_prs.slides = mock_slides_list
        mock_prs.part = MagicMock()

        generator = SlideGenerator(template_path="/path/to/template.pptx")
        deck = SlideDeck(
            metadata=DeckMetadata(title="Bullet Deck"),
            slides=[
                SlideContent(
                    title="Test Slide",
                    bullets=["First bullet", "Second bullet"],
                )
            ],
        )

        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            output_path = f.name

        generator.generate(deck, output_path)

        # Verify template was loaded and file was saved
        mock_presentation_class.assert_called_once()
        mock_prs.save.assert_called_once()

        Path(output_path).unlink(missing_ok=True)

    @patch("slides.generator.Presentation")
    def test_table_slide_generation(self, mock_presentation_class):
        """Generates slide with table content."""
        mock_prs = MagicMock()
        mock_presentation_class.return_value = mock_prs

        # Create mock slide
        mock_slide = MagicMock()
        mock_title = MagicMock()
        mock_title.is_placeholder = True
        mock_title.has_text_frame = True
        mock_title.placeholder_format.idx = 0
        mock_title.text_frame = MagicMock()
        mock_title_para = MagicMock()
        mock_title_para.text = ""
        mock_title.text_frame.paragraphs = [mock_title_para]
        mock_title_para.runs = []

        mock_text_box = MagicMock()
        mock_text_box.is_placeholder = False
        mock_text_box.shape_type = MSO_SHAPE_TYPE.TEXT_BOX
        mock_text_box._element = MagicMock()

        mock_slide.shapes = MagicMock()
        mock_slide.shapes.__iter__ = MagicMock(return_value=iter([mock_title, mock_text_box]))
        mock_slide.shapes.add_table = MagicMock()
        mock_table_shape = MagicMock()
        mock_table = MagicMock()
        mock_table_shape.table = mock_table
        mock_slide.shapes.add_table.return_value = mock_table_shape
        mock_slide.slide_layout = MagicMock()

        # Mock table cells
        mock_cell = MagicMock()
        mock_cell.text_frame = MagicMock()
        mock_cell.text_frame.paragraphs = [MagicMock()]
        mock_table.cell = MagicMock(return_value=mock_cell)
        mock_table.columns = [MagicMock() for _ in range(3)]

        mock_slides_list = MagicMock()
        mock_slides_list.__len__ = MagicMock(return_value=12)
        mock_slides_list.__getitem__ = MagicMock(return_value=mock_slide)
        mock_slides_list._sldIdLst = [MagicMock(rId=f"rId{i}") for i in range(12)]
        mock_prs.slides = mock_slides_list
        mock_prs.part = MagicMock()

        generator = SlideGenerator(template_path="/path/to/template.pptx")
        deck = SlideDeck(
            metadata=DeckMetadata(title="Table Deck"),
            slides=[
                TableSlide(
                    title="Data Table",
                    headers=["Col1", "Col2", "Col3"],
                    rows=[["A", "B", "C"], ["D", "E", "F"]],
                )
            ],
        )

        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            output_path = f.name

        generator.generate(deck, output_path)

        mock_presentation_class.assert_called_once()
        mock_prs.save.assert_called_once()

        Path(output_path).unlink(missing_ok=True)


class TestGeneratePptx(unittest.TestCase):
    """Tests for backward-compatible generate_pptx function."""

    def test_raises_without_template(self):
        """Raises ValueError when no template path provided."""
        deck = SlideDeck(
            metadata=DeckMetadata(title="Test"),
            slides=[],
            template_path=None,
        )

        with self.assertRaises(ValueError) as ctx:
            generate_pptx(deck, "/tmp/output.pptx")  # nosec B108 - mock path arg, no file created

        self.assertIn("No template path provided", str(ctx.exception))

    def test_template_path_override(self):
        """Template path parameter overrides deck template_path."""
        deck = SlideDeck(
            metadata=DeckMetadata(title="Test"),
            slides=[],
            template_path="/original/template.pptx",
        )

        with patch("slides.generator.SlideGenerator") as mock_gen_class:
            mock_gen = MagicMock()
            mock_gen_class.return_value = mock_gen
            mock_gen.generate.return_value = "/tmp/output.pptx"  # nosec B108 - mock return value, no file created

            with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
                generate_pptx(deck, f.name, template_path="/override/template.pptx")

            # Check that SlideGenerator was created with override template
            mock_gen_class.assert_called_once()
            call_kwargs = mock_gen_class.call_args
            self.assertEqual(call_kwargs[1]["template_path"], "/override/template.pptx")

            Path(f.name).unlink(missing_ok=True)


class TestGenerateFromYaml(unittest.TestCase):
    """Tests for generate_from_yaml convenience function."""

    @patch("slides.generator.SlideGenerator")
    @patch("slides.generator.load_deck_from_yaml")
    def test_loads_yaml_and_generates(self, mock_load, mock_gen_class):
        """Loads YAML and calls generate."""
        mock_deck = MagicMock()
        mock_deck.template_path = "/template.pptx"
        mock_deck.metadata = MagicMock()
        mock_deck.metadata.theme_color = "LIGHT_2"
        mock_load.return_value = mock_deck

        mock_gen = MagicMock()
        mock_gen_class.return_value = mock_gen
        mock_gen.generate.return_value = "/output/file.pptx"

        result = generate_from_yaml(
            "/input/deck.yaml",
            "/output/file.pptx",
        )

        mock_load.assert_called_once_with("/input/deck.yaml")
        mock_gen.generate.assert_called_once_with(mock_deck, "/output/file.pptx")
        self.assertEqual(result, "/output/file.pptx")

    def test_raises_without_template(self):
        """Raises ValueError when no template available."""
        yaml_content = """
title: No Template
slides: []
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()

            with self.assertRaises(ValueError) as ctx:
                generate_from_yaml(f.name, "/output.pptx")

            self.assertIn("No template path provided", str(ctx.exception))

            Path(f.name).unlink()


class TestSlideGeneratorMultipleSlides(unittest.TestCase):
    """Tests for generating decks with multiple slides."""

    @patch('slides.generator.Presentation')
    @patch('slides.generator.copy.deepcopy')
    def test_generate_multiple_bullet_slides(self, mock_deepcopy, mock_prs_class):
        """Test generating deck with multiple bullet slides."""
        # Set up mock presentation
        mock_prs = MagicMock()
        mock_prs_class.return_value = mock_prs

        mock_layout = MagicMock()
        mock_prs.slides.__getitem__.return_value.slide_layout = mock_layout

        # First slide mock
        mock_first_slide = MagicMock()
        mock_first_shape = MagicMock()
        mock_first_shape.is_placeholder = False

        mock_first_shape.shape_type = MSO_SHAPE_TYPE.TEXT_BOX
        mock_first_shape.element = MagicMock()
        mock_first_slide.shapes = [mock_first_shape]

        # New slide mock
        mock_new_slide = MagicMock()
        mock_new_slide.shapes._spTree = MagicMock()
        mock_new_slide.shapes = []

        mock_prs.slides.add_slide.return_value = mock_new_slide

        # Setup slides with proper len - needed for template_slide_index validation
        mock_prs.slides.__len__ = MagicMock(return_value=1)
        mock_prs.slides.__iter__.return_value = iter([mock_first_slide])

        # Mock deepcopy to return an element
        mock_deepcopy.return_value = MagicMock()

        generator = SlideGenerator(template_path="/template.pptx")

        deck = SlideDeck(
            metadata=DeckMetadata(title="Multi-Slide", template_slide_index=0),
            slides=[
                SlideContent(title="Slide 1", bullets=["Bullet 1"]),
                SlideContent(title="Slide 2", bullets=["Bullet 2"]),
            ],
        )

        with patch.object(generator, '_set_slide_content'):
            with patch.object(generator, '_set_slide_title'):
                with patch.object(generator, '_reposition_textbox'):
                    generator.generate(deck, "/output.pptx")

        # Verify add_slide was called for second slide
        mock_prs.slides.add_slide.assert_called()
        mock_prs.save.assert_called_once_with("/output.pptx")

    @patch('slides.generator.Presentation')
    def test_generate_table_slide(self, mock_prs_class):
        """Test generating a table slide."""
        mock_prs = MagicMock()
        mock_prs_class.return_value = mock_prs

        mock_first_slide = MagicMock()
        mock_layout = MagicMock()
        mock_first_slide.slide_layout = mock_layout

        # Setup mock slides list with proper len - needed for template_slide_index validation
        mock_slides_list = MagicMock()
        mock_slides_list.__len__ = MagicMock(return_value=1)
        mock_slides_list.__getitem__ = MagicMock(return_value=mock_first_slide)
        mock_slides_list.__iter__ = MagicMock(return_value=iter([mock_first_slide]))
        mock_slides_list._sldIdLst = [MagicMock(rId="rId1")]
        mock_prs.slides = mock_slides_list
        mock_prs.part = MagicMock()

        mock_new_slide = MagicMock()
        mock_prs.slides.add_slide.return_value = mock_new_slide

        generator = SlideGenerator(template_path="/template.pptx")

        deck = SlideDeck(
            metadata=DeckMetadata(title="Table Deck", template_slide_index=0),
            slides=[
                SlideContent(title="First Slide", bullets=["Intro"]),
                TableSlide(
                    title="Data Table",
                    headers=["Col A", "Col B"],
                    rows=[["1", "2"], ["3", "4"]],
                    first_col_width=2.5,
                ),
            ],
        )

        with patch.object(generator, '_set_slide_content'):
            with patch.object(generator, '_set_slide_title'):
                with patch.object(generator, '_add_table_to_slide') as mock_add_table:
                    generator.generate(deck, "/output.pptx")

        # Verify _add_table_to_slide was called
        mock_add_table.assert_called_once()
        call_args = mock_add_table.call_args
        self.assertEqual(call_args[0][1], ["Col A", "Col B"])  # headers
        self.assertEqual(call_args[0][2], [["1", "2"], ["3", "4"]])  # rows

    @patch('slides.generator.Presentation')
    @patch('slides.generator.copy.deepcopy')
    def test_generate_clones_textbox_for_bullet_slides(self, mock_deepcopy, mock_prs_class):
        """Test that generating multiple bullet slides clones the text box."""
        mock_prs = MagicMock()
        mock_prs_class.return_value = mock_prs

        # First slide with text box shape and title placeholder
        mock_first_slide = MagicMock()
        mock_title = MagicMock()
        mock_title.is_placeholder = True
        mock_title.has_text_frame = True
        mock_title.placeholder_format.idx = 0
        mock_title.text_frame = MagicMock()
        mock_title_para = MagicMock()
        mock_title_para.text = ""
        mock_title_para.runs = []
        mock_title.text_frame.paragraphs = [mock_title_para]

        mock_textbox = MagicMock()
        mock_textbox.is_placeholder = False
        mock_textbox.shape_type = MSO_SHAPE_TYPE.TEXT_BOX
        mock_textbox.has_text_frame = True
        mock_textbox_element = MagicMock()
        mock_textbox.element = mock_textbox_element
        mock_textbox.text_frame = MagicMock()
        mock_textbox.text_frame.paragraphs = [MagicMock()]

        mock_first_slide.shapes = [mock_title, mock_textbox]
        mock_first_slide.slide_layout = MagicMock()

        # Setup slides collection
        mock_prs.slides.__getitem__.return_value = mock_first_slide
        mock_prs.slides.__len__ = MagicMock(return_value=1)
        mock_prs.slides._sldIdLst = [MagicMock(rId="rId1")]

        # New slide mock - shapes is MagicMock with _spTree attribute
        mock_new_slide = MagicMock()
        mock_sp_tree = MagicMock()
        mock_new_slide.shapes._spTree = mock_sp_tree
        # Make shapes iterable (returns empty for _find_shape)
        mock_new_slide.shapes.__iter__ = MagicMock(return_value=iter([]))
        mock_prs.slides.add_slide.return_value = mock_new_slide

        # Set up deepcopy to return an element
        mock_cloned_element = MagicMock()
        mock_deepcopy.return_value = mock_cloned_element

        generator = SlideGenerator(template_path="/template.pptx")

        deck = SlideDeck(
            metadata=DeckMetadata(title="Multi-Bullet", template_slide_index=0),
            slides=[
                SlideContent(title="Slide 1", bullets=["Bullet 1"]),
                SlideContent(title="Slide 2", bullets=["Bullet 2"]),  # Second bullet slide
            ],
        )

        # Generate without patching internal methods to trigger cloning logic
        generator.generate(deck, "/output.pptx")

        # Verify deepcopy was called: first to save template, then to clone per slide
        # First call saves the text box element as template
        calls = mock_deepcopy.call_args_list
        assert any(  # nosec B101 - real test assertion
            c.args == (mock_textbox_element,) for c in calls
        ), f"Expected deepcopy to be called with text box element. Calls: {calls}"
        # Verify insert_element_before was called on the new slide
        mock_sp_tree.insert_element_before.assert_called_with(
            mock_cloned_element, "p:extLst"
        )


class TestSlideGeneratorFirstSlideHandling(unittest.TestCase):
    """Tests for first slide handling in generate method."""

    @patch('slides.generator.Presentation')
    def test_first_table_slide_removes_textbox(self, mock_prs_class):
        """Test that first table slide removes the text box shape."""
        mock_prs = MagicMock()
        mock_prs_class.return_value = mock_prs

        # First slide mock with text box that should be removed
        mock_first_slide = MagicMock()
        mock_title = MagicMock()
        mock_title.is_placeholder = True
        mock_title.has_text_frame = True
        mock_title.placeholder_format.idx = 0
        mock_title.text_frame = MagicMock()
        mock_title_para = MagicMock()
        mock_title_para.text = ""
        mock_title_para.runs = []
        mock_title.text_frame.paragraphs = [mock_title_para]

        mock_textbox = MagicMock()
        mock_textbox.is_placeholder = False
        mock_textbox.shape_type = MSO_SHAPE_TYPE.TEXT_BOX
        mock_textbox._element = MagicMock()

        # Setup list() iteration - return fresh iterator each time
        mock_first_slide.shapes.__iter__ = lambda self: iter([mock_title, mock_textbox])

        mock_prs.slides.__getitem__.return_value = mock_first_slide
        mock_prs.slides.__len__ = MagicMock(return_value=1)
        mock_prs.slides._sldIdLst = [MagicMock(rId="rId1")]
        mock_first_slide.slide_layout = MagicMock()

        generator = SlideGenerator(template_path="/template.pptx")

        deck = SlideDeck(
            metadata=DeckMetadata(title="Table First", template_slide_index=0),
            slides=[
                TableSlide(
                    title="Data Table",
                    headers=["Col1", "Col2"],
                    rows=[["A", "B"]],
                ),
            ],
        )

        with patch.object(generator, '_set_slide_title'):
            with patch.object(generator, '_add_table_to_slide'):
                generator.generate(deck, "/output.pptx")

        # Verify the text box element was removed
        mock_textbox._element.getparent().remove.assert_called_with(mock_textbox._element)


class TestInferLayoutMapFromTemplate(unittest.TestCase):
    """Tests for SlideGenerator.infer_layout_map_from_template."""

    def _make_mock_slide(self, layout_name: str) -> MagicMock:
        slide = MagicMock()
        slide.slide_layout.name = layout_name
        return slide

    @patch("slides.generator.Presentation")
    def test_breaker_and_object(self, mock_prs_cls):
        prs = MagicMock()
        prs.slides = [
            self._make_mock_slide("Breaker_Denim"),
            self._make_mock_slide("OBJECT"),
        ]
        mock_prs_cls.return_value = prs

        result = SlideGenerator.infer_layout_map_from_template("/fake.pptx")
        # breaker is the canonical key; section is aliased for backward compat
        self.assertEqual(result, {"breaker": 0, "section": 0, "bullet": 1, "table": 1})

    @patch("slides.generator.Presentation")
    def test_first_occurrence_wins(self, mock_prs_cls):
        prs = MagicMock()
        prs.slides = [
            self._make_mock_slide("Breaker_Denim"),
            self._make_mock_slide("OBJECT"),
            self._make_mock_slide("Breaker_Powder"),  # second breaker — ignored
            self._make_mock_slide("TITLE_AND_BODY"),  # second bullet — ignored
        ]
        mock_prs_cls.return_value = prs

        result = SlideGenerator.infer_layout_map_from_template("/fake.pptx")
        self.assertEqual(result["breaker"], 0)
        self.assertEqual(result["section"], 0)  # aliased from breaker
        self.assertEqual(result["bullet"], 1)

    @patch("slides.generator.Presentation")
    def test_section_not_aliased_when_section_header_present(self, mock_prs_cls):
        # slide-index path: SECTION_HEADER at index 2 should win over the breaker alias.
        prs = MagicMock()
        prs.slides = [
            self._make_mock_slide("Breaker_Denim"),
            self._make_mock_slide("OBJECT"),
            self._make_mock_slide("SECTION_HEADER"),
        ]
        mock_prs_cls.return_value = prs

        result = SlideGenerator.infer_layout_map_from_template("/fake.pptx")
        self.assertEqual(result["breaker"], 0)
        self.assertEqual(result["section"], 2)  # SECTION_HEADER wins, not aliased
        self.assertEqual(result["bullet"], 1)

    @patch("slides.generator.Presentation")
    def test_section_alias_applied_for_master_path(self, mock_prs_cls):
        # Master-based inference: alias fires so callers can pass section in layout_map.
        # _resolve_layouts_from_master maps section to the actual breaker layout object
        # at resolution time, so the placeholder index (0) is never used as a real index.
        prs = MagicMock()
        prs.slides = []

        mock_layout_breaker = MagicMock()
        mock_layout_breaker.name = "Breaker_Denim"
        mock_layout_bullet = MagicMock()
        mock_layout_bullet.name = "OBJECT"
        mock_master = MagicMock()
        mock_master.slide_layouts = [mock_layout_breaker, mock_layout_bullet]
        prs.slide_masters = [mock_master]

        mock_prs_cls.return_value = prs

        result = SlideGenerator.infer_layout_map_from_template("/fake.pptx")
        self.assertIn("breaker", result)
        self.assertIn("bullet", result)
        # section alias IS present — resolution uses layout object, not placeholder index
        self.assertIn("section", result)
        self.assertEqual(result["section"], result["breaker"])

    def test_resolve_layouts_aliases_section_to_breaker_object(self):
        # _resolve_layouts_from_master maps section → breaker layout object when
        # SECTION_HEADER is absent, so layout: section decks render with Breaker_*.
        breaker_layout = MagicMock()
        breaker_layout.name = "Breaker_Denim"
        bullet_layout = MagicMock()
        bullet_layout.name = "OBJECT"

        mock_master = MagicMock()
        mock_master.slide_layouts = [breaker_layout, bullet_layout]

        prs = MagicMock()
        prs.slide_masters = [mock_master]
        prs.slides = []

        layout_map = {"breaker": 0, "section": 0, "bullet": 0}
        resolved = SlideGenerator._resolve_layouts_from_master(prs, layout_map)

        # Both section and breaker resolve to the same breaker layout object
        self.assertIs(resolved["section"], breaker_layout)
        self.assertIs(resolved["breaker"], breaker_layout)
        self.assertIs(resolved["bullet"], bullet_layout)

    @patch("slides.generator.Presentation")
    def test_unrecognized_layouts_returns_none(self, mock_prs_cls):
        prs = MagicMock()
        prs.slides = [
            self._make_mock_slide("Some_Custom_Layout"),
            self._make_mock_slide("Another_Unknown"),
        ]
        mock_prs_cls.return_value = prs

        result = SlideGenerator.infer_layout_map_from_template("/fake.pptx")
        self.assertIsNone(result)

    @patch("slides.generator.Presentation")
    def test_table_aliases_bullet(self, mock_prs_cls):
        prs = MagicMock()
        prs.slides = [self._make_mock_slide("OBJECT")]
        mock_prs_cls.return_value = prs

        result = SlideGenerator.infer_layout_map_from_template("/fake.pptx")
        self.assertIn("table", result)
        self.assertEqual(result["table"], result["bullet"])

    @patch("slides.generator.Presentation")
    def test_title_only_mapping(self, mock_prs_cls):
        prs = MagicMock()
        prs.slides = [
            self._make_mock_slide("Title Slide with Streams"),
            self._make_mock_slide("OBJECT"),
        ]
        mock_prs_cls.return_value = prs

        result = SlideGenerator.infer_layout_map_from_template("/fake.pptx")
        self.assertEqual(result["title_only"], 0)

    @patch("slides.generator.Presentation")
    def test_empty_slides(self, mock_prs_cls):
        prs = MagicMock()
        prs.slides = []
        mock_prs_cls.return_value = prs

        result = SlideGenerator.infer_layout_map_from_template("/fake.pptx")
        self.assertIsNone(result)


class TestPopulateSlideTableRejection(unittest.TestCase):
    """Tests for _populate_slide rejecting TableSlide with rows but no headers."""

    def setUp(self):
        self.generator = SlideGenerator(template_path=None)

    def test_table_slide_no_headers_raises(self):
        """_populate_slide raises ValueError for a TableSlide with rows but no headers."""
        slide = MagicMock()
        content = TableSlide(
            title="Missing Headers",
            headers=[],
            rows=[["cell1", "cell2"]],
        )
        theme_color = MagicMock()
        with self.assertRaises(ValueError) as ctx:
            self.generator._populate_slide(slide, content, theme_color)
        msg = str(ctx.exception)
        self.assertIn("Missing Headers", msg)
        self.assertIn("no headers", msg)

    def test_table_slide_with_headers_does_not_raise(self):
        """_populate_slide does not raise when a TableSlide has both headers and rows."""
        slide = MagicMock()
        content = TableSlide(
            title="Good Table",
            headers=["Col A", "Col B"],
            rows=[["a", "b"]],
        )
        theme_color = MagicMock()
        with patch.object(self.generator, "_populate_table_slide") as mock_table:
            with patch.object(self.generator, "_apply_notes"):
                self.generator._populate_slide(slide, content, theme_color)
        mock_table.assert_called_once()

    def test_table_slide_no_rows_no_headers_does_not_raise(self):
        """An empty TableSlide (no rows, no headers) is not an error — no data is lost."""
        slide = MagicMock()
        content = TableSlide(title="Empty Table", headers=[], rows=[])
        theme_color = MagicMock()
        # No rows → no data loss → falls through to bullet renderer without raising
        with patch.object(self.generator, "_populate_bullet_slide") as mock_bullet:
            with patch.object(self.generator, "_apply_notes"):
                self.generator._populate_slide(slide, content, theme_color)
        mock_bullet.assert_called_once()


# ---------------------------------------------------------------------------
# Coverage-targeted tests (from test_generator_coverage.py)
# ---------------------------------------------------------------------------

class TestPreparePresentation(unittest.TestCase):
    """Cover _prepare_presentation error branches."""

    def setUp(self) -> None:
        self.generator = SlideGenerator(template_path="/fake/template.pptx")

    @patch("slides.generator.Presentation")
    def test_template_slide_index_out_of_bounds_plural(
        self, mock_prs_class: MagicMock
    ) -> None:
        """Out-of-bounds index with multiple slides uses plural 'slides'."""
        mock_prs = MagicMock()
        mock_prs_class.return_value = mock_prs
        mock_slides = MagicMock()
        mock_slides.__len__ = MagicMock(return_value=3)
        mock_prs.slides = mock_slides

        deck = SlideDeck(
            metadata=DeckMetadata(title="Test", template_slide_index=5),
            slides=[],
        )

        with self.assertRaises(ValueError) as ctx:
            self.generator._prepare_presentation(deck)

        self.assertIn("out of bounds", str(ctx.exception))
        self.assertIn("3 slides", str(ctx.exception))

    @patch("slides.generator.Presentation")
    def test_template_slide_index_out_of_bounds_singular(
        self, mock_prs_class: MagicMock
    ) -> None:
        """Out-of-bounds index with 1 slide uses singular 'slide'."""
        mock_prs = MagicMock()
        mock_prs_class.return_value = mock_prs
        mock_slides = MagicMock()
        mock_slides.__len__ = MagicMock(return_value=1)
        mock_prs.slides = mock_slides

        deck = SlideDeck(
            metadata=DeckMetadata(title="Test", template_slide_index=1),
            slides=[],
        )

        with self.assertRaises(ValueError) as ctx:
            self.generator._prepare_presentation(deck)

        self.assertIn("out of bounds", str(ctx.exception))
        # Singular: "1 slide" not "1 slides"
        self.assertIn("1 slide)", str(ctx.exception))
        self.assertNotIn("1 slides", str(ctx.exception))

    def test_no_template_raises_value_error(self) -> None:
        """Deck and generator both without template raises ValueError."""
        generator = SlideGenerator(template_path=None)
        deck = SlideDeck(
            metadata=DeckMetadata(title="Test"),
            slides=[],
            template_path=None,
        )

        with self.assertRaises(ValueError) as ctx:
            generator._prepare_presentation(deck)

        self.assertIn("No template path provided", str(ctx.exception))

    @patch("slides.generator.Presentation")
    def test_deck_template_path_takes_priority(
        self, mock_prs_class: MagicMock
    ) -> None:
        """Deck's template_path is used over generator's when both set."""
        mock_prs = MagicMock()
        mock_prs_class.return_value = mock_prs
        mock_slides = MagicMock()
        mock_slides.__len__ = MagicMock(return_value=12)
        # Need to support iteration for the keep-only-template loop
        mock_sld_ids = [MagicMock(rId=f"rId{i}") for i in range(12)]
        mock_slides._sldIdLst = mock_sld_ids
        mock_slides.__getitem__ = MagicMock(return_value=MagicMock())
        mock_prs.slides = mock_slides
        mock_prs.part = MagicMock()

        deck = SlideDeck(
            metadata=DeckMetadata(title="Test"),
            slides=[],
            template_path="/deck/template.pptx",
        )

        self.generator._prepare_presentation(deck)

        mock_prs_class.assert_called_once_with("/deck/template.pptx")


class TestGenerateMultipleSlidesWithTableAndBullets(unittest.TestCase):
    """Cover generate() path where second slide is a TableSlide (no textbox clone)."""

    @patch("slides.generator.Presentation")
    def test_second_slide_table_skips_textbox_clone(
        self, mock_prs_class: MagicMock
    ) -> None:
        """When second slide is a TableSlide with headers, textbox is not cloned."""
        mock_prs = MagicMock()
        mock_prs_class.return_value = mock_prs

        # First slide
        mock_first_slide = MagicMock()
        mock_title = MagicMock()
        mock_title.is_placeholder = True
        mock_title.has_text_frame = True
        mock_title.placeholder_format.idx = 0
        mock_title.text_frame = MagicMock()
        mock_title_para = MagicMock()
        mock_title_para.text = ""
        mock_title_para.runs = []
        mock_title.text_frame.paragraphs = [mock_title_para]

        mock_text_box = MagicMock()
        mock_text_box.is_placeholder = False
        mock_text_box.shape_type = MSO_SHAPE_TYPE.TEXT_BOX
        mock_text_box.has_text_frame = True
        mock_text_box.text_frame = MagicMock()
        mock_text_box.element = MagicMock()

        mock_first_slide.shapes = [mock_title, mock_text_box]
        mock_first_slide.slide_layout = MagicMock()

        # Second slide (new slide added)
        mock_new_slide = MagicMock()
        mock_new_slide.shapes = MagicMock()
        mock_new_slide.shapes.__iter__ = MagicMock(
            return_value=iter([MagicMock(is_placeholder=True)])
        )
        mock_table_shape = MagicMock()
        mock_table = MagicMock()
        mock_table_shape.table = mock_table
        mock_new_slide.shapes.add_table = MagicMock(return_value=mock_table_shape)
        mock_cell = MagicMock()
        mock_cell.text_frame = MagicMock()
        mock_cell.text_frame.paragraphs = [MagicMock()]
        mock_table.cell = MagicMock(return_value=mock_cell)
        mock_table.columns = [MagicMock(), MagicMock()]

        mock_slides = MagicMock()
        mock_slides.__len__ = MagicMock(return_value=12)
        mock_slides.__getitem__ = MagicMock(return_value=mock_first_slide)
        mock_slides._sldIdLst = [MagicMock(rId=f"rId{i}") for i in range(12)]
        mock_slides.add_slide = MagicMock(return_value=mock_new_slide)
        mock_prs.slides = mock_slides
        mock_prs.part = MagicMock()

        generator = SlideGenerator(template_path="/fake/template.pptx")
        deck = SlideDeck(
            metadata=DeckMetadata(title="Multi Slide", template_slide_index=0),
            slides=[
                SlideContent(title="Slide 1", bullets=["Bullet 1"]),
                TableSlide(
                    title="Table Slide",
                    headers=["A", "B"],
                    rows=[["x", "y"]],
                ),
            ],
            template_path=None,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "output.pptx")
            result = generator.generate(deck, out_path)

        self.assertEqual(result, out_path)
        # The new slide should NOT have insert_element_before called (no textbox clone)
        mock_new_slide.shapes._spTree.insert_element_before.assert_not_called()


class TestEmptyLayoutMapFallbackError(unittest.TestCase):
    """Cover line 1087: empty layout_map with invalid template_slide_index raises ValueError."""

    def setUp(self) -> None:
        self.generator = SlideGenerator(template_path="/fake/template.pptx")

    @patch("slides.generator.Presentation")
    def test_empty_layout_map_invalid_fallback_raises_value_error(
        self, mock_prs_class: MagicMock
    ) -> None:
        """Empty layout_map with out-of-bounds template_slide_index raises ValueError."""
        mock_prs = MagicMock()
        mock_prs_class.return_value = mock_prs
        mock_prs.slides.__len__ = MagicMock(return_value=2)

        deck = SlideDeck(
            metadata=DeckMetadata(
                title="Test",
                template_slide_index=99,  # out of bounds
                layout_map={},            # empty — no named layouts
            ),
            slides=[],
        )

        with self.assertRaises(ValueError) as ctx:
            self.generator._prepare_presentation(deck)

        msg = str(ctx.exception)
        self.assertIn("layout_map is empty", msg)
        self.assertIn("template_slide_index=99", msg)

    @patch("slides.generator.Presentation")
    def test_empty_layout_map_valid_fallback_does_not_raise(
        self, mock_prs_class: MagicMock
    ) -> None:
        """Empty layout_map with valid template_slide_index uses fallback without raising."""
        mock_prs = MagicMock()
        mock_prs_class.return_value = mock_prs

        # Set up prs.slides with 2 slides
        mock_slide_0 = MagicMock()
        mock_slide_0.slide_layout = MagicMock()
        mock_slides_list = [mock_slide_0, MagicMock()]

        mock_prs.slides.__len__ = MagicMock(return_value=2)
        mock_prs.slides.__getitem__ = MagicMock(side_effect=lambda i: mock_slides_list[i])

        with patch.object(self.generator, "_delete_all_slides"):
            deck = SlideDeck(
                metadata=DeckMetadata(
                    title="Test",
                    template_slide_index=0,  # valid index
                    layout_map={},           # empty but fallback is valid
                ),
                slides=[],
            )

            # Should not raise — fallback_layout comes from template_slide_index=0
            result = self.generator._prepare_presentation(deck)
            self.assertIsNotNone(result)


class TestGenerateCallsRenameSlidesParts(unittest.TestCase):
    """Verify generate() calls prs.part.rename_slide_parts with correct rel_ids."""

    def test_rename_slide_parts_called_with_rel_ids(self) -> None:
        """generate() extracts rel_ids from sldIdLst and passes to rename_slide_parts."""
        generator = SlideGenerator(template_path="/fake/template.pptx")

        # Build mock sldId elements with r:id attributes
        mock_sld_id_1 = MagicMock()
        mock_sld_id_1.get.return_value = "rId2"
        mock_sld_id_2 = MagicMock()
        mock_sld_id_2.get.return_value = "rId3"

        mock_prs = MagicMock()
        mock_prs.slides._sldIdLst = [mock_sld_id_1, mock_sld_id_2]

        deck = SlideDeck(
            metadata=DeckMetadata(title="Test"),
            slides=[SlideContent(title="Slide 1", bullets=["a"])],
        )

        with patch.object(generator, "_prepare_presentation") as mock_prep, \
             patch.object(generator, "_generate_legacy_mode"):
            # layouts="not_a_dict" (non-dict) triggers legacy mode
            mock_prep.return_value = (
                mock_prs, MagicMock(), "not_a_dict", MagicMock()
            )

            generator.generate(deck, os.path.join(tempfile.gettempdir(), "out.pptx"))

        mock_prs.part.rename_slide_parts.assert_called_once_with(["rId2", "rId3"])


class TestApplyNotes(unittest.TestCase):
    """Cover _apply_notes, including the template-notes leak path.

    Legacy mode reuses the first template slide, so notes already present on
    that slide would survive into a deck that declares none — shipping
    template-only content in the generated .pptx.
    """

    def test_writes_notes_when_present(self) -> None:
        """A deck slide with notes writes them to the notes text frame."""
        slide = MagicMock()

        SlideGenerator._apply_notes(slide, "speaker notes here")

        self.assertEqual(
            slide.notes_slide.notes_text_frame.text, "speaker notes here"
        )

    def test_clears_inherited_notes_when_deck_has_none(self) -> None:
        """A reused template slide's existing notes are cleared, not inherited."""
        slide = MagicMock()
        slide.has_notes_slide = True

        SlideGenerator._apply_notes(slide, None)

        self.assertEqual(slide.notes_slide.notes_text_frame.text, "")

    def test_does_not_create_notes_part_for_new_slide(self) -> None:
        """A slide with no notes part does not gain an empty one."""
        slide = MagicMock()
        slide.has_notes_slide = False

        SlideGenerator._apply_notes(slide, None)

        # Touching .notes_slide at all would materialise the part in python-pptx.
        self.assertNotIn("notes_slide", slide._mock_children)


class TestInferLayoutMapNoBulletLayout(unittest.TestCase):
    """Cover the branch where LAYOUT_BULLET is absent from scan result (branch 183->189)."""

    @patch("slides.generator.Presentation")
    def test_no_bullet_layout_skips_table_alias(self, mock_prs_cls):
        """When scan finds only section-type layouts and no OBJECT, table alias is not added."""
        prs = MagicMock()
        # Only a Title Slide layout — maps to title_only, not bullet
        slide = MagicMock()
        slide.slide_layout.name = "Title Slide with Streams"
        slides_mock = MagicMock()
        slides_mock.__iter__ = MagicMock(return_value=iter([slide]))
        prs.slides = slides_mock
        prs.slide_masters = []
        mock_prs_cls.return_value = prs

        result = SlideGenerator.infer_layout_map_from_template("/fake.pptx")
        # The mock template holds a recognised layout, so inference must produce a
        # mapping — assert unconditionally rather than guarding on None, or the
        # test would silently pass without checking anything.
        self.assertIsNotNone(result)
        self.assertIn("title_only", result)
        # No bullet layout was found, so the table alias must not be added.
        self.assertNotIn("table", result)


class TestGenerateRenameFnAndParent(unittest.TestCase):
    """Cover generate() branches: rename_fn missing and output in current directory."""

    @patch("slides.generator.Presentation")
    def test_generate_no_rename_fn_still_saves(self, mock_prs_cls):
        """When prs.part has no rename_slide_parts, generate() still saves without error."""
        prs = MagicMock()
        prs.slides._sldIdLst = []
        # Ensure rename_slide_parts is NOT present as an attribute
        del prs.part.rename_slide_parts
        mock_prs_cls.return_value = prs

        generator = SlideGenerator(template_path="/fake.pptx")
        deck = SlideDeck(
            metadata=DeckMetadata(title="Test"),
            slides=[],
        )

        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tf:
            out_path = tf.name
        try:
            with patch.object(generator, "_prepare_presentation") as mock_prep, \
                 patch.object(generator, "_generate_layout_map_mode"), \
                 patch.object(generator, "_generate_legacy_mode"):
                mock_prep.return_value = (prs, None, {}, MSO_THEME_COLOR.LIGHT_2)
                generator.generate(deck, out_path)
            prs.save.assert_called_once_with(out_path)
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)

    @patch("slides.generator.Presentation")
    def test_generate_basename_only_path_skips_makedirs(self, mock_prs_cls):
        """When output_path has no parent directory, makedirs is not called."""
        prs = MagicMock()
        prs.slides._sldIdLst = []
        mock_prs_cls.return_value = prs

        generator = SlideGenerator(template_path="/fake.pptx")
        deck = SlideDeck(
            metadata=DeckMetadata(title="Test"),
            slides=[],
        )

        with tempfile.TemporaryDirectory() as td:
            # Use just the basename so os.path.dirname returns ""
            basename_only = "out.pptx"
            original_dir = os.getcwd()
            os.chdir(td)
            try:
                with patch.object(generator, "_prepare_presentation") as mock_prep, \
                     patch.object(generator, "_generate_layout_map_mode"), \
                     patch.object(generator, "_generate_legacy_mode"), \
                     patch("os.makedirs") as mock_makedirs:
                    mock_prep.return_value = (prs, None, {}, MSO_THEME_COLOR.LIGHT_2)
                    generator.generate(deck, basename_only)
                # makedirs should NOT have been called (no parent directory)
                mock_makedirs.assert_not_called()
            finally:
                os.chdir(original_dir)


class TestRenderMermaidCleanupOnError(unittest.TestCase):
    """Cover os.unlink(png_path) in error handlers when png_path exists (lines 954, 961)."""

    def _make_ntf_mock(self, mmd_name: str) -> MagicMock:
        """Build a NamedTemporaryFile context manager mock with the given .mmd path."""
        mock_file = MagicMock()
        mock_file.name = mmd_name
        mock_ntf = MagicMock()
        mock_ntf.__enter__ = MagicMock(return_value=mock_file)
        mock_ntf.__exit__ = MagicMock(return_value=False)
        return mock_ntf

    def test_file_not_found_cleans_up_existing_png(self) -> None:
        """When mmdc is not found and png_path exists, os.unlink is called on the PNG."""
        mmd_name = os.path.join(tempfile.gettempdir(), "test_fnf.mmd")
        expected_png = mmd_name.replace(".mmd", ".png")

        with patch("slides.generator.subprocess.run") as mock_run, \
             patch("slides.generator.tempfile.NamedTemporaryFile") as mock_ntf_cls, \
             patch("slides.generator.os.path.exists", return_value=True) as mock_exists, \
             patch("slides.generator.os.unlink") as mock_unlink:
            mock_ntf_cls.return_value = self._make_ntf_mock(mmd_name)
            mock_run.side_effect = FileNotFoundError()

            with self.assertRaises(RuntimeError) as ctx:
                SlideGenerator._render_mermaid("graph TD\n  A --> B")

            self.assertIn("mmdc", str(ctx.exception))
            mock_exists.assert_any_call(expected_png)
            # unlink called for png (cleanup) and mmd (finally block)
            unlink_paths = [call.args[0] for call in mock_unlink.call_args_list]
            self.assertIn(expected_png, unlink_paths)

    def test_called_process_error_cleans_up_existing_png(self) -> None:
        """When mmdc exits non-zero and png_path exists, os.unlink is called on the PNG."""
        mmd_name = os.path.join(tempfile.gettempdir(), "test_cpe.mmd")
        expected_png = mmd_name.replace(".mmd", ".png")

        with patch("slides.generator.subprocess.run") as mock_run, \
             patch("slides.generator.tempfile.NamedTemporaryFile") as mock_ntf_cls, \
             patch("slides.generator.os.path.exists", return_value=True) as mock_exists, \
             patch("slides.generator.os.unlink") as mock_unlink:
            mock_ntf_cls.return_value = self._make_ntf_mock(mmd_name)
            exc = subprocess.CalledProcessError(1, "mmdc", stderr=b"render error")
            mock_run.side_effect = exc

            with self.assertRaises(RuntimeError) as ctx:
                SlideGenerator._render_mermaid("invalid mermaid")

            self.assertIn("Mermaid render failed", str(ctx.exception))
            mock_exists.assert_any_call(expected_png)
            unlink_paths = [call.args[0] for call in mock_unlink.call_args_list]
            self.assertIn(expected_png, unlink_paths)

    def test_file_not_found_skips_unlink_when_png_missing(self) -> None:
        """When mmdc is not found but png_path does not exist, os.unlink is not called for PNG."""
        mmd_name = os.path.join(tempfile.gettempdir(), "test_fnf_no_png.mmd")
        expected_png = mmd_name.replace(".mmd", ".png")

        with patch("slides.generator.subprocess.run") as mock_run, \
             patch("slides.generator.tempfile.NamedTemporaryFile") as mock_ntf_cls, \
             patch("slides.generator.os.path.exists", return_value=False), \
             patch("slides.generator.os.unlink") as mock_unlink:
            mock_ntf_cls.return_value = self._make_ntf_mock(mmd_name)
            mock_run.side_effect = FileNotFoundError()

            with self.assertRaises(RuntimeError):
                SlideGenerator._render_mermaid("graph TD\n  A --> B")

            # Only the .mmd file (finally block) should be unlinked, not the png
            unlink_paths = [call.args[0] for call in mock_unlink.call_args_list]
            self.assertNotIn(expected_png, unlink_paths)


if __name__ == "__main__":
    unittest.main()
