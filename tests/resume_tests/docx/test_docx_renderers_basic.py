"""Basic docx renderer tests: BulletRenderer, HeaderRenderer, ListSectionRenderer, misc."""
from __future__ import annotations
import unittest
from tests.resume_tests.fixtures import make_fake_renderer, mock_docx_modules
from resume.render_config import HeaderLineConfig


@mock_docx_modules
class TestBulletRenderer(unittest.TestCase):
    """Tests for BulletRenderer class."""

    def _get_renderer(self):
        from resume.docx_renderers import BulletRenderer
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

    def test_add_bullets_list_style_mode(self):
        """Test add_bullets(plain=False) uses the configured list_style paragraphs."""
        renderer, doc = self._get_renderer()
        renderer.add_bullets(["Item 1", "Item 2"], plain=False, list_style="List Bullet")
        self.assertEqual(len(doc.paragraphs), 2)
        self.assertEqual(getattr(doc.paragraphs[0].style, "name", doc.paragraphs[0].style), "List Bullet")

    def test_get_bullet_config_page_cfg_fallback(self):
        """Constructor-level page_cfg supplies bullet config when sec is None."""
        from resume.docx_renderers import BulletRenderer
        from tests.resume_tests.fixtures import FakeDocument
        doc = FakeDocument()
        page_cfg = {"bullets": {"glyph": "★", "style": "plain"}}
        renderer = BulletRenderer(doc, page_cfg)
        plain, glyph = renderer.get_bullet_config(None)
        self.assertEqual(glyph, "★")
        self.assertTrue(plain)

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
        from resume.docx_renderers import HeaderRenderer
        return make_fake_renderer(HeaderRenderer)

    def test_add_header_line_title_only(self):
        """Test header with title only."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(HeaderLineConfig(title_text="Software Engineer"))
        self.assertEqual(len(doc.paragraphs), 1)
        runs = doc.paragraphs[0].runs
        self.assertEqual(runs[0].text, "Software Engineer")
        self.assertTrue(runs[0].bold)

    def test_add_header_line_title_and_company(self):
        """Test header with title and company."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(HeaderLineConfig(title_text="Software Engineer", company_text="Acme Corp"))
        runs = doc.paragraphs[0].runs
        texts = [r.text for r in runs]
        self.assertIn("Software Engineer", texts)
        self.assertIn(" at ", texts)
        self.assertIn("Acme Corp", texts)

    def test_add_header_line_with_location(self):
        """Test header with location."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(
            HeaderLineConfig(
                title_text="Engineer",
                company_text="Company",
                loc_text="New York",
            )
        )
        runs = doc.paragraphs[0].runs
        texts = [r.text for r in runs]
        self.assertIn("New York", texts)

    def test_add_header_line_location_brackets_by_default(self):
        """Location is bracketed by default: distinct '[' / ']' runs."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(HeaderLineConfig(title_text="Engineer", loc_text="NYC"))
        texts = [r.text for r in doc.paragraphs[0].runs]
        self.assertIn("[", texts)
        self.assertIn("]", texts)

    def test_add_header_line_without_location_brackets(self):
        """sec={"location_brackets": False} suppresses the bracket runs."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(
            HeaderLineConfig(title_text="Engineer", loc_text="NYC"),
            sec={"location_brackets": False},
        )
        texts = [r.text for r in doc.paragraphs[0].runs]
        self.assertNotIn("[", texts)
        self.assertNotIn("]", texts)

    def test_add_header_line_with_duration(self):
        """Test header with duration."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(
            HeaderLineConfig(
                title_text="Engineer",
                span_text="2020-2024",
            )
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

    def test_parse_meta_pt_float(self):
        """A bare float value passes through unchanged."""
        renderer, _ = self._get_renderer()
        self.assertEqual(renderer._parse_meta_pt({"meta_pt": 10.5}), 10.5)

    def test_parse_meta_pt_int_as_float(self):
        """An int value is coerced to float."""
        renderer, _ = self._get_renderer()
        self.assertEqual(renderer._parse_meta_pt({"meta_pt": 12}), 12.0)

    def test_parse_meta_pt_none_value(self):
        """An explicit None value (vs. missing key) returns None."""
        renderer, _ = self._get_renderer()
        self.assertIsNone(renderer._parse_meta_pt({"meta_pt": None}))

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
        from resume.docx_renderers import ListSectionRenderer
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

    def test_extract_item_text_dict_with_title_fallback(self):
        """The 'title' key is used when 'name' is absent."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text({"title": "Docker"}, ("name", "title"), None, " — ")
        self.assertEqual(result, "Docker")

    def test_extract_item_text_empty_dict(self):
        """An empty dict (distinct from an empty string) yields None."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text({}, ("name",), None, " — ")
        self.assertIsNone(result)

    def test_render_simple_list(self):
        """Test rendering a simple list."""
        renderer, doc = self._get_renderer()
        items = ["Item 1", "Item 2", "Item 3"]
        result = renderer.render_simple_list(items)
        self.assertEqual(result, ["Item 1", "Item 2", "Item 3"])
        self.assertEqual(len(doc.paragraphs), 3)

    def test_render_simple_list_inline(self):
        """sec={"bullets": False} joins items into a single separator-delimited paragraph."""
        renderer, doc = self._get_renderer()
        sec = {"bullets": False, "separator": ", "}
        renderer.render_simple_list(["A", "B", "C"], sec)
        self.assertEqual(len(doc.paragraphs), 1)

    def test_render_simple_list_skips_empty_items(self):
        """Blank strings and empty dict items are dropped from the rendered list."""
        renderer, _ = self._get_renderer()
        items = ["Valid", "", "  ", {"name": ""}, "Also Valid"]
        result = renderer.render_simple_list(items)
        self.assertEqual(result, ["Valid", "Also Valid"])

    def test_render_simple_list_title_and_label_fallback(self):
        """render_simple_list's default name_keys include 'title' and 'label'."""
        renderer, _ = self._get_renderer()
        items = [{"name": "First"}, {"title": "Second"}, {"label": "Third"}]
        result = renderer.render_simple_list(items)
        self.assertEqual(result, ["First", "Second", "Third"])


@mock_docx_modules
class TestSectionRenderers(unittest.TestCase):
    """Tests for specific section renderers."""

    def test_interests_renderer(self):
        """Test InterestsSectionRenderer."""
        from resume.docx_sections_simple import InterestsSectionRenderer
        renderer, _ = make_fake_renderer(InterestsSectionRenderer)
        data = {"interests": ["Reading", "Hiking", "Photography"]}
        result = renderer.render(data)
        self.assertEqual(len(result), 3)

    def test_languages_renderer(self):
        """Test LanguagesSectionRenderer."""
        from resume.docx_sections_simple import LanguagesSectionRenderer
        renderer, _ = make_fake_renderer(LanguagesSectionRenderer)
        data = {"languages": [
            {"name": "English", "level": "Native"},
            {"language": "Spanish", "level": "Fluent"},
        ]}
        result = renderer.render(data)
        self.assertEqual(len(result), 2)

    def test_coursework_renderer(self):
        """Test CourseworkSectionRenderer."""
        from resume.docx_sections_simple import CourseworkSectionRenderer
        renderer, _ = make_fake_renderer(CourseworkSectionRenderer)
        data = {"coursework": [
            {"name": "Data Structures"},
            {"course": "Algorithms"},
        ]}
        result = renderer.render(data)
        self.assertEqual(len(result), 2)

    def test_certifications_renderer(self):
        """Test CertificationsSectionRenderer."""
        from resume.docx_sections_simple import CertificationsSectionRenderer
        renderer, _ = make_fake_renderer(CertificationsSectionRenderer)
        data = {"certifications": [
            {"name": "AWS Certified", "year": "2023"},
            {"cert": "GCP Professional"},
        ]}
        result = renderer.render(data)
        self.assertEqual(len(result), 2)

    def test_presentations_renderer(self):
        """Test PresentationsSectionRenderer."""
        from resume.docx_sections_simple import PresentationsSectionRenderer
        renderer, _ = make_fake_renderer(PresentationsSectionRenderer)
        data = {"presentations": [
            {"title": "Intro to Python", "event": "PyCon", "year": "2023"},
            "Another Talk",
        ]}
        result = renderer.render(data)
        self.assertEqual(len(result), 2)

    def test_presentations_link_only_no_duplication(self):
        """Link-only presentation (no title/event/year) renders a single hyperlink run.

        Before the fix, _render_dict_item would set `display = url` (raw URL) then
        add a bullet run with the raw URL AND append a hyperlink run — duplicating
        the URL text. After the fix, only the hyperlink run is appended (with the
        cleaned display URL), not the raw URL as plain text first.
        """
        from resume.docx_sections_simple import PresentationsSectionRenderer
        renderer, doc = make_fake_renderer(PresentationsSectionRenderer)
        data = {"presentations": [
            {"link": "https://slides.example.com/my-talk"},
        ]}
        result = renderer.render(data)

        # Exactly one item rendered.
        self.assertEqual(len(result), 1)
        # The returned display text should be the cleaned URL, not the raw URL.
        self.assertEqual(result[0], "slides.example.com/my-talk")

        # The bullet paragraph should NOT have a plain-text run equal to the raw URL.
        # (add_hyperlink falls back to add_run in fake context, but the glyph run
        # should be the only content run before the hyperlink — never the raw URL.)
        bullet_para = doc.paragraphs[0]
        raw_url = "https://slides.example.com/my-talk"
        plain_runs_with_raw_url = [r for r in bullet_para.runs if r.text == raw_url]
        self.assertEqual(
            plain_runs_with_raw_url, [],
            "Raw URL must not appear as a plain-text run — only as hyperlink display text.",
        )

    def test_presentations_unsafe_link_renders_as_plain_text(self):
        """Presentation with a file: link must NOT create a w:hyperlink — renders plain."""
        from resume.docx_sections_simple import PresentationsSectionRenderer
        renderer, doc = make_fake_renderer(PresentationsSectionRenderer)
        data = {"presentations": [
            {"title": "Secret", "link": "file:///etc/passwd"},
        ]}
        result = renderer.render(data)
        self.assertEqual(len(result), 1)
        # The display should be the title, not any URL.
        self.assertEqual(result[0], "Secret")
        # No paragraph should contain a run with the file: URL.
        for para in doc.paragraphs:
            for r in para.runs:
                self.assertNotIn("file:", r.text)

    def test_presentations_honors_plain_bullet_config(self):
        """When sec configures plain_bullets=False, paragraphs use 'List Bullet' style."""
        from resume.docx_sections_simple import PresentationsSectionRenderer
        renderer, doc = make_fake_renderer(PresentationsSectionRenderer)
        sec = {"plain_bullets": False, "bullets": {"style": "list"}}
        data = {"presentations": [
            {"title": "My Talk", "event": "PyCon", "year": "2024"},
        ]}
        renderer.render(data, sec=sec)
        # At least one paragraph should use 'List Bullet' style.
        styles = [getattr(p.style, "name", None) for p in doc.paragraphs]
        self.assertIn("List Bullet", styles, "Expected 'List Bullet' style for non-plain config.")


if __name__ == "__main__":
    unittest.main()
