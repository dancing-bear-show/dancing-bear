"""Tests for resume/docx_writer.py DOCX rendering utilities."""

from __future__ import annotations

from tests.fixtures import test_path
import unittest
from unittest.mock import MagicMock, patch


class TestMatchSectionKey(unittest.TestCase):
    """Tests for _match_section_key function."""

    def test_matches_summary_variants(self):
        from resume.docx_writer import _match_section_key
        self.assertEqual(_match_section_key("Summary"), "summary")
        self.assertEqual(_match_section_key("profile"), "summary")
        self.assertEqual(_match_section_key("ABOUT"), "summary")

    def test_matches_skills_variants(self):
        from resume.docx_writer import _match_section_key
        self.assertEqual(_match_section_key("Skills"), "skills")
        self.assertEqual(_match_section_key("TECHNICAL SKILLS"), "skills")

    def test_matches_technologies(self):
        from resume.docx_writer import _match_section_key
        self.assertEqual(_match_section_key("Technologies"), "technologies")
        self.assertEqual(_match_section_key("technology"), "technologies")
        self.assertEqual(_match_section_key("tools"), "technologies")

    def test_matches_experience_variants(self):
        from resume.docx_writer import _match_section_key
        self.assertEqual(_match_section_key("Experience"), "experience")
        self.assertEqual(_match_section_key("work history"), "experience")
        self.assertEqual(_match_section_key("employment"), "experience")

    def test_matches_education_variants(self):
        from resume.docx_writer import _match_section_key
        self.assertEqual(_match_section_key("Education"), "education")
        self.assertEqual(_match_section_key("academics"), "education")

    def test_returns_none_for_unknown(self):
        from resume.docx_writer import _match_section_key
        self.assertIsNone(_match_section_key("Unknown Section"))
        self.assertIsNone(_match_section_key("Certifications"))

    def test_strips_whitespace(self):
        from resume.docx_writer import _match_section_key
        self.assertEqual(_match_section_key("  Summary  "), "summary")


class TestGetHeaderLevel(unittest.TestCase):
    """Tests for _get_header_level function."""

    def test_returns_from_sec_if_present(self):
        from resume.docx_writer import _get_header_level
        sec = {"header_level": 2}
        result = _get_header_level(sec, None)
        self.assertEqual(result, 2)

    def test_returns_from_page_cfg_if_sec_missing(self):
        from resume.docx_writer import _get_header_level
        page_cfg = {"header_level": 3}
        result = _get_header_level(None, page_cfg)
        self.assertEqual(result, 3)

    def test_prefers_sec_over_page_cfg(self):
        from resume.docx_writer import _get_header_level
        sec = {"header_level": 2}
        page_cfg = {"header_level": 3}
        result = _get_header_level(sec, page_cfg)
        self.assertEqual(result, 2)

    def test_defaults_to_1_if_missing(self):
        from resume.docx_writer import _get_header_level
        result = _get_header_level(None, None)
        self.assertEqual(result, 1)

    def test_handles_invalid_header_level(self):
        from resume.docx_writer import _get_header_level
        sec = {"header_level": "not-a-number"}
        result = _get_header_level(sec, None)
        self.assertEqual(result, 1)

    def test_handles_exception_during_header_level_conversion(self):
        from resume.docx_writer import _get_header_level
        # Create a dict-like object that raises on .get()
        class BadDict:
            def get(self, key, default=None):
                raise RuntimeError("test exception")

        sec = BadDict()
        result = _get_header_level(sec, None)
        # Should return default of 1 when exception occurs
        self.assertEqual(result, 1)


class TestExtractExperienceLocations(unittest.TestCase):
    """Tests for _extract_experience_locations function."""

    def test_extracts_unique_locations(self):
        from resume.docx_writer import _extract_experience_locations
        data = {
            "experience": [
                {"title": "Engineer", "location": "Seattle, WA"},
                {"title": "Manager", "location": "Portland, OR"},
                {"title": "Director", "location": "Seattle, WA"},  # Duplicate
            ]
        }
        result = _extract_experience_locations(data)
        self.assertEqual(result, ["Seattle, WA", "Portland, OR"])

    def test_handles_empty_locations(self):
        from resume.docx_writer import _extract_experience_locations
        data = {
            "experience": [
                {"title": "Engineer", "location": ""},
                {"title": "Manager", "location": None},
                {"title": "Director"},  # No location key
            ]
        }
        result = _extract_experience_locations(data)
        self.assertEqual(result, [])

    def test_handles_missing_experience(self):
        from resume.docx_writer import _extract_experience_locations
        data = {}
        result = _extract_experience_locations(data)
        self.assertEqual(result, [])

    def test_handles_none_experience(self):
        from resume.docx_writer import _extract_experience_locations
        data = {"experience": None}
        result = _extract_experience_locations(data)
        self.assertEqual(result, [])

    def test_preserves_order(self):
        from resume.docx_writer import _extract_experience_locations
        data = {
            "experience": [
                {"location": "A"},
                {"location": "C"},
                {"location": "B"},
            ]
        }
        result = _extract_experience_locations(data)
        self.assertEqual(result, ["A", "C", "B"])


class TestGetContactField(unittest.TestCase):
    """Tests for _get_contact_field function."""

    def test_returns_top_level_field(self):
        from resume.docx_writer import _get_contact_field
        data = {"email": "test@example.com"}
        result = _get_contact_field(data, "email")
        self.assertEqual(result, "test@example.com")

    def test_returns_nested_contact_field(self):
        from resume.docx_writer import _get_contact_field
        data = {"contact": {"email": "nested@example.com"}}
        result = _get_contact_field(data, "email")
        self.assertEqual(result, "nested@example.com")

    def test_prefers_top_level_over_nested(self):
        from resume.docx_writer import _get_contact_field
        data = {
            "email": "top@example.com",
            "contact": {"email": "nested@example.com"},
        }
        result = _get_contact_field(data, "email")
        self.assertEqual(result, "top@example.com")

    def test_returns_empty_if_missing(self):
        from resume.docx_writer import _get_contact_field
        data = {}
        result = _get_contact_field(data, "email")
        self.assertEqual(result, "")


class TestCollectLinkExtras(unittest.TestCase):
    """Tests for _collect_link_extras function."""

    def test_collects_website_linkedin_github(self):
        from resume.docx_writer import _collect_link_extras
        data = {
            "website": "https://example.com",
            "linkedin": "https://linkedin.com/in/johndoe",
            "github": "https://github.com/johndoe",
        }
        result = _collect_link_extras(data)
        self.assertEqual(len(result), 3)

    def test_collects_from_nested_contact(self):
        from resume.docx_writer import _collect_link_extras
        data = {
            "contact": {
                "website": "https://example.com",
            }
        }
        result = _collect_link_extras(data)
        self.assertEqual(len(result), 1)

    def test_collects_from_links_list(self):
        from resume.docx_writer import _collect_link_extras
        data = {
            "links": ["https://portfolio.com", "https://blog.com"],
        }
        result = _collect_link_extras(data)
        self.assertEqual(len(result), 2)

    def test_handles_empty_data(self):
        from resume.docx_writer import _collect_link_extras
        data = {}
        result = _collect_link_extras(data)
        self.assertEqual(result, [])

    def test_handles_non_list_links(self):
        from resume.docx_writer import _collect_link_extras
        data = {
            "links": "not-a-list",  # Should be ignored
        }
        result = _collect_link_extras(data)
        self.assertEqual(result, [])

    def test_filters_empty_links_from_list(self):
        from resume.docx_writer import _collect_link_extras
        data = {
            "links": ["https://valid.com", "", "   ", None, "https://another.com"],
        }
        result = _collect_link_extras(data)
        # Should only include valid non-empty links
        self.assertEqual(len(result), 2)


class TestResolveSections(unittest.TestCase):
    """Tests for _resolve_sections function."""

    def test_returns_template_sections_by_default(self):
        from resume.docx_writer import _resolve_sections
        template = {
            "sections": [
                {"key": "summary", "title": "Summary"},
                {"key": "experience", "title": "Experience"},
            ]
        }
        result = _resolve_sections(template, None)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["key"], "summary")

    def test_respects_structure_order(self):
        from resume.docx_writer import _resolve_sections
        template = {
            "sections": [
                {"key": "summary", "title": "Summary"},
                {"key": "experience", "title": "Experience"},
                {"key": "skills", "title": "Skills"},
            ]
        }
        structure = {"order": ["skills", "experience", "summary"]}
        result = _resolve_sections(template, structure)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["key"], "skills")
        self.assertEqual(result[1]["key"], "experience")
        self.assertEqual(result[2]["key"], "summary")

    def test_uses_custom_titles_from_structure(self):
        from resume.docx_writer import _resolve_sections
        template = {"sections": [{"key": "skills", "title": "Skills"}]}
        structure = {
            "order": ["skills"],
            "titles": {"skills": "Technical Expertise"},
        }
        result = _resolve_sections(template, structure)
        # When key is in template, it uses template's config
        self.assertEqual(result[0]["key"], "skills")

    def test_handles_empty_sections(self):
        from resume.docx_writer import _resolve_sections
        template = {"sections": []}
        result = _resolve_sections(template, None)
        self.assertEqual(result, [])


class TestSectionRenderers(unittest.TestCase):
    """Tests for SECTION_RENDERERS registry."""

    def test_has_expected_renderers(self):
        from resume.docx_writer import SECTION_RENDERERS
        expected_keys = [
            "summary",
            "skills",
            "technologies",
            "interests",
            "presentations",
            "languages",
            "coursework",
            "certifications",
            "experience",
            "education",
        ]
        for key in expected_keys:
            self.assertIn(key, SECTION_RENDERERS, f"Missing renderer for {key}")


class TestSectionsWithKeywords(unittest.TestCase):
    """Tests for SECTIONS_WITH_KEYWORDS set."""

    def test_includes_expected_sections(self):
        from resume.docx_writer import SECTIONS_WITH_KEYWORDS
        self.assertIn("summary", SECTIONS_WITH_KEYWORDS)
        self.assertIn("experience", SECTIONS_WITH_KEYWORDS)

    def test_excludes_other_sections(self):
        from resume.docx_writer import SECTIONS_WITH_KEYWORDS
        self.assertNotIn("skills", SECTIONS_WITH_KEYWORDS)
        self.assertNotIn("education", SECTIONS_WITH_KEYWORDS)


class TestWriteResumeDocx(unittest.TestCase):
    """Tests for write_resume_docx function."""

    @patch("resume.docx_writer.safe_import")
    def test_raises_when_docx_unavailable(self, mock_safe_import):
        from resume.docx_writer import write_resume_docx
        mock_safe_import.return_value = None
        with self.assertRaises(RuntimeError) as ctx:
            write_resume_docx({}, {}, test_path("out.docx"))  # nosec B108 - test fixture path
        self.assertIn("python-docx", str(ctx.exception))

    @patch("resume.docx_writer.safe_import")
    def test_creates_document_and_saves(self, mock_safe_import):
        from resume.docx_writer import write_resume_docx
        # Mock the docx module with all necessary components
        mock_docx = MagicMock()
        mock_doc = MagicMock()
        mock_section = MagicMock()
        mock_doc.sections = [mock_section]
        # Mock paragraphs list that grows when add_heading/add_paragraph is called
        mock_paragraphs = []
        mock_doc.paragraphs = mock_paragraphs

        def add_heading_side_effect(*args, **kwargs):
            mock_para = MagicMock()
            mock_para.paragraph_format = MagicMock()
            mock_paragraphs.append(mock_para)
            return mock_para

        def add_paragraph_side_effect(*args, **kwargs):
            mock_para = MagicMock()
            mock_para.paragraph_format = MagicMock()
            mock_paragraphs.append(mock_para)
            return mock_para

        mock_doc.add_heading.side_effect = add_heading_side_effect
        mock_doc.add_paragraph.side_effect = add_paragraph_side_effect
        mock_doc.styles = {"Normal": MagicMock(), "Heading 1": MagicMock(), "Title": MagicMock()}
        mock_docx.Document.return_value = mock_doc
        mock_safe_import.return_value = mock_docx

        # Patch the import inside the function
        with patch.dict("sys.modules", {"docx": mock_docx}):
            data = {"name": "John Doe"}
            template = {"sections": [], "page": {"compact": False}}
            write_resume_docx(data, template, test_path("test.docx"))  # nosec B108 - test fixture path

        mock_doc.save.assert_called_once_with(test_path("test.docx"))  # nosec B108 - test fixture path

    @patch("resume.docx_sidebar.write_resume_docx_sidebar")
    def test_delegates_to_sidebar_writer_when_layout_is_sidebar(self, mock_sidebar_writer):
        from resume.docx_writer import write_resume_docx
        data = {"name": "Test"}
        template = {"layout": {"type": "sidebar"}}
        out_path = test_path("test.docx")  # nosec B108 - test fixture path
        seed = {"keywords": ["Python"]}
        structure = {"order": ["summary"]}

        write_resume_docx(data, template, out_path, seed, structure)

        # Should delegate to sidebar writer
        mock_sidebar_writer.assert_called_once_with(data, template, out_path, seed, structure)

    @patch("resume.docx_writer.safe_import")
    def test_renders_all_sections_in_loop(self, mock_safe_import):
        from resume.docx_writer import write_resume_docx
        # Mock the docx module
        mock_docx = MagicMock()
        mock_doc = MagicMock()
        mock_section = MagicMock()
        mock_doc.sections = [mock_section]
        mock_paragraphs = []
        mock_doc.paragraphs = mock_paragraphs

        def add_heading_side_effect(*args, **kwargs):
            mock_para = MagicMock()
            mock_para.paragraph_format = MagicMock()
            mock_paragraphs.append(mock_para)
            return mock_para

        def add_paragraph_side_effect(*args, **kwargs):
            mock_para = MagicMock()
            mock_para.paragraph_format = MagicMock()
            mock_paragraphs.append(mock_para)
            return mock_para

        mock_doc.add_heading.side_effect = add_heading_side_effect
        mock_doc.add_paragraph.side_effect = add_paragraph_side_effect
        mock_doc.styles = {"Normal": MagicMock(), "Heading 1": MagicMock(), "Title": MagicMock()}
        mock_doc.core_properties = MagicMock()
        mock_docx.Document.return_value = mock_doc
        mock_safe_import.return_value = mock_docx

        # Test with multiple sections to ensure loop is executed
        with patch.dict("sys.modules", {"docx": mock_docx}):
            data = {
                "name": "Test",
                "summary": "Test summary",
                "skills": ["Python", "Java"],
                "experience": [],
            }
            template = {
                "sections": [
                    {"key": "summary", "title": "Summary"},
                    {"key": "skills", "title": "Skills"},
                    {"key": "experience", "title": "Experience"},
                ],
                "page": {"compact": False},
            }
            write_resume_docx(data, template, test_path("test.docx"))  # nosec B108 - test fixture path

        # Verify save was called
        mock_doc.save.assert_called_once()


class TestSectionSynonyms(unittest.TestCase):
    """Tests for SECTION_SYNONYMS mapping."""

    def test_summary_synonyms(self):
        from resume.docx_writer import SECTION_SYNONYMS
        self.assertIn("summary", SECTION_SYNONYMS["summary"])
        self.assertIn("profile", SECTION_SYNONYMS["summary"])
        self.assertIn("about", SECTION_SYNONYMS["summary"])

    def test_skills_synonyms(self):
        from resume.docx_writer import SECTION_SYNONYMS
        self.assertIn("skills", SECTION_SYNONYMS["skills"])
        self.assertIn("technical skills", SECTION_SYNONYMS["skills"])

    def test_experience_synonyms(self):
        from resume.docx_writer import SECTION_SYNONYMS
        self.assertIn("experience", SECTION_SYNONYMS["experience"])
        self.assertIn("work history", SECTION_SYNONYMS["experience"])
        self.assertIn("employment", SECTION_SYNONYMS["experience"])

    def test_education_synonyms(self):
        from resume.docx_writer import SECTION_SYNONYMS
        self.assertIn("education", SECTION_SYNONYMS["education"])
        self.assertIn("academics", SECTION_SYNONYMS["education"])


class TestBackwardCompatibleWrappers(unittest.TestCase):
    """Tests for backward-compatible wrapper functions."""

    def test_bold_keywords(self):
        from resume.docx_writer import _bold_keywords
        from tests.resume_tests.fixtures import FakeParagraph
        para = FakeParagraph()
        # Should not raise; delegates to BulletRenderer._bold_keywords
        _bold_keywords(para, "Python and Java developer", ["Python", "Java"])

    def test_add_bullet_line(self):
        from resume.docx_writer import _add_bullet_line
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()
        _add_bullet_line(doc, "Test bullet", keywords=["Test"], glyph="•")
        self.assertEqual(len(doc.paragraphs), 1)

    def test_add_plain_bullet(self):
        from resume.docx_writer import _add_plain_bullet
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()
        _add_plain_bullet(doc, "Plain bullet", keywords=["Plain"])
        self.assertEqual(len(doc.paragraphs), 1)

    def test_add_bullets(self):
        from resume.docx_writer import _add_bullets
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()
        items = ["First bullet", "Second bullet"]
        _add_bullets(doc, items, keywords=["First"], plain=True, glyph="•")
        self.assertEqual(len(doc.paragraphs), 2)

    def test_render_group_title(self):
        from resume.docx_writer import _render_group_title
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()
        _render_group_title(doc, "Skills", sec={"key": "skills"})
        self.assertEqual(len(doc.paragraphs), 1)

    def test_add_header_line(self):
        from resume.docx_writer import _add_header_line
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()
        _add_header_line(
            doc,
            title_text="Senior Engineer",
            company_text="TechCorp",
            loc_text="Seattle",
            span_text="2020-2023",
            sec=None,
            style="Normal",
        )
        self.assertEqual(len(doc.paragraphs), 1)

    def test_add_named_bullet(self):
        from resume.docx_writer import _add_named_bullet
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()
        _add_named_bullet(doc, "Python", "Expert level", sec=None, glyph="•", sep=": ")
        self.assertEqual(len(doc.paragraphs), 1)

    def test_use_plain_bullets(self):
        from resume.docx_writer import _use_plain_bullets
        sec = {"plain_bullets": True}
        page_cfg = {"plain_bullets": False}
        plain, glyph = _use_plain_bullets(sec, page_cfg)
        self.assertTrue(plain)
        self.assertEqual(glyph, "•")


class TestApplyMargins(unittest.TestCase):
    """Tests for _apply_margins function."""

    @patch("resume.docx_writer.Inches")
    def test_applies_margins_from_config(self, mock_inches):
        from resume.docx_writer import _apply_margins
        mock_doc = MagicMock()
        mock_section = MagicMock()
        mock_doc.sections = [mock_section]
        mock_inches.return_value = 36  # Mock value

        page_cfg = {"margins_in": 0.75}
        _apply_margins(mock_doc, page_cfg)

        mock_inches.assert_called_with(0.75)
        self.assertEqual(mock_section.top_margin, 36)
        self.assertEqual(mock_section.bottom_margin, 36)
        self.assertEqual(mock_section.left_margin, 36)
        self.assertEqual(mock_section.right_margin, 36)

    @patch("resume.docx_writer.Inches")
    def test_uses_default_margin_when_not_specified(self, mock_inches):
        from resume.docx_writer import _apply_margins
        mock_doc = MagicMock()
        mock_section = MagicMock()
        mock_doc.sections = [mock_section]
        mock_inches.return_value = 36

        page_cfg = {}
        _apply_margins(mock_doc, page_cfg)

        mock_inches.assert_called_with(0.5)

    def test_handles_exception_gracefully(self):
        from resume.docx_writer import _apply_margins
        mock_doc = MagicMock()
        mock_doc.sections = []  # Empty sections to cause error
        page_cfg = {"margins_in": 0.5}
        # Should not raise
        _apply_margins(mock_doc, page_cfg)


class TestApplyHeading1Style(unittest.TestCase):
    """Tests for _apply_heading1_style function."""

    @patch("resume.docx_writer.RGBColor")
    @patch("resume.docx_writer.Pt")
    def test_applies_heading1_style(self, mock_pt, mock_rgb):
        from resume.docx_writer import _apply_heading1_style, STYLE_HEADING_1
        mock_doc = MagicMock()
        mock_h1_style = MagicMock()
        mock_doc.styles = {STYLE_HEADING_1: mock_h1_style}
        mock_pt.return_value = 144  # 12pt

        _apply_heading1_style(mock_doc, 12.0, "#003366", None)

        mock_pt.assert_called_with(12.0)
        self.assertEqual(mock_h1_style.font.size, 144)
        self.assertTrue(mock_h1_style.font.bold)

    @patch("resume.docx_writer.RGBColor")
    @patch("resume.docx_writer.Pt")
    def test_auto_contrast_color_for_dark_bg(self, mock_pt, mock_rgb):
        from resume.docx_writer import _apply_heading1_style, STYLE_HEADING_1
        mock_doc = MagicMock()
        mock_h1_style = MagicMock()
        mock_doc.styles = {STYLE_HEADING_1: mock_h1_style}
        mock_pt.return_value = 144

        # Dark background, no text color specified
        _apply_heading1_style(mock_doc, 12.0, None, "#000000")

        # Should set white text for dark background
        mock_rgb.assert_called_with(255, 255, 255)

    @patch("resume.docx_writer.RGBColor")
    @patch("resume.docx_writer.Pt")
    def test_auto_contrast_color_for_light_bg(self, mock_pt, mock_rgb):
        from resume.docx_writer import _apply_heading1_style, STYLE_HEADING_1
        mock_doc = MagicMock()
        mock_h1_style = MagicMock()
        mock_doc.styles = {STYLE_HEADING_1: mock_h1_style}
        mock_pt.return_value = 144

        # Light background, no text color specified
        _apply_heading1_style(mock_doc, 12.0, None, "#FFFFFF")

        # Should set black text for light background
        mock_rgb.assert_called_with(0, 0, 0)

    def test_returns_early_if_style_missing(self):
        from resume.docx_writer import _apply_heading1_style
        mock_doc = MagicMock()
        mock_doc.styles = {}
        # Should not raise
        _apply_heading1_style(mock_doc, 12.0, "#000000", None)


class TestApplyTitleStyle(unittest.TestCase):
    """Tests for _apply_title_style function."""

    @patch("resume.docx_writer.RGBColor")
    @patch("resume.docx_writer.Pt")
    def test_applies_title_style(self, mock_pt, mock_rgb):
        from resume.docx_writer import _apply_title_style
        mock_doc = MagicMock()
        mock_title_style = MagicMock()
        mock_doc.styles = {"Title": mock_title_style}
        mock_pt.return_value = 168  # 14pt

        _apply_title_style(mock_doc, 14.0, "#003366")

        mock_pt.assert_called_with(14.0)
        self.assertEqual(mock_title_style.font.size, 168)
        self.assertTrue(mock_title_style.font.bold)
        mock_rgb.assert_called_with(0, 51, 102)

    def test_returns_early_if_style_missing(self):
        from resume.docx_writer import _apply_title_style
        mock_doc = MagicMock()
        mock_doc.styles = {}
        # Should not raise
        _apply_title_style(mock_doc, 14.0, "#000000")

    @patch("resume.docx_writer.Pt")
    def test_handles_none_color(self, mock_pt):
        from resume.docx_writer import _apply_title_style
        mock_doc = MagicMock()
        mock_title_style = MagicMock()
        mock_doc.styles = {"Title": mock_title_style}
        mock_pt.return_value = 168

        _apply_title_style(mock_doc, 14.0, None)
        # Should not raise and not set color


class TestApplyPageStyles(unittest.TestCase):
    """Tests for _apply_page_styles function."""

    @patch("resume.docx_writer._apply_title_style")
    @patch("resume.docx_writer._apply_heading1_style")
    @patch("resume.docx_writer._apply_margins")
    @patch("resume.docx_writer.Pt")
    def test_applies_all_styles_when_compact(self, mock_pt, mock_margins, mock_h1, mock_title):
        from resume.docx_writer import _apply_page_styles
        mock_doc = MagicMock()
        mock_normal_style = MagicMock()
        mock_doc.styles = {"Normal": mock_normal_style, "Heading 1": MagicMock(), "Title": MagicMock()}
        mock_pt.return_value = 126  # 10.5pt

        page_cfg = {
            "compact": True,
            "margins_in": 0.5,
            "body_pt": 10.5,
            "h1_pt": 12.0,
            "title_pt": 14.0,
            "h1_color": "#003366",
            "h1_bg": "#EEEEEE",
            "title_color": "#000000",
        }
        _apply_page_styles(mock_doc, page_cfg)

        mock_margins.assert_called_once_with(mock_doc, page_cfg)
        mock_h1.assert_called_once_with(mock_doc, 12.0, "#003366", "#EEEEEE")
        mock_title.assert_called_once_with(mock_doc, 14.0, "#000000")
        self.assertEqual(mock_normal_style.font.size, 126)

    def test_returns_early_if_not_compact(self):
        from resume.docx_writer import _apply_page_styles
        mock_doc = MagicMock()
        page_cfg = {"compact": False}
        _apply_page_styles(mock_doc, page_cfg)
        # Should not modify doc

    @patch("resume.docx_writer._apply_margins")
    def test_uses_defaults_for_missing_values(self, mock_margins):
        from resume.docx_writer import _apply_page_styles
        mock_doc = MagicMock()
        mock_normal_style = MagicMock()
        mock_doc.styles = {"Normal": mock_normal_style}
        page_cfg = {"compact": True}
        _apply_page_styles(mock_doc, page_cfg)
        mock_margins.assert_called_once()

    @patch("resume.docx_writer._apply_margins")
    def test_uses_heading_color_fallback(self, mock_margins):
        from resume.docx_writer import _apply_page_styles
        mock_doc = MagicMock()
        mock_doc.styles = {"Normal": MagicMock(), "Heading 1": MagicMock()}
        page_cfg = {"compact": True, "heading_color": "#FF0000", "heading_bg": "#00FF00"}
        _apply_page_styles(mock_doc, page_cfg)

    def test_handles_exception_gracefully(self):
        from resume.docx_writer import _apply_page_styles
        mock_doc = MagicMock()
        mock_doc.styles = {}  # Missing Normal style
        page_cfg = {"compact": True}
        # Should not raise
        _apply_page_styles(mock_doc, page_cfg)


class TestSetDocumentMetadata(unittest.TestCase):
    """Tests for _set_document_metadata function."""

    def test_sets_basic_metadata(self):
        from resume.docx_writer import _set_document_metadata
        mock_doc = MagicMock()
        mock_cp = MagicMock()
        mock_doc.core_properties = mock_cp

        data = {
            "name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "(555) 123-4567",
            "location": "Seattle, WA",
        }
        template = {"page": {}}

        _set_document_metadata(mock_doc, data, template)

        self.assertIn("Jane Doe", mock_cp.title)
        self.assertEqual(mock_cp.author, "Jane Doe")
        self.assertEqual(mock_cp.subject, "Resume")
        self.assertIn("jane@example.com", mock_cp.keywords)

    def test_includes_experience_locations_by_default(self):
        from resume.docx_writer import _set_document_metadata
        mock_doc = MagicMock()
        mock_cp = MagicMock()
        mock_doc.core_properties = mock_cp

        data = {
            "name": "John",
            "experience": [
                {"location": "Seattle, WA"},
                {"location": "Portland, OR"},
            ],
        }
        template = {"page": {"metadata_include_locations": True}}

        _set_document_metadata(mock_doc, data, template)

        self.assertIn("Seattle, WA", mock_cp.keywords)
        self.assertIn("Portland, OR", mock_cp.keywords)
        self.assertIn("Seattle, WA", mock_cp.category)

    def test_excludes_experience_locations_when_disabled(self):
        from resume.docx_writer import _set_document_metadata
        mock_doc = MagicMock()
        mock_cp = MagicMock()
        mock_doc.core_properties = mock_cp

        data = {
            "name": "John",
            "experience": [{"location": "Seattle, WA"}],
        }
        template = {"page": {"metadata_include_locations": False}}

        _set_document_metadata(mock_doc, data, template)

        keywords = mock_cp.keywords
        self.assertNotIn("Seattle, WA", keywords)

    def test_handles_nested_contact_data(self):
        from resume.docx_writer import _set_document_metadata
        mock_doc = MagicMock()
        mock_cp = MagicMock()
        mock_doc.core_properties = mock_cp

        data = {
            "contact": {
                "email": "nested@example.com",
                "phone": "(555) 999-8888",
                "location": "Boston, MA",
            }
        }
        template = {"page": {}}

        _set_document_metadata(mock_doc, data, template)

        self.assertIn("nested@example.com", mock_cp.keywords)

    def test_handles_category_set_failure(self):
        from resume.docx_writer import _set_document_metadata
        mock_doc = MagicMock()
        mock_cp = MagicMock()
        # Simulate category property raising exception
        type(mock_cp).category = property(lambda self: None, lambda self, v: (_ for _ in ()).throw(Exception("test")))
        mock_doc.core_properties = mock_cp

        data = {
            "name": "Test",
            "experience": [{"location": "Seattle"}],
        }
        template = {}

        # Should not raise
        _set_document_metadata(mock_doc, data, template)

    def test_handles_complete_metadata_failure(self):
        from resume.docx_writer import _set_document_metadata
        mock_doc = MagicMock()
        # Simulate core_properties raising exception
        type(mock_doc).core_properties = property(lambda self: (_ for _ in ()).throw(Exception("test")))

        data = {"name": "Test"}
        template = {}

        # Should not raise
        _set_document_metadata(mock_doc, data, template)


class TestCenterParagraph(unittest.TestCase):
    """Tests for _center_paragraph function."""

    def test_centers_paragraph(self):
        from resume.docx_writer import _center_paragraph
        from tests.resume_tests.fixtures import FakeParagraph
        para = FakeParagraph()
        _center_paragraph(para)
        # Should set alignment to CENTER (value 1)
        self.assertEqual(para.alignment, 1)

    def test_handles_exception_gracefully(self):
        from resume.docx_writer import _center_paragraph
        mock_para = MagicMock()
        # Make alignment setter raise exception
        type(mock_para).alignment = property(lambda self: None, lambda self, v: (_ for _ in ()).throw(Exception("test")))
        # Should not raise
        _center_paragraph(mock_para)


class TestRenderDocumentHeader(unittest.TestCase):
    """Tests for _render_document_header function."""

    def test_renders_name_headline_contact(self):
        from resume.docx_writer import _render_document_header
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()

        data = {
            "name": "Jane Doe",
            "headline": "Senior Software Engineer",
            "email": "jane@example.com",
            "phone": "(555) 123-4567",
            "location": "Seattle, WA",
        }

        _render_document_header(doc, data)

        # Should have 3 paragraphs: name, headline, contact line
        self.assertGreaterEqual(len(doc.paragraphs), 3)

    def test_includes_links_in_contact_line(self):
        from resume.docx_writer import _render_document_header
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()

        data = {
            "name": "John Doe",
            "email": "john@example.com",
            "website": "https://johndoe.com",
            "linkedin": "https://linkedin.com/in/johndoe",
            "github": "https://github.com/johndoe",
        }

        _render_document_header(doc, data)

        # Contact line should be present with links
        self.assertGreater(len(doc.paragraphs), 0)

    def test_handles_nested_contact_data(self):
        from resume.docx_writer import _render_document_header
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()

        data = {
            "contact": {
                "name": "Nested Name",
                "email": "nested@example.com",
            }
        }

        _render_document_header(doc, data)

        self.assertGreater(len(doc.paragraphs), 0)

    def test_formats_phone_display(self):
        from resume.docx_writer import _render_document_header
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()

        data = {
            "name": "Test",
            "phone": "5551234567",  # Will be formatted
        }

        _render_document_header(doc, data)

        self.assertGreater(len(doc.paragraphs), 0)

    def test_handles_links_list(self):
        from resume.docx_writer import _render_document_header
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()

        data = {
            "name": "Test",
            "links": ["https://blog.example.com", "https://portfolio.example.com"],
        }

        _render_document_header(doc, data)

        self.assertGreater(len(doc.paragraphs), 0)

    def test_handles_empty_data(self):
        from resume.docx_writer import _render_document_header
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()

        _render_document_header(doc, {})

        # Should not crash with empty data


class TestRenderSectionHeading(unittest.TestCase):
    """Tests for _render_section_heading function."""

    def test_renders_section_heading(self):
        from resume.docx_writer import _render_section_heading
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()

        _render_section_heading(doc, "Experience", {})

        self.assertEqual(len(doc.paragraphs), 1)

    def test_applies_background_shading(self):
        from resume.docx_writer import _render_section_heading
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()

        template = {"page": {"h1_bg": "#EEEEEE"}}
        _render_section_heading(doc, "Skills", template)

        self.assertEqual(len(doc.paragraphs), 1)

    def test_uses_heading_bg_fallback(self):
        from resume.docx_writer import _render_section_heading
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()

        template = {"page": {"heading_bg": "#DDDDDD"}}
        _render_section_heading(doc, "Education", template)

        self.assertEqual(len(doc.paragraphs), 1)

    def test_returns_early_if_no_title(self):
        from resume.docx_writer import _render_section_heading
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()

        _render_section_heading(doc, "", {})

        self.assertEqual(len(doc.paragraphs), 0)


class TestExtractKeywords(unittest.TestCase):
    """Tests for _extract_keywords function."""

    def test_extracts_keywords_from_seed(self):
        from resume.docx_writer import _extract_keywords
        seed = {"keywords": ["Python", "AWS", "Docker"]}
        result = _extract_keywords(seed)
        self.assertEqual(result, ["Python", "AWS", "Docker"])

    def test_returns_empty_list_if_no_seed(self):
        from resume.docx_writer import _extract_keywords
        result = _extract_keywords(None)
        self.assertEqual(result, [])

    def test_returns_empty_list_if_keywords_missing(self):
        from resume.docx_writer import _extract_keywords
        seed = {}
        result = _extract_keywords(seed)
        self.assertEqual(result, [])

    def test_returns_empty_list_if_keywords_not_list(self):
        from resume.docx_writer import _extract_keywords
        seed = {"keywords": "not-a-list"}
        result = _extract_keywords(seed)
        self.assertEqual(result, [])


class TestRenderSection(unittest.TestCase):
    """Tests for _render_section function."""

    def test_renders_summary_section_with_keywords(self):
        from resume.docx_writer import _render_section
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()

        sec = {"key": "summary", "title": "Summary"}
        template = {}
        page_cfg = {}
        data = {"summary": "Experienced engineer with Python and AWS expertise"}
        keywords = ["Python", "AWS"]

        _render_section(doc, sec, template, page_cfg, data, keywords)

        # Should have heading + summary content
        self.assertGreater(len(doc.paragraphs), 0)

    def test_renders_experience_section_with_keywords(self):
        from resume.docx_writer import _render_section
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()

        sec = {"key": "experience", "title": "Experience"}
        template = {}
        page_cfg = {}
        data = {
            "experience": [
                {
                    "title": "Engineer",
                    "company": "TechCorp",
                    "start": "2020",
                    "end": "2023",
                    "bullets": ["Built Python APIs"],
                }
            ]
        }
        keywords = ["Python"]

        _render_section(doc, sec, template, page_cfg, data, keywords)

        self.assertGreater(len(doc.paragraphs), 0)

    def test_renders_skills_section_without_keywords(self):
        from resume.docx_writer import _render_section
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()

        sec = {"key": "skills", "title": "Skills"}
        template = {}
        page_cfg = {}
        data = {"skills": ["Python", "Java", "Go"]}
        keywords = []

        _render_section(doc, sec, template, page_cfg, data, keywords)

        self.assertGreater(len(doc.paragraphs), 0)

    def test_returns_early_if_no_key(self):
        from resume.docx_writer import _render_section
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()

        sec = {"title": "No Key"}
        _render_section(doc, sec, {}, {}, {}, [])

        # Should not add anything
        self.assertEqual(len(doc.paragraphs), 0)

    def test_returns_early_if_renderer_not_found(self):
        from resume.docx_writer import _render_section
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()

        sec = {"key": "unknown_section", "title": "Unknown"}
        _render_section(doc, sec, {}, {}, {}, [])

        # Should only add heading
        self.assertEqual(len(doc.paragraphs), 1)

    def test_uses_key_title_if_title_missing(self):
        from resume.docx_writer import _render_section
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()

        sec = {"key": "skills"}  # No title
        template = {}
        page_cfg = {}
        data = {"skills": ["Python"]}

        _render_section(doc, sec, template, page_cfg, data, [])

        # Should still render with key.title() as title
        self.assertGreater(len(doc.paragraphs), 0)

    def test_renders_all_registered_sections(self):
        from resume.docx_writer import _render_section, SECTION_RENDERERS
        from tests.resume_tests.fixtures import FakeDocument

        # Test that each registered renderer can be invoked
        for key in SECTION_RENDERERS.keys():
            doc = FakeDocument()
            sec = {"key": key, "title": key.title()}
            template = {}
            page_cfg = {}
            data = {key: []}  # Empty data
            keywords = []

            _render_section(doc, sec, template, page_cfg, data, keywords)

            # Should at least add the heading
            self.assertGreaterEqual(len(doc.paragraphs), 1, f"Failed for section: {key}")


if __name__ == "__main__":
    unittest.main()
