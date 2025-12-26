"""Tests for docx_sections helper methods.

These tests focus on helper methods that can be tested without a full DOCX document.
Mock objects are used where document interaction is needed.
"""
import unittest
from unittest.mock import Mock, MagicMock

from resume.docx_sections import (
    BulletRenderer,
    HeaderRenderer,
    ListSectionRenderer,
    ExperienceSectionRenderer,
    SummarySectionRenderer,
)


class MockDocument:
    """Minimal mock for docx.Document."""

    def __init__(self):
        self.paragraphs = []

    def add_paragraph(self, text="", style=None):
        p = MockParagraph(text)
        self.paragraphs.append(p)
        return p


class MockParagraph:
    """Minimal mock for docx paragraph."""

    def __init__(self, text=""):
        self._text = text
        self.runs = []
        self.paragraph_format = MockParagraphFormat()
        self.style = None

    def add_run(self, text=""):
        r = MockRun(text)
        self.runs.append(r)
        return r


class MockParagraphFormat:
    """Minimal mock for paragraph_format."""

    def __init__(self):
        self.space_after = None
        self.space_before = None
        self.left_indent = None
        self.first_line_indent = None


class MockRun:
    """Minimal mock for docx run."""

    def __init__(self, text=""):
        self.text = text
        self.bold = False
        self.italic = False
        self.font = MockFont()


class MockFont:
    """Minimal mock for run font."""

    def __init__(self):
        self.size = None
        self.color = MockColor()


class MockColor:
    """Minimal mock for font color."""

    def __init__(self):
        self.rgb = None


class TestBulletRendererGetBulletConfig(unittest.TestCase):
    """Tests for BulletRenderer.get_bullet_config method."""

    def setUp(self):
        self.doc = MockDocument()
        self.renderer = BulletRenderer(self.doc)

    def test_default_glyph(self):
        plain, glyph = self.renderer.get_bullet_config(None)
        self.assertEqual(glyph, "•")

    def test_custom_glyph_from_section(self):
        sec = {"bullets": {"glyph": "→"}}
        plain, glyph = self.renderer.get_bullet_config(sec)
        self.assertEqual(glyph, "→")

    def test_plain_bullets_flag(self):
        sec = {"plain_bullets": True}
        plain, glyph = self.renderer.get_bullet_config(sec)
        self.assertTrue(plain)

    def test_plain_style_from_bullets(self):
        sec = {"bullets": {"style": "plain"}}
        plain, glyph = self.renderer.get_bullet_config(sec)
        self.assertTrue(plain)

    def test_page_cfg_fallback(self):
        doc = MockDocument()
        page_cfg = {"bullets": {"glyph": "★", "style": "plain"}}
        renderer = BulletRenderer(doc, page_cfg)
        plain, glyph = renderer.get_bullet_config(None)
        self.assertEqual(glyph, "★")
        self.assertTrue(plain)


class TestHeaderRendererParseMetaPt(unittest.TestCase):
    """Tests for HeaderRenderer._parse_meta_pt method."""

    def setUp(self):
        self.doc = MockDocument()
        self.renderer = HeaderRenderer(self.doc)

    def test_parses_float(self):
        self.assertEqual(self.renderer._parse_meta_pt({"meta_pt": 10.5}), 10.5)

    def test_parses_int_as_float(self):
        self.assertEqual(self.renderer._parse_meta_pt({"meta_pt": 12}), 12.0)

    def test_parses_string_number(self):
        self.assertEqual(self.renderer._parse_meta_pt({"meta_pt": "11"}), 11.0)

    def test_returns_none_for_missing(self):
        self.assertIsNone(self.renderer._parse_meta_pt({}))

    def test_returns_none_for_invalid(self):
        self.assertIsNone(self.renderer._parse_meta_pt({"meta_pt": "invalid"}))

    def test_returns_none_for_none_value(self):
        self.assertIsNone(self.renderer._parse_meta_pt({"meta_pt": None}))


class TestListSectionRendererExtractItemText(unittest.TestCase):
    """Tests for ListSectionRenderer._extract_item_text method."""

    def setUp(self):
        self.doc = MockDocument()
        self.renderer = ListSectionRenderer(self.doc)

    def test_extracts_string(self):
        result = self.renderer._extract_item_text("Python", ("name",), None, " — ")
        self.assertEqual(result, "Python")

    def test_extracts_from_dict_name(self):
        item = {"name": "AWS", "level": "Expert"}
        result = self.renderer._extract_item_text(item, ("name", "title"), None, " — ")
        self.assertEqual(result, "AWS")

    def test_extracts_from_dict_title(self):
        item = {"title": "Docker"}
        result = self.renderer._extract_item_text(item, ("name", "title"), None, " — ")
        self.assertEqual(result, "Docker")

    def test_includes_description(self):
        item = {"name": "Python", "level": "Expert"}
        result = self.renderer._extract_item_text(item, ("name",), "level", " — ")
        self.assertEqual(result, "Python — Expert")

    def test_strips_whitespace(self):
        result = self.renderer._extract_item_text("  Python  ", ("name",), None, " — ")
        self.assertEqual(result, "Python")

    def test_returns_none_for_empty_string(self):
        result = self.renderer._extract_item_text("", ("name",), None, " — ")
        self.assertIsNone(result)

    def test_returns_none_for_empty_dict(self):
        result = self.renderer._extract_item_text({}, ("name",), None, " — ")
        self.assertIsNone(result)


class TestExperienceSectionFormatDateSpan(unittest.TestCase):
    """Tests for ExperienceSectionRenderer._format_date_span method."""

    def setUp(self):
        self.doc = MockDocument()
        self.renderer = ExperienceSectionRenderer(self.doc)

    def test_formats_start_and_end(self):
        exp = {"start": "2020", "end": "2023"}
        result = self.renderer._format_date_span(exp)
        self.assertEqual(result, "2020 – 2023")

    def test_formats_start_only_adds_present(self):
        exp = {"start": "2020"}
        result = self.renderer._format_date_span(exp)
        self.assertEqual(result, "2020 – Present")

    def test_formats_end_only(self):
        exp = {"end": "2023"}
        result = self.renderer._format_date_span(exp)
        self.assertEqual(result, "2023")

    def test_normalizes_present_variants(self):
        exp = {"start": "2020", "end": "present"}
        result = self.renderer._format_date_span(exp)
        self.assertEqual(result, "2020 – Present")

    def test_normalizes_current(self):
        exp = {"start": "2020", "end": "current"}
        result = self.renderer._format_date_span(exp)
        self.assertEqual(result, "2020 – Present")

    def test_returns_empty_for_no_dates(self):
        exp = {}
        result = self.renderer._format_date_span(exp)
        self.assertEqual(result, "")


class TestExperienceSectionCalculateBulletLimit(unittest.TestCase):
    """Tests for ExperienceSectionRenderer._calculate_bullet_limit method."""

    def setUp(self):
        self.doc = MockDocument()
        self.renderer = ExperienceSectionRenderer(self.doc)

    def test_returns_max_when_no_recency(self):
        result = self.renderer._calculate_bullet_limit(
            idx=0, max_bullets=5, recent_roles_count=0,
            recent_max_bullets=3, prior_max_bullets=2
        )
        self.assertEqual(result, 5)

    def test_uses_recent_limit_for_recent_role(self):
        result = self.renderer._calculate_bullet_limit(
            idx=0, max_bullets=5, recent_roles_count=2,
            recent_max_bullets=4, prior_max_bullets=2
        )
        self.assertEqual(result, 4)

    def test_uses_prior_limit_for_older_role(self):
        result = self.renderer._calculate_bullet_limit(
            idx=2, max_bullets=5, recent_roles_count=2,
            recent_max_bullets=4, prior_max_bullets=2
        )
        self.assertEqual(result, 2)

    def test_respects_max_bullets_cap(self):
        result = self.renderer._calculate_bullet_limit(
            idx=0, max_bullets=3, recent_roles_count=2,
            recent_max_bullets=5, prior_max_bullets=2
        )
        self.assertEqual(result, 3)


class TestExperienceSectionNormalizeBullets(unittest.TestCase):
    """Tests for ExperienceSectionRenderer._normalize_bullets method."""

    def setUp(self):
        self.doc = MockDocument()
        self.renderer = ExperienceSectionRenderer(self.doc)

    def test_normalizes_strings(self):
        bullets = ["Built APIs", "Led team"]
        result = self.renderer._normalize_bullets(bullets, 10)
        self.assertEqual(len(result), 2)
        self.assertIn("Built APIs", result)

    def test_extracts_from_dicts(self):
        bullets = [{"text": "Built APIs"}, {"line": "Led team"}]
        result = self.renderer._normalize_bullets(bullets, 10)
        self.assertEqual(len(result), 2)

    def test_respects_limit(self):
        bullets = ["One", "Two", "Three", "Four"]
        result = self.renderer._normalize_bullets(bullets, 2)
        self.assertEqual(len(result), 2)

    def test_skips_empty(self):
        bullets = ["Valid", "", {"text": ""}]
        result = self.renderer._normalize_bullets(bullets, 10)
        self.assertEqual(len(result), 1)


class TestSummarySectionNormalizeListItems(unittest.TestCase):
    """Tests for SummarySectionRenderer._normalize_list_items method."""

    def setUp(self):
        self.doc = MockDocument()
        self.renderer = SummarySectionRenderer(self.doc)

    def test_extracts_strings(self):
        items = ["First point", "Second point"]
        result = self.renderer._normalize_list_items(items)
        self.assertEqual(result, ["First point", "Second point"])

    def test_extracts_text_from_dicts(self):
        items = [{"text": "Point 1"}, {"line": "Point 2"}, {"desc": "Point 3"}]
        result = self.renderer._normalize_list_items(items)
        self.assertEqual(len(result), 3)

    def test_skips_empty(self):
        items = ["Valid", "", {"text": ""}]
        result = self.renderer._normalize_list_items(items)
        self.assertEqual(result, ["Valid"])


class TestBulletRendererBoldKeywords(unittest.TestCase):
    """Tests for BulletRenderer._bold_keywords method."""

    def setUp(self):
        self.doc = MockDocument()
        self.renderer = BulletRenderer(self.doc)

    def test_bolds_single_keyword(self):
        p = MockParagraph()
        self.renderer._bold_keywords(p, "I use Python daily", ["Python"])
        # Check that runs were added
        self.assertGreater(len(p.runs), 0)
        # Find the bold run
        bold_runs = [r for r in p.runs if r.bold]
        self.assertTrue(any(r.text == "Python" for r in bold_runs))

    def test_bolds_multiple_keywords(self):
        p = MockParagraph()
        self.renderer._bold_keywords(p, "Python and Docker", ["Python", "Docker"])
        bold_runs = [r for r in p.runs if r.bold]
        self.assertEqual(len(bold_runs), 2)

    def test_handles_no_keywords(self):
        p = MockParagraph()
        self.renderer._bold_keywords(p, "Some text", [])
        # Should add text as a single run
        self.assertGreater(len(p.runs), 0)

    def test_case_insensitive(self):
        p = MockParagraph()
        self.renderer._bold_keywords(p, "Using PYTHON for work", ["python"])
        bold_runs = [r for r in p.runs if r.bold]
        self.assertTrue(any("PYTHON" in r.text for r in bold_runs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
