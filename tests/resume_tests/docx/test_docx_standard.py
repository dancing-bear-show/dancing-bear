"""Tests for resume/docx_standard.py — StandardResumeWriter."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from tests.resume_tests.fixtures import mock_docx_modules


def _make_mock_doc():
    """Make a mock Document that tracks paragraphs."""
    doc = MagicMock()
    paragraphs = []

    def _make_para(text="", **_kwargs):
        p = MagicMock()
        p.text = text
        p.paragraph_format = MagicMock()
        p.alignment = None
        paragraphs.append(p)
        return p

    doc.add_heading = MagicMock(side_effect=_make_para)
    doc.add_paragraph = MagicMock(side_effect=_make_para)
    doc.paragraphs = paragraphs
    doc.styles = {}
    doc.sections = [MagicMock()]
    doc.core_properties = MagicMock()
    return doc


@mock_docx_modules
class TestStandardResumeWriterInit(unittest.TestCase):
    """Tests for StandardResumeWriter initialization."""

    def test_creates_writer_with_data_and_template(self):
        from resume.docx_standard import StandardResumeWriter
        data = {"name": "John Doe"}
        template = {"sections": [], "page": {"compact": False}}
        writer = StandardResumeWriter(data, template)
        self.assertEqual(writer.data, data)
        self.assertEqual(writer.template, template)
        self.assertEqual(writer.page_cfg, {"compact": False})

    def test_empty_page_cfg(self):
        from resume.docx_standard import StandardResumeWriter
        data = {"name": "Jane"}
        template = {"sections": []}
        writer = StandardResumeWriter(data, template)
        self.assertEqual(writer.page_cfg, {})


@mock_docx_modules
class TestSectionRenderers(unittest.TestCase):
    """Tests for SECTION_RENDERERS and SECTIONS_WITH_KEYWORDS constants."""

    def test_section_renderers_registry(self):
        from resume.docx_standard import SECTION_RENDERERS
        expected = {
            "summary", "skills", "technologies", "interests",
            "presentations", "languages", "coursework",
            "certifications", "experience", "education", "teaching",
        }
        self.assertEqual(set(SECTION_RENDERERS.keys()), expected)

    def test_sections_with_keywords_is_subset(self):
        from resume.docx_standard import SECTION_RENDERERS, SECTIONS_WITH_KEYWORDS
        self.assertTrue(SECTIONS_WITH_KEYWORDS.issubset(set(SECTION_RENDERERS.keys())))

    def test_sections_with_keywords_contains_expected(self):
        from resume.docx_standard import SECTIONS_WITH_KEYWORDS
        self.assertIn("summary", SECTIONS_WITH_KEYWORDS)
        self.assertIn("experience", SECTIONS_WITH_KEYWORDS)


@mock_docx_modules
class TestResolveSections(unittest.TestCase):
    """Tests for StandardResumeWriter._resolve_sections."""

    def _make_writer(self, sections):
        from resume.docx_standard import StandardResumeWriter
        return StandardResumeWriter({}, {"sections": sections})

    def test_returns_sections_from_template(self):
        sections = [{"key": "summary"}, {"key": "experience"}]
        writer = self._make_writer(sections)
        result = writer._resolve_sections()
        self.assertEqual(result, sections)

    def test_returns_empty_when_no_sections(self):
        writer = self._make_writer([])
        result = writer._resolve_sections()
        self.assertEqual(result, [])

    def test_returns_empty_when_template_missing_sections(self):
        from resume.docx_standard import StandardResumeWriter
        writer = StandardResumeWriter({}, {})
        result = writer._resolve_sections()
        self.assertEqual(result, [])


@mock_docx_modules
class TestRenderDocumentHeader(unittest.TestCase):
    """Tests for StandardResumeWriter._render_document_header."""

    def _make_writer(self, data, template=None):
        from resume.docx_standard import StandardResumeWriter
        writer = StandardResumeWriter(data, template or {})
        writer.doc = _make_mock_doc()
        return writer

    def test_renders_name_heading(self):
        data = {"name": "Alice Smith"}
        writer = self._make_writer(data)
        writer._render_document_header()
        # Name heading should be added
        writer.doc.add_heading.assert_called()
        calls = [str(c) for c in writer.doc.add_heading.call_args_list]
        self.assertTrue(any("Alice Smith" in c for c in calls))

    def test_renders_headline(self):
        data = {"name": "Alice", "headline": "Senior Engineer"}
        writer = self._make_writer(data)
        writer._render_document_header()
        # Headline paragraph should be added
        writer.doc.add_paragraph.assert_called()

    def test_renders_contact_line_with_email_and_phone(self):
        data = {"name": "Alice", "email": "alice@example.com", "phone": "555-1234"}
        writer = self._make_writer(data)
        writer._render_document_header()
        # Contact line should be in add_paragraph calls
        para_texts = [
            str(call) for call in writer.doc.add_paragraph.call_args_list
        ]
        self.assertTrue(any("alice@example.com" in t for t in para_texts))

    def test_no_name_skips_name_heading(self):
        data = {"email": "alice@example.com"}
        writer = self._make_writer(data)
        writer._render_document_header()
        # With no name, add_heading should not be called
        writer.doc.add_heading.assert_not_called()

    def test_no_headline_skips_headline_paragraph(self):
        data = {"name": "Alice"}
        writer = self._make_writer(data)
        # Track add_paragraph calls before
        writer._render_document_header()
        # With name only (no contact info, no headline), add_paragraph should not be called
        writer.doc.add_paragraph.assert_not_called()


@mock_docx_modules
class TestRenderSectionHeading(unittest.TestCase):
    """Tests for StandardResumeWriter._render_section_heading."""

    def _make_writer(self, page_cfg=None):
        from resume.docx_standard import StandardResumeWriter
        writer = StandardResumeWriter({}, {"page": page_cfg or {}})
        writer.doc = _make_mock_doc()
        return writer

    def test_renders_section_heading_with_title(self):
        writer = self._make_writer()
        writer._render_section_heading("Experience")
        writer.doc.add_heading.assert_called_with("Experience", level=1)

    def test_skips_empty_title(self):
        writer = self._make_writer()
        writer._render_section_heading("")
        writer.doc.add_heading.assert_not_called()

    def test_renders_with_background_color(self):
        writer = self._make_writer(page_cfg={"h1_bg": "#336699"})
        # Should not raise even when shading applied
        writer._render_section_heading("Education")
        writer.doc.add_heading.assert_called()


@mock_docx_modules
class TestRenderContent(unittest.TestCase):
    """Tests for StandardResumeWriter._render_content."""

    def _make_writer_with_doc(self, data, sections, page_cfg=None):
        from resume.docx_standard import StandardResumeWriter
        template = {"sections": sections, "page": page_cfg or {}}
        writer = StandardResumeWriter(data, template)
        writer.doc = _make_mock_doc()
        return writer

    def test_renders_with_empty_sections(self):
        data = {"name": "John"}
        writer = self._make_writer_with_doc(data, [])
        # Should not raise
        writer._render_content()

    def test_renders_with_known_section(self):
        data = {"name": "John", "skills": ["Python"]}
        sections = [{"key": "skills", "title": "Skills"}]
        writer = self._make_writer_with_doc(data, sections)
        # Mock the renderer to avoid actual rendering complexity
        with patch("resume.docx_standard.SECTION_RENDERERS") as mock_renderers:
            mock_renderer_class = MagicMock()
            mock_renderer_instance = MagicMock()
            mock_renderer_class.return_value = mock_renderer_instance
            mock_renderers.get.return_value = mock_renderer_class
            writer._render_content()
        # add_heading called for name + section title
        self.assertGreaterEqual(writer.doc.add_heading.call_count, 1)

    def test_skips_sections_without_key(self):
        data = {"name": "John"}
        sections = [{"title": "No Key Section"}]
        writer = self._make_writer_with_doc(data, sections)
        with patch("resume.docx_standard.SECTION_RENDERERS") as mock_renderers:
            mock_renderers.get.return_value = None
            writer._render_content()
        # Skipped keyless section means no extra heading beyond name
        # add_heading might be called for name
        # No section renderer should be called
        mock_renderers.get.assert_not_called()

    def test_renders_keywords_from_seed(self):
        data = {"name": "John", "summary": "Python developer"}
        sections = [{"key": "summary", "title": "Summary"}]
        seed = {"keywords": ["Python", "AWS"]}
        writer = self._make_writer_with_doc(data, sections)
        with patch("resume.docx_standard.SECTION_RENDERERS") as mock_renderers:
            mock_renderer_class = MagicMock()
            mock_renderer_instance = MagicMock()
            mock_renderer_class.return_value = mock_renderer_instance
            mock_renderers.get.return_value = mock_renderer_class
            writer._render_content(seed=seed)
        # summary is in SECTIONS_WITH_KEYWORDS, so render called with keywords
        mock_renderer_instance.render.assert_called()

    def test_renders_section_title_from_key_when_missing(self):
        data = {"name": "John", "skills": ["Python"]}
        # Section has key but no explicit title
        sections = [{"key": "skills"}]
        writer = self._make_writer_with_doc(data, sections)
        with patch("resume.docx_standard.SECTION_RENDERERS") as mock_renderers:
            mock_renderers.get.return_value = None  # No renderer
            writer._render_content()
        # Section heading should be rendered with "Skills" (title-cased key)
        heading_calls = writer.doc.add_heading.call_args_list
        titles = [str(c) for c in heading_calls]
        self.assertTrue(any("Skills" in t for t in titles))


if __name__ == "__main__":
    unittest.main()
