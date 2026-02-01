"""Tests for resume/docx_sections.py section renderers."""
from __future__ import annotations

import unittest

from tests.resume_tests.fixtures import make_fake_renderer, mock_docx_modules


@mock_docx_modules
class TestBulletRenderer(unittest.TestCase):
    """Tests for BulletRenderer class."""

    def _get_renderer(self):
        from resume.docx_sections import BulletRenderer
        return make_fake_renderer(BulletRenderer)

    def test_get_bullet_config_defaults(self):
        """Test default bullet config."""
        renderer, _ = self._get_renderer()
        _, glyph = renderer.get_bullet_config(None)
        self.assertEqual(glyph, "•")

    def test_get_bullet_config_custom_glyph(self):
        """Test custom glyph from section config."""
        renderer, _ = self._get_renderer()
        sec = {"bullets": {"glyph": "→"}}
        _, glyph = renderer.get_bullet_config(sec)
        self.assertEqual(glyph, "→")

    def test_get_bullet_config_plain_style(self):
        """Test plain bullet style."""
        renderer, _ = self._get_renderer()
        sec = {"bullets": {"style": "plain"}}
        plain, _ = renderer.get_bullet_config(sec)
        self.assertTrue(plain)

    def test_get_bullet_config_plain_bullets_flag(self):
        """Test plain_bullets flag."""
        renderer, _ = self._get_renderer()
        sec = {"plain_bullets": True}
        plain, _ = renderer.get_bullet_config(sec)
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

    def test_bold_keywords_overlapping(self):
        """Test keyword bolding with overlapping keywords.

        Note: When keywords overlap (e.g., "Python" within "Pythonic"),
        the algorithm matches the first occurrence it finds, which may
        consume characters needed for a longer match.
        """
        renderer, doc = self._get_renderer()
        # "Python" appears both standalone and within "Pythonic"
        renderer.add_bullet_line(
            "Expert in Python and Pythonic code",
            keywords=["Python", "Pythonic"],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        bolded = [r.text for r in runs if r.bold]
        # "Python" matches in both locations (including within "Pythonic")
        # This documents current behavior - not ideal, but consistent
        self.assertEqual(bolded.count("Python"), 2)

    def test_bold_keywords_case_insensitive(self):
        """Test keyword bolding is case-insensitive."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Developed with PYTHON and javascript frameworks",
            keywords=["Python", "JavaScript"],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        # Should match case-insensitively
        bolded = [r.text for r in runs if r.bold]
        self.assertIn("PYTHON", bolded)
        self.assertIn("javascript", bolded)

    def test_bold_keywords_empty_list(self):
        """Test keyword bolding with empty keyword list."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Experience with Python",
            keywords=[],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        # With no keywords, text should not be bolded
        bolded = [r.text for r in runs if r.bold]
        self.assertEqual(len(bolded), 0)

    def test_bold_keywords_none_in_list(self):
        """Test keyword bolding handles None in keyword list."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Experience with Python",
            keywords=["Python", None, ""],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        # Should still bold Python, ignore None/empty
        bolded = [r.text for r in runs if r.bold]
        self.assertIn("Python", bolded)


@mock_docx_modules
class TestHeaderRenderer(unittest.TestCase):
    """Tests for HeaderRenderer class."""

    def _get_renderer(self):
        from resume.docx_sections import HeaderRenderer
        return make_fake_renderer(HeaderRenderer)

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


@mock_docx_modules
class TestListSectionRenderer(unittest.TestCase):
    """Tests for ListSectionRenderer class."""

    def _get_renderer(self):
        from resume.docx_sections import ListSectionRenderer
        return make_fake_renderer(ListSectionRenderer)

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


@mock_docx_modules
class TestSectionRenderers(unittest.TestCase):
    """Tests for specific section renderers."""

    def test_interests_renderer(self):
        """Test InterestsSectionRenderer."""
        from resume.docx_sections import InterestsSectionRenderer
        renderer, _ = make_fake_renderer(InterestsSectionRenderer)
        data = {"interests": ["Reading", "Hiking", "Photography"]}
        result = renderer.render(data)
        self.assertEqual(len(result), 3)

    def test_languages_renderer(self):
        """Test LanguagesSectionRenderer."""
        from resume.docx_sections import LanguagesSectionRenderer
        renderer, _ = make_fake_renderer(LanguagesSectionRenderer)
        data = {"languages": [
            {"name": "English", "level": "Native"},
            {"language": "Spanish", "level": "Fluent"},
        ]}
        result = renderer.render(data)
        self.assertEqual(len(result), 2)

    def test_coursework_renderer(self):
        """Test CourseworkSectionRenderer."""
        from resume.docx_sections import CourseworkSectionRenderer
        renderer, _ = make_fake_renderer(CourseworkSectionRenderer)
        data = {"coursework": [
            {"name": "Data Structures"},
            {"course": "Algorithms"},
        ]}
        result = renderer.render(data)
        self.assertEqual(len(result), 2)

    def test_certifications_renderer(self):
        """Test CertificationsSectionRenderer."""
        from resume.docx_sections import CertificationsSectionRenderer
        renderer, _ = make_fake_renderer(CertificationsSectionRenderer)
        data = {"certifications": [
            {"name": "AWS Certified", "year": "2023"},
            {"cert": "GCP Professional"},
        ]}
        result = renderer.render(data)
        self.assertEqual(len(result), 2)

    def test_presentations_renderer(self):
        """Test PresentationsSectionRenderer."""
        from resume.docx_sections import PresentationsSectionRenderer
        renderer, _ = make_fake_renderer(PresentationsSectionRenderer)
        data = {"presentations": [
            {"title": "Intro to Python", "event": "PyCon", "year": "2023"},
            "Another Talk",
        ]}
        result = renderer.render(data)
        self.assertEqual(len(result), 2)

    def test_teaching_renderer(self):
        """Test TeachingSectionRenderer."""
        from resume.docx_sections import TeachingSectionRenderer
        renderer, _ = make_fake_renderer(TeachingSectionRenderer)
        data = {"teaching": ["Course 1", "Course 2"]}
        result = renderer.render(data)
        self.assertEqual(len(result), 2)

    def test_teaching_renderer_empty(self):
        """Test TeachingSectionRenderer with no data."""
        from resume.docx_sections import TeachingSectionRenderer
        renderer, _ = make_fake_renderer(TeachingSectionRenderer)
        data = {}
        result = renderer.render(data)
        self.assertEqual(len(result), 0)


@mock_docx_modules
class TestPresentationsSectionRenderer(unittest.TestCase):
    """Tests for PresentationsSectionRenderer edge cases."""

    def _get_renderer(self):
        from resume.docx_sections import PresentationsSectionRenderer
        return make_fake_renderer(PresentationsSectionRenderer)

    def test_render_with_bullets(self):
        """Test rendering presentations with bullets (lines 101-105)."""
        renderer, doc = self._get_renderer()
        data = {"presentations": [
            {"title": "Talk 1", "event": "Conference A"},
            {"title": "Talk 2", "event": "Conference B"},
        ]}
        sec = {"bullets": {"style": "plain", "glyph": "→"}}
        result = renderer.render(data, sec)
        self.assertEqual(len(result), 2)
        # Should have bullet paragraphs
        self.assertGreater(len(doc.paragraphs), 0)

    def test_render_empty_presentations(self):
        """Test rendering with empty presentations list."""
        renderer, doc = self._get_renderer()
        data = {"presentations": []}
        result = renderer.render(data)
        self.assertEqual(len(result), 0)

    def test_format_dict_with_link(self):
        """Test formatting presentation with link (line 139)."""
        renderer, _ = self._get_renderer()
        item = {
            "title": "My Talk",
            "event": "PyCon",
            "year": "2023",
            "link": "https://example.com/talk"
        }
        result = renderer._format_presentation_item(item)
        self.assertIn("My Talk", result)
        self.assertIn("https://example.com/talk", result)
        self.assertIn("(https://example.com/talk)", result)

    def test_format_dict_link_only(self):
        """Test link-only presentation (edge case for line 139)."""
        renderer, _ = self._get_renderer()
        item = {"link": "https://example.com/video"}
        result = renderer._format_presentation_item(item)
        self.assertEqual(result, "https://example.com/video")

    def test_format_dict_no_title_has_event(self):
        """Test presentation with event but no title."""
        renderer, _ = self._get_renderer()
        item = {"event": "Tech Conference", "year": "2024"}
        result = renderer._format_presentation_item(item)
        self.assertIn("Tech Conference", result)
        self.assertIn("2024", result)

    def test_format_empty_presentation(self):
        """Test formatting empty presentation item."""
        renderer, _ = self._get_renderer()
        result = renderer._format_presentation_item({})
        self.assertEqual(result, "")

    def test_format_string_presentation(self):
        """Test formatting string presentation."""
        renderer, _ = self._get_renderer()
        result = renderer._format_string_presentation("  My Talk Title  ")
        self.assertEqual(result, "My Talk Title")

    def test_format_string_empty(self):
        """Test formatting empty string presentation."""
        renderer, _ = self._get_renderer()
        result = renderer._format_string_presentation("")
        self.assertEqual(result, "")


@mock_docx_modules
class TestSummarySectionRenderer(unittest.TestCase):
    """Tests for SummarySectionRenderer."""

    def _get_renderer(self):
        from resume.docx_sections import SummarySectionRenderer
        return make_fake_renderer(SummarySectionRenderer)

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

    def test_render_list_summary_empty_items(self):
        """Test rendering list summary with empty items (lines 160-166)."""
        renderer, doc = self._get_renderer()
        data = {"summary": []}
        sec = {"bullets": {"style": "plain"}}
        renderer.render(data, sec)
        # Empty list should not create paragraphs
        self.assertEqual(len(doc.paragraphs), 0)

    def test_render_list_summary_with_keywords(self):
        """Test rendering list summary with keywords (lines 160-165)."""
        renderer, doc = self._get_renderer()
        data = {"summary": ["Expert in Python", "Proficient in Go"]}
        keywords = ["Python", "Go"]
        sec = {"bullets": {"style": "plain"}}
        renderer.render(data, sec, keywords=keywords)
        self.assertEqual(len(doc.paragraphs), 2)

    def test_render_bulleted_string_with_max_sentences(self):
        """Test bulleted string with max_sentences limit (lines 191-196)."""
        renderer, doc = self._get_renderer()
        data = {"summary": "First sentence. Second sentence. Third sentence. Fourth sentence."}
        sec = {"bulleted": True, "max_sentences": 2}
        renderer.render(data, sec)
        # Should only render first 2 sentences
        self.assertEqual(len(doc.paragraphs), 2)

    def test_render_bulleted_string_invalid_max_sentences(self):
        """Test bulleted string with invalid max_sentences (lines 191-194)."""
        renderer, doc = self._get_renderer()
        data = {"summary": "First. Second. Third."}
        sec = {"bulleted": True, "max_sentences": "not-a-number"}
        renderer.render(data, sec)
        # Should render all when max_sentences is invalid
        self.assertEqual(len(doc.paragraphs), 3)

    def test_render_string_summary_with_keywords(self):
        """Test non-bulleted string summary with keywords (lines 203-208)."""
        renderer, doc = self._get_renderer()
        data = {"summary": "Expert in Python and JavaScript development"}
        renderer.render(data, sec={"bulleted": False}, keywords=["Python", "JavaScript"])
        self.assertEqual(len(doc.paragraphs), 1)

    def test_render_string_summary_no_keywords(self):
        """Test non-bulleted string without keywords (lines 207-208)."""
        renderer, doc = self._get_renderer()
        data = {"summary": "General software development experience"}
        renderer.render(data, sec={"bulleted": False})
        self.assertEqual(len(doc.paragraphs), 1)

    def test_render_from_headline(self):
        """Test using headline when summary not present."""
        renderer, doc = self._get_renderer()
        data = {"headline": "Senior Software Engineer"}
        renderer.render(data)
        self.assertEqual(len(doc.paragraphs), 1)


@mock_docx_modules
class TestSkillsSectionRenderer(unittest.TestCase):
    """Tests for SkillsSectionRenderer."""

    def _get_renderer(self):
        from resume.docx_sections import SkillsSectionRenderer
        return make_fake_renderer(SkillsSectionRenderer)

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

    def test_render_groups_as_bullets(self):
        """Test rendering skills groups as bullets (lines 229-252)."""
        renderer, doc = self._get_renderer()
        data = {"skills_groups": [
            {"title": "Languages", "items": ["Python", "Go"]},
            {"title": "Tools", "items": ["Docker", "K8s"]},
        ]}
        sec = {"bullets": True}
        renderer.render(data, sec)
        self.assertGreater(len(doc.paragraphs), 0)

    def test_render_groups_with_max_groups(self):
        """Test max_groups limit (line 241)."""
        renderer, doc = self._get_renderer()
        data = {"skills_groups": [
            {"title": "Group 1", "items": ["A", "B"]},
            {"title": "Group 2", "items": ["C", "D"]},
            {"title": "Group 3", "items": ["E", "F"]},
        ]}
        sec = {"max_groups": 2}
        renderer.render(data, sec)
        # Should only process first 2 groups
        self.assertGreater(len(doc.paragraphs), 0)

    def test_render_groups_with_max_items_per_group(self):
        """Test max_items_per_group limit (line 244)."""
        renderer, doc = self._get_renderer()
        data = {"skills_groups": [
            {"title": "Languages", "items": ["Python", "Go", "Rust", "Java"]},
        ]}
        sec = {"max_items_per_group": 2}
        renderer.render(data, sec)
        self.assertGreater(len(doc.paragraphs), 0)

    def test_render_groups_skip_empty(self):
        """Test skipping groups with no items (lines 246-247)."""
        renderer, doc = self._get_renderer()
        data = {"skills_groups": [
            {"title": "Empty", "items": []},
            {"title": "Has Items", "items": ["Python"]},
        ]}
        renderer.render(data)
        # Should skip empty group
        self.assertGreater(len(doc.paragraphs), 0)

    def test_render_groups_inline_with_title(self):
        """Test inline rendering with title (lines 290-300)."""
        renderer, doc = self._get_renderer()
        data = {"skills_groups": [
            {"title": "Languages", "items": ["Python", "Go"]},
        ]}
        sec = {"bullets": False, "compact": True}
        renderer.render(data, sec)
        self.assertEqual(len(doc.paragraphs), 1)

    def test_render_groups_inline_no_title(self):
        """Test inline rendering without title (line 298)."""
        renderer, doc = self._get_renderer()
        data = {"skills_groups": [
            {"title": "", "items": ["Python", "Go"]},
        ]}
        sec = {"bullets": False, "compact": True}
        renderer.render(data, sec)
        self.assertEqual(len(doc.paragraphs), 1)

    def test_render_groups_non_compact(self):
        """Test non-compact inline rendering (lines 296-298)."""
        renderer, doc = self._get_renderer()
        data = {"skills_groups": [
            {"title": "Languages", "items": ["Python", "Go"]},
        ]}
        sec = {"bullets": False, "compact": False}
        renderer.render(data, sec)
        self.assertEqual(len(doc.paragraphs), 1)

    def test_render_bullet_items_with_desc_separator(self):
        """Test bullet items with desc separator (lines 273-288)."""
        renderer, doc = self._get_renderer()
        items = ["Python: Expert", "Go: Intermediate"]
        cfg = {"bullets": {"style": "plain"}, "show_desc": True, "desc_separator": ": "}
        renderer._render_bullet_items(items, cfg)
        self.assertGreater(len(doc.paragraphs), 0)

    def test_render_bullet_items_plain_no_desc(self):
        """Test plain bullets without desc (lines 282-283)."""
        renderer, doc = self._get_renderer()
        items = ["Python", "Go"]
        cfg = {"bullets": {"style": "plain"}}
        renderer._render_bullet_items(items, cfg)
        self.assertEqual(len(doc.paragraphs), 2)

    def test_render_bullet_items_non_plain(self):
        """Test non-plain bullet style (lines 285-288)."""
        renderer, doc = self._get_renderer()
        items = ["Python", "Go"]
        cfg = {}  # Non-plain bullets
        renderer._render_bullet_items(items, cfg)
        self.assertGreater(len(doc.paragraphs), 0)

    def test_render_flat_skills_with_max_items(self):
        """Test flat skills with max_items limit (lines 302-313)."""
        renderer, doc = self._get_renderer()
        skills = ["Python", "Go", "Rust", "Java", "C++"]
        cfg = {"max_items": 3}
        renderer._render_flat_skills(skills, cfg)
        self.assertGreater(len(doc.paragraphs), 0)

    def test_render_flat_skills_non_bullets(self):
        """Test flat skills inline rendering (lines 312-313)."""
        renderer, doc = self._get_renderer()
        skills = ["Python", "Go", "Rust"]
        cfg = {"bullets": False}
        renderer._render_flat_skills(skills, cfg)
        self.assertEqual(len(doc.paragraphs), 1)


@mock_docx_modules
class TestExperienceSectionRenderer(unittest.TestCase):
    """Tests for ExperienceSectionRenderer."""

    def _get_renderer(self):
        from resume.docx_sections import ExperienceSectionRenderer
        return make_fake_renderer(ExperienceSectionRenderer)

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

    def test_render_experience_with_recency_limits(self):
        """Test experience rendering with recency-based bullet limits (lines 414-428)."""
        renderer, doc = self._get_renderer()
        data = {"experience": [
            {
                "title": "Senior Engineer",
                "company": "Recent Corp",
                "start": "2023",
                "bullets": ["A", "B", "C", "D", "E"],
            },
            {
                "title": "Mid Engineer",
                "company": "Recent Corp",
                "start": "2021",
                "bullets": ["F", "G", "H", "I"],
            },
            {
                "title": "Junior Engineer",
                "company": "Old Corp",
                "start": "2018",
                "bullets": ["J", "K", "L"],
            },
        ]}
        sec = {
            "recent_roles_count": 2,
            "recent_max_bullets": 3,
            "prior_max_bullets": 1,
        }
        renderer.render(data, sec)
        self.assertGreater(len(doc.paragraphs), 0)

    def test_render_experience_custom_styles(self):
        """Test experience with custom role and bullet styles (lines 411-412, 422-423)."""
        renderer, doc = self._get_renderer()
        data = {"experience": [
            {
                "title": "Engineer",
                "company": "Corp",
                "bullets": ["Task 1"],
            }
        ]}
        sec = {
            "role_style": "Heading 2",
            "bullet_style": "Custom Bullet",
        }
        renderer.render(data, sec)
        self.assertGreater(len(doc.paragraphs), 0)

    def test_render_experience_with_location(self):
        """Test experience entry with location."""
        renderer, doc = self._get_renderer()
        data = {"experience": [
            {
                "title": "Engineer",
                "company": "Corp",
                "location": "San Francisco, CA",
                "start": "2020",
            }
        ]}
        renderer.render(data)
        self.assertGreater(len(doc.paragraphs), 0)

    def test_render_experience_no_title_or_company(self):
        """Test experience entry without title or company (line 450)."""
        renderer, doc = self._get_renderer()
        data = {"experience": [
            {
                "bullets": ["Just some bullets"],
            }
        ]}
        renderer.render(data)
        # Should still render bullets even without header
        self.assertGreater(len(doc.paragraphs), 0)

    def test_render_experience_with_keywords(self):
        """Test experience rendering with keyword highlighting (lines 469-471)."""
        renderer, doc = self._get_renderer()
        data = {"experience": [
            {
                "title": "Python Developer",
                "bullets": ["Developed Python applications"],
            }
        ]}
        renderer.render(data, keywords=["Python"])
        self.assertGreater(len(doc.paragraphs), 0)

    def test_format_date_span_empty(self):
        """Test formatting empty date span (line 484)."""
        renderer, _ = self._get_renderer()
        e = {}
        result = renderer._format_date_span(e)
        self.assertEqual(result, "")

    def test_format_date_span_empty_strings(self):
        """Test formatting with empty string dates."""
        renderer, _ = self._get_renderer()
        e = {"start": "", "end": ""}
        result = renderer._format_date_span(e)
        self.assertEqual(result, "")

    def test_normalize_bullets_empty_dict_fields(self):
        """Test normalizing bullets with empty dict fields."""
        renderer, _ = self._get_renderer()
        bullets = [
            {"text": ""},
            {"line": "Valid point"},
            {},
        ]
        result = renderer._normalize_bullets(bullets, 10)
        # Should only include the valid one
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "Valid point")


@mock_docx_modules
class TestEducationSectionRenderer(unittest.TestCase):
    """Tests for EducationSectionRenderer."""

    def _get_renderer(self):
        from resume.docx_sections import EducationSectionRenderer
        return make_fake_renderer(EducationSectionRenderer)

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


@mock_docx_modules
class TestTechnologiesSectionRenderer(unittest.TestCase):
    """Tests for TechnologiesSectionRenderer."""

    def _get_renderer(self):
        from resume.docx_sections import TechnologiesSectionRenderer
        return make_fake_renderer(TechnologiesSectionRenderer)

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

    def test_render_technologies_with_max_items(self):
        """Test rendering technologies with max_items limit (lines 325-330)."""
        renderer, doc = self._get_renderer()
        data = {"technologies": ["Docker", "K8s", "AWS", "GCP", "Azure"]}
        sec = {"max_items": 3}
        renderer.render(data, sec)
        self.assertGreater(len(doc.paragraphs), 0)

    def test_render_technologies_invalid_max_items(self):
        """Test with invalid max_items value (lines 326-328)."""
        renderer, doc = self._get_renderer()
        data = {"technologies": ["Docker", "K8s"]}
        sec = {"max_items": "invalid"}
        renderer.render(data, sec)
        self.assertGreater(len(doc.paragraphs), 0)

    def test_render_technologies_non_bullets(self):
        """Test inline technologies rendering (lines 338-339)."""
        renderer, doc = self._get_renderer()
        data = {"technologies": ["Docker", "K8s", "AWS"]}
        sec = {"bullets": False}
        renderer.render(data, sec)
        self.assertEqual(len(doc.paragraphs), 1)

    def test_normalize_tech_item_with_desc(self):
        """Test normalizing tech item with description (line 371)."""
        renderer, _ = self._get_renderer()
        item = {"name": "Docker", "desc": "Container platform"}
        result = renderer._normalize_tech_item(item, show_desc=True, desc_sep=": ")
        self.assertEqual(result, "Docker: Container platform")

    def test_normalize_tech_item_no_desc(self):
        """Test normalizing tech item without showing description."""
        renderer, _ = self._get_renderer()
        item = {"name": "Docker", "desc": "Container platform"}
        result = renderer._normalize_tech_item(item, show_desc=False, desc_sep=": ")
        self.assertEqual(result, "Docker")

    def test_normalize_tech_item_string(self):
        """Test normalizing string tech item."""
        renderer, _ = self._get_renderer()
        result = renderer._normalize_tech_item("Docker", show_desc=False, desc_sep=": ")
        self.assertEqual(result, "Docker")

    def test_extract_from_skills_groups_multiple_groups(self):
        """Test extracting from skills_groups with multiple tech groups (lines 382-391)."""
        renderer, _ = self._get_renderer()
        data = {
            "skills_groups": [
                {"title": "Languages", "items": ["Python", "Go"]},
                {"title": "Technologies", "items": ["Docker", "K8s"]},
                {"title": "Tools", "items": ["Git", "VSCode"]},
            ]
        }
        result = renderer._extract_from_skills_groups(data, show_desc=False, desc_sep=": ")
        # Should extract from "Technologies" group and break
        self.assertEqual(result, ["Docker", "K8s"])

    def test_extract_from_skills_groups_tooling_title(self):
        """Test extraction with 'tooling' title variant (lines 379-390)."""
        renderer, _ = self._get_renderer()
        data = {
            "skills_groups": [
                {"title": "Tooling", "items": ["Git", "Docker"]},
            ]
        }
        result = renderer._extract_from_skills_groups(data, show_desc=False, desc_sep=": ")
        self.assertEqual(result, ["Git", "Docker"])

    def test_extract_from_skills_groups_no_match(self):
        """Test extraction when no tech-related groups found."""
        renderer, _ = self._get_renderer()
        data = {
            "skills_groups": [
                {"title": "Languages", "items": ["Python", "Go"]},
            ]
        }
        result = renderer._extract_from_skills_groups(data, show_desc=False, desc_sep=": ")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
