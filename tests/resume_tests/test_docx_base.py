"""Tests for resume/docx_base.py base DOCX writer classes."""

from __future__ import annotations

from tests.fixtures import test_path
import unittest
from unittest.mock import MagicMock, patch

@patch.dict("sys.modules", {
    "docx": MagicMock(),
    "docx.shared": MagicMock(),
    "docx.enum.text": MagicMock(),
    "docx.enum.table": MagicMock(),
    "docx.oxml": MagicMock(),
    "docx.oxml.ns": MagicMock(),
})
class TestCreateResumeWriter(unittest.TestCase):
    """Tests for create_resume_writer factory function."""

    def test_returns_standard_writer_by_default(self):
        """Test factory returns StandardResumeWriter for no layout specified."""
        from resume.docx_base import create_resume_writer
        data = {"name": "John Doe"}
        template = {"sections": []}
        writer = create_resume_writer(data, template)
        self.assertEqual(writer.__class__.__name__, "StandardResumeWriter")

    def test_returns_standard_writer_for_standard_layout(self):
        """Test factory returns StandardResumeWriter for 'standard' layout."""
        from resume.docx_base import create_resume_writer
        data = {"name": "John Doe"}
        template = {"sections": [], "layout": {"type": "standard"}}
        writer = create_resume_writer(data, template)
        self.assertEqual(writer.__class__.__name__, "StandardResumeWriter")

    def test_returns_sidebar_writer_for_sidebar_layout(self):
        """Test factory returns SidebarResumeWriter for 'sidebar' layout."""
        from resume.docx_base import create_resume_writer
        data = {"name": "John Doe"}
        template = {"sections": [], "layout": {"type": "sidebar"}}
        writer = create_resume_writer(data, template)
        self.assertEqual(writer.__class__.__name__, "SidebarResumeWriter")

    def test_stores_data_and_template(self):
        """Test writer stores data and template."""
        from resume.docx_base import create_resume_writer
        data = {"name": "John Doe"}
        template = {"sections": [], "page": {"compact": True}}
        writer = create_resume_writer(data, template)
        self.assertEqual(writer.data, data)
        self.assertEqual(writer.template, template)

    def test_extracts_page_config(self):
        """Test writer extracts page config from template."""
        from resume.docx_base import create_resume_writer
        data = {"name": "John Doe"}
        template = {"page": {"compact": True, "margins_in": 0.4}}
        writer = create_resume_writer(data, template)
        self.assertEqual(writer.page_cfg, {"compact": True, "margins_in": 0.4})

    def test_extracts_layout_config(self):
        """Test writer extracts layout config from template."""
        from resume.docx_base import create_resume_writer
        data = {"name": "John Doe"}
        template = {"layout": {"type": "standard", "columns": 1}}
        writer = create_resume_writer(data, template)
        self.assertEqual(writer.layout_cfg, {"type": "standard", "columns": 1})


@patch.dict("sys.modules", {
    "docx": MagicMock(),
    "docx.shared": MagicMock(),
    "docx.enum.text": MagicMock(),
    "docx.oxml": MagicMock(),
    "docx.oxml.ns": MagicMock(),
})
class TestResumeWriterBase(unittest.TestCase):
    """Tests for ResumeWriterBase methods."""

    def _get_writer(self):
        """Create a StandardResumeWriter for testing base methods."""
        from resume.docx_base import create_resume_writer
        data = {
            "name": "John Doe",
            "email": "john@example.com",
            "experience": [
                {"title": "Dev", "location": "Seattle, WA"},
                {"title": "Mgr", "location": "Portland, OR"},
                {"title": "Dir", "location": "Seattle, WA"},  # Duplicate
            ],
        }
        template = {"page": {}}
        return create_resume_writer(data, template)

    def test_extract_experience_locations_unique(self):
        """Test extracting unique locations from experience."""
        writer = self._get_writer()
        result = writer._extract_experience_locations()
        self.assertEqual(result, ["Seattle, WA", "Portland, OR"])

    def test_extract_experience_locations_empty(self):
        """Test extracting locations with no experience."""
        from resume.docx_base import create_resume_writer
        data = {"name": "John"}
        template = {"page": {}}
        writer = create_resume_writer(data, template)
        result = writer._extract_experience_locations()
        self.assertEqual(result, [])

    def test_get_contact_field_top_level(self):
        """Test getting contact field from top level."""
        writer = self._get_writer()
        result = writer._get_contact_field("email")
        self.assertEqual(result, "john@example.com")

    def test_get_contact_field_nested(self):
        """Test getting contact field from nested contact dict."""
        from resume.docx_base import create_resume_writer
        data = {"name": "John", "contact": {"phone": "555-1234"}}
        template = {"page": {}}
        writer = create_resume_writer(data, template)
        result = writer._get_contact_field("phone")
        self.assertEqual(result, "555-1234")

    def test_get_contact_field_prefers_top_level(self):
        """Test top level field is preferred over nested."""
        from resume.docx_base import create_resume_writer
        data = {
            "name": "John",
            "email": "top@example.com",
            "contact": {"email": "nested@example.com"},
        }
        template = {"page": {}}
        writer = create_resume_writer(data, template)
        result = writer._get_contact_field("email")
        self.assertEqual(result, "top@example.com")

    def test_get_contact_field_missing(self):
        """Test getting missing contact field returns empty string."""
        writer = self._get_writer()
        result = writer._get_contact_field("phone")
        self.assertEqual(result, "")

    def test_collect_link_extras_single_links(self):
        """Test collecting individual link fields."""
        from resume.docx_base import create_resume_writer
        data = {
            "name": "John",
            "website": "https://example.com",
            "linkedin": "https://linkedin.com/in/john",
            "github": "https://github.com/john",
        }
        template = {"page": {}}
        writer = create_resume_writer(data, template)
        result = writer._collect_link_extras()
        self.assertEqual(len(result), 3)

    def test_collect_link_extras_links_list(self):
        """Test collecting from links list."""
        from resume.docx_base import create_resume_writer
        data = {
            "name": "John",
            "links": ["https://blog.example.com", "https://portfolio.example.com"],
        }
        template = {"page": {}}
        writer = create_resume_writer(data, template)
        result = writer._collect_link_extras()
        self.assertEqual(len(result), 2)

    def test_collect_link_extras_empty(self):
        """Test collecting links with no links."""
        from resume.docx_base import create_resume_writer
        data = {"name": "John"}
        template = {"page": {}}
        writer = create_resume_writer(data, template)
        result = writer._collect_link_extras()
        self.assertEqual(result, [])


@patch.dict("sys.modules", {
    "docx": MagicMock(),
    "docx.shared": MagicMock(),
    "docx.enum.text": MagicMock(),
    "docx.oxml": MagicMock(),
    "docx.oxml.ns": MagicMock(),
})
class TestResumeWriterBaseWrite(unittest.TestCase):
    """Tests for ResumeWriterBase.write() method."""

    @patch("resume.docx_base.safe_import")
    def test_raises_when_docx_unavailable(self, mock_safe_import):
        """Test write raises when python-docx is not installed."""
        mock_safe_import.return_value = None
        from resume.docx_base import create_resume_writer
        data = {"name": "John"}
        template = {"page": {}}
        writer = create_resume_writer(data, template)
        with self.assertRaises(RuntimeError) as ctx:
            writer.write(test_path("test.docx"))  # nosec B108 - test fixture path
        self.assertIn("python-docx", str(ctx.exception))

    @patch("resume.docx_base.safe_import")
    def test_write_creates_and_saves_document(self, mock_safe_import):
        """Test write creates document and saves to path."""
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
        mock_doc.styles = {
            "Normal": MagicMock(),
            "Heading 1": MagicMock(),
            "Title": MagicMock(),
        }
        mock_docx.Document.return_value = mock_doc
        mock_safe_import.return_value = mock_docx

        with patch.dict("sys.modules", {"docx": mock_docx}):
            from resume.docx_base import create_resume_writer
            data = {"name": "John Doe"}
            template = {"sections": [], "page": {"compact": False}}
            writer = create_resume_writer(data, template)
            writer.write(test_path("test.docx"))  # nosec B108 - test fixture path

        mock_doc.save.assert_called_once_with(test_path("test.docx"))  # nosec B108 - test fixture path


if __name__ == "__main__":
    unittest.main()
