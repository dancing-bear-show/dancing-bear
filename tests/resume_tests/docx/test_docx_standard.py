"""Tests for resume/docx_standard.py standard resume writer."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from tests.resume_tests.fixtures import mock_docx_modules


@mock_docx_modules
class TestStandardResumeWriter(unittest.TestCase):
    """Tests for StandardResumeWriter class."""

    def _create_writer(self, data=None, template=None):
        """Helper to create a StandardResumeWriter instance."""
        from resume.docx_standard import StandardResumeWriter

        if data is None:
            data = {"name": "John Doe"}
        if template is None:
            template = {"sections": []}
        return StandardResumeWriter(data, template)

    def _setup_mock_doc(self, writer):
        """Helper to setup a mock document with required attributes."""
        mock_doc = MagicMock()
        mock_section = MagicMock()
        mock_doc.sections = [mock_section]
        mock_paragraphs = []
        mock_doc.paragraphs = mock_paragraphs

        def add_heading_side_effect(*args, **kwargs):
            mock_para = MagicMock()
            mock_para.paragraph_format = MagicMock()
            mock_para.alignment = None
            mock_paragraphs.append(mock_para)
            return mock_para

        def add_paragraph_side_effect(*args, **kwargs):
            mock_para = MagicMock()
            mock_para.paragraph_format = MagicMock()
            mock_para.alignment = None
            mock_paragraphs.append(mock_para)
            return mock_para

        mock_doc.add_heading = MagicMock(side_effect=add_heading_side_effect)
        mock_doc.add_paragraph = MagicMock(side_effect=add_paragraph_side_effect)
        mock_doc.styles = {
            "Normal": MagicMock(),
            "Heading 1": MagicMock(),
            "Title": MagicMock(),
        }

        writer.doc = mock_doc
        return mock_doc

    def test_render_content_with_keywords_from_seed(self):
        """Test _render_content extracts keywords from seed (line 61)."""
        from resume import docx_standard

        data = {"name": "John Doe", "summary": "Software engineer"}
        template = {
            "sections": [
                {"key": "summary", "title": "Summary"},
            ]
        }
        writer = self._create_writer(data, template)
        self._setup_mock_doc(writer)

        seed = {"keywords": ["Python", "AWS", "Docker"]}

        # Mock the summary renderer
        mock_renderer = MagicMock()
        original_renderer = docx_standard.SECTION_RENDERERS["summary"]
        docx_standard.SECTION_RENDERERS["summary"] = MagicMock(return_value=mock_renderer)

        try:
            writer._render_content(seed)

            # Verify renderer was called with keywords
            mock_renderer.render.assert_called_once()
            call_args = mock_renderer.render.call_args[0]
            keywords_arg = call_args[2]  # Third argument should be keywords
            self.assertEqual(keywords_arg, ["Python", "AWS", "Docker"])
        finally:
            docx_standard.SECTION_RENDERERS["summary"] = original_renderer

    def test_render_content_with_no_seed(self):
        """Test _render_content with no seed passes empty keywords list."""
        from resume import docx_standard

        data = {"name": "John Doe", "summary": "Software engineer"}
        template = {
            "sections": [
                {"key": "summary", "title": "Summary"},
            ]
        }
        writer = self._create_writer(data, template)
        self._setup_mock_doc(writer)

        mock_renderer = MagicMock()
        original_renderer = docx_standard.SECTION_RENDERERS["summary"]
        docx_standard.SECTION_RENDERERS["summary"] = MagicMock(return_value=mock_renderer)

        try:
            writer._render_content(None)

            # Verify renderer was called with empty keywords
            mock_renderer.render.assert_called_once()
            call_args = mock_renderer.render.call_args[0]
            keywords_arg = call_args[2]
            self.assertEqual(keywords_arg, [])
        finally:
            docx_standard.SECTION_RENDERERS["summary"] = original_renderer

    def test_render_content_section_without_key(self):
        """Test _render_content skips sections without key (lines 67-69)."""
        from resume import docx_standard

        data = {"name": "John Doe", "summary": "Engineer"}
        template = {
            "sections": [
                {"title": "No Key Section"},  # Missing 'key' field
                {"key": "summary", "title": "Summary"},
            ]
        }
        writer = self._create_writer(data, template)
        self._setup_mock_doc(writer)

        mock_renderer = MagicMock()
        mock_renderer_class = MagicMock(return_value=mock_renderer)
        original_renderer = docx_standard.SECTION_RENDERERS["summary"]
        docx_standard.SECTION_RENDERERS["summary"] = mock_renderer_class

        try:
            writer._render_content()

            # Should only render summary section, not the one without key
            self.assertEqual(mock_renderer_class.call_count, 1)
        finally:
            docx_standard.SECTION_RENDERERS["summary"] = original_renderer

    def test_render_content_generates_title_from_key(self):
        """Test _render_content generates title from key if not provided (line 70)."""
        data = {"name": "John Doe", "skills": ["Python"]}
        template = {
            "sections": [
                {"key": "skills"},  # No title provided
            ]
        }
        writer = self._create_writer(data, template)
        mock_doc = self._setup_mock_doc(writer)

        with patch("resume.docx_standard.SkillsSectionRenderer") as mock_renderer_class:
            mock_renderer = MagicMock()
            mock_renderer_class.return_value = mock_renderer

            writer._render_content()

            # Verify heading was added with title generated from key
            mock_doc.add_heading.assert_called()
            heading_call = mock_doc.add_heading.call_args_list[1]  # First is name, second is section
            self.assertEqual(heading_call[0][0], "Skills")  # key.title()

    def test_render_content_calls_renderer_for_known_section(self):
        """Test _render_content calls appropriate renderer (lines 73-79)."""
        from resume import docx_standard

        data = {"name": "John Doe", "skills": ["Python", "Java"]}
        template = {
            "sections": [
                {"key": "skills", "title": "Technical Skills"},
            ]
        }
        writer = self._create_writer(data, template)
        mock_doc = self._setup_mock_doc(writer)

        mock_renderer = MagicMock()
        mock_renderer_class = MagicMock(return_value=mock_renderer)
        original_renderer = docx_standard.SECTION_RENDERERS["skills"]
        docx_standard.SECTION_RENDERERS["skills"] = mock_renderer_class

        try:
            writer._render_content()

            # Verify renderer was instantiated and called
            mock_renderer_class.assert_called_once_with(mock_doc, {})
            mock_renderer.render.assert_called_once()
        finally:
            docx_standard.SECTION_RENDERERS["skills"] = original_renderer

    def test_render_content_experience_with_keywords(self):
        """Test _render_content passes keywords to experience section (lines 76-77)."""
        from resume import docx_standard

        data = {
            "name": "John Doe",
            "experience": [
                {"title": "Dev", "company": "TechCo", "bullets": ["Built APIs"]},
            ],
        }
        template = {
            "sections": [
                {"key": "experience", "title": "Experience"},
            ]
        }
        writer = self._create_writer(data, template)
        self._setup_mock_doc(writer)

        seed = {"keywords": ["Python", "API"]}

        mock_renderer = MagicMock()
        mock_renderer_class = MagicMock(return_value=mock_renderer)
        original_renderer = docx_standard.SECTION_RENDERERS["experience"]
        docx_standard.SECTION_RENDERERS["experience"] = mock_renderer_class

        try:
            writer._render_content(seed)

            # Verify keywords were passed to experience renderer
            mock_renderer.render.assert_called_once()
            call_args = mock_renderer.render.call_args[0]
            keywords_arg = call_args[2]
            self.assertEqual(keywords_arg, ["Python", "API"])
        finally:
            docx_standard.SECTION_RENDERERS["experience"] = original_renderer

    def test_render_content_non_keyword_section(self):
        """Test _render_content calls renderer without keywords for non-keyword sections (line 79)."""
        from resume import docx_standard

        data = {"name": "John Doe", "skills": ["Python"]}
        template = {
            "sections": [
                {"key": "skills", "title": "Skills"},
            ]
        }
        writer = self._create_writer(data, template)
        self._setup_mock_doc(writer)

        seed = {"keywords": ["Python"]}

        mock_renderer = MagicMock()
        mock_renderer_class = MagicMock(return_value=mock_renderer)
        original_renderer = docx_standard.SECTION_RENDERERS["skills"]
        docx_standard.SECTION_RENDERERS["skills"] = mock_renderer_class

        try:
            writer._render_content(seed)

            # Verify renderer was called with only data and section (no keywords)
            mock_renderer.render.assert_called_once()
            call_args = mock_renderer.render.call_args[0]
            self.assertEqual(len(call_args), 2)  # Only data and section
        finally:
            docx_standard.SECTION_RENDERERS["skills"] = original_renderer

    def test_render_document_header_with_name(self):
        """Test _render_document_header renders name as heading (lines 91-94)."""
        data = {"name": "Jane Smith"}
        template = {"sections": []}
        writer = self._create_writer(data, template)
        mock_doc = self._setup_mock_doc(writer)

        writer._render_document_header()

        # Verify name was added as level 0 heading
        mock_doc.add_heading.assert_called_with("Jane Smith", level=0)

    def test_render_document_header_without_name(self):
        """Test _render_document_header handles missing name (line 91)."""
        data = {}
        template = {"sections": []}
        writer = self._create_writer(data, template)
        mock_doc = self._setup_mock_doc(writer)

        writer._render_document_header()

        # Should not add heading if no name
        mock_doc.add_heading.assert_not_called()

    def test_render_document_header_with_headline(self):
        """Test _render_document_header renders headline (lines 97-100)."""
        data = {"name": "Jane Smith", "headline": "Senior Software Engineer"}
        template = {"sections": []}
        writer = self._create_writer(data, template)
        mock_doc = self._setup_mock_doc(writer)

        writer._render_document_header()

        # Verify headline paragraph was added
        mock_doc.add_paragraph.assert_any_call("Senior Software Engineer")

    def test_render_document_header_without_headline(self):
        """Test _render_document_header handles missing headline (line 97)."""
        data = {"name": "Jane Smith"}
        template = {"sections": []}
        writer = self._create_writer(data, template)
        mock_doc = self._setup_mock_doc(writer)

        writer._render_document_header()

        # Only name heading should be added, no headline paragraph
        self.assertEqual(mock_doc.add_heading.call_count, 1)

    def test_render_document_header_contact_line_with_all_fields(self):
        """Test _render_document_header creates contact line (lines 103-109)."""
        data = {
            "name": "Jane Smith",
            "email": "jane@example.com",
            "phone": "555-1234",
            "location": "Seattle, WA",
            "website": "https://jane.dev",
        }
        template = {"sections": []}
        writer = self._create_writer(data, template)
        mock_doc = self._setup_mock_doc(writer)

        writer._render_document_header()

        # Verify contact line paragraph was added with separator
        contact_calls = [call for call in mock_doc.add_paragraph.call_args_list]
        contact_line = None
        for call in contact_calls:
            if call[0] and " | " in str(call[0][0]):
                contact_line = call[0][0]
                break

        self.assertIsNotNone(contact_line)
        self.assertIn("jane@example.com", contact_line)
        self.assertIn("Seattle, WA", contact_line)

    def test_render_document_header_contact_line_empty_when_no_fields(self):
        """Test _render_document_header skips contact line when no contact info (line 106)."""
        data = {"name": "Jane Smith"}
        template = {"sections": []}
        writer = self._create_writer(data, template)
        mock_doc = self._setup_mock_doc(writer)

        writer._render_document_header()

        # Should only have name heading, no contact paragraph
        self.assertEqual(mock_doc.add_heading.call_count, 1)
        # No paragraph with " | " separator
        for call in mock_doc.add_paragraph.call_args_list:
            if call[0]:
                self.assertNotIn(" | ", str(call[0][0]))

    def test_render_section_heading_with_title(self):
        """Test _render_section_heading adds heading (lines 118-122)."""
        data = {"name": "John Doe"}
        template = {"sections": []}
        writer = self._create_writer(data, template)
        mock_doc = self._setup_mock_doc(writer)

        writer._render_section_heading("Experience")

        # Verify heading was added as level 1
        mock_doc.add_heading.assert_called_with("Experience", level=1)

    def test_render_section_heading_without_title(self):
        """Test _render_section_heading skips empty title (lines 118-119)."""
        data = {"name": "John Doe"}
        template = {"sections": []}
        writer = self._create_writer(data, template)
        mock_doc = self._setup_mock_doc(writer)

        writer._render_section_heading("")

        # Should not add heading for empty title
        mock_doc.add_heading.assert_not_called()

    def test_render_section_heading_with_h1_bg_color(self):
        """Test _render_section_heading applies background shading (lines 123-126)."""
        data = {"name": "John Doe"}
        template = {"sections": [], "page": {"h1_bg": "#0066cc"}}
        writer = self._create_writer(data, template)
        self._setup_mock_doc(writer)

        with patch("resume.docx_standard._parse_hex_color") as mock_parse:
            mock_parse.return_value = (0, 102, 204)
            with patch("resume.docx_standard._apply_paragraph_shading") as mock_apply:
                writer._render_section_heading("Skills")

                # Verify shading was applied
                mock_parse.assert_called_with("#0066cc")
                mock_apply.assert_called_once()
                call_args = mock_apply.call_args
                self.assertEqual(call_args[0][1], (0, 102, 204))

    def test_render_section_heading_with_heading_bg_fallback(self):
        """Test _render_section_heading uses heading_bg as fallback (line 123)."""
        data = {"name": "John Doe"}
        template = {"sections": [], "page": {"heading_bg": "#ff9900"}}
        writer = self._create_writer(data, template)
        self._setup_mock_doc(writer)

        with patch("resume.docx_standard._parse_hex_color") as mock_parse:
            mock_parse.return_value = (255, 153, 0)
            with patch("resume.docx_standard._apply_paragraph_shading") as mock_apply:
                writer._render_section_heading("Education")

                # Verify heading_bg was used as fallback
                mock_parse.assert_called_with("#ff9900")
                mock_apply.assert_called_once()

    def test_render_section_heading_without_bg_color(self):
        """Test _render_section_heading without background color (line 125)."""
        data = {"name": "John Doe"}
        template = {"sections": []}
        writer = self._create_writer(data, template)
        self._setup_mock_doc(writer)

        with patch("resume.docx_standard._apply_paragraph_shading") as mock_apply:
            writer._render_section_heading("Skills")

            # Should not apply shading when no bg color configured
            mock_apply.assert_not_called()

    def test_resolve_sections_returns_template_sections(self):
        """Test _resolve_sections returns sections from template."""
        data = {"name": "John Doe"}
        template = {
            "sections": [
                {"key": "summary", "title": "Summary"},
                {"key": "experience", "title": "Experience"},
            ]
        }
        writer = self._create_writer(data, template)

        sections = writer._resolve_sections()

        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0]["key"], "summary")
        self.assertEqual(sections[1]["key"], "experience")

    def test_resolve_sections_returns_empty_when_no_sections(self):
        """Test _resolve_sections returns empty list when no sections in template."""
        data = {"name": "John Doe"}
        template = {}
        writer = self._create_writer(data, template)

        sections = writer._resolve_sections()

        self.assertEqual(sections, [])

    def test_all_section_renderers_available(self):
        """Test SECTION_RENDERERS registry contains all expected renderers."""
        from resume.docx_standard import SECTION_RENDERERS

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
            "teaching",
        ]

        for key in expected_keys:
            self.assertIn(key, SECTION_RENDERERS)

    def test_sections_with_keywords_contains_expected_sections(self):
        """Test SECTIONS_WITH_KEYWORDS contains summary and experience."""
        from resume.docx_standard import SECTIONS_WITH_KEYWORDS

        self.assertIn("summary", SECTIONS_WITH_KEYWORDS)
        self.assertIn("experience", SECTIONS_WITH_KEYWORDS)

    def test_render_content_with_multiple_sections(self):
        """Test _render_content renders multiple sections in order."""
        from resume import docx_standard

        data = {
            "name": "John Doe",
            "summary": "Software engineer",
            "skills": ["Python"],
            "experience": [{"title": "Dev", "company": "Co"}],
        }
        template = {
            "sections": [
                {"key": "summary", "title": "Summary"},
                {"key": "skills", "title": "Skills"},
                {"key": "experience", "title": "Experience"},
            ]
        }
        writer = self._create_writer(data, template)
        self._setup_mock_doc(writer)

        mock_summary = MagicMock(return_value=MagicMock())
        mock_skills = MagicMock(return_value=MagicMock())
        mock_exp = MagicMock(return_value=MagicMock())

        original_summary = docx_standard.SECTION_RENDERERS["summary"]
        original_skills = docx_standard.SECTION_RENDERERS["skills"]
        original_exp = docx_standard.SECTION_RENDERERS["experience"]

        docx_standard.SECTION_RENDERERS["summary"] = mock_summary
        docx_standard.SECTION_RENDERERS["skills"] = mock_skills
        docx_standard.SECTION_RENDERERS["experience"] = mock_exp

        try:
            writer._render_content()

            # Verify all three renderers were instantiated
            mock_summary.assert_called_once()
            mock_skills.assert_called_once()
            mock_exp.assert_called_once()
        finally:
            docx_standard.SECTION_RENDERERS["summary"] = original_summary
            docx_standard.SECTION_RENDERERS["skills"] = original_skills
            docx_standard.SECTION_RENDERERS["experience"] = original_exp

    def test_render_content_unknown_section_key(self):
        """Test _render_content handles unknown section keys gracefully."""
        data = {"name": "John Doe"}
        template = {
            "sections": [
                {"key": "unknown_section", "title": "Unknown"},
            ]
        }
        writer = self._create_writer(data, template)
        mock_doc = self._setup_mock_doc(writer)

        # Should not raise, just skip unknown sections
        writer._render_content()

        # Verify heading was added but no renderer called
        mock_doc.add_heading.assert_any_call("Unknown", level=1)


if __name__ == "__main__":
    unittest.main()
