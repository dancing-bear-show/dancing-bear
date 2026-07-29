"""Basic docx renderer tests: BulletRenderer, HeaderRenderer, ListSectionRenderer, misc."""
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
        _plain, glyph = renderer.get_bullet_config(None)
        self.assertEqual(glyph, "•")

    def test_get_bullet_config_custom_glyph(self):
        """Test custom glyph from section config."""
        renderer, _ = self._get_renderer()
        sec = {"bullets": {"glyph": "→"}}
        _plain, glyph = renderer.get_bullet_config(sec)
        self.assertEqual(glyph, "→")

    def test_get_bullet_config_plain_style(self):
        """Test plain bullet style."""
        renderer, _ = self._get_renderer()
        sec = {"bullets": {"style": "plain"}}
        plain, _glyph = renderer.get_bullet_config(sec)
        self.assertTrue(plain)

    def test_get_bullet_config_plain_bullets_flag(self):
        """Test plain_bullets flag."""
        renderer, _ = self._get_renderer()
        sec = {"plain_bullets": True}
        plain, _glyph = renderer.get_bullet_config(sec)
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


if __name__ == "__main__":
    unittest.main()
