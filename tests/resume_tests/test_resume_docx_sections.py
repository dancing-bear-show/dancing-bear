"""Tests for resume/docx_sections.py section renderers."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from tests.resume_tests.fixtures import FakeDocument


# Patch the docx_styles module before importing docx_sections
@patch.dict("sys.modules", {
    "docx": MagicMock(),
    "docx.shared": MagicMock(),
    "docx.enum.text": MagicMock(),
    "docx.oxml": MagicMock(),
    "docx.oxml.ns": MagicMock(),
})
class TestBulletRenderer(unittest.TestCase):
    """Tests for BulletRenderer class."""

    def _get_renderer(self):
        from resume.docx_sections import BulletRenderer
        doc = FakeDocument()
        return BulletRenderer(doc), doc

    def test_get_bullet_config_defaults(self):
        """Test default bullet config."""
        renderer, _ = self._get_renderer()
        plain, glyph = renderer.get_bullet_config(None)
        self.assertEqual(glyph, "•")

    def test_get_bullet_config_custom_glyph(self):
        """Test custom glyph from section config."""
        renderer, _ = self._get_renderer()
        sec = {"bullets": {"glyph": "→"}}
        plain, glyph = renderer.get_bullet_config(sec)
        self.assertEqual(glyph, "→")

    def test_get_bullet_config_plain_style(self):
        """Test plain bullet style."""
        renderer, _ = self._get_renderer()
        sec = {"bullets": {"style": "plain"}}
        plain, glyph = renderer.get_bullet_config(sec)
        self.assertTrue(plain)

    def test_get_bullet_config_plain_bullets_flag(self):
        """Test plain_bullets flag."""
        renderer, _ = self._get_renderer()
        sec = {"plain_bullets": True}
        plain, glyph = renderer.get_bullet_config(sec)
        self.assertTrue(plain)

    def test_add_bullet_line(self):
        """Test adding a plain bullet line."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line("Test item", glyph="•")
        self.assertEqual(len(doc.paragraphs), 1)
        runs = doc.paragraphs[0].runs
        self.assertEqual(runs[0].text, "• ")
        self.assertEqual(runs[1].text, "Test item")

    def test_add_named_bullet(self):
        """Test adding a bullet with bold name."""
        renderer, doc = self._get_renderer()
        renderer.add_named_bullet("Python", "Programming language", glyph="•")
        self.assertEqual(len(doc.paragraphs), 1)
        runs = doc.paragraphs[0].runs
        self.assertEqual(runs[0].text, "• ")
        self.assertEqual(runs[1].text, "Python")
        self.assertTrue(runs[1].bold)
        self.assertEqual(runs[2].text, ": ")
        self.assertEqual(runs[3].text, "Programming language")

    def test_add_bullets_plain(self):
        """Test adding multiple plain bullets."""
        renderer, doc = self._get_renderer()
        renderer.add_bullets(["Item 1", "Item 2", "Item 3"], plain=True, glyph="•")
        self.assertEqual(len(doc.paragraphs), 3)

    def test_bold_keywords(self):
        """Test keyword bolding in text."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Experience with Python and JavaScript",
            keywords=["Python", "JavaScript"],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        # Find the bolded runs
        bolded = [r.text for r in runs if r.bold]
        self.assertIn("Python", bolded)
        self.assertIn("JavaScript", bolded)


@patch.dict("sys.modules", {
    "docx": MagicMock(),
    "docx.shared": MagicMock(),
    "docx.enum.text": MagicMock(),
    "docx.oxml": MagicMock(),
    "docx.oxml.ns": MagicMock(),
})
class TestHeaderRenderer(unittest.TestCase):
    """Tests for HeaderRenderer class."""

    def _get_renderer(self):
        from resume.docx_sections import HeaderRenderer
        doc = FakeDocument()
        return HeaderRenderer(doc), doc

    def test_add_header_line_title_only(self):
        """Test header with title only."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(title_text="Software Engineer")
        self.assertEqual(len(doc.paragraphs), 1)
        runs = doc.paragraphs[0].runs
        self.assertEqual(runs[0].text, "Software Engineer")
        self.assertTrue(runs[0].bold)

    def test_add_header_line_title_and_company(self):
        """Test header with title and company."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(title_text="Software Engineer", company_text="Acme Corp")
        runs = doc.paragraphs[0].runs
        texts = [r.text for r in runs]
        self.assertIn("Software Engineer", texts)
        self.assertIn(" at ", texts)
        self.assertIn("Acme Corp", texts)

    def test_add_header_line_with_location(self):
        """Test header with location."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(
            title_text="Engineer",
            company_text="Company",
            loc_text="New York",
        )
        runs = doc.paragraphs[0].runs
        texts = [r.text for r in runs]
        self.assertIn("New York", texts)

    def test_add_header_line_with_duration(self):
        """Test header with duration."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(
            title_text="Engineer",
            span_text="2020-2024",
        )
        runs = doc.paragraphs[0].runs
        texts = [r.text for r in runs]
        self.assertIn("2020-2024", texts)

    def test_parse_meta_pt_valid(self):
        """Test parsing valid meta_pt."""
        renderer, _ = self._get_renderer()
        result = renderer._parse_meta_pt({"meta_pt": "10"})
        self.assertEqual(result, 10.0)

    def test_parse_meta_pt_invalid(self):
        """Test parsing invalid meta_pt."""
        renderer, _ = self._get_renderer()
        result = renderer._parse_meta_pt({"meta_pt": "not-a-number"})
        self.assertIsNone(result)

    def test_parse_meta_pt_empty(self):
        """Test parsing empty meta_pt."""
        renderer, _ = self._get_renderer()
        result = renderer._parse_meta_pt({})
        self.assertIsNone(result)

    def test_add_group_title(self):
        """Test adding a group title."""
        renderer, doc = self._get_renderer()
        renderer.add_group_title("Programming Languages")
        self.assertEqual(len(doc.paragraphs), 1)
        runs = doc.paragraphs[0].runs
        self.assertEqual(runs[0].text, "Programming Languages")
        self.assertTrue(runs[0].bold)

    def test_add_group_title_empty(self):
        """Test adding empty group title returns None."""
        renderer, doc = self._get_renderer()
        result = renderer.add_group_title("")
        self.assertIsNone(result)
        self.assertEqual(len(doc.paragraphs), 0)


@patch.dict("sys.modules", {
    "docx": MagicMock(),
    "docx.shared": MagicMock(),
    "docx.enum.text": MagicMock(),
    "docx.oxml": MagicMock(),
    "docx.oxml.ns": MagicMock(),
})
class TestListSectionRenderer(unittest.TestCase):
    """Tests for ListSectionRenderer class."""

    def _get_renderer(self):
        from resume.docx_sections import ListSectionRenderer
        doc = FakeDocument()
        return ListSectionRenderer(doc), doc

    def test_extract_item_text_string(self):
        """Test extracting text from string item."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text("  Hello World  ", ("name",), None, " — ")
        self.assertEqual(result, "Hello World")

    def test_extract_item_text_dict_with_name(self):
        """Test extracting text from dict with name key."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text(
            {"name": "Python"},
            ("name", "title"),
            None,
            " — ",
        )
        self.assertEqual(result, "Python")

    def test_extract_item_text_dict_with_desc(self):
        """Test extracting text from dict with description."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text(
            {"name": "Python", "level": "Expert"},
            ("name",),
            "level",
            " — ",
        )
        self.assertEqual(result, "Python — Expert")

    def test_extract_item_text_empty(self):
        """Test extracting text from empty item."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text("", ("name",), None, " — ")
        self.assertIsNone(result)

    def test_render_simple_list(self):
        """Test rendering a simple list."""
        renderer, doc = self._get_renderer()
        items = ["Item 1", "Item 2", "Item 3"]
        result = renderer.render_simple_list(items)
        self.assertEqual(result, ["Item 1", "Item 2", "Item 3"])
        self.assertEqual(len(doc.paragraphs), 3)


@patch.dict("sys.modules", {
    "docx": MagicMock(),
    "docx.shared": MagicMock(),
    "docx.enum.text": MagicMock(),
    "docx.oxml": MagicMock(),
    "docx.oxml.ns": MagicMock(),
})
class TestSectionRenderers(unittest.TestCase):
    """Tests for specific section renderers."""

    def test_interests_renderer(self):
        """Test InterestsSectionRenderer."""
        from resume.docx_sections import InterestsSectionRenderer
        doc = FakeDocument()
        renderer = InterestsSectionRenderer(doc)
        data = {"interests": ["Reading", "Hiking", "Photography"]}
        result = renderer.render(data)
        self.assertEqual(len(result), 3)

    def test_languages_renderer(self):
        """Test LanguagesSectionRenderer."""
        from resume.docx_sections import LanguagesSectionRenderer
        doc = FakeDocument()
        renderer = LanguagesSectionRenderer(doc)
        data = {"languages": [
            {"name": "English", "level": "Native"},
            {"language": "Spanish", "level": "Fluent"},
        ]}
        result = renderer.render(data)
        self.assertEqual(len(result), 2)

    def test_coursework_renderer(self):
        """Test CourseworkSectionRenderer."""
        from resume.docx_sections import CourseworkSectionRenderer
        doc = FakeDocument()
        renderer = CourseworkSectionRenderer(doc)
        data = {"coursework": [
            {"name": "Data Structures"},
            {"course": "Algorithms"},
        ]}
        result = renderer.render(data)
        self.assertEqual(len(result), 2)

    def test_certifications_renderer(self):
        """Test CertificationsSectionRenderer."""
        from resume.docx_sections import CertificationsSectionRenderer
        doc = FakeDocument()
        renderer = CertificationsSectionRenderer(doc)
        data = {"certifications": [
            {"name": "AWS Certified", "year": "2023"},
            {"cert": "GCP Professional"},
        ]}
        result = renderer.render(data)
        self.assertEqual(len(result), 2)

    def test_presentations_renderer(self):
        """Test PresentationsSectionRenderer."""
        from resume.docx_sections import PresentationsSectionRenderer
        doc = FakeDocument()
        renderer = PresentationsSectionRenderer(doc)
        data = {"presentations": [
            {"title": "Intro to Python", "event": "PyCon", "year": "2023"},
            "Another Talk",
        ]}
        result = renderer.render(data)
        self.assertEqual(len(result), 2)


@patch.dict("sys.modules", {
    "docx": MagicMock(),
    "docx.shared": MagicMock(),
    "docx.enum.text": MagicMock(),
    "docx.oxml": MagicMock(),
    "docx.oxml.ns": MagicMock(),
})
class TestSummarySectionRenderer(unittest.TestCase):
    """Tests for SummarySectionRenderer."""

    def _get_renderer(self):
        from resume.docx_sections import SummarySectionRenderer
        doc = FakeDocument()
        return SummarySectionRenderer(doc), doc

    def test_render_string_summary(self):
        """Test rendering string summary."""
        renderer, doc = self._get_renderer()
        data = {"summary": "Experienced software engineer with 10 years of experience."}
        renderer.render(data)
        self.assertEqual(len(doc.paragraphs), 1)

    def test_render_list_summary(self):
        """Test rendering list summary."""
        renderer, doc = self._get_renderer()
        data = {"summary": ["Point 1", "Point 2", "Point 3"]}
        renderer.render(data)
        self.assertEqual(len(doc.paragraphs), 3)

    def test_render_bulleted_string(self):
        """Test rendering bulleted string summary."""
        renderer, doc = self._get_renderer()
        data = {"summary": "First point. Second point. Third point."}
        renderer.render(data, sec={"bulleted": True})
        self.assertEqual(len(doc.paragraphs), 3)

    def test_render_with_keywords(self):
        """Test rendering with keyword highlighting."""
        renderer, doc = self._get_renderer()
        data = {"summary": "Expert in Python and JavaScript development."}
        renderer.render(data, keywords=["Python", "JavaScript"])
        self.assertEqual(len(doc.paragraphs), 1)

    def test_normalize_list_items_dicts(self):
        """Test normalizing list items from dicts."""
        renderer, _ = self._get_renderer()
        items = [
            {"text": "Item 1"},
            {"line": "Item 2"},
            {"desc": "Item 3"},
        ]
        result = renderer._normalize_list_items(items)
        self.assertEqual(result, ["Item 1", "Item 2", "Item 3"])

    def test_normalize_list_items_strings(self):
        """Test normalizing list items from strings."""
        renderer, _ = self._get_renderer()
        items = ["Item 1", "Item 2", "Item 3"]
        result = renderer._normalize_list_items(items)
        self.assertEqual(result, ["Item 1", "Item 2", "Item 3"])


@patch.dict("sys.modules", {
    "docx": MagicMock(),
    "docx.shared": MagicMock(),
    "docx.enum.text": MagicMock(),
    "docx.oxml": MagicMock(),
    "docx.oxml.ns": MagicMock(),
})
class TestSkillsSectionRenderer(unittest.TestCase):
    """Tests for SkillsSectionRenderer."""

    def _get_renderer(self):
        from resume.docx_sections import SkillsSectionRenderer
        doc = FakeDocument()
        return SkillsSectionRenderer(doc), doc

    def test_render_flat_skills(self):
        """Test rendering flat skills list."""
        renderer, doc = self._get_renderer()
        data = {"skills": ["Python", "JavaScript", "Go"]}
        renderer.render(data)
        self.assertGreater(len(doc.paragraphs), 0)

    def test_render_skills_groups(self):
        """Test rendering skills groups."""
        renderer, doc = self._get_renderer()
        data = {"skills_groups": [
            {"title": "Languages", "items": ["Python", "Go"]},
            {"title": "Frameworks", "items": ["Django", "Flask"]},
        ]}
        renderer.render(data)
        self.assertGreater(len(doc.paragraphs), 0)

    def test_normalize_group_items_strings(self):
        """Test normalizing group items from strings."""
        renderer, _ = self._get_renderer()
        items = ["Python", "JavaScript", "Go"]
        result = renderer._normalize_group_items(items, False, " — ")
        self.assertEqual(result, ["Python", "JavaScript", "Go"])

    def test_normalize_group_items_dicts(self):
        """Test normalizing group items from dicts."""
        renderer, _ = self._get_renderer()
        items = [
            {"name": "Python", "desc": "Expert"},
            {"title": "Go", "description": "Intermediate"},
        ]
        result = renderer._normalize_group_items(items, True, " — ")
        self.assertEqual(len(result), 2)
        self.assertIn("Python — Expert", result)


@patch.dict("sys.modules", {
    "docx": MagicMock(),
    "docx.shared": MagicMock(),
    "docx.enum.text": MagicMock(),
    "docx.oxml": MagicMock(),
    "docx.oxml.ns": MagicMock(),
})
class TestExperienceSectionRenderer(unittest.TestCase):
    """Tests for ExperienceSectionRenderer."""

    def _get_renderer(self):
        from resume.docx_sections import ExperienceSectionRenderer
        doc = FakeDocument()
        return ExperienceSectionRenderer(doc), doc

    def test_render_experience(self):
        """Test rendering experience entries."""
        renderer, doc = self._get_renderer()
        data = {"experience": [
            {
                "title": "Senior Engineer",
                "company": "Tech Corp",
                "start": "2020",
                "end": "Present",
                "bullets": ["Led team of 5", "Shipped product"],
            }
        ]}
        renderer.render(data)
        self.assertGreater(len(doc.paragraphs), 0)

    def test_format_date_span_start_end(self):
        """Test formatting date span with start and end."""
        renderer, _ = self._get_renderer()
        e = {"start": "2020", "end": "2024"}
        result = renderer._format_date_span(e)
        self.assertEqual(result, "2020 – 2024")

    def test_format_date_span_start_only(self):
        """Test formatting date span with start only."""
        renderer, _ = self._get_renderer()
        e = {"start": "2020"}
        result = renderer._format_date_span(e)
        self.assertEqual(result, "2020 – Present")

    def test_format_date_span_end_only(self):
        """Test formatting date span with end only."""
        renderer, _ = self._get_renderer()
        e = {"end": "2024"}
        result = renderer._format_date_span(e)
        self.assertEqual(result, "2024")

    def test_normalize_present(self):
        """Test normalizing present variants."""
        renderer, _ = self._get_renderer()
        self.assertEqual(renderer._normalize_present("present"), "Present")
        self.assertEqual(renderer._normalize_present("current"), "Present")
        self.assertEqual(renderer._normalize_present("now"), "Present")
        self.assertEqual(renderer._normalize_present("2024"), "2024")

    def test_calculate_bullet_limit_no_recency(self):
        """Test bullet limit without recency rules."""
        renderer, _ = self._get_renderer()
        result = renderer._calculate_bullet_limit(0, 10, 0, 5, 3)
        self.assertEqual(result, 10)

    def test_calculate_bullet_limit_recent_role(self):
        """Test bullet limit for recent roles."""
        renderer, _ = self._get_renderer()
        result = renderer._calculate_bullet_limit(0, 10, 2, 5, 3)
        self.assertEqual(result, 5)

    def test_calculate_bullet_limit_prior_role(self):
        """Test bullet limit for prior roles."""
        renderer, _ = self._get_renderer()
        result = renderer._calculate_bullet_limit(2, 10, 2, 5, 3)
        self.assertEqual(result, 3)

    def test_normalize_bullets_strings(self):
        """Test normalizing bullet strings."""
        renderer, _ = self._get_renderer()
        bullets = ["Point 1", "Point 2", "Point 3"]
        result = renderer._normalize_bullets(bullets, 10)
        self.assertEqual(len(result), 3)

    def test_normalize_bullets_dicts(self):
        """Test normalizing bullet dicts."""
        renderer, _ = self._get_renderer()
        bullets = [
            {"text": "Point 1"},
            {"line": "Point 2"},
            {"name": "Point 3"},
        ]
        result = renderer._normalize_bullets(bullets, 10)
        self.assertEqual(len(result), 3)

    def test_normalize_bullets_limit(self):
        """Test bullet limit enforcement."""
        renderer, _ = self._get_renderer()
        bullets = ["Point 1", "Point 2", "Point 3", "Point 4", "Point 5"]
        result = renderer._normalize_bullets(bullets, 3)
        self.assertEqual(len(result), 3)


@patch.dict("sys.modules", {
    "docx": MagicMock(),
    "docx.shared": MagicMock(),
    "docx.enum.text": MagicMock(),
    "docx.oxml": MagicMock(),
    "docx.oxml.ns": MagicMock(),
})
class TestEducationSectionRenderer(unittest.TestCase):
    """Tests for EducationSectionRenderer."""

    def _get_renderer(self):
        from resume.docx_sections import EducationSectionRenderer
        doc = FakeDocument()
        return EducationSectionRenderer(doc), doc

    def test_render_education(self):
        """Test rendering education entries."""
        renderer, doc = self._get_renderer()
        data = {"education": [
            {
                "degree": "B.S. Computer Science",
                "institution": "MIT",
                "year": "2020",
            },
            {
                "degree": "M.S. Data Science",
                "institution": "Stanford",
                "year": "2022",
            },
        ]}
        renderer.render(data)
        self.assertEqual(len(doc.paragraphs), 2)

    def test_render_education_empty(self):
        """Test rendering with no education."""
        renderer, doc = self._get_renderer()
        data = {"education": []}
        renderer.render(data)
        self.assertEqual(len(doc.paragraphs), 0)


@patch.dict("sys.modules", {
    "docx": MagicMock(),
    "docx.shared": MagicMock(),
    "docx.enum.text": MagicMock(),
    "docx.oxml": MagicMock(),
    "docx.oxml.ns": MagicMock(),
})
class TestTechnologiesSectionRenderer(unittest.TestCase):
    """Tests for TechnologiesSectionRenderer."""

    def _get_renderer(self):
        from resume.docx_sections import TechnologiesSectionRenderer
        doc = FakeDocument()
        return TechnologiesSectionRenderer(doc), doc

    def test_render_technologies(self):
        """Test rendering technologies."""
        renderer, doc = self._get_renderer()
        data = {"technologies": ["Docker", "Kubernetes", "AWS"]}
        renderer.render(data)
        self.assertGreater(len(doc.paragraphs), 0)

    def test_collect_tech_items_list(self):
        """Test collecting tech items from list."""
        renderer, _ = self._get_renderer()
        data = {"technologies": ["Docker", "K8s"]}
        result = renderer._collect_tech_items(data, None)
        self.assertEqual(result, ["Docker", "K8s"])

    def test_collect_tech_items_dicts(self):
        """Test collecting tech items from dicts."""
        renderer, _ = self._get_renderer()
        data = {"technologies": [
            {"name": "Docker"},
            {"title": "Kubernetes"},
        ]}
        result = renderer._collect_tech_items(data, None)
        self.assertEqual(len(result), 2)

    def test_fallback_to_skills_groups(self):
        """Test fallback to skills_groups for tech items."""
        renderer, _ = self._get_renderer()
        data = {
            "technologies": [],
            "skills_groups": [
                {"title": "Technologies", "items": ["Docker", "K8s"]},
            ],
        }
        result = renderer._collect_tech_items(data, None)
        self.assertEqual(result, ["Docker", "K8s"])


if __name__ == "__main__":
    unittest.main()
