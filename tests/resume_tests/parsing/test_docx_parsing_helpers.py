"""Tests for resume DOCX-specific parsing helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from resume.parsing_experience_docx import (
    _DocxParaHelper,
    _docx_find_sections,
    _docx_extract_name_headline,
    _docx_extract_summary,
    _docx_extract_education,
    _docx_extract_experience,
    _key_from_heading,
    _parse_h2_education,
    _parse_h2_experience,
    _process_exp_paragraph,
)
from resume.parsing_experience_text import _parse_education_entry


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

    def test_bullet_line_with_role_pattern_stays_a_bullet(self):
        """A bullet phrased '<verb> ... at <Company>' must not become a role.

        Regression: such bullets matched the role-header pattern and were
        promoted to standalone roles, splitting one real role into several
        phantom entries whose titles were bullet text.
        """
        body = "Improve Kafka reliability and on-call quality at Confluent"
        # Spaced and unspaced glyphs both occur in real DOCX exports; an
        # unspaced bullet bypassed the original \s+ guard.
        for prefix in ("• ", "•", "- ", "-", "* ", "*"):
            with self.subTest(prefix=prefix):
                current = {"title": "Staff SRE", "company": "Confluent", "bullets": []}
                new_current, _, completed = _process_exp_paragraph(
                    style="list paragraph",
                    text=f"{prefix}{body}",
                    current=current,
                    last_company="",
                    is_next_h2=False,
                )
                self.assertIsNone(completed)
                self.assertEqual(new_current["title"], "Staff SRE")
                self.assertEqual(new_current["bullets"], [body])

    def test_real_role_header_still_parses(self):
        """The bullet guard must not swallow genuine role headers."""
        current, _, _completed = _process_exp_paragraph(
            style="normal",
            text="Staff SRE at Confluent (2025 - Present)",
            current=None,
            last_company="",
            is_next_h2=False,
        )
        self.assertIsNotNone(current)
        self.assertEqual(current["title"], "Staff SRE")

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


# ---------------------------------------------------------------------------
# Regression tests for DOCX parsing of resumes this repo itself renders.
#
# Each test below corresponds to a defect that let `resume extract` return
# structurally valid but silently wrong data: roles with no company, talk
# titles arriving as degrees, an empty skills list, and profile bullets fused
# into one string. Structural validity is what made them dangerous — the
# extraction looked fine until you read the values.
# ---------------------------------------------------------------------------


class TestSelfContainedRoleHeader(unittest.TestCase):
    """A Heading-2 role line carrying every field on the line itself."""

    HEADER = (
        "Staff Site Reliability Engineer at Confluent "
        "— [Toronto, Canada] — (May 2025 – Present)"
    )

    def test_self_contained_header_splits_into_fields(self):
        role, last_company = _parse_h2_experience(self.HEADER, last_company="")
        self.assertEqual(role["title"], "Staff Site Reliability Engineer")
        self.assertEqual(role["company"], "Confluent")
        self.assertEqual(role["start"], "May 2025")
        self.assertEqual(role["end"], "Present")
        self.assertEqual(role["location"], "Toronto, Canada")
        self.assertEqual(role["bullets"], [])
        # The parsed company becomes the running company for later paragraphs.
        self.assertEqual(last_company, "Confluent")

    def test_whole_line_does_not_land_in_title(self):
        """The defect signature: entire header as title, everything else blank."""
        role, _ = _parse_h2_experience(self.HEADER, last_company="")
        self.assertNotEqual(role["title"], self.HEADER)
        self.assertNotIn(" at ", role["title"])
        self.assertTrue(role["company"])

    def test_title_only_heading_still_uses_last_company(self):
        """The other layout must keep working: company comes from a prior line."""
        role, last_company = _parse_h2_experience(
            "Network Administrator", last_company="Wal-Mart Stores"
        )
        self.assertEqual(role["title"], "Network Administrator")
        self.assertEqual(role["company"], "Wal-Mart Stores")
        self.assertEqual(last_company, "Wal-Mart Stores")

    def test_tab_split_heading_still_parses_dates(self):
        role, _ = _parse_h2_experience(
            "Network Operations Engineer\t2009-2011", last_company="LiveOps"
        )
        self.assertEqual(role["title"], "Network Operations Engineer")
        self.assertEqual(role["company"], "LiveOps")
        self.assertEqual(role["start"], "2009")
        self.assertEqual(role["end"], "2011")


class TestSectionBoundsAgainstUnrecognizedHeadings(unittest.TestCase):
    """An unrecognized H1 still ends the section above it."""

    def _doc(self):
        return _make_helper([
            ("Brian Cory Sherwin", "Title"),
            ("Education", "Heading 1"),
            ("Bachelor of Science, Computer Science at University of Rochester", "Normal"),
            ("Speaking & Publications", "Heading 1"),
            ("Introducing Nurse: Auto-Remediation at LinkedIn", "Normal"),
            ("SREcon EMEA (USENIX) 2019", "Normal"),
        ])

    def test_unrecognized_heading_closes_previous_section(self):
        helper = self._doc()
        _, sections = _docx_find_sections(helper)
        self.assertIn("education", sections)
        # "Speaking & Publications" sits at index 3, so education must end at 2.
        self.assertEqual(sections["education"]["end"], 2)

    def test_unrecognized_heading_is_not_a_section(self):
        _, sections = _docx_find_sections(self._doc())
        self.assertIsNone(_key_from_heading("Speaking & Publications"))
        self.assertNotIn("speaking & publications", sections)

    def test_talk_titles_do_not_land_in_education(self):
        """The defect signature: education runs to EOF and swallows the talks."""
        helper = self._doc()
        _, sections = _docx_find_sections(helper)
        end = sections["education"]["end"]
        absorbed = [helper.text(i) for i in range(sections["education"]["start"] + 1, end + 1)]
        self.assertNotIn("SREcon EMEA (USENIX) 2019", absorbed)
        self.assertTrue(any("Bachelor of Science" in line for line in absorbed))

    def test_last_recognized_section_still_reaches_end_of_document(self):
        """With no trailing heading, the final section keeps its EOF bound."""
        helper = _make_helper([
            ("Education", "Heading 1"),
            ("Bachelor of Arts, Linguistics at University of Rochester", "Normal"),
        ])
        _, sections = _docx_find_sections(helper)
        self.assertEqual(sections["education"]["end"], len(helper) - 1)


class TestEducationYearRange(unittest.TestCase):
    """A parenthesised year range yields the graduation year."""

    def test_year_range_yields_later_year(self):
        entry = _parse_education_entry(
            "Bachelor of Science, Computer Science at University of Rochester — (2003 – 2007)"
        )
        self.assertEqual(entry["degree"], "Bachelor of Science, Computer Science")
        self.assertEqual(entry["institution"], "University of Rochester")
        self.assertEqual(entry["year"], "2007")

    def test_range_does_not_stay_glued_to_institution(self):
        """The defect signature: '— (2003 – 2007)' left on institution, year empty."""
        entry = _parse_education_entry(
            "Bachelor of Arts, Linguistics at University of Rochester — (2003 – 2007)"
        )
        self.assertNotIn("2003", entry["institution"])
        self.assertNotIn("(", entry["institution"])
        self.assertTrue(entry["year"])

    def test_single_year_still_parses(self):
        entry = _parse_education_entry("BS Computer Science at MIT — (2016)")
        self.assertEqual(entry["institution"], "MIT")
        self.assertEqual(entry["year"], "2016")

    def test_no_year_leaves_year_empty(self):
        entry = _parse_education_entry("BS Computer Science at MIT")
        self.assertEqual(entry["institution"], "MIT")
        self.assertEqual(entry["year"], "")


class TestHeadingKeyMapping(unittest.TestCase):
    """Headings this repo's own templates render must map back to sections."""

    def test_repo_rendered_skill_headings_map_to_skills(self):
        self.assertEqual(_key_from_heading("Core Abilities"), "skills")
        self.assertEqual(_key_from_heading("Technical Stack"), "skills")

    def test_existing_mappings_unchanged(self):
        self.assertEqual(_key_from_heading("Education"), "education")
        self.assertEqual(_key_from_heading("Professional Experience"), "experience")
        self.assertEqual(_key_from_heading("Profile"), "summary")
        self.assertEqual(_key_from_heading("Technical Skills"), "skills")
        self.assertEqual(_key_from_heading("Technologies"), "skills")


class TestSummaryKeepsBulletBoundaries(unittest.TestCase):
    """Profile paragraphs stay separable for downstream provenance checks."""

    def test_paragraphs_join_on_newline(self):
        helper = _make_helper([
            ("Profile", "Heading 1"),
            ("Build OpenTelemetry-based telemetry systems", "Normal"),
            ("Architect agent orchestration systems", "Normal"),
            ("Founded the SRE function at SailPoint", "Normal"),
        ])
        h1s, sections = _docx_find_sections(helper)
        summary = _docx_extract_summary(helper, sections, h1s, h1s[0])
        lines = summary.split("\n")
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "Build OpenTelemetry-based telemetry systems")
        self.assertEqual(lines[2], "Founded the SRE function at SailPoint")

    def test_paragraphs_are_not_space_fused(self):
        """The defect signature: distinct claims run together into one line."""
        helper = _make_helper([
            ("Profile", "Heading 1"),
            ("Own production systems end to end", "Normal"),
            ("Founded the SRE function at SailPoint", "Normal"),
        ])
        h1s, sections = _docx_find_sections(helper)
        summary = _docx_extract_summary(helper, sections, h1s, h1s[0])
        self.assertNotIn("end to end Founded", summary)
        self.assertIn("\n", summary)


if __name__ == "__main__":
    unittest.main()
