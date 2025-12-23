"""Unit tests for docx_sections renderers."""

import unittest
from unittest.mock import MagicMock


class MockParagraph:
    """Mock paragraph object for testing."""

    def __init__(self):
        self.runs = []
        self.style = None
        self.paragraph_format = MagicMock()

    def add_run(self, text=""):
        run = MagicMock()
        run.text = text
        run.bold = False
        run.italic = False
        self.runs.append(run)
        return run


class MockDocument:
    """Mock document object for testing."""

    def __init__(self):
        self.paragraphs = []

    def add_paragraph(self, text="", style=None):
        p = MockParagraph()
        p.style = style
        if text:
            p.add_run(text)
        self.paragraphs.append(p)
        return p


class TestBulletRenderer(unittest.TestCase):
    """Tests for BulletRenderer class."""

    def setUp(self):
        self.doc = MockDocument()

    def test_get_bullet_config_defaults(self):
        from resume.docx_sections import BulletRenderer
        renderer = BulletRenderer(self.doc)
        plain, glyph = renderer.get_bullet_config(None)
        self.assertFalse(plain)
        self.assertEqual(glyph, "•")

    def test_get_bullet_config_plain_from_section(self):
        from resume.docx_sections import BulletRenderer
        renderer = BulletRenderer(self.doc)
        sec = {"plain_bullets": True}
        plain, glyph = renderer.get_bullet_config(sec)
        self.assertTrue(plain)

    def test_get_bullet_config_custom_glyph(self):
        from resume.docx_sections import BulletRenderer
        renderer = BulletRenderer(self.doc)
        sec = {"bullets": {"glyph": "→"}}
        plain, glyph = renderer.get_bullet_config(sec)
        self.assertEqual(glyph, "→")

    def test_get_bullet_config_from_page_cfg(self):
        from resume.docx_sections import BulletRenderer
        page_cfg = {"bullets": {"style": "plain", "glyph": "-"}}
        renderer = BulletRenderer(self.doc, page_cfg)
        plain, glyph = renderer.get_bullet_config(None)
        self.assertTrue(plain)
        self.assertEqual(glyph, "-")

    def test_add_bullet_line_creates_paragraph(self):
        from resume.docx_sections import BulletRenderer
        renderer = BulletRenderer(self.doc)
        renderer.add_bullet_line("Test bullet")
        self.assertEqual(len(self.doc.paragraphs), 1)

    def test_add_bullet_line_includes_glyph(self):
        from resume.docx_sections import BulletRenderer
        renderer = BulletRenderer(self.doc)
        p = renderer.add_bullet_line("Test bullet", glyph="*")
        self.assertEqual(p.runs[0].text, "* ")

    def test_add_named_bullet_creates_bold_name(self):
        from resume.docx_sections import BulletRenderer
        renderer = BulletRenderer(self.doc)
        p = renderer.add_named_bullet("Name", "Description")
        # Check that name run is bold
        name_run = p.runs[1]  # After glyph run
        self.assertTrue(name_run.bold)

    def test_add_bullets_plain_mode(self):
        from resume.docx_sections import BulletRenderer
        renderer = BulletRenderer(self.doc)
        renderer.add_bullets(["Item 1", "Item 2"], plain=True)
        self.assertEqual(len(self.doc.paragraphs), 2)

    def test_add_bullets_list_style_mode(self):
        from resume.docx_sections import BulletRenderer
        renderer = BulletRenderer(self.doc)
        renderer.add_bullets(["Item 1", "Item 2"], plain=False, list_style="List Bullet")
        self.assertEqual(len(self.doc.paragraphs), 2)
        self.assertEqual(self.doc.paragraphs[0].style, "List Bullet")

    def test_bold_keywords_bolds_matching_text(self):
        from resume.docx_sections import BulletRenderer
        renderer = BulletRenderer(self.doc)
        p = MockParagraph()
        renderer._bold_keywords(p, "Python and Java skills", ["Python", "Java"])
        # Should have multiple runs with some bold
        bold_runs = [r for r in p.runs if r.bold]
        self.assertGreater(len(bold_runs), 0)

    def test_bold_keywords_case_insensitive(self):
        from resume.docx_sections import BulletRenderer
        renderer = BulletRenderer(self.doc)
        p = MockParagraph()
        renderer._bold_keywords(p, "PYTHON programming", ["python"])
        bold_runs = [r for r in p.runs if r.bold]
        self.assertEqual(len(bold_runs), 1)

    def test_bold_keywords_no_match(self):
        from resume.docx_sections import BulletRenderer
        renderer = BulletRenderer(self.doc)
        p = MockParagraph()
        renderer._bold_keywords(p, "No matches here", ["xyz"])
        # When no keywords match, text is added as non-bold runs
        self.assertGreater(len(p.runs), 0)
        # None of the runs should be bold
        bold_runs = [r for r in p.runs if r.bold]
        self.assertEqual(len(bold_runs), 0)


class TestHeaderRenderer(unittest.TestCase):
    """Tests for HeaderRenderer class."""

    def setUp(self):
        self.doc = MockDocument()

    def test_add_header_line_with_title_only(self):
        from resume.docx_sections import HeaderRenderer
        renderer = HeaderRenderer(self.doc)
        p = renderer.add_header_line(title_text="Software Engineer")
        self.assertEqual(len(self.doc.paragraphs), 1)
        self.assertTrue(p.runs[0].bold)

    def test_add_header_line_with_company(self):
        from resume.docx_sections import HeaderRenderer
        renderer = HeaderRenderer(self.doc)
        p = renderer.add_header_line(title_text="Engineer", company_text="Acme Corp")
        # Should have "at" separator
        texts = [r.text for r in p.runs]
        self.assertIn(" at ", texts)

    def test_add_header_line_with_location(self):
        from resume.docx_sections import HeaderRenderer
        renderer = HeaderRenderer(self.doc)
        p = renderer.add_header_line(title_text="Engineer", loc_text="NYC")
        texts = [r.text for r in p.runs]
        self.assertIn(" — ", texts)
        self.assertIn("[", texts)
        self.assertIn("]", texts)

    def test_add_header_line_without_location_brackets(self):
        from resume.docx_sections import HeaderRenderer
        renderer = HeaderRenderer(self.doc)
        sec = {"location_brackets": False}
        p = renderer.add_header_line(title_text="Engineer", loc_text="NYC", sec=sec)
        texts = [r.text for r in p.runs]
        self.assertNotIn("[", texts)

    def test_add_header_line_with_duration(self):
        from resume.docx_sections import HeaderRenderer
        renderer = HeaderRenderer(self.doc)
        p = renderer.add_header_line(title_text="Engineer", span_text="2020-2023")
        texts = [r.text for r in p.runs]
        self.assertIn("(", texts)
        self.assertIn(")", texts)

    def test_add_group_title_returns_none_for_empty(self):
        from resume.docx_sections import HeaderRenderer
        renderer = HeaderRenderer(self.doc)
        result = renderer.add_group_title("")
        self.assertIsNone(result)

    def test_add_group_title_creates_bold_paragraph(self):
        from resume.docx_sections import HeaderRenderer
        renderer = HeaderRenderer(self.doc)
        p = renderer.add_group_title("Skills Category")
        self.assertIsNotNone(p)
        self.assertTrue(p.runs[0].bold)


class TestListSectionRenderer(unittest.TestCase):
    """Tests for ListSectionRenderer class."""

    def setUp(self):
        self.doc = MockDocument()

    def test_render_simple_list_with_strings(self):
        from resume.docx_sections import ListSectionRenderer
        renderer = ListSectionRenderer(self.doc)
        items = ["Item 1", "Item 2", "Item 3"]
        result = renderer.render_simple_list(items)
        self.assertEqual(len(result), 3)

    def test_render_simple_list_with_dicts(self):
        from resume.docx_sections import ListSectionRenderer
        renderer = ListSectionRenderer(self.doc)
        items = [{"name": "First"}, {"title": "Second"}, {"label": "Third"}]
        result = renderer.render_simple_list(items)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], "First")

    def test_render_simple_list_with_description(self):
        from resume.docx_sections import ListSectionRenderer
        renderer = ListSectionRenderer(self.doc)
        items = [{"name": "Python", "level": "Expert"}]
        result = renderer.render_simple_list(items, desc_key="level")
        self.assertIn("Expert", result[0])

    def test_render_simple_list_as_inline(self):
        from resume.docx_sections import ListSectionRenderer
        renderer = ListSectionRenderer(self.doc)
        items = ["A", "B", "C"]
        sec = {"bullets": False, "separator": ", "}
        renderer.render_simple_list(items, sec)
        self.assertEqual(len(self.doc.paragraphs), 1)

    def test_render_simple_list_skips_empty_items(self):
        from resume.docx_sections import ListSectionRenderer
        renderer = ListSectionRenderer(self.doc)
        items = ["Valid", "", "  ", {"name": ""}, "Also Valid"]
        result = renderer.render_simple_list(items)
        self.assertEqual(len(result), 2)


class TestInterestsSectionRenderer(unittest.TestCase):
    """Tests for InterestsSectionRenderer class."""

    def setUp(self):
        self.doc = MockDocument()

    def test_render_interests(self):
        from resume.docx_sections import InterestsSectionRenderer
        renderer = InterestsSectionRenderer(self.doc)
        data = {"interests": ["Hiking", "Photography", "Music"]}
        result = renderer.render(data)
        self.assertEqual(len(result), 3)


class TestLanguagesSectionRenderer(unittest.TestCase):
    """Tests for LanguagesSectionRenderer class."""

    def setUp(self):
        self.doc = MockDocument()

    def test_render_languages_with_levels(self):
        from resume.docx_sections import LanguagesSectionRenderer
        renderer = LanguagesSectionRenderer(self.doc)
        data = {"languages": [
            {"name": "English", "level": "Native"},
            {"language": "Spanish", "level": "Fluent"},
        ]}
        result = renderer.render(data)
        self.assertEqual(len(result), 2)
        self.assertIn("Native", result[0])


class TestCertificationsSectionRenderer(unittest.TestCase):
    """Tests for CertificationsSectionRenderer class."""

    def setUp(self):
        self.doc = MockDocument()

    def test_render_certifications_with_year(self):
        from resume.docx_sections import CertificationsSectionRenderer
        renderer = CertificationsSectionRenderer(self.doc)
        data = {"certifications": [{"name": "AWS Solutions Architect", "year": "2023"}]}
        result = renderer.render(data)
        self.assertEqual(len(result), 1)
        self.assertIn("2023", result[0])


class TestPresentationsSectionRenderer(unittest.TestCase):
    """Tests for PresentationsSectionRenderer class."""

    def setUp(self):
        self.doc = MockDocument()

    def test_render_presentations_with_event(self):
        from resume.docx_sections import PresentationsSectionRenderer
        renderer = PresentationsSectionRenderer(self.doc)
        data = {"presentations": [
            {"title": "My Talk", "event": "Conference 2023", "year": "2023"}
        ]}
        result = renderer.render(data)
        self.assertEqual(len(result), 1)
        self.assertIn("My Talk", result[0])
        self.assertIn("2023", result[0])

    def test_render_presentations_with_link(self):
        from resume.docx_sections import PresentationsSectionRenderer
        renderer = PresentationsSectionRenderer(self.doc)
        data = {"presentations": [
            {"title": "Talk", "link": "https://example.com"}
        ]}
        result = renderer.render(data)
        self.assertIn("https://example.com", result[0])


class TestSummarySectionRenderer(unittest.TestCase):
    """Tests for SummarySectionRenderer class."""

    def setUp(self):
        self.doc = MockDocument()

    def test_render_string_summary(self):
        from resume.docx_sections import SummarySectionRenderer
        renderer = SummarySectionRenderer(self.doc)
        data = {"summary": "Experienced engineer with 10 years of expertise."}
        renderer.render(data)
        self.assertEqual(len(self.doc.paragraphs), 1)

    def test_render_list_summary(self):
        from resume.docx_sections import SummarySectionRenderer
        renderer = SummarySectionRenderer(self.doc)
        data = {"summary": ["Point 1", "Point 2", "Point 3"]}
        renderer.render(data)
        self.assertGreater(len(self.doc.paragraphs), 0)

    def test_render_bulleted_string_summary(self):
        from resume.docx_sections import SummarySectionRenderer
        renderer = SummarySectionRenderer(self.doc)
        data = {"summary": "First point. Second point. Third point."}
        sec = {"bulleted": True}
        renderer.render(data, sec)
        self.assertGreater(len(self.doc.paragraphs), 0)

    def test_render_summary_with_max_sentences(self):
        from resume.docx_sections import SummarySectionRenderer
        renderer = SummarySectionRenderer(self.doc)
        data = {"summary": "One. Two. Three. Four. Five."}
        sec = {"bulleted": True, "max_sentences": 2}
        renderer.render(data, sec)
        # Should only render 2 sentences
        self.assertEqual(len(self.doc.paragraphs), 2)

    def test_render_headline_fallback(self):
        from resume.docx_sections import SummarySectionRenderer
        renderer = SummarySectionRenderer(self.doc)
        data = {"headline": "Software Engineer at Tech Co"}
        renderer.render(data)
        self.assertEqual(len(self.doc.paragraphs), 1)


class TestSkillsSectionRenderer(unittest.TestCase):
    """Tests for SkillsSectionRenderer class."""

    def setUp(self):
        self.doc = MockDocument()

    def test_render_flat_skills(self):
        from resume.docx_sections import SkillsSectionRenderer
        renderer = SkillsSectionRenderer(self.doc)
        data = {"skills": ["Python", "JavaScript", "Go"]}
        renderer.render(data)
        self.assertGreater(len(self.doc.paragraphs), 0)

    def test_render_skills_groups(self):
        from resume.docx_sections import SkillsSectionRenderer
        renderer = SkillsSectionRenderer(self.doc)
        data = {"skills_groups": [
            {"title": "Languages", "items": ["Python", "Java"]},
            {"title": "Frameworks", "items": ["Django", "Spring"]},
        ]}
        renderer.render(data)
        self.assertGreater(len(self.doc.paragraphs), 0)

    def test_render_skills_with_bullets(self):
        from resume.docx_sections import SkillsSectionRenderer
        renderer = SkillsSectionRenderer(self.doc)
        data = {"skills": ["Python", "JavaScript"]}
        sec = {"bullets": True}
        renderer.render(data, sec)
        self.assertGreater(len(self.doc.paragraphs), 0)

    def test_render_skills_groups_with_max(self):
        from resume.docx_sections import SkillsSectionRenderer
        renderer = SkillsSectionRenderer(self.doc)
        data = {"skills_groups": [
            {"title": "Group 1", "items": ["A", "B", "C"]},
            {"title": "Group 2", "items": ["X", "Y", "Z"]},
            {"title": "Group 3", "items": ["1", "2", "3"]},
        ]}
        sec = {"max_groups": 2}
        renderer.render(data, sec)
        # Should only render 2 groups


class TestTechnologiesSectionRenderer(unittest.TestCase):
    """Tests for TechnologiesSectionRenderer class."""

    def setUp(self):
        self.doc = MockDocument()

    def test_render_technologies(self):
        from resume.docx_sections import TechnologiesSectionRenderer
        renderer = TechnologiesSectionRenderer(self.doc)
        data = {"technologies": ["Docker", "Kubernetes", "AWS"]}
        renderer.render(data)
        self.assertGreater(len(self.doc.paragraphs), 0)

    def test_render_technologies_from_skills_groups(self):
        from resume.docx_sections import TechnologiesSectionRenderer
        renderer = TechnologiesSectionRenderer(self.doc)
        data = {"skills_groups": [
            {"title": "Technologies", "items": ["Docker", "K8s"]},
        ]}
        renderer.render(data)
        self.assertGreater(len(self.doc.paragraphs), 0)

    def test_render_technologies_with_description(self):
        from resume.docx_sections import TechnologiesSectionRenderer
        renderer = TechnologiesSectionRenderer(self.doc)
        data = {"technologies": [
            {"name": "Docker", "desc": "Container platform"},
        ]}
        sec = {"show_desc": True}
        renderer.render(data, sec)
        self.assertGreater(len(self.doc.paragraphs), 0)


class TestExperienceSectionRenderer(unittest.TestCase):
    """Tests for ExperienceSectionRenderer class."""

    def setUp(self):
        self.doc = MockDocument()

    def test_render_experience_entry(self):
        from resume.docx_sections import ExperienceSectionRenderer
        renderer = ExperienceSectionRenderer(self.doc)
        data = {"experience": [
            {
                "title": "Senior Engineer",
                "company": "Tech Corp",
                "location": "NYC",
                "start": "2020",
                "end": "Present",
                "bullets": ["Led team of 5", "Shipped major feature"],
            }
        ]}
        renderer.render(data)
        self.assertGreater(len(self.doc.paragraphs), 0)

    def test_render_experience_date_formatting(self):
        from resume.docx_sections import ExperienceSectionRenderer
        renderer = ExperienceSectionRenderer(self.doc)
        span = renderer._format_date_span({"start": "2020", "end": "2023"})
        self.assertEqual(span, "2020 – 2023")

    def test_render_experience_present_normalization(self):
        from resume.docx_sections import ExperienceSectionRenderer
        renderer = ExperienceSectionRenderer(self.doc)
        self.assertEqual(renderer._normalize_present("present"), "Present")
        self.assertEqual(renderer._normalize_present("current"), "Present")
        self.assertEqual(renderer._normalize_present("now"), "Present")
        self.assertEqual(renderer._normalize_present("2023"), "2023")

    def test_render_experience_with_max_bullets(self):
        from resume.docx_sections import ExperienceSectionRenderer
        renderer = ExperienceSectionRenderer(self.doc)
        data = {"experience": [
            {"title": "Engineer", "bullets": ["B1", "B2", "B3", "B4", "B5"]}
        ]}
        sec = {"max_bullets": 2}
        renderer.render(data, sec)

    def test_render_experience_recent_vs_prior_bullets(self):
        from resume.docx_sections import ExperienceSectionRenderer
        renderer = ExperienceSectionRenderer(self.doc)
        # Test the bullet limit calculation
        limit = renderer._calculate_bullet_limit(
            idx=0, max_bullets=10,
            recent_roles_count=2,
            recent_max_bullets=5,
            prior_max_bullets=2,
        )
        self.assertEqual(limit, 5)  # First role gets recent limit

        limit = renderer._calculate_bullet_limit(
            idx=3, max_bullets=10,
            recent_roles_count=2,
            recent_max_bullets=5,
            prior_max_bullets=2,
        )
        self.assertEqual(limit, 2)  # Later role gets prior limit

    def test_normalize_bullets_from_dicts(self):
        from resume.docx_sections import ExperienceSectionRenderer
        renderer = ExperienceSectionRenderer(self.doc)
        bullets = [
            {"text": "First bullet"},
            {"line": "Second bullet"},
            "Third bullet",
        ]
        result = renderer._normalize_bullets(bullets, 10)
        self.assertEqual(len(result), 3)


class TestEducationSectionRenderer(unittest.TestCase):
    """Tests for EducationSectionRenderer class."""

    def setUp(self):
        self.doc = MockDocument()

    def test_render_education(self):
        from resume.docx_sections import EducationSectionRenderer
        renderer = EducationSectionRenderer(self.doc)
        data = {"education": [
            {"degree": "B.S. Computer Science", "institution": "MIT", "year": "2020"}
        ]}
        renderer.render(data)
        self.assertEqual(len(self.doc.paragraphs), 1)

    def test_render_multiple_education_entries(self):
        from resume.docx_sections import EducationSectionRenderer
        renderer = EducationSectionRenderer(self.doc)
        data = {"education": [
            {"degree": "M.S.", "institution": "Stanford"},
            {"degree": "B.S.", "institution": "MIT"},
        ]}
        renderer.render(data)
        self.assertEqual(len(self.doc.paragraphs), 2)

    def test_render_education_partial_data(self):
        from resume.docx_sections import EducationSectionRenderer
        renderer = EducationSectionRenderer(self.doc)
        data = {"education": [{"institution": "Harvard"}]}
        renderer.render(data)
        self.assertEqual(len(self.doc.paragraphs), 1)


class TestCourseworkSectionRenderer(unittest.TestCase):
    """Tests for CourseworkSectionRenderer class."""

    def setUp(self):
        self.doc = MockDocument()

    def test_render_coursework(self):
        from resume.docx_sections import CourseworkSectionRenderer
        renderer = CourseworkSectionRenderer(self.doc)
        data = {"coursework": [
            {"name": "Machine Learning", "desc": "Graduate level"},
            "Data Structures",
        ]}
        result = renderer.render(data)
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
