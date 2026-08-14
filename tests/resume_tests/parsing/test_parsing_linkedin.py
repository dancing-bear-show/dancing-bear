"""Tests for resume LinkedIn and PDF parsing helpers."""

from __future__ import annotations

import unittest

from resume.parsing_experience_pdf import (
    _pdf_empty_result,
    _pdf_extract_name_headline,
    _pdf_find_sections,
    _pdf_get_section_lines,
    _pdf_extract_summary,
    _pdf_extract_experience,
    _pdf_extract_education,
)
from resume.parsing_linkedin import (
    _parse_linkedin_meta_from_html,
    parse_linkedin_text,
)
from tests.resume_tests.fixtures import (
    SAMPLE_LINKEDIN_HTML,
    SAMPLE_PDF_LINES_WITH_SECTIONS,
    SAMPLE_RESUME_TEXT,
)


class PdfSectionTestCase(unittest.TestCase):
    """Base class for PDF section-related tests with shared helpers."""

    def find_sections(self, lines):
        """Helper to find sections and return both results."""
        return _pdf_find_sections(lines)

    def get_section_lines(self, key, lines):
        """Helper to get section lines with automatic section finding."""
        section_indices, sorted_sections = self.find_sections(lines)
        return _pdf_get_section_lines(key, lines, section_indices, sorted_sections)


class TestPdfEmptyResult(unittest.TestCase):
    """Tests for _pdf_empty_result function."""

    def test_returns_empty_structure(self):
        result = _pdf_empty_result()
        self.assertEqual(result["name"], "")
        self.assertEqual(result["email"], "")
        self.assertEqual(result["skills"], [])
        self.assertEqual(result["experience"], [])
        self.assertEqual(result["education"], [])


class TestPdfExtractNameHeadline(unittest.TestCase):
    """Tests for _pdf_extract_name_headline function."""

    def test_extract_name_from_first_line(self):
        lines = ["John Doe", "Software Engineer", "john@example.com"]
        name, headline = _pdf_extract_name_headline(lines)
        self.assertEqual(name, "John Doe")
        self.assertEqual(headline, "Software Engineer")

    def test_skip_section_heading(self):
        lines = ["Experience", "Senior Dev at Company"]
        name, _headline = _pdf_extract_name_headline(lines)
        self.assertEqual(name, "")

    def test_skip_contact_line(self):
        lines = ["john@example.com (555) 123-4567"]
        name, _headline = _pdf_extract_name_headline(lines)
        self.assertEqual(name, "")

    def test_empty_lines(self):
        name, headline = _pdf_extract_name_headline([])
        self.assertEqual(name, "")
        self.assertEqual(headline, "")


class TestPdfFindSections(PdfSectionTestCase):
    """Tests for _pdf_find_sections function."""

    def test_find_multiple_sections(self):
        section_indices, _ = self.find_sections(SAMPLE_PDF_LINES_WITH_SECTIONS)
        self.assertIn("experience", section_indices)
        self.assertIn("education", section_indices)
        self.assertEqual(section_indices["experience"], 1)
        self.assertEqual(section_indices["education"], 3)

    def test_no_sections(self):
        lines = ["John Doe", "Software Engineer", "Some text"]
        section_indices, _ = self.find_sections(lines)
        self.assertEqual(len(section_indices), 0)

    def test_sorted_by_index(self):
        _, sorted_sections = self.find_sections(SAMPLE_PDF_LINES_WITH_SECTIONS)
        indices = [idx for _, idx in sorted_sections]
        self.assertEqual(indices, sorted(indices))


class TestPdfGetSectionLines(PdfSectionTestCase):
    """Tests for _pdf_get_section_lines function."""

    def test_get_section_content(self):
        lines = ["Name", "Experience", "Job 1", "Job 2", "Education", "Degree"]
        exp_lines = self.get_section_lines("experience", lines)
        self.assertEqual(exp_lines, ["Job 1", "Job 2"])

    def test_missing_section(self):
        lines = ["Name", "Experience", "Job 1"]
        skill_lines = self.get_section_lines("skills", lines)
        self.assertEqual(skill_lines, [])

    def test_last_section_to_end(self):
        lines = ["Experience", "Job 1", "Skills", "Python", "Java"]
        skill_lines = self.get_section_lines("skills", lines)
        self.assertEqual(skill_lines, ["Python", "Java"])


class TestPdfExtractSummary(PdfSectionTestCase):
    """Tests for _pdf_extract_summary function."""

    def _extract_summary(self, lines, has_name=True):
        """Helper to extract summary with automatic section finding."""
        section_indices, sorted_sections = self.find_sections(lines)
        return _pdf_extract_summary(lines, section_indices, sorted_sections, has_name)

    def test_extract_from_summary_section(self):
        # Avoid words containing section keywords as substrings
        lines = ["Name", "Summary", "Senior software developer", "Skills", "Python"]
        summary = self._extract_summary(lines)
        self.assertEqual(summary, "Senior software developer")

    def test_extract_preface_when_no_summary_section(self):
        # Use content that won't be detected as section headings
        # Avoid words containing section keywords like "about", "experience", "skills"
        # Need content after index 2 (name + headline) but before first section
        lines = ["John Doe", "Software Developer", "10 years of coding", "Skills", "Java"]
        summary = self._extract_summary(lines)
        self.assertIn("10 years of coding", summary)

    def test_no_sections_returns_empty(self):
        lines = ["John Doe", "Some text"]
        summary = self._extract_summary(lines)
        self.assertEqual(summary, "")


class TestPdfExtractExperience(unittest.TestCase):
    """Tests for _pdf_extract_experience function."""

    def test_extract_experience_entries(self):
        lines = [
            "Senior Engineer at TechCorp, 2020 - 2023",
            "• Built scalable systems",
            "• Led team initiatives",
        ]
        result = _pdf_extract_experience(lines)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Senior Engineer")
        self.assertIn("TechCorp", result[0]["company"])
        self.assertEqual(len(result[0]["bullets"]), 2)

    def test_extract_multiple_jobs(self):
        lines = [
            "Manager at BigCo (2020 - 2022)",
            "• Managed team",
            "Developer at SmallCo (2018 - 2020)",
            "• Wrote code",
        ]
        result = _pdf_extract_experience(lines)
        self.assertEqual(len(result), 2)

    def test_empty_lines(self):
        result = _pdf_extract_experience([])
        self.assertEqual(result, [])


class TestPdfExtractEducation(unittest.TestCase):
    """Tests for _pdf_extract_education function."""

    def test_extract_education_entries(self):
        lines = [
            "B.S. Computer Science, MIT, 2018",
            "MBA at Harvard — (2020)",
        ]
        result = _pdf_extract_education(lines)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["degree"], "B.S. Computer Science")
        self.assertEqual(result[1]["degree"], "MBA")

    def test_empty_lines(self):
        result = _pdf_extract_education([])
        self.assertEqual(result, [])


class TestParseLinkedinMetaFromHtml(unittest.TestCase):
    """Tests for _parse_linkedin_meta_from_html function."""

    def test_parse_og_tags(self):
        result = _parse_linkedin_meta_from_html(SAMPLE_LINKEDIN_HTML)
        self.assertEqual(result["name"], "John Doe")
        self.assertEqual(result["headline"], "Software Engineer")

    def test_parse_description(self):
        # SAMPLE_LINKEDIN_HTML includes description with location
        result = _parse_linkedin_meta_from_html(SAMPLE_LINKEDIN_HTML)
        self.assertEqual(result["summary"], "Senior Engineer")
        self.assertEqual(result["location"], "San Francisco")

    def test_returns_empty_when_no_data(self):
        html = '<html><head></head><body></body></html>'
        result = _parse_linkedin_meta_from_html(html)
        self.assertEqual(result, {})


class TestParseLinkedinText(unittest.TestCase):
    """Tests for parse_linkedin_text function."""

    def test_parse_plain_text(self):
        result = parse_linkedin_text(SAMPLE_RESUME_TEXT)
        self.assertEqual(result["name"], "John Doe")
        self.assertEqual(result["email"], "john@example.com")
        self.assertIn("San Francisco", result["location"])
        self.assertIn("Python", result["skills"])

    def test_parse_returns_structure(self):
        text = "Simple Name\nsimple@email.com"
        result = parse_linkedin_text(text)
        self.assertIn("name", result)
        self.assertIn("email", result)
        self.assertIn("skills", result)
        self.assertIn("experience", result)
        self.assertIn("education", result)


if __name__ == "__main__":
    unittest.main()
