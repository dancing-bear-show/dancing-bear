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

    def test_render_main_education_empty(self):
        """Test rendering education with no data."""
        from resume.docx_sidebar import _render_main_education
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10, "meta_pt": 9}
        data = {}
        sec = {}

        _render_main_education(cell, data, page_cfg, sec)

        # Should have no paragraphs
        self.assertEqual(len(cell.paragraphs), 0)

    def test_render_education_degree(self):
        """Test rendering education degree line."""
        from resume.docx_sidebar import _render_education_degree
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10}
        edu = {"degree": "PhD Computer Science"}

        _render_education_degree(cell, edu, page_cfg, "#4A90A4")

        self.assertEqual(len(cell.paragraphs), 1)

    def test_render_education_details_with_all_fields(self):
        """Test rendering education details with institution and year."""
        from resume.docx_sidebar import _render_education_details
        cell = self._get_fake_cell()
        page_cfg = {"meta_pt": 9}
        edu = {"institution": "Stanford University", "year": "2020"}

        _render_education_details(cell, edu, page_cfg)

        self.assertEqual(len(cell.paragraphs), 1)

    def test_render_education_details_only_institution(self):
        """Test rendering education details with only institution."""
        from resume.docx_sidebar import _render_education_details
        cell = self._get_fake_cell()
        page_cfg = {"meta_pt": 9}
        edu = {"institution": "MIT"}

        _render_education_details(cell, edu, page_cfg)

        self.assertEqual(len(cell.paragraphs), 1)

    def test_render_education_details_no_fields(self):
        """Test rendering education details with no institution or year."""
        from resume.docx_sidebar import _render_education_details
        cell = self._get_fake_cell()
        page_cfg = {"meta_pt": 9}
        edu = {}

        _render_education_details(cell, edu, page_cfg)

        # Should not add paragraph if no details
        self.assertEqual(len(cell.paragraphs), 0)

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

    def test_render_main_experience_empty(self):
        """Test rendering experience with no data."""
        from resume.docx_sidebar import _render_main_experience
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10, "meta_pt": 9}
        data = {}
        sec = {}

        _render_main_experience(cell, data, page_cfg, sec)

        # Should have no paragraphs
        self.assertEqual(len(cell.paragraphs), 0)

    def test_render_experience_header_with_end_date(self):
        """Test rendering experience header with end date."""
        from resume.docx_sidebar import _render_experience_header
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10, "meta_pt": 9}
        exp = {"title": "Developer", "start": "2020", "end": "2023"}

        _render_experience_header(cell, exp, page_cfg, "#4A90A4")

        self.assertEqual(len(cell.paragraphs), 1)

    def test_render_experience_header_without_end_date(self):
        """Test rendering experience header without end date (current position)."""
        from resume.docx_sidebar import _render_experience_header
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10, "meta_pt": 9}
        exp = {"title": "Developer", "start": "2020", "end": ""}

        _render_experience_header(cell, exp, page_cfg, "#4A90A4")

        self.assertEqual(len(cell.paragraphs), 1)

    def test_render_experience_company(self):
        """Test rendering experience company name."""
        from resume.docx_sidebar import _render_experience_company
        cell = self._get_fake_cell()
        page_cfg = {"meta_pt": 9}
        exp = {"company": "TechCorp Inc."}

        _render_experience_company(cell, exp, page_cfg)

        self.assertEqual(len(cell.paragraphs), 1)

    def test_render_experience_company_no_company(self):
        """Test rendering experience with no company."""
        from resume.docx_sidebar import _render_experience_company
        cell = self._get_fake_cell()
        page_cfg = {"meta_pt": 9}
        exp = {}

        _render_experience_company(cell, exp, page_cfg)

        # Should not add paragraph if no company
        self.assertEqual(len(cell.paragraphs), 0)

    def test_render_experience_bullets_with_limit(self):
        """Test rendering experience bullets respects max limit."""
        from resume.docx_sidebar import _render_experience_bullets
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10}
        exp = {
            "bullets": ["Bullet 1", "Bullet 2", "Bullet 3", "Bullet 4", "Bullet 5"]
        }
        sec = {"recent_max_bullets": 3}

        _render_experience_bullets(cell, exp, page_cfg, sec)

        # Should only render 3 bullets (max)
        self.assertEqual(len(cell.paragraphs), 3)

    def test_render_experience_bullets_from_dict(self):
        """Test rendering experience bullets from dict format."""
        from resume.docx_sidebar import _render_experience_bullets
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10}
        exp = {
            "bullets": [
                {"text": "Built APIs"},
                {"text": "Led team"},
            ]
        }
        sec = {"recent_max_bullets": 3}

        _render_experience_bullets(cell, exp, page_cfg, sec)

        self.assertEqual(len(cell.paragraphs), 2)

    def test_render_experience_bullets_empty(self):
        """Test rendering experience with no bullets."""
        from resume.docx_sidebar import _render_experience_bullets
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10}
        exp = {}
        sec = {"recent_max_bullets": 3}

        _render_experience_bullets(cell, exp, page_cfg, sec)

        # Should have no paragraphs
        self.assertEqual(len(cell.paragraphs), 0)

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

    def test_render_main_teaching_with_institution(self):
        """Test rendering teaching with institution in parentheses."""
        from resume.docx_sidebar import _render_main_teaching
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10, "meta_pt": 9}
        data = {
            "teaching": ["Advanced Python (Stanford University)"]
        }
        sec = {}

        _render_main_teaching(cell, data, page_cfg, sec)

        # Should have title + institution = 2 paragraphs
        self.assertEqual(len(cell.paragraphs), 2)

    def test_render_main_teaching_without_institution(self):
        """Test rendering teaching without institution."""
        from resume.docx_sidebar import _render_main_teaching
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10, "meta_pt": 9}
        data = {
            "teaching": ["Workshop on Machine Learning"]
        }
        sec = {}

        _render_main_teaching(cell, data, page_cfg, sec)

        # Should have only title = 1 paragraph
        self.assertEqual(len(cell.paragraphs), 1)

    def test_render_main_teaching_empty(self):
        """Test rendering teaching with no data."""
        from resume.docx_sidebar import _render_main_teaching
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10, "meta_pt": 9}
        data = {}
        sec = {}

        _render_main_teaching(cell, data, page_cfg, sec)

        # Should have no paragraphs
        self.assertEqual(len(cell.paragraphs), 0)

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

    def test_render_main_presentations_empty_data(self):
        """Test rendering presentations with no data."""
        from resume.docx_sidebar import _render_main_presentations
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10, "meta_pt": 9}
        data = {}
        sec = {}

        _render_main_presentations(cell, data, page_cfg, sec)

        # Should have no paragraphs
        self.assertEqual(len(cell.paragraphs), 0)

    def test_render_presentation_title(self):
        """Test rendering presentation title with bullet."""
        from resume.docx_sidebar import _render_presentation_title
        cell = self._get_fake_cell()
        page_cfg = {"body_pt": 10, "main_bullet_color": "#4A90A4"}
        pres = {"title": "Machine Learning Research"}

        _render_presentation_title(cell, pres, page_cfg, "#4A90A4")

        self.assertEqual(len(cell.paragraphs), 1)

    def test_render_presentation_details_all_fields(self):
        """Test rendering presentation details with all fields."""
        from resume.docx_sidebar import _render_presentation_details
        cell = self._get_fake_cell()
        page_cfg = {"meta_pt": 9}
        pres = {
            "authors": "John Doe, Jane Smith",
            "event": "International Conference 2023",
            "note": "Keynote Speaker",
        }

        last_para = _render_presentation_details(cell, pres, page_cfg)

        # Should have authors + event + note = 3 paragraphs
        self.assertEqual(len(cell.paragraphs), 3)
        self.assertIsNotNone(last_para)

    def test_render_presentation_details_partial_fields(self):
        """Test rendering presentation details with only some fields."""
        from resume.docx_sidebar import _render_presentation_details
        cell = self._get_fake_cell()
        page_cfg = {"meta_pt": 9}
        pres = {"authors": "John Doe"}

        last_para = _render_presentation_details(cell, pres, page_cfg)

        # Should have only authors
        self.assertEqual(len(cell.paragraphs), 1)
        self.assertIsNotNone(last_para)

    def test_render_presentation_details_no_fields(self):
        """Test rendering presentation details with no optional fields."""
        from resume.docx_sidebar import _render_presentation_details
        cell = self._get_fake_cell()
        page_cfg = {"meta_pt": 9}
        pres = {}

        last_para = _render_presentation_details(cell, pres, page_cfg)

        # Should have no paragraphs
        self.assertEqual(len(cell.paragraphs), 0)
        self.assertIsNone(last_para)

    def test_render_presentation_authors(self):
        """Test rendering presentation authors."""
        from resume.docx_sidebar import _render_presentation_authors
        cell = self._get_fake_cell()
        page_cfg = {"meta_pt": 9}

        para = _render_presentation_authors(cell, "John Doe, Jane Smith", page_cfg)

        self.assertEqual(len(cell.paragraphs), 1)
        self.assertIsNotNone(para)

    def test_render_presentation_event(self):
        """Test rendering presentation event."""
        from resume.docx_sidebar import _render_presentation_event
        cell = self._get_fake_cell()
        page_cfg = {"meta_pt": 9}

        para = _render_presentation_event(cell, "PyCon 2023", page_cfg)

        self.assertEqual(len(cell.paragraphs), 1)
        self.assertIsNotNone(para)

    def test_render_presentation_note(self):
        """Test rendering presentation note."""
        from resume.docx_sidebar import _render_presentation_note
        cell = self._get_fake_cell()
        page_cfg = {"meta_pt": 9}

        para = _render_presentation_note(cell, "Best Paper Award", page_cfg)

        self.assertEqual(len(cell.paragraphs), 1)
        self.assertIsNotNone(para)

    def test_adjust_presentation_spacing(self):
        """Test adjusting presentation spacing."""
        from resume.docx_sidebar import _adjust_presentation_spacing
        from docx.shared import Pt

        para = MagicMock()
        para.paragraph_format = MagicMock()

        _adjust_presentation_spacing(para)

        # Should set space_after
        self.assertTrue(para.paragraph_format.space_after is not None)

    def test_adjust_presentation_spacing_with_none(self):
        """Test adjusting presentation spacing with None paragraph."""
        from resume.docx_sidebar import _adjust_presentation_spacing

        # Should not raise error
        _adjust_presentation_spacing(None)


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

    def test_extract_summary_items_from_list(self):
        """Test extracting summary items from list."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = {"summary": ["Item 1", "Item 2", "Item 3"]}
        template = {}

        writer = SidebarResumeWriter(data, template)
        result = writer._extract_summary_items()

        self.assertEqual(result, ["Item 1", "Item 2", "Item 3"])

    def test_extract_summary_items_from_string(self):
        """Test extracting summary items from string."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = {"summary": "Single summary text"}
        template = {}

        writer = SidebarResumeWriter(data, template)
        result = writer._extract_summary_items()

        self.assertEqual(result, ["Single summary text"])

    def test_extract_summary_items_from_dict_list(self):
        """Test extracting summary items from list of dicts."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = {"summary": [{"text": "Item 1"}, {"text": "Item 2"}]}
        template = {}

        writer = SidebarResumeWriter(data, template)
        result = writer._extract_summary_items()

        self.assertEqual(result, ["Item 1", "Item 2"])

    def test_extract_summary_items_empty(self):
        """Test extracting summary items when none exist."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = {}
        template = {}

        writer = SidebarResumeWriter(data, template)
        result = writer._extract_summary_items()

        self.assertEqual(result, [])

    def test_extract_summary_items_with_none_value(self):
        """Test extracting summary items when summary is None."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = {"summary": None}
        template = {}

        writer = SidebarResumeWriter(data, template)
        result = writer._extract_summary_items()

        self.assertEqual(result, [])

    def test_extract_skill_items(self):
        """Test extracting skill items from skills_groups."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = {
            "skills_groups": [
                {"title": "Languages", "items": ["Python", "Java"]},
                {"title": "Tools", "items": [{"name": "Docker"}, {"name": "Git"}]},
            ]
        }
        template = {}

        writer = SidebarResumeWriter(data, template)
        result = writer._extract_skill_items()

        self.assertEqual(result, ["Python", "Java", "Docker", "Git"])

    def test_extract_skill_items_empty(self):
        """Test extracting skill items when none exist."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = {}
        template = {}

        writer = SidebarResumeWriter(data, template)
        result = writer._extract_skill_items()

        self.assertEqual(result, [])


@mock_docx_modules
class TestRenderingMethods(unittest.TestCase):
    """Tests for rendering methods that orchestrate content generation."""

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

    def test_render_content_creates_two_column_table(self):
        """Test _render_content creates two-column layout."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = make_candidate(
            name="Test User",
            email="test@example.com",
            summary=["Summary item"],
            skills_groups=[{"title": "Languages", "items": ["Python"]}],
        )
        template = {
            "page": {},
            "layout": {"sidebar_width": 2.3, "main_width": 5.2},
            "sections": [
                {"key": "summary", "title": "Profile"},
                {"key": "skills", "title": "Skills"},
            ],
        }

        writer = SidebarResumeWriter(data, template)
        # Mock the doc to track table creation
        writer.doc = MagicMock()
        writer.doc.sections = [MagicMock()]
        writer.doc.sections[0].header = MagicMock()
        writer.doc.sections[0].header.paragraphs = []

        # Mock table structure
        mock_table = MagicMock()
        mock_row = MagicMock()
        mock_sidebar_cell = self._get_fake_cell()
        mock_main_cell = self._get_fake_cell()
        mock_sidebar_cell._tc = MagicMock()
        mock_main_cell._tc = MagicMock()
        mock_sidebar_cell._tc.get_or_add_tcPr = MagicMock()
        mock_main_cell._tc.get_or_add_tcPr = MagicMock()

        mock_row.cells = [mock_sidebar_cell, mock_main_cell]
        mock_table.rows = [mock_row]
        mock_table.columns = [MagicMock(), MagicMock()]
        writer.doc.add_table.return_value = mock_table

        writer._render_content()

        # Verify table was created with correct structure
        writer.doc.add_table.assert_called_once_with(rows=1, cols=2)

    def test_render_content_with_sidebar_background(self):
        """Test _render_content applies sidebar background color."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = make_candidate(name="Test User", email="test@example.com")
        template = {
            "page": {},
            "layout": {"sidebar_width": 2.3, "main_width": 5.2, "sidebar_bg": "#F0F0F0"},
            "sections": [],
        }

        writer = SidebarResumeWriter(data, template)
        writer.doc = MagicMock()
        writer.doc.sections = [MagicMock()]
        writer.doc.sections[0].header = MagicMock()
        writer.doc.sections[0].header.paragraphs = []

        # Mock table with cells that have paragraphs
        mock_table = MagicMock()
        mock_row = MagicMock()
        mock_sidebar_cell = self._get_fake_cell()
        mock_main_cell = self._get_fake_cell()

        # Add paragraph to cells to trigger the clear() branch
        mock_para = MagicMock()
        mock_para.clear = MagicMock()
        mock_sidebar_cell.paragraphs = [mock_para]
        mock_main_cell.paragraphs = [MagicMock()]

        mock_sidebar_cell._tc = MagicMock()
        mock_main_cell._tc = MagicMock()
        mock_sidebar_cell._tc.get_or_add_tcPr = MagicMock()
        mock_main_cell._tc.get_or_add_tcPr = MagicMock()

        mock_row.cells = [mock_sidebar_cell, mock_main_cell]
        mock_table.rows = [mock_row]
        mock_table.columns = [MagicMock(), MagicMock()]
        writer.doc.add_table.return_value = mock_table

        writer._render_content()

        # Verify sidebar background was set
        mock_sidebar_cell._tc.get_or_add_tcPr.assert_called()
        # Verify paragraphs were cleared
        mock_para.clear.assert_called_once()

    def test_render_sidebar_content_with_summary_and_skills(self):
        """Test _render_sidebar_content renders summary and skills."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = make_candidate(
            summary=["Expert in Python", "10 years experience"],
            skills_groups=[
                {"title": "Languages", "items": ["Python", "Java"]},
            ],
        )
        template = {
            "page": {},
            "sections": [
                {"key": "summary", "title": "Profile"},
                {"key": "skills", "title": "Skills"},
            ],
        }

        writer = SidebarResumeWriter(data, template)
        cell = self._get_fake_cell()

        writer._render_sidebar_content(cell)

        # Should have paragraphs for both sections
        self.assertGreater(len(cell.paragraphs), 0)

    def test_render_sidebar_summary_limits_to_six_items(self):
        """Test _render_sidebar_summary limits summary to 6 items."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = make_candidate(
            summary=["Item 1", "Item 2", "Item 3", "Item 4", "Item 5", "Item 6", "Item 7", "Item 8"]
        )
        template = {
            "page": {},
            "sections": [{"key": "summary", "title": "Professional Summary"}],
        }

        writer = SidebarResumeWriter(data, template)
        cell = self._get_fake_cell()

        writer._render_sidebar_summary(cell)

        # Title + 6 items = 7 paragraphs
        self.assertEqual(len(cell.paragraphs), 7)

    def test_render_sidebar_skills_limits_to_eight_items(self):
        """Test _render_sidebar_skills limits skills to 8 items."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = make_candidate(
            skills_groups=[
                {"title": "Languages", "items": ["Skill1", "Skill2", "Skill3", "Skill4", "Skill5"]},
                {"title": "Tools", "items": ["Skill6", "Skill7", "Skill8", "Skill9", "Skill10"]},
            ]
        )
        template = {
            "page": {},
            "sections": [{"key": "skills", "title": "Key Skills"}],
        }

        writer = SidebarResumeWriter(data, template)
        cell = self._get_fake_cell()

        writer._render_sidebar_skills(cell)

        # Title + 8 items = 9 paragraphs
        self.assertEqual(len(cell.paragraphs), 9)

    def test_render_main_content_with_all_sections(self):
        """Test _render_main_content renders all section types."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = make_candidate(
            education=[{"degree": "BS CS", "institution": "MIT", "year": "2020"}],
            experience=[{
                "title": "Developer",
                "company": "TechCorp",
                "start": "2020",
                "end": "2023",
                "bullets": ["Built APIs"],
            }],
            teaching=["Python Course (University)"],
            presentations=[{
                "title": "Intro to Python",
                "authors": "John Doe",
                "event": "PyCon 2023",
            }],
        )
        template = {
            "page": {},
            "sections": [
                {"key": "education", "title": "Education"},
                {"key": "experience", "title": "Experience"},
                {"key": "teaching", "title": "Teaching"},
                {"key": "presentations", "title": "Presentations"},
            ],
        }

        writer = SidebarResumeWriter(data, template)
        cell = self._get_fake_cell()

        writer._render_main_content(cell)

        # Should have paragraphs for all sections
        self.assertGreater(len(cell.paragraphs), 4)

    def test_render_page_header_with_all_fields(self):
        """Test _render_page_header with name, headline, and contact."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = make_candidate(
            name="John Doe",
            headline="Senior Developer",
            email="john@example.com",
            phone="555-1234",
            location="San Francisco, CA",
        )
        template = {
            "page": {
                "sidebar_name_color": "#1A365D",
                "sidebar_text_color": "#333333",
                "header_bg": "#F7F9FC",
                "sidebar_name_pt": 20,
                "sidebar_headline_pt": 10,
                "body_pt": 10,
            }
        }

        writer = SidebarResumeWriter(data, template)
        # Mock document sections
        writer.doc = MagicMock()
        section = MagicMock()
        header = MagicMock()
        paragraphs = []

        def add_paragraph():
            p = MagicMock()
            p.add_run = MagicMock(return_value=MagicMock())
            p.paragraph_format = MagicMock()
            paragraphs.append(p)
            return p

        header.paragraphs = []
        header.add_paragraph = add_paragraph
        section.header = header
        writer.doc.sections = [section]

        writer._render_page_header()

        # Should have created paragraphs for name, headline, and contact
        self.assertGreater(len(paragraphs), 0)

    def test_render_page_header_without_headline(self):
        """Test _render_page_header works without headline."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = make_candidate(name="John Doe", email="john@example.com")
        template = {"page": {}}

        writer = SidebarResumeWriter(data, template)
        writer.doc = MagicMock()
        section = MagicMock()
        header = MagicMock()
        paragraphs = []

        def add_paragraph():
            p = MagicMock()
            p.add_run = MagicMock(return_value=MagicMock())
            p.paragraph_format = MagicMock()
            paragraphs.append(p)
            return p

        header.paragraphs = []
        header.add_paragraph = add_paragraph
        section.header = header
        writer.doc.sections = [section]

        writer._render_page_header()

        # Should still work without headline
        self.assertGreater(len(paragraphs), 0)

    def test_render_page_header_with_existing_paragraphs(self):
        """Test _render_page_header reuses existing paragraph."""
        from resume.docx_sidebar import SidebarResumeWriter
        data = make_candidate(name="John Doe")
        template = {"page": {}}

        writer = SidebarResumeWriter(data, template)
        writer.doc = MagicMock()
        section = MagicMock()
        header = MagicMock()

        # Create existing paragraph
        existing_para = MagicMock()
        existing_para.clear = MagicMock()
        existing_para.add_run = MagicMock(return_value=MagicMock())
        existing_para.paragraph_format = MagicMock()
        header.paragraphs = [existing_para]
        section.header = header
        writer.doc.sections = [section]

        writer._render_page_header()

        # Should clear and reuse existing paragraph
        existing_para.clear.assert_called_once()


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
