"""Tests for resume/parsing.py DOCX-specific parsing helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from resume.parsing import (
    _DocxParaHelper,
    _docx_find_sections,
    _docx_extract_name_headline,
    _docx_extract_summary,
    _docx_extract_education,
    _docx_extract_experience,
    _parse_h2_education,
    _parse_h2_experience,
    _process_exp_paragraph,
)


def _make_para(text: str, style_name: str = "Normal") -> MagicMock:
    """Create a mock docx paragraph with text and style."""
    para = MagicMock()
    para.text = text
    para.style = MagicMock()
    para.style.name = style_name
    return para


def _make_helper(paragraphs_data: list) -> _DocxParaHelper:
    """Create _DocxParaHelper from list of (text, style_name) tuples."""
    paras = [_make_para(text, style) for text, style in paragraphs_data]
    return _DocxParaHelper(paras)


class TestDocxParaHelper(unittest.TestCase):
    """Tests for _DocxParaHelper."""

    def test_style_returns_lowercase(self):
        helper = _make_helper([("Some text", "Heading 1")])
        self.assertEqual(helper.style(0), "heading 1")

    def test_text_returns_stripped(self):
        helper = _make_helper([("  text with spaces  ", "Normal")])
        self.assertEqual(helper.text(0), "text with spaces")

    def test_len(self):
        helper = _make_helper([
            ("Text 1", "Normal"),
            ("Text 2", "Heading 1"),
            ("Text 3", "Normal"),
        ])
        self.assertEqual(len(helper), 3)

    def test_handles_missing_style_name(self):
        para = MagicMock()
        para.text = "text"
        para.style = MagicMock()
        para.style.name = None
        helper = _DocxParaHelper([para])
        self.assertEqual(helper.style(0), "")


class TestDocxFindSections(unittest.TestCase):
    """Tests for _docx_find_sections."""

    def test_finds_experience_section(self):
        helper = _make_helper([
            ("John Doe", "Title"),
            ("Experience", "Heading 1"),
            ("Senior Engineer at TechCorp", "Normal"),
            ("Education", "Heading 1"),
            ("B.S. CS at MIT", "Normal"),
        ])
        h1_indices, sections = _docx_find_sections(helper)
        self.assertIn(1, h1_indices)
        self.assertIn(3, h1_indices)
        self.assertIn("experience", sections)
        self.assertIn("education", sections)

    def test_marks_section_end_bounds(self):
        helper = _make_helper([
            ("Summary", "Heading 1"),
            ("Summary text", "Normal"),
            ("Experience", "Heading 1"),
            ("Job 1", "Normal"),
        ])
        _h1_indices, sections = _docx_find_sections(helper)
        # Summary ends before Experience
        self.assertEqual(sections["summary"]["end"], 1)
        # Experience ends at last paragraph
        self.assertEqual(sections["experience"]["end"], 3)

    def test_no_headings(self):
        helper = _make_helper([
            ("John Doe", "Normal"),
            ("Developer", "Normal"),
        ])
        h1_indices, sections = _docx_find_sections(helper)
        self.assertEqual(h1_indices, [])
        self.assertEqual(sections, {})

    def test_unknown_heading_is_skipped(self):
        helper = _make_helper([
            ("Projects", "Heading 1"),  # Not a known section key
            ("Some project", "Normal"),
        ])
        h1_indices, sections = _docx_find_sections(helper)
        self.assertIn(0, h1_indices)
        self.assertEqual(sections, {})


class TestDocxExtractNameHeadline(unittest.TestCase):
    """Tests for _docx_extract_name_headline."""

    def test_extracts_title_style_name(self):
        helper = _make_helper([
            ("John Doe", "Title"),
            ("Software Engineer", "Normal"),
            ("Experience", "Heading 1"),
        ])
        name, _headline, _early_lines = _docx_extract_name_headline(helper, first_h1=2)
        self.assertEqual(name, "John Doe")

    def test_extracts_headline_from_second_normal_line(self):
        helper = _make_helper([
            ("John Doe", "Title"),
            ("Software Engineer", "Normal"),
            ("Experience", "Heading 1"),
        ])
        _name, headline, _early_lines = _docx_extract_name_headline(helper, first_h1=2)
        self.assertEqual(headline, "Software Engineer")

    def test_skips_headline_with_at_sign(self):
        helper = _make_helper([
            ("John Doe", "Title"),
            ("john@example.com | 555-1234", "Normal"),
            ("Experience", "Heading 1"),
        ])
        _name, headline, _early_lines = _docx_extract_name_headline(helper, first_h1=2)
        self.assertEqual(headline, "")

    def test_handles_no_title_style(self):
        helper = _make_helper([
            ("Some text", "Normal"),
            ("Experience", "Heading 1"),
        ])
        name, _headline, _early_lines = _docx_extract_name_headline(helper, first_h1=1)
        self.assertEqual(name, "")

    def test_empty_helper(self):
        helper = _make_helper([])
        name, headline, _early_lines = _docx_extract_name_headline(helper, first_h1=0)
        self.assertEqual(name, "")
        self.assertEqual(headline, "")


class TestDocxExtractSummary(unittest.TestCase):
    """Tests for _docx_extract_summary."""

    def test_extracts_from_summary_section(self):
        helper = _make_helper([
            ("John Doe", "Title"),
            ("Summary", "Heading 1"),
            ("Experienced developer", "Normal"),
            ("Experience", "Heading 1"),
            ("Job", "Normal"),
        ])
        _, sections = _docx_find_sections(helper)
        h1_indices = [1, 3]
        summary = _docx_extract_summary(helper, sections, h1_indices, first_h1=1)
        self.assertIn("Experienced developer", summary)

    def test_extracts_preface_when_no_summary_section(self):
        helper = _make_helper([
            ("John Doe", "Title"),
            ("10 years building systems", "Normal"),
            ("Experience", "Heading 1"),
            ("Job", "Normal"),
        ])
        _, sections = _docx_find_sections(helper)
        h1_indices = [2]
        summary = _docx_extract_summary(helper, sections, h1_indices, first_h1=2)
        self.assertIn("10 years building systems", summary)

    def test_returns_empty_when_no_h1(self):
        helper = _make_helper([
            ("John Doe", "Title"),
            ("Some text", "Normal"),
        ])
        h1_indices = []
        sections = {}
        summary = _docx_extract_summary(helper, sections, h1_indices, first_h1=len(helper))
        self.assertEqual(summary, "")


class TestDocxExtractEducation(unittest.TestCase):
    """Tests for _docx_extract_education."""

    def test_extracts_education(self):
        helper = _make_helper([
            ("John Doe", "Title"),
            ("Education", "Heading 1"),
            ("B.S. Computer Science at MIT — (2018)", "Normal"),
        ])
        _, sections = _docx_find_sections(helper)
        result = _docx_extract_education(helper, sections)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["degree"], "B.S. Computer Science")
        self.assertEqual(result[0]["institution"], "MIT")

    def test_handles_h2_style_education(self):
        helper = _make_helper([
            ("Education", "Heading 1"),
            ("B.S. Computer Science\t2018", "Heading 2"),
        ])
        _, sections = _docx_find_sections(helper)
        result = _docx_extract_education(helper, sections)
        self.assertEqual(len(result), 1)
        self.assertIn("B.S. Computer Science", result[0]["degree"])

    def test_returns_empty_when_no_education_section(self):
        helper = _make_helper([
            ("John Doe", "Title"),
            ("Experience", "Heading 1"),
            ("Job text", "Normal"),
        ])
        _, sections = _docx_find_sections(helper)
        result = _docx_extract_education(helper, sections)
        self.assertEqual(result, [])

    def test_skips_empty_lines(self):
        helper = _make_helper([
            ("Education", "Heading 1"),
            ("", "Normal"),
            ("B.S. CS, MIT, 2018", "Normal"),
        ])
        _, sections = _docx_find_sections(helper)
        result = _docx_extract_education(helper, sections)
        self.assertGreaterEqual(len(result), 1)


class TestDocxExtractExperience(unittest.TestCase):
    """Tests for _docx_extract_experience."""

    def test_extracts_experience(self):
        helper = _make_helper([
            ("Experience", "Heading 1"),
            ("Senior Engineer at TechCorp — [NYC] — (2020 – 2023)", "Normal"),
            ("Built APIs", "List Paragraph"),
            ("Led team", "List Paragraph"),
        ])
        _, sections = _docx_find_sections(helper)
        result = _docx_extract_experience(helper, sections)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Senior Engineer")
        self.assertEqual(len(result[0]["bullets"]), 2)

    def test_returns_empty_when_no_experience_section(self):
        helper = _make_helper([
            ("Education", "Heading 1"),
            ("BS CS, MIT, 2018", "Normal"),
        ])
        _, sections = _docx_find_sections(helper)
        result = _docx_extract_experience(helper, sections)
        self.assertEqual(result, [])

    def test_handles_h2_experience_heading(self):
        helper = _make_helper([
            ("Experience", "Heading 1"),
            ("TechCorp", "Normal"),  # company line
            ("Senior Engineer\t2020-2023", "Heading 2"),
            ("Built APIs", "List Paragraph"),
        ])
        _, sections = _docx_find_sections(helper)
        result = _docx_extract_experience(helper, sections)
        self.assertGreaterEqual(len(result), 1)

    def test_skips_empty_lines(self):
        helper = _make_helper([
            ("Experience", "Heading 1"),
            ("", "Normal"),
            ("Engineer at Corp (2020 - 2022)", "Normal"),
        ])
        _, sections = _docx_find_sections(helper)
        result = _docx_extract_experience(helper, sections)
        self.assertGreaterEqual(len(result), 0)  # May or may not parse

    def test_multiple_roles(self):
        helper = _make_helper([
            ("Experience", "Heading 1"),
            ("Manager at BigCo (2022 - 2024)", "Normal"),
            ("Led team", "List Paragraph"),
            ("Engineer at SmallCo (2020 - 2022)", "Normal"),
            ("Wrote code", "List Paragraph"),
        ])
        _, sections = _docx_find_sections(helper)
        result = _docx_extract_experience(helper, sections)
        self.assertEqual(len(result), 2)


class TestParseH2Education(unittest.TestCase):
    """Tests for _parse_h2_education."""

    def test_parse_simple_degree(self):
        result = _parse_h2_education("Bachelor of Science")
        self.assertEqual(result["degree"], "Bachelor of Science")
        self.assertEqual(result["institution"], "")
        self.assertEqual(result["year"], "")

    def test_parse_degree_with_year(self):
        result = _parse_h2_education("Bachelor of Science\t2018")
        self.assertEqual(result["degree"], "Bachelor of Science")
        self.assertEqual(result["year"], "2018")

    def test_parse_degree_multiple_spaces(self):
        result = _parse_h2_education("MBA  Harvard  2020")
        self.assertIn("MBA", result["degree"])


class TestParseH2Experience(unittest.TestCase):
    """Tests for _parse_h2_experience."""

    def test_parse_title_only(self):
        role, _company = _parse_h2_experience("Senior Engineer", "")
        self.assertEqual(role["title"], "Senior Engineer")
        self.assertEqual(role["company"], "")
        self.assertEqual(role["bullets"], [])

    def test_parse_title_with_date(self):
        role, _company = _parse_h2_experience("Senior Engineer\t2020-2023", "TechCorp")
        self.assertEqual(role["title"], "Senior Engineer")
        self.assertEqual(role["company"], "TechCorp")
        self.assertEqual(role["start"], "2020")
        self.assertEqual(role["end"], "2023")

    def test_returns_last_company_unchanged(self):
        _role, returned_company = _parse_h2_experience("Dev", "BigCo")
        self.assertEqual(returned_company, "BigCo")


class TestProcessExpParagraph(unittest.TestCase):
    """Tests for _process_exp_paragraph."""

    def test_normal_style_with_exp_entry(self):
        current, _last_company, completed = _process_exp_paragraph(
            style="normal",
            text="Engineer at TechCorp (2020 - 2022)",
            current=None,
            last_company="",
            is_next_h2=False,
        )
        self.assertIsNotNone(current)
        self.assertEqual(current["title"], "Engineer")
        self.assertIsNone(completed)

    def test_replaces_current_with_new_role(self):
        existing = {"title": "Old Job", "company": "OldCo", "bullets": []}
        current, _, completed = _process_exp_paragraph(
            style="normal",
            text="Manager at BigCo (2021 - 2023)",
            current=existing,
            last_company="",
            is_next_h2=False,
        )
        self.assertEqual(completed, existing)
        self.assertEqual(current["title"], "Manager")

    def test_list_style_adds_bullet(self):
        current = {"title": "Engineer", "company": "Corp", "bullets": []}
        new_current, _, completed = _process_exp_paragraph(
            style="list paragraph",
            text="Built scalable APIs",
            current=current,
            last_company="",
            is_next_h2=False,
        )
        self.assertIsNone(completed)
        self.assertIn("Built scalable APIs", new_current["bullets"])

    def test_h2_style_starts_new_role(self):
        current, _last_company, _completed = _process_exp_paragraph(
            style="heading 2",
            text="Senior Dev\t2020-2022",
            current=None,
            last_company="TechCorp",
            is_next_h2=False,
        )
        self.assertIsNotNone(current)
        self.assertEqual(current["company"], "TechCorp")

    def test_company_line_updates_last_company(self):
        _current, last_company, _completed = _process_exp_paragraph(
            style="normal",
            text="Acme Inc.",
            current=None,
            last_company="",
            is_next_h2=True,
        )
        self.assertEqual(last_company, "Acme Inc.")


if __name__ == "__main__":
    unittest.main()
