"""Tests for resume/docx_renderers.py base renderer classes."""
from __future__ import annotations

import unittest

from tests.resume_tests.fixtures import make_fake_renderer, mock_docx_modules


@mock_docx_modules
class TestBulletRendererConfig(unittest.TestCase):
    """Tests for BulletRenderer bullet configuration."""

    def _get_renderer(self, page_cfg=None):
        from resume.docx_renderers import BulletRenderer
        from tests.fakes.docx import FakeDocument
        doc = FakeDocument()
        renderer = BulletRenderer(doc, page_cfg=page_cfg)
        return renderer, doc

    def test_get_bullet_config_defaults(self):
        """Test default bullet config with no section."""
        renderer, _ = self._get_renderer()
        _, glyph = renderer.get_bullet_config(None)
        self.assertEqual(glyph, "•")

    def test_get_bullet_config_section_plain_style(self):
        """Test section-level plain style."""
        renderer, _ = self._get_renderer()
        sec = {"bullets": {"style": "plain"}}
        use_plain, glyph = renderer.get_bullet_config(sec)
        self.assertTrue(use_plain)
        self.assertEqual(glyph, "•")

    def test_get_bullet_config_section_plain_bullets_flag(self):
        """Test section-level plain_bullets flag."""
        renderer, _ = self._get_renderer()
        sec = {"plain_bullets": True}
        use_plain, _ = renderer.get_bullet_config(sec)
        self.assertTrue(use_plain)

    def test_get_bullet_config_section_custom_glyph(self):
        """Test section-level custom glyph."""
        renderer, _ = self._get_renderer()
        sec = {"bullets": {"glyph": "→"}}
        _, glyph = renderer.get_bullet_config(sec)
        self.assertEqual(glyph, "→")

    def test_get_bullet_config_page_level_style(self):
        """Test page-level bullet config."""
        page_cfg = {"bullets": {"style": "plain", "glyph": "▸"}}
        renderer, _ = self._get_renderer(page_cfg=page_cfg)
        use_plain, glyph = renderer.get_bullet_config(None)
        self.assertTrue(use_plain)
        self.assertEqual(glyph, "▸")

    def test_get_bullet_config_section_overrides_page(self):
        """Test section config overrides page config."""
        page_cfg = {"bullets": {"style": "plain", "glyph": "▸"}}
        renderer, _ = self._get_renderer(page_cfg=page_cfg)
        sec = {"bullets": {"style": "plain", "glyph": "→"}}
        use_plain, glyph = renderer.get_bullet_config(sec)
        self.assertTrue(use_plain)  # from section
        self.assertEqual(glyph, "→")  # from section, overrides page

    def test_get_bullet_config_non_dict_bullets(self):
        """Test section with bullets not being a dict."""
        renderer, _ = self._get_renderer()
        sec = {"bullets": True}  # Not a dict
        use_plain, glyph = renderer.get_bullet_config(sec)
        self.assertFalse(use_plain)
        self.assertEqual(glyph, "•")

    def test_extract_page_bullet_config_no_bullets_key(self):
        """Test page config without bullets key."""
        page_cfg = {"other_key": "value"}
        renderer, _ = self._get_renderer(page_cfg=page_cfg)
        use_plain, glyph = renderer.get_bullet_config(None)
        self.assertFalse(use_plain)
        self.assertEqual(glyph, "•")

    def test_extract_page_bullet_config_bullets_not_dict(self):
        """Test page config with bullets not being a dict."""
        page_cfg = {"bullets": True}
        renderer, _ = self._get_renderer(page_cfg=page_cfg)
        use_plain, glyph = renderer.get_bullet_config(None)
        self.assertFalse(use_plain)
        self.assertEqual(glyph, "•")


@mock_docx_modules
class TestBulletRendererRendering(unittest.TestCase):
    """Tests for BulletRenderer rendering methods."""

    def _get_renderer(self):
        from resume.docx_renderers import BulletRenderer
        return make_fake_renderer(BulletRenderer)

    def test_add_bullet_line_basic(self):
        """Test adding a basic bullet line."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line("Test item", glyph="•")
        self.assertEqual(len(doc.paragraphs), 1)
        runs = doc.paragraphs[0].runs
        self.assertEqual(runs[0].text, "• ")
        self.assertEqual(runs[1].text, "Test item")

    def test_add_bullet_line_with_keywords(self):
        """Test adding bullet line with keyword bolding."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Experience with Python and JavaScript",
            keywords=["Python", "JavaScript"],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        bolded = [r.text for r in runs if r.bold]
        self.assertIn("Python", bolded)
        self.assertIn("JavaScript", bolded)

    def test_add_named_bullet_basic(self):
        """Test adding named bullet."""
        renderer, doc = self._get_renderer()
        renderer.add_named_bullet("Python", "Programming language", glyph="•")
        self.assertEqual(len(doc.paragraphs), 1)
        runs = doc.paragraphs[0].runs
        self.assertEqual(runs[0].text, "• ")
        self.assertEqual(runs[1].text, "Python")
        self.assertTrue(runs[1].bold)
        self.assertEqual(runs[2].text, ": ")
        self.assertEqual(runs[3].text, "Programming language")

    def test_add_named_bullet_with_colors(self):
        """Test named bullet with color configuration."""
        renderer, doc = self._get_renderer()
        sec = {"name_color": "#FF0000"}
        renderer.add_named_bullet("Python", "Language", sec=sec, glyph="•")
        runs = doc.paragraphs[0].runs
        # Verify name run is bolded (color application tested in docx_styles)
        name_run = runs[1]
        self.assertTrue(name_run.bold)
        self.assertEqual(name_run.text, "Python")

    def test_add_named_bullet_custom_separator(self):
        """Test named bullet with custom separator."""
        renderer, doc = self._get_renderer()
        renderer.add_named_bullet("Python", "Language", glyph="•", sep=" - ")
        runs = doc.paragraphs[0].runs
        self.assertEqual(runs[2].text, " - ")

    def test_add_bullets_plain_mode(self):
        """Test adding bullets in plain mode."""
        renderer, doc = self._get_renderer()
        items = ["Item 1", "Item 2", "Item 3"]
        renderer.add_bullets(items, plain=True, glyph="•")
        self.assertEqual(len(doc.paragraphs), 3)
        for i, p in enumerate(doc.paragraphs):
            self.assertEqual(p.runs[0].text, "• ")
            self.assertEqual(p.runs[1].text, f"Item {i+1}")

    def test_add_bullets_list_style_mode(self):
        """Test adding bullets with list style (non-plain)."""
        renderer, doc = self._get_renderer()
        items = ["Item 1", "Item 2"]
        renderer.add_bullets(items, plain=False, list_style="List Bullet")
        self.assertEqual(len(doc.paragraphs), 2)
        # Verify each paragraph was created with the style
        for i, p in enumerate(doc.paragraphs):
            self.assertEqual(p.style.name, "List Bullet")

    def test_add_bullets_with_keywords(self):
        """Test adding bullets with keyword bolding in list style mode."""
        renderer, doc = self._get_renderer()
        items = ["Python developer", "JavaScript expert"]
        renderer.add_bullets(
            items,
            keywords=["Python", "JavaScript"],
            plain=False,
        )
        self.assertEqual(len(doc.paragraphs), 2)
        # Check that keywords were bolded
        all_bolded = []
        for p in doc.paragraphs:
            all_bolded.extend([r.text for r in p.runs if r.bold])
        self.assertIn("Python", all_bolded)
        self.assertIn("JavaScript", all_bolded)


@mock_docx_modules
class TestBulletRendererKeywordBolding(unittest.TestCase):
    """Tests for keyword bolding logic in BulletRenderer."""

    def _get_renderer(self):
        from resume.docx_renderers import BulletRenderer
        return make_fake_renderer(BulletRenderer)

    def test_bold_keywords_no_matches(self):
        """Test keyword bolding when no keywords match."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Experience with Ruby on Rails",
            keywords=["Python", "Java"],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        bolded = [r.text for r in runs if r.bold]
        self.assertEqual(len(bolded), 0)

    def test_bold_keywords_empty_keyword_list(self):
        """Test keyword bolding with empty list."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Experience with Python",
            keywords=[],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        bolded = [r.text for r in runs if r.bold]
        self.assertEqual(len(bolded), 0)

    def test_bold_keywords_none_in_list(self):
        """Test keyword bolding skips None/empty values."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Experience with Python",
            keywords=["Python", None, ""],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        bolded = [r.text for r in runs if r.bold]
        self.assertIn("Python", bolded)
        self.assertEqual(len(bolded), 1)

    def test_bold_keywords_case_insensitive(self):
        """Test keyword bolding is case-insensitive."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "PYTHON and javascript",
            keywords=["Python", "JavaScript"],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        bolded = [r.text for r in runs if r.bold]
        self.assertIn("PYTHON", bolded)
        self.assertIn("javascript", bolded)

    def test_bold_keywords_multiple_matches(self):
        """Test bolding multiple keyword matches in text."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Python, Java, and Go programming",
            keywords=["Python", "Java", "Go"],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        bolded = [r.text for r in runs if r.bold]
        self.assertIn("Python", bolded)
        self.assertIn("Java", bolded)
        self.assertIn("Go", bolded)

    def test_bold_keywords_overlapping(self):
        """Test keyword bolding with overlapping matches."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Python and Pythonic code",
            keywords=["Python", "Pythonic"],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        bolded = [r.text for r in runs if r.bold]
        # Current behavior: matches first occurrence
        self.assertEqual(bolded.count("Python"), 2)

    def test_bold_keywords_text_before_match(self):
        """Test text before keyword match is not bolded."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Experience with Python",
            keywords=["Python"],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        # Should have: glyph, "Experience with ", bolded "Python"
        unbolded_text = [r.text for r in runs if not r.bold]
        self.assertIn("Experience with ", unbolded_text)


@mock_docx_modules
class TestHeaderRendererBasic(unittest.TestCase):
    """Tests for HeaderRenderer basic functionality."""

    def _get_renderer(self):
        from resume.docx_renderers import HeaderRenderer
        return make_fake_renderer(HeaderRenderer)

    def test_add_header_line_title_only(self):
        """Test header with title only."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(title_text="Software Engineer")
        self.assertEqual(len(doc.paragraphs), 1)
        runs = doc.paragraphs[0].runs
        self.assertEqual(runs[0].text, "Software Engineer")
        self.assertTrue(runs[0].bold)

    def test_add_header_line_company_only(self):
        """Test header with company only (no title)."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(company_text="TechCorp")
        self.assertEqual(len(doc.paragraphs), 1)
        runs = doc.paragraphs[0].runs
        self.assertEqual(runs[0].text, "TechCorp")
        self.assertTrue(runs[0].bold)

    def test_add_header_line_title_and_company(self):
        """Test header with title and company."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(
            title_text="Software Engineer",
            company_text="TechCorp",
        )
        runs = doc.paragraphs[0].runs
        texts = [r.text for r in runs]
        self.assertIn("Software Engineer", texts)
        self.assertIn(" at ", texts)
        self.assertIn("TechCorp", texts)

    def test_add_header_line_with_location(self):
        """Test header with location metadata."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(
            title_text="Engineer",
            loc_text="San Francisco, CA",
        )
        runs = doc.paragraphs[0].runs
        texts = [r.text for r in runs]
        self.assertIn("San Francisco, CA", texts)
        self.assertIn(" — ", texts)
        # Check for brackets
        self.assertIn("[", texts)
        self.assertIn("]", texts)

    def test_add_header_line_location_no_brackets(self):
        """Test location without brackets."""
        renderer, doc = self._get_renderer()
        sec = {"location_brackets": False}
        renderer.add_header_line(
            title_text="Engineer",
            loc_text="San Francisco",
            sec=sec,
        )
        runs = doc.paragraphs[0].runs
        texts = [r.text for r in runs]
        self.assertNotIn("[", texts)
        self.assertNotIn("]", texts)
        self.assertIn("San Francisco", texts)

    def test_add_header_line_with_duration(self):
        """Test header with duration metadata."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(
            title_text="Engineer",
            span_text="2020-2024",
        )
        runs = doc.paragraphs[0].runs
        texts = [r.text for r in runs]
        self.assertIn("2020-2024", texts)
        self.assertIn(" — ", texts)
        # Check for parentheses
        self.assertIn("(", texts)
        self.assertIn(")", texts)

    def test_add_header_line_duration_no_brackets(self):
        """Test duration without brackets."""
        renderer, doc = self._get_renderer()
        sec = {"duration_brackets": False}
        renderer.add_header_line(
            title_text="Engineer",
            span_text="2020-2024",
            sec=sec,
        )
        runs = doc.paragraphs[0].runs
        texts = [r.text for r in runs]
        self.assertNotIn("(", texts)
        self.assertNotIn(")", texts)
        self.assertIn("2020-2024", texts)

    def test_add_header_line_all_fields(self):
        """Test header with all fields populated."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(
            title_text="Senior Engineer",
            company_text="TechCorp",
            loc_text="SF, CA",
            span_text="2020-2024",
        )
        runs = doc.paragraphs[0].runs
        texts = [r.text for r in runs]
        self.assertIn("Senior Engineer", texts)
        self.assertIn("TechCorp", texts)
        self.assertIn("SF, CA", texts)
        self.assertIn("2020-2024", texts)

    def test_parse_meta_pt_valid_int(self):
        """Test parsing valid integer meta_pt."""
        renderer, _ = self._get_renderer()
        result = renderer._parse_meta_pt({"meta_pt": "10"})
        self.assertEqual(result, 10.0)

    def test_parse_meta_pt_valid_float(self):
        """Test parsing valid float meta_pt."""
        renderer, _ = self._get_renderer()
        result = renderer._parse_meta_pt({"meta_pt": "10.5"})
        self.assertEqual(result, 10.5)

    def test_parse_meta_pt_invalid_string(self):
        """Test parsing invalid meta_pt string."""
        renderer, _ = self._get_renderer()
        result = renderer._parse_meta_pt({"meta_pt": "not-a-number"})
        self.assertIsNone(result)

    def test_parse_meta_pt_empty(self):
        """Test parsing when meta_pt is missing."""
        renderer, _ = self._get_renderer()
        result = renderer._parse_meta_pt({})
        self.assertIsNone(result)

    def test_parse_meta_pt_none(self):
        """Test parsing when meta_pt is None."""
        renderer, _ = self._get_renderer()
        result = renderer._parse_meta_pt({"meta_pt": None})
        self.assertIsNone(result)


@mock_docx_modules
class TestHeaderRendererColors(unittest.TestCase):
    """Tests for HeaderRenderer color handling."""

    def _get_renderer(self):
        from resume.docx_renderers import HeaderRenderer
        return make_fake_renderer(HeaderRenderer)

    def test_add_header_line_item_color(self):
        """Test header with item_color applied."""
        renderer, _ = self._get_renderer()
        sec = {"item_color": "#FF0000"}
        result = renderer.add_header_line(
            title_text="Engineer",
            company_text="TechCorp",
            sec=sec,
        )
        # Color application is tested in docx_styles tests
        # Here we verify the method completes successfully
        self.assertIsNotNone(result)

    def test_add_header_line_location_color(self):
        """Test header with location_color override."""
        renderer, _ = self._get_renderer()
        sec = {"item_color": "#FF0000", "location_color": "#00FF00"}
        result = renderer.add_header_line(
            title_text="Engineer",
            loc_text="SF",
            sec=sec,
        )
        self.assertIsNotNone(result)

    def test_add_header_line_duration_color(self):
        """Test header with duration_color override."""
        renderer, _ = self._get_renderer()
        sec = {"item_color": "#FF0000", "duration_color": "#0000FF"}
        result = renderer.add_header_line(
            title_text="Engineer",
            span_text="2020-2024",
            sec=sec,
        )
        self.assertIsNotNone(result)


@mock_docx_modules
class TestHeaderRendererGroupTitle(unittest.TestCase):
    """Tests for HeaderRenderer group title functionality."""

    def _get_renderer(self):
        from resume.docx_renderers import HeaderRenderer
        return make_fake_renderer(HeaderRenderer)

    def test_add_group_title_basic(self):
        """Test adding a basic group title."""
        renderer, doc = self._get_renderer()
        renderer.add_group_title("Programming Languages")
        self.assertEqual(len(doc.paragraphs), 1)
        runs = doc.paragraphs[0].runs
        self.assertEqual(runs[0].text, "Programming Languages")
        self.assertTrue(runs[0].bold)

    def test_add_group_title_empty_returns_none(self):
        """Test empty group title returns None."""
        renderer, doc = self._get_renderer()
        result = renderer.add_group_title("")
        self.assertIsNone(result)
        self.assertEqual(len(doc.paragraphs), 0)

    def test_add_group_title_whitespace_only_returns_none(self):
        """Test whitespace-only group title returns None."""
        renderer, doc = self._get_renderer()
        result = renderer.add_group_title("   ")
        self.assertIsNone(result)
        self.assertEqual(len(doc.paragraphs), 0)

    def test_add_group_title_with_color(self):
        """Test group title with color configuration."""
        renderer, doc = self._get_renderer()
        sec = {"group_title_color": "#FF0000"}
        renderer.add_group_title("Languages", sec=sec)
        self.assertEqual(len(doc.paragraphs), 1)
        # Color verified in separate tests

    def test_add_group_title_with_background(self):
        """Test group title with background shading."""
        renderer, doc = self._get_renderer()
        sec = {"group_title_bg": "#EEEEEE"}
        result = renderer.add_group_title("Languages", sec=sec)
        self.assertIsNotNone(result)
        self.assertEqual(len(doc.paragraphs), 1)

    def test_add_group_title_auto_contrast(self):
        """Test group title with auto-contrast color on dark background."""
        renderer, _ = self._get_renderer()
        sec = {"group_title_bg": "#000000"}  # Dark background
        result = renderer.add_group_title("Languages", sec=sec)
        self.assertIsNotNone(result)
        # Auto-contrast logic tested in docx_styles tests

    def test_add_group_title_fallback_to_title_bg(self):
        """Test group title falls back to title_bg if no group_title_bg."""
        renderer, _ = self._get_renderer()
        sec = {"title_bg": "#CCCCCC"}
        result = renderer.add_group_title("Languages", sec=sec)
        self.assertIsNotNone(result)

    def test_add_group_title_with_explicit_color_and_bg(self):
        """Test group title with both explicit color and background."""
        renderer, _ = self._get_renderer()
        # When both color and bg are set, should use explicit color (not auto-contrast)
        sec = {"group_title_color": "#FF0000", "group_title_bg": "#000000"}
        result = renderer.add_group_title("Languages", sec=sec)
        self.assertIsNotNone(result)


@mock_docx_modules
class TestListSectionRenderer(unittest.TestCase):
    """Tests for ListSectionRenderer."""

    def _get_renderer(self):
        from resume.docx_renderers import ListSectionRenderer
        return make_fake_renderer(ListSectionRenderer)

    def test_extract_item_text_string(self):
        """Test extracting text from string item."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text(
            "  Python  ",
            ("name",),
            None,
            " — ",
        )
        self.assertEqual(result, "Python")

    def test_extract_item_text_dict_name(self):
        """Test extracting text from dict with name key."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text(
            {"name": "Python"},
            ("name", "title"),
            None,
            " — ",
        )
        self.assertEqual(result, "Python")

    def test_extract_item_text_dict_with_description(self):
        """Test extracting text from dict with description."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text(
            {"name": "Python", "level": "Expert"},
            ("name",),
            "level",
            " — ",
        )
        self.assertEqual(result, "Python — Expert")

    def test_extract_item_text_dict_with_empty_description(self):
        """Test extracting text from dict with empty description key."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text(
            {"name": "Python", "level": ""},
            ("name",),
            "level",
            " — ",
        )
        # Should return just name when desc is empty
        self.assertEqual(result, "Python")

    def test_extract_item_text_empty_string(self):
        """Test extracting from empty string returns None."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text("", ("name",), None, " — ")
        self.assertIsNone(result)

    def test_extract_item_text_dict_no_matching_keys(self):
        """Test extracting from dict with no matching keys."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text(
            {"other": "value"},
            ("name", "title"),
            None,
            " — ",
        )
        self.assertIsNone(result)

    def test_render_simple_list_with_bullets(self):
        """Test rendering simple list with bullets."""
        renderer, doc = self._get_renderer()
        items = ["Python", "Java", "Go"]
        result = renderer.render_simple_list(items)
        self.assertEqual(result, ["Python", "Java", "Go"])
        self.assertEqual(len(doc.paragraphs), 3)

    def test_render_simple_list_no_bullets(self):
        """Test rendering simple list without bullets (inline)."""
        renderer, doc = self._get_renderer()
        items = ["Python", "Java", "Go"]
        sec = {"bullets": False, "separator": " | "}
        result = renderer.render_simple_list(items, sec=sec)
        self.assertEqual(result, ["Python", "Java", "Go"])
        # Should create one paragraph with joined text
        self.assertEqual(len(doc.paragraphs), 1)
        # Check that items were joined with separator
        # FakeParagraph stores the initial text passed to add_paragraph
        paragraph_text = doc.paragraphs[0].text
        self.assertEqual(paragraph_text, "Python | Java | Go")

    def test_render_simple_list_default_separator(self):
        """Test rendering inline list with default separator."""
        renderer, doc = self._get_renderer()
        items = ["Python", "Java"]
        sec = {"bullets": False}
        renderer.render_simple_list(items, sec=sec)
        # Default separator is " • "
        paragraph_text = doc.paragraphs[0].text
        self.assertEqual(paragraph_text, "Python • Java")

    def test_render_simple_list_empty(self):
        """Test rendering empty list."""
        renderer, doc = self._get_renderer()
        result = renderer.render_simple_list([])
        self.assertEqual(result, [])
        self.assertEqual(len(doc.paragraphs), 0)

    def test_render_simple_list_filters_empty_items(self):
        """Test rendering list filters out empty items."""
        renderer, doc = self._get_renderer()
        items = ["Python", "", "Java", "   ", "Go"]
        result = renderer.render_simple_list(items)
        self.assertEqual(result, ["Python", "Java", "Go"])
        self.assertEqual(len(doc.paragraphs), 3)

    def test_render_simple_list_dict_items(self):
        """Test rendering list with dict items."""
        renderer, _ = self._get_renderer()
        items = [
            {"name": "Python", "level": "Expert"},
            {"name": "Java", "level": "Intermediate"},
        ]
        result = renderer.render_simple_list(
            items,
            desc_key="level",
            desc_sep=" — ",
        )
        self.assertEqual(len(result), 2)
        self.assertIn("Python — Expert", result)
        self.assertIn("Java — Intermediate", result)

    def test_render_simple_list_custom_name_keys(self):
        """Test rendering with custom name key priority."""
        renderer, _ = self._get_renderer()
        items = [
            {"title": "Python"},
            {"label": "Java"},
            {"text": "Go"},
        ]
        result = renderer.render_simple_list(
            items,
            name_keys=("name", "title", "label", "text"),
        )
        self.assertEqual(result, ["Python", "Java", "Go"])


if __name__ == "__main__":
    unittest.main()
