"""Tests for resume/parsing_experience_pdf.py — PDF parsing helpers and parse_resume_pdf."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

from resume.parsing_experience_pdf import (
    _pdf_empty_result,
    _pdf_extract_education,
    _pdf_extract_experience,
    _pdf_extract_summary,
    _pdf_find_sections,
    parse_resume_pdf,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find(lines):
    """Return (section_indices, sorted_sections) for the given lines."""
    return _pdf_find_sections(lines)


def _summary(lines, has_name=True):
    section_indices, sorted_sections = _find(lines)
    return _pdf_extract_summary(lines, section_indices, sorted_sections, has_name)


# ---------------------------------------------------------------------------
# _pdf_extract_summary — branch 96->97 (first_section_idx <= start_idx)
# ---------------------------------------------------------------------------

class TestPdfExtractSummaryBranches(unittest.TestCase):
    """Cover the branch where the first section starts at or before the name+headline offset."""

    def test_summary_section_header_immediately_after_name_returns_empty(self):
        # start_idx is 2 (has_name=True). If first section is at index 2 or earlier,
        # there is no preface content to harvest and the function returns "".
        lines = ["John Doe", "Engineer", "Skills", "Python"]
        # "Skills" is a section heading at index 2 == start_idx -> should return ""
        result = _summary(lines, has_name=True)
        self.assertEqual(result, "")

    def test_summary_section_at_index_zero_has_name_false_returns_empty(self):
        # has_name=False means start_idx=0; section at index 0 -> first_section_idx == 0 == start_idx
        lines = ["Experience", "Dev at Acme"]
        result = _summary(lines, has_name=False)
        self.assertEqual(result, "")

    def test_summary_content_before_first_section_returned(self):
        # start_idx=2, first section at index 4 -> indices 2..4 are preface
        lines = ["John Doe", "Engineer", "Builds reliable systems", "10 years", "Skills", "Python"]
        result = _summary(lines, has_name=True)
        self.assertIn("Builds reliable systems", result)


# ---------------------------------------------------------------------------
# _pdf_extract_experience — branches 119->113 and 121->113 (empty bullet)
# ---------------------------------------------------------------------------

class TestPdfExtractExperienceBullets(unittest.TestCase):
    """Cover bullet-filtering branches in _pdf_extract_experience."""

    def test_whitespace_only_bullet_not_appended(self):
        # A line that is only whitespace after stripping the bullet marker is discarded.
        lines = [
            "Senior Engineer at TechCorp, 2020 - 2023",
            "• ",  # bullet marker with no content -> stripped to "" -> discarded
            "• Built scalable systems",
        ]
        result = _pdf_extract_experience(lines)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["bullets"]), 1)
        self.assertEqual(result[0]["bullets"][0], "Built scalable systems")

    def test_dash_only_bullet_not_appended(self):
        lines = [
            "Manager at BigCo (2019 - 2022)",
            "-",  # bare dash -> stripped to "" -> discarded
            "- Led team",
        ]
        result = _pdf_extract_experience(lines)
        self.assertEqual(len(result[0]["bullets"]), 1)
        self.assertEqual(result[0]["bullets"][0], "Led team")

    def test_non_job_non_current_line_skipped(self):
        # Lines that are neither a job entry nor follow a current job are ignored.
        lines = [
            "Just a random line with no job marker",
        ]
        result = _pdf_extract_experience(lines)
        self.assertEqual(result, [])

    def test_happy_path_all_bullets_appended(self):
        lines = [
            "Developer at Startup (2021 - 2023)",
            "• Deployed microservices",
            "• Reduced latency by 30%",
        ]
        result = _pdf_extract_experience(lines)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["bullets"]), 2)


# ---------------------------------------------------------------------------
# _pdf_extract_education — branch 134->132 (entry is None/falsy)
# ---------------------------------------------------------------------------

class TestPdfExtractEducationFalsyEntry(unittest.TestCase):
    """Cover the branch where _parse_education_entry returns None."""

    def test_unparseable_line_skipped(self):
        # Short strings that match no education pattern return None from
        # _parse_education_entry and are skipped by _pdf_extract_education.
        lines = [
            "abc",  # too short / no pattern match -> None
            "B.S. Computer Science, MIT, 2018",
        ]
        result = _pdf_extract_education(lines)
        # Only the parseable line should produce an entry.
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["degree"], "B.S. Computer Science")

    def test_all_unparseable_returns_empty(self):
        lines = [
            "abc",
            "xyz",
        ]
        result = _pdf_extract_education(lines)
        self.assertEqual(result, [])

    def test_happy_path_all_entries_parsed(self):
        lines = [
            "B.S. Computer Science, MIT, 2018",
            "MBA at Harvard — (2020)",
        ]
        result = _pdf_extract_education(lines)
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# parse_resume_pdf — lines 141-170
# ---------------------------------------------------------------------------

class TestParseResumePdfMissingDependency(unittest.TestCase):
    """parse_resume_pdf raises RuntimeError when pdfminer.six is absent."""

    def test_raises_runtime_error_when_pdfminer_missing(self):
        with patch("resume.io_utils.safe_import", return_value=None):
            with self.assertRaises(RuntimeError) as ctx:
                parse_resume_pdf("/fake/path.pdf")
        self.assertIn("pdfminer", str(ctx.exception).lower())


class TestParseResumePdfEmptyText(unittest.TestCase):
    """parse_resume_pdf returns empty result when extracted text has no non-blank lines."""

    def _run_with_text(self, text: str) -> dict:
        mock_pdfminer = MagicMock()
        mock_extract_text = MagicMock(return_value=text)
        mock_laparams_instance = MagicMock()

        with patch("resume.io_utils.safe_import", return_value=mock_pdfminer):
            with patch.dict(
                sys.modules,
                {
                    "pdfminer": MagicMock(),
                    "pdfminer.high_level": MagicMock(extract_text=mock_extract_text),
                    "pdfminer.layout": MagicMock(
                        LAParams=MagicMock(return_value=mock_laparams_instance)
                    ),
                },
            ):
                return parse_resume_pdf("/fake/path.pdf")

    def test_all_blank_lines_returns_empty_result(self):
        result = self._run_with_text("   \n  \n\n  ")
        empty = _pdf_empty_result()
        self.assertEqual(result["name"], empty["name"])
        self.assertEqual(result["experience"], [])
        self.assertEqual(result["education"], [])

    def test_completely_empty_string_returns_empty_result(self):
        result = self._run_with_text("")
        self.assertEqual(result["experience"], [])
        self.assertEqual(result["skills"], [])


class TestParseResumePdfFullParse(unittest.TestCase):
    """parse_resume_pdf correctly assembles a result from a synthetic text block."""

    _RESUME_TEXT = "\n".join([
        "Jane Smith",
        "Staff Engineer",
        "jane@example.com",
        "415-555-0100",
        "San Francisco, CA",
        "Summary",
        "Builds distributed systems at scale.",
        "Employment",
        "Staff Engineer at CloudCo (2020 - 2023)",
        "• Architected distributed systems",
        "• Mentored junior engineers",
        "Education",
        "B.S. Computer Science, Stanford, 2012",
        "Skills",
        "Python, Go, Kubernetes",
    ])

    def _run(self) -> dict:
        mock_extract_text = MagicMock(return_value=self._RESUME_TEXT)
        mock_laparams_instance = MagicMock()

        with patch("resume.io_utils.safe_import", return_value=MagicMock()):
            with patch.dict(
                sys.modules,
                {
                    "pdfminer": MagicMock(),
                    "pdfminer.high_level": MagicMock(extract_text=mock_extract_text),
                    "pdfminer.layout": MagicMock(
                        LAParams=MagicMock(return_value=mock_laparams_instance)
                    ),
                },
            ):
                return parse_resume_pdf("/fake/resume.pdf")

    def test_name_extracted(self):
        result = self._run()
        self.assertEqual(result["name"], "Jane Smith")

    def test_headline_extracted(self):
        result = self._run()
        self.assertEqual(result["headline"], "Staff Engineer")

    def test_email_extracted(self):
        result = self._run()
        self.assertEqual(result["email"], "jane@example.com")

    def test_summary_extracted(self):
        result = self._run()
        self.assertIn("Builds distributed systems", result["summary"])

    def test_experience_extracted(self):
        result = self._run()
        self.assertEqual(len(result["experience"]), 1)
        self.assertEqual(result["experience"][0]["title"], "Staff Engineer")
        self.assertIn("CloudCo", result["experience"][0]["company"])
        self.assertEqual(len(result["experience"][0]["bullets"]), 2)

    def test_education_extracted(self):
        result = self._run()
        self.assertEqual(len(result["education"]), 1)
        self.assertEqual(result["education"][0]["degree"], "B.S. Computer Science")

    def test_skills_extracted(self):
        result = self._run()
        self.assertIn("Python", result["skills"])

    def test_result_has_all_required_keys(self):
        result = self._run()
        for key in ("name", "headline", "email", "phone", "location", "linkedin",
                    "github", "website", "summary", "skills", "experience", "education"):
            self.assertIn(key, result)


class TestParseResumePdfNoSections(unittest.TestCase):
    """parse_resume_pdf handles a PDF with content but no recognisable section headings."""

    _TEXT = "\n".join([
        "Alex Jones",
        "Data Scientist",
        "alex@example.com",
        "Built models for recommendation engines",
    ])

    def _run(self) -> dict:
        mock_extract_text = MagicMock(return_value=self._TEXT)
        with patch("resume.io_utils.safe_import", return_value=MagicMock()):
            with patch.dict(
                sys.modules,
                {
                    "pdfminer": MagicMock(),
                    "pdfminer.high_level": MagicMock(extract_text=mock_extract_text),
                    "pdfminer.layout": MagicMock(LAParams=MagicMock(return_value=MagicMock())),
                },
            ):
                return parse_resume_pdf("/fake/no_sections.pdf")

    def test_name_still_extracted(self):
        result = self._run()
        self.assertEqual(result["name"], "Alex Jones")

    def test_experience_is_empty_when_no_section(self):
        result = self._run()
        self.assertEqual(result["experience"], [])

    def test_skills_is_empty_when_no_section(self):
        result = self._run()
        self.assertEqual(result["skills"], [])


if __name__ == "__main__":
    unittest.main()
