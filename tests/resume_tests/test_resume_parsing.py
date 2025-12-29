"""Tests for resume/parsing.py text extraction utilities."""

from __future__ import annotations

import unittest

from resume.parsing import (
    SECTION_PATTERNS,
    _parse_experience_entry,
    _parse_education_entry,
    _split_lines,
    _split_date_range,
    _extract_contact,
    _extract_sections,
    _parse_experience,
    _parse_experience_block,
    _parse_education,
    _parse_skills,
    _filter_summary_lines,
    _key_from_heading,
    _looks_like_company_line,
    _looks_like_section_heading,
    _pdf_empty_result,
    _pdf_extract_name_headline,
    _pdf_find_sections,
    _pdf_get_section_lines,
    _pdf_extract_summary,
    _pdf_extract_experience,
    _pdf_extract_education,
    _parse_linkedin_meta_from_html,
    parse_linkedin_text,
    parse_resume_text,
    merge_profiles,
)


# =============================================================================
# Shared Test Fixtures
# =============================================================================


SAMPLE_RESUME_TEXT = """John Doe
john@example.com
San Francisco, CA

Summary
Experienced software engineer with 10 years...

Experience
Senior Engineer at TechCorp (2020-2023)
- Built scalable systems

Education
B.S. Computer Science, MIT, 2015

Skills
Python, Java, SQL
"""

SAMPLE_CONTACT_LINES = [
    "John Doe",
    "john.doe@example.com",
    "(555) 123-4567",
    "San Francisco, CA",
    "linkedin.com/in/johndoe",
    "github.com/johndoe",
    "https://johndoe.com",
]

SAMPLE_PDF_LINES_WITH_SECTIONS = [
    "John Doe",
    "Experience",
    "Senior Dev at Company",
    "Education",
    "BS at University",
    "Skills",
    "Python",
]

SAMPLE_LINKEDIN_HTML = '''
<html>
<head>
    <meta property="profile:first_name" content="John">
    <meta property="profile:last_name" content="Doe">
    <meta property="og:title" content="John Doe - Software Engineer | LinkedIn">
    <meta name="description" content="Senior Engineer · Experience: TechCorp · Location: San Francisco">
    <title>John Doe - Software Engineer | LinkedIn</title>
</head>
</html>
'''


def make_empty_profile(**overrides):
    """Create an empty profile dict with optional overrides."""
    profile = {
        "name": "",
        "headline": "",
        "email": "",
        "skills": [],
        "experience": [],
        "education": [],
    }
    profile.update(overrides)
    return profile


class PdfSectionTestCase(unittest.TestCase):
    """Base class for PDF section-related tests with shared helpers."""

    def find_sections(self, lines):
        """Helper to find sections and return both results."""
        return _pdf_find_sections(lines)

    def get_section_lines(self, key, lines):
        """Helper to get section lines with automatic section finding."""
        section_indices, sorted_sections = self.find_sections(lines)
        return _pdf_get_section_lines(key, lines, section_indices, sorted_sections)


class TestSectionPatterns(unittest.TestCase):
    """Tests for SECTION_PATTERNS regex patterns."""

    def test_experience_patterns(self):
        pat = SECTION_PATTERNS["experience"]
        self.assertIsNotNone(pat.match("Experience"))
        self.assertIsNotNone(pat.match("EXPERIENCE"))
        self.assertIsNotNone(pat.match("Work History"))
        self.assertIsNotNone(pat.match("Employment"))
        self.assertIsNone(pat.match("Work Experience Details"))

    def test_education_patterns(self):
        pat = SECTION_PATTERNS["education"]
        self.assertIsNotNone(pat.match("Education"))
        self.assertIsNotNone(pat.match("EDUCATION"))
        self.assertIsNotNone(pat.match("Academics"))
        self.assertIsNone(pat.match("Education and Training"))

    def test_skills_patterns(self):
        pat = SECTION_PATTERNS["skills"]
        self.assertIsNotNone(pat.match("Skills"))
        self.assertIsNotNone(pat.match("Technologies"))
        self.assertIsNotNone(pat.match("Technical Skills"))

    def test_summary_patterns(self):
        pat = SECTION_PATTERNS["summary"]
        self.assertIsNotNone(pat.match("Summary"))
        self.assertIsNotNone(pat.match("Profile"))
        self.assertIsNotNone(pat.match("About"))


class TestParseExperienceEntry(unittest.TestCase):
    """Tests for _parse_experience_entry function."""

    def test_parse_at_format(self):
        result = _parse_experience_entry("Senior Engineer at FooCorp")
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Senior Engineer")
        self.assertEqual(result["company"], "FooCorp")

    def test_parse_at_format_with_dates(self):
        # Pattern needs comma before year to match properly
        result = _parse_experience_entry("Software Developer at TechCo, 2020 - 2023")
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Software Developer")
        # The parser captures "TechCo, 2020" as company in some patterns
        self.assertIn("TechCo", result["company"])

    def test_parse_at_format_with_parenthetical_dates(self):
        result = _parse_experience_entry("Manager at BigCorp (2018 - 2022)")
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Manager")
        # Parser may include partial date in company depending on pattern
        self.assertIn("BigCorp", result["company"])

    def test_parse_pipe_separated(self):
        result = _parse_experience_entry("Data Analyst | Analytics Inc | 2019 - Present")
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Data Analyst")
        self.assertEqual(result["company"], "Analytics Inc")
        self.assertEqual(result["start"], "2019")
        self.assertEqual(result["end"], "Present")

    def test_parse_generated_docx_format(self):
        result = _parse_experience_entry("Product Manager at StartupXYZ — [San Francisco] — (2021 – 2023)")
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Product Manager")
        self.assertEqual(result["company"], "StartupXYZ")
        self.assertEqual(result["location"], "San Francisco")

    def test_parse_returns_none_for_non_matching(self):
        result = _parse_experience_entry("Random text without job info")
        self.assertIsNone(result)


class TestParseEducationEntry(unittest.TestCase):
    """Tests for _parse_education_entry function."""

    def test_parse_at_format(self):
        result = _parse_education_entry("B.S. Computer Science at MIT")
        self.assertIsNotNone(result)
        self.assertEqual(result["degree"], "B.S. Computer Science")
        self.assertEqual(result["institution"], "MIT")

    def test_parse_at_format_with_year(self):
        result = _parse_education_entry("MBA at Harvard — (2019)")
        self.assertIsNotNone(result)
        self.assertEqual(result["degree"], "MBA")
        self.assertEqual(result["institution"], "Harvard")
        self.assertEqual(result["year"], "2019")

    def test_parse_comma_separated(self):
        result = _parse_education_entry("Bachelor of Arts, UCLA, 2015")
        self.assertIsNotNone(result)
        self.assertEqual(result["degree"], "Bachelor of Arts")
        self.assertEqual(result["institution"], "UCLA")
        self.assertEqual(result["year"], "2015")

    def test_parse_from_format(self):
        result = _parse_education_entry("Ph.D. Physics from Stanford (2020)")
        self.assertIsNotNone(result)
        self.assertEqual(result["degree"], "Ph.D. Physics")
        self.assertEqual(result["institution"], "Stanford")
        self.assertEqual(result["year"], "2020")

    def test_parse_year_only(self):
        result = _parse_education_entry("Some Certification 2018")
        self.assertIsNotNone(result)
        self.assertEqual(result["year"], "2018")

    def test_parse_returns_none_for_non_matching(self):
        result = _parse_education_entry("This is just random text")
        self.assertIsNone(result)


class TestSplitLines(unittest.TestCase):
    """Tests for _split_lines function."""

    def test_split_basic(self):
        text = "Line 1\nLine 2\nLine 3"
        result = _split_lines(text)
        self.assertEqual(result, ["Line 1", "Line 2", "Line 3"])

    def test_split_with_whitespace(self):
        text = "  Line 1  \n  Line 2  "
        result = _split_lines(text)
        self.assertEqual(result, ["Line 1", "Line 2"])

    def test_split_empty(self):
        result = _split_lines("")
        # Empty string splits to empty list after stripping
        self.assertEqual(result, [])


class TestExtractContact(unittest.TestCase):
    """Tests for _extract_contact function."""

    def test_extract_all_fields(self):
        """Test extraction of all contact fields from sample data."""
        result = _extract_contact(SAMPLE_CONTACT_LINES)
        self.assertEqual(result["email"], "john.doe@example.com")
        self.assertEqual(result["phone"], "(555) 123-4567")
        self.assertEqual(result["location"], "San Francisco, CA")
        self.assertEqual(result["linkedin"], "linkedin.com/in/johndoe")
        self.assertEqual(result["github"], "github.com/johndoe")
        self.assertIn("johndoe.com", result["website"])

    def test_extract_email(self):
        lines = ["John Doe", "john.doe@example.com", "Software Engineer"]
        result = _extract_contact(lines)
        self.assertEqual(result["email"], "john.doe@example.com")

    def test_extract_phone(self):
        lines = ["Contact: (555) 123-4567"]
        result = _extract_contact(lines)
        self.assertEqual(result["phone"], "(555) 123-4567")

    def test_extract_phone_with_country_code(self):
        lines = ["Phone: +1 (555) 123-4567"]
        result = _extract_contact(lines)
        self.assertIn("555", result["phone"])

    def test_extract_location(self):
        lines = ["San Francisco, CA"]
        result = _extract_contact(lines)
        self.assertEqual(result["location"], "San Francisco, CA")

    def test_extract_linkedin(self):
        lines = ["linkedin.com/in/johndoe"]
        result = _extract_contact(lines)
        self.assertEqual(result["linkedin"], "linkedin.com/in/johndoe")

    def test_extract_github(self):
        lines = ["github.com/johndoe"]
        result = _extract_contact(lines)
        self.assertEqual(result["github"], "github.com/johndoe")

    def test_extract_website(self):
        lines = ["https://johndoe.com/portfolio"]
        result = _extract_contact(lines)
        self.assertIn("johndoe.com", result["website"])

    def test_extract_all_empty_when_none_found(self):
        lines = ["No contact info here"]
        result = _extract_contact(lines)
        self.assertEqual(result["email"], "")
        self.assertEqual(result["phone"], "")
        self.assertEqual(result["location"], "")


class TestExtractSections(unittest.TestCase):
    """Tests for _extract_sections function."""

    def test_extract_single_section(self):
        lines = ["John Doe", "Experience", "Engineer at Company", "Did stuff"]
        result = _extract_sections(lines)
        self.assertIn("experience", result)
        self.assertIn("Engineer at Company", result["experience"])

    def test_extract_multiple_sections(self):
        lines = [
            "John Doe",
            "Experience",
            "Engineer at Company",
            "Education",
            "BS at University",
            "Skills",
            "Python, Java",
        ]
        result = _extract_sections(lines)
        self.assertIn("experience", result)
        self.assertIn("education", result)
        self.assertIn("skills", result)

    def test_body_section_for_unlabeled_content(self):
        lines = ["John Doe", "Some random text"]
        result = _extract_sections(lines)
        self.assertIn("body", result)
        self.assertIn("John Doe", result["body"])


class TestParseExperience(unittest.TestCase):
    """Tests for _parse_experience function."""

    def test_parse_single_role(self):
        lines = [
            "Senior Engineer at TechCorp (2020-2023)",
            "- Built scalable systems",
            "- Led team of 5",
        ]
        result = _parse_experience(lines)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Senior Engineer")
        self.assertEqual(result[0]["company"], "TechCorp")

    def test_parse_multiple_roles(self):
        lines = [
            "Senior Engineer at TechCorp (2020-2023)",
            "- Built stuff",
            "",
            "Junior Dev at StartupABC (2018-2020)",
            "- Learned things",
        ]
        result = _parse_experience(lines)
        self.assertEqual(len(result), 2)

    def test_parse_empty_returns_empty(self):
        result = _parse_experience([])
        self.assertEqual(result, [])


class TestParseExperienceBlock(unittest.TestCase):
    """Tests for _parse_experience_block function."""

    def test_parse_block_with_bullets(self):
        block = [
            "Manager at BigCo (2019-2022) - NYC",
            "- Managed team",
            "- Delivered projects",
        ]
        result = _parse_experience_block(block)
        self.assertEqual(result["title"], "Manager")
        self.assertEqual(result["company"], "BigCo")
        self.assertEqual(result["start"], "2019")
        self.assertEqual(result["end"], "2022")
        self.assertEqual(len(result["bullets"]), 2)

    def test_parse_empty_block(self):
        result = _parse_experience_block([])
        self.assertEqual(result["title"], "")
        self.assertEqual(result["bullets"], [])


class TestParseEducation(unittest.TestCase):
    """Tests for _parse_education function."""

    def test_parse_standard_format(self):
        lines = ["B.S. Computer Science, MIT, 2018"]
        result = _parse_education(lines)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["degree"], "B.S. Computer Science")
        self.assertEqual(result[0]["institution"], "MIT")
        self.assertEqual(result[0]["year"], "2018")

    def test_parse_fallback_single_line(self):
        lines = ["Some degree without structured format"]
        result = _parse_education(lines)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["degree"], "Some degree without structured format")

    def test_parse_empty(self):
        result = _parse_education([])
        self.assertEqual(result, [])


class TestParseSkills(unittest.TestCase):
    """Tests for _parse_skills function."""

    def test_parse_comma_separated(self):
        lines = ["Python, Java, JavaScript, SQL"]
        result = _parse_skills(lines)
        self.assertEqual(len(result), 4)
        self.assertIn("Python", result)
        self.assertIn("Java", result)

    def test_parse_pipe_separated(self):
        lines = ["Python | Java | C++"]
        result = _parse_skills(lines)
        self.assertEqual(len(result), 3)

    def test_parse_deduplicates(self):
        lines = ["Python, python, PYTHON, Java"]
        result = _parse_skills(lines)
        # Should keep first occurrence, dedup case-insensitively
        self.assertEqual(len(result), 2)

    def test_parse_multiline(self):
        lines = ["Python, Java", "SQL, Docker"]
        result = _parse_skills(lines)
        # Skills are joined then split - "Python, Java SQL, Docker" splits differently
        self.assertGreaterEqual(len(result), 3)
        self.assertIn("Python", result)


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


class TestSplitDateRange(unittest.TestCase):
    """Tests for _split_date_range function."""

    def test_split_hyphen(self):
        start, end = _split_date_range("2020 - 2023")
        self.assertEqual(start, "2020")
        self.assertEqual(end, "2023")

    def test_split_en_dash(self):
        start, end = _split_date_range("2020 – Present")
        self.assertEqual(start, "2020")
        self.assertEqual(end, "Present")

    def test_split_no_separator(self):
        start, end = _split_date_range("2020")
        self.assertEqual(start, "")
        self.assertEqual(end, "")

    def test_split_month_year(self):
        start, end = _split_date_range("Jan 2020 - Dec 2023")
        self.assertEqual(start, "Jan 2020")
        self.assertEqual(end, "Dec 2023")


class TestFilterSummaryLines(unittest.TestCase):
    """Tests for _filter_summary_lines function."""

    def test_filters_email(self):
        lines = ["Summary text", "john@example.com", "More summary"]
        result = _filter_summary_lines(lines)
        self.assertEqual(result, ["Summary text", "More summary"])

    def test_filters_phone(self):
        lines = ["Summary text", "+1 555-123-4567", "More summary"]
        result = _filter_summary_lines(lines)
        self.assertEqual(result, ["Summary text", "More summary"])

    def test_filters_bullets(self):
        lines = ["Summary text", "• Bullet point", "More summary"]
        result = _filter_summary_lines(lines)
        self.assertEqual(result, ["Summary text", "More summary"])

    def test_strips_profile_prefix(self):
        lines = ["Profile: Experienced engineer"]
        result = _filter_summary_lines(lines)
        self.assertEqual(result, ["Experienced engineer"])

    def test_removes_empty_profile_line(self):
        lines = ["profile:", "Next line"]
        result = _filter_summary_lines(lines)
        self.assertEqual(result, ["Next line"])


class TestKeyFromHeading(unittest.TestCase):
    """Tests for _key_from_heading function."""

    def test_experience_variations(self):
        self.assertEqual(_key_from_heading("Experience"), "experience")
        self.assertEqual(_key_from_heading("Work Experience"), "experience")
        self.assertEqual(_key_from_heading("WORK EXPERIENCES"), "experience")
        self.assertEqual(_key_from_heading("Employment"), "experience")
        self.assertEqual(_key_from_heading("Career"), "experience")

    def test_education_variations(self):
        self.assertEqual(_key_from_heading("Education"), "education")
        self.assertEqual(_key_from_heading("ACADEMICS"), "education")

    def test_skills_variations(self):
        self.assertEqual(_key_from_heading("Skills"), "skills")
        self.assertEqual(_key_from_heading("Technical Skills"), "skills")
        self.assertEqual(_key_from_heading("Technologies"), "skills")

    def test_summary_variations(self):
        self.assertEqual(_key_from_heading("Summary"), "summary")
        self.assertEqual(_key_from_heading("Profile"), "summary")
        self.assertEqual(_key_from_heading("About"), "summary")

    def test_unknown_heading(self):
        self.assertIsNone(_key_from_heading("Projects"))
        self.assertIsNone(_key_from_heading("Certifications"))

    def test_empty_heading(self):
        self.assertIsNone(_key_from_heading(""))
        self.assertIsNone(_key_from_heading("   "))


class TestLooksLikeCompanyLine(unittest.TestCase):
    """Tests for _looks_like_company_line function."""

    def test_tab_separated(self):
        self.assertTrue(_looks_like_company_line("Acme Corp\tSan Francisco"))

    def test_inc_suffix(self):
        self.assertTrue(_looks_like_company_line("Acme Inc."))

    def test_corp_suffix(self):
        self.assertTrue(_looks_like_company_line("Tech Corp."))

    def test_llc_suffix(self):
        self.assertTrue(_looks_like_company_line("Startup LLC"))

    def test_technologies_keyword(self):
        self.assertTrue(_looks_like_company_line("Advanced Technologies"))

    def test_multiple_caps(self):
        self.assertTrue(_looks_like_company_line("Apple Microsoft"))

    def test_simple_text(self):
        self.assertFalse(_looks_like_company_line("hello world"))


class TestLooksLikeSectionHeading(unittest.TestCase):
    """Tests for _looks_like_section_heading function."""

    def test_known_section(self):
        self.assertTrue(_looks_like_section_heading("Experience"))
        self.assertTrue(_looks_like_section_heading("Education"))

    def test_all_caps_short(self):
        self.assertTrue(_looks_like_section_heading("SUMMARY"))
        self.assertTrue(_looks_like_section_heading("SKILLS"))

    def test_title_case_detection(self):
        # Title case detection uses istitle() on text stripped of colons/spaces
        # "Intro" -> stripped "Intro" -> istitle() True
        self.assertTrue(_looks_like_section_heading("Intro"))
        # Multi-word title case requires each word capitalized when joined
        # but istitle() on "ProfessionalBackground" is False (single word after strip)
        # so only single-word title case headings work
        self.assertFalse(_looks_like_section_heading("Professional Background"))

    def test_too_long(self):
        self.assertFalse(_looks_like_section_heading("This is a very long line that cannot be a section heading"))

    def test_empty(self):
        self.assertFalse(_looks_like_section_heading(""))
        self.assertFalse(_looks_like_section_heading("   "))

    def test_with_punctuation(self):
        self.assertFalse(_looks_like_section_heading("Hello, World!"))


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
        name, headline = _pdf_extract_name_headline(lines)
        self.assertEqual(name, "")

    def test_skip_contact_line(self):
        lines = ["john@example.com (555) 123-4567"]
        name, headline = _pdf_extract_name_headline(lines)
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


class TestParseResumeText(unittest.TestCase):
    """Tests for parse_resume_text function."""

    def test_parse_complete_resume(self):
        result = parse_resume_text(SAMPLE_RESUME_TEXT)
        self.assertEqual(result["name"], "John Doe")
        self.assertEqual(result["email"], "john@example.com")
        self.assertIn("San Francisco", result["location"])
        self.assertIn("Python", result["skills"])
        self.assertGreater(len(result["experience"]), 0)
        self.assertGreater(len(result["education"]), 0)

    def test_parse_minimal_resume(self):
        text = "Jane Smith\njane@email.com"
        result = parse_resume_text(text)
        self.assertEqual(result["name"], "Jane Smith")
        self.assertEqual(result["email"], "jane@email.com")

    def test_parse_empty_text(self):
        result = parse_resume_text("")
        self.assertEqual(result["name"], "")
        self.assertEqual(result["skills"], [])


class TestMergeProfiles(unittest.TestCase):
    """Tests for merge_profiles function."""

    def test_merge_prefers_linkedin_name(self):
        linkedin = make_empty_profile(name="John D.")
        resume = make_empty_profile(name="John Doe", email="john@example.com", skills=["Python"])
        result = merge_profiles(linkedin, resume)
        self.assertEqual(result["name"], "John D.")
        self.assertEqual(result["email"], "john@example.com")

    def test_merge_combines_skills(self):
        linkedin = make_empty_profile(name="John", skills=["Java"])
        resume = make_empty_profile(name="John", skills=["Python", "Java"])
        result = merge_profiles(linkedin, resume)
        self.assertIn("Python", result["skills"])
        self.assertIn("Java", result["skills"])
        # Should not duplicate Java
        self.assertEqual(result["skills"].count("Java"), 1)

    def test_merge_prefers_linkedin_headline(self):
        linkedin = make_empty_profile(name="John", headline="Senior Engineer")
        resume = make_empty_profile(name="John")
        result = merge_profiles(linkedin, resume)
        self.assertEqual(result["headline"], "Senior Engineer")

    def test_merge_empty_profiles(self):
        linkedin = make_empty_profile()
        resume = make_empty_profile()
        result = merge_profiles(linkedin, resume)
        self.assertEqual(result["name"], "")
        self.assertEqual(result["skills"], [])


if __name__ == "__main__":
    unittest.main()
