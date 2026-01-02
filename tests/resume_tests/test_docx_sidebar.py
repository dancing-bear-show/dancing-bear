"""Tests for resume/docx_sidebar.py sidebar layout renderer."""

from __future__ import annotations

from tests.fixtures import test_path
import unittest
from unittest.mock import MagicMock, patch

from tests.resume_tests.fixtures import make_candidate, mock_docx_modules


@mock_docx_modules
class TestCellHelpers(unittest.TestCase):
    """Tests for cell styling helper functions."""

    def test_set_cell_shading_valid_color(self):
        """Test setting cell shading with valid hex color."""
        from resume.docx_sidebar import _set_cell_shading
        cell = MagicMock()
        cell._tc.get_or_add_tcPr.return_value = MagicMock()
        _set_cell_shading(cell, "#F0F0F0")
        cell._tc.get_or_add_tcPr.assert_called()

    def test_set_cell_shading_invalid_color(self):
        """Test setting cell shading with invalid color is no-op."""
        from resume.docx_sidebar import _set_cell_shading
        cell = MagicMock()
        _set_cell_shading(cell, "invalid")
        # Should not raise error

    def test_remove_cell_borders(self):
        """Test removing cell borders."""
        from resume.docx_sidebar import _remove_cell_borders
        cell = MagicMock()
        cell._tc.get_or_add_tcPr.return_value = MagicMock()
        _remove_cell_borders(cell)
        cell._tc.get_or_add_tcPr.assert_called()


@mock_docx_modules
class TestSidebarSectionRenderers(unittest.TestCase):
    """Tests for sidebar section rendering functions."""

    def _get_fake_cell(self):
        """Create a fake cell with paragraph tracking."""
        cell = MagicMock()
        paragraphs = []

        def add_paragraph():
            p = MagicMock()
            runs = []

            def add_run(text=""):
                run = MagicMock()
                run.text = text
                run.bold = False
                run.italic = False
                run.font = MagicMock()
                runs.append(run)
                return run

            p.add_run = add_run
            p.runs = runs
            p.paragraph_format = MagicMock()
            paragraphs.append(p)
            return p

        cell.add_paragraph = add_paragraph
        cell.paragraphs = paragraphs
        return cell

    def test_render_sidebar_section_with_title(self):
        """Test rendering sidebar section with title."""
        from resume.docx_sidebar import _render_sidebar_section
        cell = self._get_fake_cell()
        page_cfg = {"h1_pt": 14, "body_pt": 10}

        _render_sidebar_section(cell, "Test Section", ["Item 1", "Item 2"], page_cfg)

        # Should have 3 paragraphs: title + 2 items
        self.assertEqual(len(cell.paragraphs), 3)

    def test_render_sidebar_section_bulleted(self):
        """Test rendering sidebar section with bullets."""
        from resume.docx_sidebar import _render_sidebar_section
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10}

        _render_sidebar_section(cell, "Skills", ["Python", "Java"], page_cfg, bulleted=True)

        # First paragraph is title, subsequent are items
        self.assertEqual(len(cell.paragraphs), 3)

    def test_render_sidebar_section_not_bulleted(self):
        """Test rendering sidebar section without bullets."""
        from resume.docx_sidebar import _render_sidebar_section
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10}

        _render_sidebar_section(cell, "Skills", ["Python", "Java"], page_cfg, bulleted=False)

        # Should still render items
        self.assertEqual(len(cell.paragraphs), 3)


@mock_docx_modules
class TestMainColumnRenderers(unittest.TestCase):
    """Tests for main column section rendering functions."""

    def _get_fake_cell(self):
        """Create a fake cell with paragraph tracking."""
        cell = MagicMock()
        paragraphs = []

        def add_paragraph():
            p = MagicMock()
            runs = []

            def add_run(text=""):
                run = MagicMock()
                run.text = text
                run.bold = False
                run.italic = False
                run.font = MagicMock()
                runs.append(run)
                return run

            p.add_run = add_run
            p.runs = runs
            p.paragraph_format = MagicMock()
            paragraphs.append(p)
            return p

        cell.add_paragraph = add_paragraph
        cell.paragraphs = paragraphs
        return cell

    def test_render_main_section_heading(self):
        """Test rendering main section heading."""
        from resume.docx_sidebar import _render_main_section_heading
        cell = self._get_fake_cell()
        page_cfg = {"h1_pt": 14, "h1_color": "#D4A84B"}

        _render_main_section_heading(cell, "Experience", page_cfg)

        self.assertEqual(len(cell.paragraphs), 1)

    def test_render_main_education(self):
        """Test rendering education in main column."""
        from resume.docx_sidebar import _render_main_education
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10, "meta_pt": 9}
        data = {
            "education": [
                {"degree": "BS Computer Science", "institution": "MIT", "year": "2020"},
                {"degree": "MS Data Science", "institution": "Stanford", "year": "2022"},
            ]
        }
        sec = {}

        _render_main_education(cell, data, page_cfg, sec)

        # Each education entry creates 2 paragraphs (degree + institution line)
        self.assertGreaterEqual(len(cell.paragraphs), 4)

    def test_render_main_experience(self):
        """Test rendering experience in main column."""
        from resume.docx_sidebar import _render_main_experience
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10, "meta_pt": 9}
        data = {
            "experience": [
                {
                    "title": "Senior Engineer",
                    "company": "TechCorp",
                    "start": "2020",
                    "end": "2023",
                    "bullets": ["Built APIs", "Led team"],
                }
            ]
        }
        sec = {"recent_max_bullets": 3}

        _render_main_experience(cell, data, page_cfg, sec)

        # Should have: title + company + 2 bullets = 4+ paragraphs
        self.assertGreaterEqual(len(cell.paragraphs), 4)

    def test_render_main_teaching(self):
        """Test rendering teaching in main column."""
        from resume.docx_sidebar import _render_main_teaching
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10, "meta_pt": 9}
        data = {
            "teaching": [
                {"text": "Python Course (University)"},
                "JavaScript Workshop",
            ]
        }
        sec = {}

        _render_main_teaching(cell, data, page_cfg, sec)

        # Should have entries for each teaching item
        self.assertGreaterEqual(len(cell.paragraphs), 2)

    def test_render_main_presentations(self):
        """Test rendering presentations in main column."""
        from resume.docx_sidebar import _render_main_presentations
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10, "meta_pt": 9}
        data = {
            "presentations": [
                {
                    "title": "Intro to Python",
                    "authors": "John Doe",
                    "event": "PyCon 2023",
                    "note": "Best Paper Award",
                }
            ]
        }
        sec = {}

        _render_main_presentations(cell, data, page_cfg, sec)

        # Should have title + authors + event + note
        self.assertGreaterEqual(len(cell.paragraphs), 4)


@mock_docx_modules
class TestSidebarResumeWriter(unittest.TestCase):
    """Tests for SidebarResumeWriter class."""

    def test_writer_initialization(self):
        """Test SidebarResumeWriter initialization."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = make_candidate()
        template = {"page": {"compact": True}, "layout": {"type": "sidebar"}}

        writer = SidebarResumeWriter(data, template)

        self.assertEqual(writer.data, data)
        self.assertEqual(writer.template, template)

    def test_get_contact_field_top_level(self):
        """Test getting contact field from top level."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = {"name": "John Doe", "email": "john@example.com"}
        template = {}

        writer = SidebarResumeWriter(data, template)
        result = writer._get_contact_field("email")

        self.assertEqual(result, "john@example.com")

    def test_get_contact_field_nested(self):
        """Test getting contact field from nested contact dict."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = {"name": "John Doe", "contact": {"email": "nested@example.com"}}
        template = {}

        writer = SidebarResumeWriter(data, template)
        result = writer._get_contact_field("email")

        self.assertEqual(result, "nested@example.com")


@mock_docx_modules
class TestBackwardCompatibility(unittest.TestCase):
    """Tests for backward-compatible function."""

    @patch("resume.docx_sidebar.SidebarResumeWriter")
    def test_write_resume_docx_sidebar_delegates(self, mock_writer_class):
        """Test that write_resume_docx_sidebar delegates to SidebarResumeWriter."""
        from resume.docx_sidebar import write_resume_docx_sidebar

        mock_writer = MagicMock()
        mock_writer_class.return_value = mock_writer

        data = make_candidate()
        template = {"page": {}}

        write_resume_docx_sidebar(data, template, test_path("test.docx"))  # nosec B108 - test fixture path

        mock_writer_class.assert_called_once_with(data, template)
        mock_writer.write.assert_called_once()


if __name__ == "__main__":
    unittest.main()
