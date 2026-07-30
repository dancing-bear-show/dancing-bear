"""Unit tests for docx_writer helper functions."""
from tests.fixtures import test_path


import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from resume.docx_writer import (
    _get_contact_field,
    _collect_link_extras,
    _extract_experience_locations,
    _match_section_key,
    _resolve_sections,
    _get_header_level,
    _use_plain_bullets,
    _apply_page_styles,
    _set_document_metadata,
    _center_paragraph,
    SECTION_RENDERERS,
    SECTIONS_WITH_KEYWORDS,
    write_resume_docx,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def make_mock_doc():
    """Create a mock Document with core_properties."""
    doc = MagicMock()
    doc.core_properties = MagicMock()
    return doc


def sample_resume_data(*, name="Test User", email=None, experience=None):
    """Build a sample resume data dict."""
    data = {"name": name}
    if email:
        data["email"] = email
    if experience is not None:
        data["experience"] = experience
    return data


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetContactField(unittest.TestCase):
    """Tests for _get_contact_field helper."""

    def test_returns_top_level_field(self):
        data = {"name": "John Doe", "contact": {"name": "Jane Doe"}}
        self.assertEqual(_get_contact_field(data, "name"), "John Doe")

    def test_falls_back_to_contact_dict(self):
        data = {"contact": {"email": "test@example.com"}}
        self.assertEqual(_get_contact_field(data, "email"), "test@example.com")

    def test_returns_empty_string_when_missing(self):
        data = {"contact": {}}
        self.assertEqual(_get_contact_field(data, "phone"), "")

    def test_handles_missing_contact_dict(self):
        self.assertEqual(_get_contact_field({}, "email"), "")


class TestCollectLinkExtras(unittest.TestCase):
    """Tests for _collect_link_extras helper."""

    def test_collects_website_linkedin_github(self):
        data = {
            "website": "https://example.com",
            "linkedin": "https://linkedin.com/in/test",
            "github": "https://github.com/test",
        }
        extras = _collect_link_extras(data)
        self.assertEqual(len(extras), 3)
        self.assertIn("example.com", extras[0])

    def test_collects_from_links_list(self):
        data = {"links": ["https://blog.example.com", "https://portfolio.example.com"]}
        extras = _collect_link_extras(data)
        self.assertEqual(len(extras), 2)

    def test_skips_empty_values(self):
        data = {"website": "", "linkedin": None, "github": "https://github.com/test"}
        extras = _collect_link_extras(data)
        self.assertEqual(len(extras), 1)

    def test_handles_contact_nested_links(self):
        data = {"contact": {"website": "https://example.com"}}
        extras = _collect_link_extras(data)
        self.assertEqual(len(extras), 1)


class TestExtractExperienceLocations(unittest.TestCase):
    """Tests for _extract_experience_locations helper."""

    def test_extracts_unique_locations(self):
        data = sample_resume_data(experience=[
            {"location": "New York, NY"},
            {"location": "San Francisco, CA"},
            {"location": "New York, NY"},  # duplicate
        ])
        locs = _extract_experience_locations(data)
        self.assertEqual(locs, ["New York, NY", "San Francisco, CA"])

    def test_handles_missing_locations(self):
        data = sample_resume_data(experience=[
            {"title": "Engineer"},
            {"location": "Boston, MA"},
            {"location": ""},
        ])
        locs = _extract_experience_locations(data)
        self.assertEqual(locs, ["Boston, MA"])

    def test_handles_no_experience(self):
        self.assertEqual(_extract_experience_locations({}), [])


class TestMatchSectionKey(unittest.TestCase):
    """Tests for _match_section_key helper."""

    def test_matches_summary_synonyms(self):
        self.assertEqual(_match_section_key("Summary"), "summary")
        self.assertEqual(_match_section_key("Profile"), "summary")
        self.assertEqual(_match_section_key("About"), "summary")

    def test_matches_experience_synonyms(self):
        self.assertEqual(_match_section_key("Experience"), "experience")
        self.assertEqual(_match_section_key("Work History"), "experience")
        self.assertEqual(_match_section_key("Employment"), "experience")

    def test_returns_none_for_unknown(self):
        self.assertIsNone(_match_section_key("Unknown Section"))

    def test_case_insensitive(self):
        self.assertEqual(_match_section_key("SKILLS"), "skills")
        self.assertEqual(_match_section_key("education"), "education")


class TestSectionRenderers(unittest.TestCase):
    """Tests for SECTION_RENDERERS registry."""

    def test_all_section_keys_have_renderers(self):
        expected_keys = {
            "summary", "skills", "technologies", "interests",
            "presentations", "languages", "coursework",
            "certifications", "experience", "education",
        }
        self.assertEqual(set(SECTION_RENDERERS.keys()), expected_keys)

    def test_sections_with_keywords_is_subset(self):
        self.assertTrue(SECTIONS_WITH_KEYWORDS.issubset(set(SECTION_RENDERERS.keys())))


class TestResolveSections(unittest.TestCase):
    """Tests for _resolve_sections helper."""

    def test_returns_template_sections_by_default(self):
        template = {"sections": [{"key": "summary"}, {"key": "experience"}]}
        sections = _resolve_sections(template, None)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0]["key"], "summary")

    def test_respects_structure_order(self):
        template = {"sections": [{"key": "summary"}, {"key": "experience"}, {"key": "education"}]}
        structure = {"order": ["education", "experience"]}
        sections = _resolve_sections(template, structure)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0]["key"], "education")
        self.assertEqual(sections[1]["key"], "experience")

    def test_uses_structure_titles(self):
        template = {"sections": []}
        structure = {"order": ["custom"], "titles": {"custom": "My Custom Section"}}
        sections = _resolve_sections(template, structure)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["title"], "My Custom Section")

    def test_empty_template_sections(self):
        self.assertEqual(_resolve_sections({}, None), [])

    def test_structure_order_filters_missing_keys(self):
        template = {"sections": [{"key": "summary"}]}
        structure = {"order": ["summary", "nonexistent"]}
        sections = _resolve_sections(template, structure)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["key"], "summary")


class TestGetHeaderLevel(unittest.TestCase):
    """Tests for _get_header_level helper."""

    def test_returns_section_header_level(self):
        self.assertEqual(_get_header_level({"header_level": 2}, None), 2)

    def test_returns_page_cfg_header_level(self):
        self.assertEqual(_get_header_level(None, {"header_level": 3}), 3)

    def test_section_overrides_page_cfg(self):
        self.assertEqual(_get_header_level({"header_level": 2}, {"header_level": 3}), 2)

    def test_defaults_to_1(self):
        self.assertEqual(_get_header_level(None, None), 1)
        self.assertEqual(_get_header_level({}, {}), 1)

    def test_handles_invalid_header_level(self):
        self.assertEqual(_get_header_level({"header_level": "invalid"}, None), 1)


class TestUsePlainBullets(unittest.TestCase):
    """Tests for _use_plain_bullets helper."""

    def test_returns_tuple(self):
        self.assertIsInstance(_use_plain_bullets(None, None), tuple)


class TestApplyPageStyles(unittest.TestCase):
    """Tests for _apply_page_styles helper."""

    def test_skips_non_compact(self):
        doc = make_mock_doc()
        _apply_page_styles(doc, {"compact": False})
        doc.sections.__getitem__.assert_not_called()

    def test_skips_empty_config(self):
        doc = make_mock_doc()
        _apply_page_styles(doc, {})
        doc.sections.__getitem__.assert_not_called()


class TestSetDocumentMetadata(unittest.TestCase):
    """Tests for _set_document_metadata helper."""

    def setUp(self):
        self.doc = make_mock_doc()

    def test_sets_title_from_name(self):
        data = sample_resume_data(name="John Doe", email="john@example.com")
        _set_document_metadata(self.doc, data, {})
        self.assertIn("John Doe", self.doc.core_properties.title)

    def test_sets_author_from_name(self):
        data = sample_resume_data(name="Jane Smith")
        _set_document_metadata(self.doc, data, {})
        self.assertEqual(self.doc.core_properties.author, "Jane Smith")

    def test_includes_experience_locations_in_keywords(self):
        data = sample_resume_data(experience=[{"location": "NYC"}, {"location": "LA"}])
        template = {"page": {"metadata_include_locations": True}}
        _set_document_metadata(self.doc, data, template)
        self.assertIn("NYC", self.doc.core_properties.keywords)
        self.assertIn("LA", self.doc.core_properties.keywords)

    def test_excludes_locations_when_disabled(self):
        data = sample_resume_data(experience=[{"location": "NYC"}])
        template = {"page": {"metadata_include_locations": False}}
        _set_document_metadata(self.doc, data, template)
        self.assertNotIn("NYC", self.doc.core_properties.keywords)

    def test_handles_missing_data(self):
        _set_document_metadata(self.doc, {}, {})
        self.assertEqual(self.doc.core_properties.title, "Resume")


class TestCenterParagraph(unittest.TestCase):
    """Tests for _center_paragraph helper."""

    def test_centers_paragraph(self):
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        para = MagicMock()
        para.paragraph_format = MagicMock()
        _center_paragraph(para)
        self.assertEqual(para.alignment, WD_ALIGN_PARAGRAPH.CENTER)

    def test_handles_exception_gracefully(self):
        para = MagicMock()
        type(para).alignment = PropertyMock(side_effect=Exception("test"))
        # Should not raise
        _center_paragraph(para)


class TestWriteResumeDocx(unittest.TestCase):
    """Tests for write_resume_docx main function."""

    def test_raises_without_docx_module(self):
        with patch("resume.docx_writer.safe_import", return_value=None):
            with self.assertRaises(RuntimeError) as ctx:
                write_resume_docx({}, {}, test_path("test.docx"))  # noqa: S108 - test fixture path
            self.assertIn("python-docx", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
