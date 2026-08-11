"""Regression tests for DOCX parsing of resumes this repo itself renders.

Each test here corresponds to a defect that let `resume extract` return
structurally valid but silently wrong data: roles with no company, talk titles
arriving as degrees, an empty skills list, and profile bullets fused into one
string. Structural validity is what made them dangerous — the extraction looked
fine until you read the values.
"""

import unittest

from resume.parsing_experience_docx import (
    _DocxParaHelper,
    _docx_extract_summary,
    _docx_find_sections,
    _key_from_heading,
    _parse_h2_experience,
)
from resume.parsing_experience_text import _parse_education_entry


class _FakeStyle:
    def __init__(self, name):
        self.name = name


class _FakePara:
    """Minimal stand-in for a python-docx paragraph (.text and .style.name)."""

    def __init__(self, text, style="Normal"):
        self.text = text
        self.style = _FakeStyle(style)


def _helper(pairs):
    """Build a _DocxParaHelper from (text, style) pairs."""
    return _DocxParaHelper([_FakePara(t, s) for t, s in pairs])


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
        return _helper([
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
        helper = _helper([
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
        helper = _helper([
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
        helper = _helper([
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
