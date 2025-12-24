"""Unit tests for docx_writer helper functions."""

import unittest


class TestGetContactField(unittest.TestCase):
    """Tests for _get_contact_field helper."""

    def test_returns_top_level_field(self):
        from resume.docx_writer import _get_contact_field
        data = {"name": "John Doe", "contact": {"name": "Jane Doe"}}
        self.assertEqual(_get_contact_field(data, "name"), "John Doe")

    def test_falls_back_to_contact_dict(self):
        from resume.docx_writer import _get_contact_field
        data = {"contact": {"email": "test@example.com"}}
        self.assertEqual(_get_contact_field(data, "email"), "test@example.com")

    def test_returns_empty_string_when_missing(self):
        from resume.docx_writer import _get_contact_field
        data = {"contact": {}}
        self.assertEqual(_get_contact_field(data, "phone"), "")

    def test_handles_missing_contact_dict(self):
        from resume.docx_writer import _get_contact_field
        data = {}
        self.assertEqual(_get_contact_field(data, "email"), "")


class TestCollectLinkExtras(unittest.TestCase):
    """Tests for _collect_link_extras helper."""

    def test_collects_website_linkedin_github(self):
        from resume.docx_writer import _collect_link_extras
        data = {
            "website": "https://example.com",
            "linkedin": "https://linkedin.com/in/test",
            "github": "https://github.com/test",
        }
        extras = _collect_link_extras(data)
        self.assertEqual(len(extras), 3)
        self.assertIn("example.com", extras[0])

    def test_collects_from_links_list(self):
        from resume.docx_writer import _collect_link_extras
        data = {"links": ["https://blog.example.com", "https://portfolio.example.com"]}
        extras = _collect_link_extras(data)
        self.assertEqual(len(extras), 2)

    def test_skips_empty_values(self):
        from resume.docx_writer import _collect_link_extras
        data = {"website": "", "linkedin": None, "github": "https://github.com/test"}
        extras = _collect_link_extras(data)
        self.assertEqual(len(extras), 1)

    def test_handles_contact_nested_links(self):
        from resume.docx_writer import _collect_link_extras
        data = {"contact": {"website": "https://example.com"}}
        extras = _collect_link_extras(data)
        self.assertEqual(len(extras), 1)


class TestExtractExperienceLocations(unittest.TestCase):
    """Tests for _extract_experience_locations helper."""

    def test_extracts_unique_locations(self):
        from resume.docx_writer import _extract_experience_locations
        data = {
            "experience": [
                {"location": "New York, NY"},
                {"location": "San Francisco, CA"},
                {"location": "New York, NY"},  # duplicate
            ]
        }
        locs = _extract_experience_locations(data)
        self.assertEqual(locs, ["New York, NY", "San Francisco, CA"])

    def test_handles_missing_locations(self):
        from resume.docx_writer import _extract_experience_locations
        data = {
            "experience": [
                {"title": "Engineer"},
                {"location": "Boston, MA"},
                {"location": ""},
            ]
        }
        locs = _extract_experience_locations(data)
        self.assertEqual(locs, ["Boston, MA"])

    def test_handles_no_experience(self):
        from resume.docx_writer import _extract_experience_locations
        data = {}
        locs = _extract_experience_locations(data)
        self.assertEqual(locs, [])


class TestMatchSectionKey(unittest.TestCase):
    """Tests for _match_section_key helper."""

    def test_matches_summary_synonyms(self):
        from resume.docx_writer import _match_section_key
        self.assertEqual(_match_section_key("Summary"), "summary")
        self.assertEqual(_match_section_key("Profile"), "summary")
        self.assertEqual(_match_section_key("About"), "summary")

    def test_matches_experience_synonyms(self):
        from resume.docx_writer import _match_section_key
        self.assertEqual(_match_section_key("Experience"), "experience")
        self.assertEqual(_match_section_key("Work History"), "experience")
        self.assertEqual(_match_section_key("Employment"), "experience")

    def test_returns_none_for_unknown(self):
        from resume.docx_writer import _match_section_key
        self.assertIsNone(_match_section_key("Unknown Section"))

    def test_case_insensitive(self):
        from resume.docx_writer import _match_section_key
        self.assertEqual(_match_section_key("SKILLS"), "skills")
        self.assertEqual(_match_section_key("education"), "education")


class TestSectionRenderers(unittest.TestCase):
    """Tests for SECTION_RENDERERS registry."""

    def test_all_section_keys_have_renderers(self):
        from resume.docx_writer import SECTION_RENDERERS
        expected_keys = {
            "summary", "skills", "technologies", "interests",
            "presentations", "languages", "coursework",
            "certifications", "experience", "education",
        }
        self.assertEqual(set(SECTION_RENDERERS.keys()), expected_keys)

    def test_sections_with_keywords_is_subset(self):
        from resume.docx_writer import SECTION_RENDERERS, SECTIONS_WITH_KEYWORDS
        self.assertTrue(SECTIONS_WITH_KEYWORDS.issubset(set(SECTION_RENDERERS.keys())))


class TestResolveSections(unittest.TestCase):
    """Tests for _resolve_sections helper."""

    def test_returns_template_sections_by_default(self):
        from resume.docx_writer import _resolve_sections
        template = {"sections": [{"key": "summary"}, {"key": "experience"}]}
        sections = _resolve_sections(template, None)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0]["key"], "summary")

    def test_respects_structure_order(self):
        from resume.docx_writer import _resolve_sections
        template = {"sections": [{"key": "summary"}, {"key": "experience"}, {"key": "education"}]}
        structure = {"order": ["education", "experience"]}
        sections = _resolve_sections(template, structure)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0]["key"], "education")
        self.assertEqual(sections[1]["key"], "experience")

    def test_uses_structure_titles(self):
        from resume.docx_writer import _resolve_sections
        template = {"sections": []}
        structure = {"order": ["custom"], "titles": {"custom": "My Custom Section"}}
        sections = _resolve_sections(template, structure)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["title"], "My Custom Section")


if __name__ == "__main__":
    unittest.main()
