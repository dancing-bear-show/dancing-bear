"""Regression tests for four extraction defects found parsing a real resume.

Every one produced plausible-looking output with no error, which is what let
them survive: a truncated employer, a missing location, bullet glyphs in prose,
and a skills section shredded into sentence fragments.

Sad-path methods use the test_rejects_* / test_invalid_* naming contract from
workflows/resume/consolidate-schema.yaml so the ratio stays countable.
"""

from __future__ import annotations

import unittest

from resume.parsing_experience_text import (
    _PAT_LOCATION,
    _parse_experience_entry,
    _parse_skills,
    parse_skill_groups,
    strip_bullet_glyph,
)


class TestHyphenatedCompanyNames(unittest.TestCase):
    """A hyphen inside a company name is not a field separator."""

    def test_preserves_hyphenated_company(self):
        """Regression: "Wal-Mart Stores Inc." parsed as company "Wal".

        The location separator was `[—\\-]`, so the hyphen inside the employer
        matched and the tail leaked into `location`. This corrupts data that
        then appears on a resume sent to an employer.
        """
        r = _parse_experience_entry(
            "Network Administrator at Wal-Mart Stores Inc. — (June 2007 – November 2009)"
        )
        self.assertEqual(r["company"], "Wal-Mart Stores Inc.")
        self.assertEqual(r["location"], "")
        self.assertEqual(r["start"], "June 2007")
        self.assertEqual(r["end"], "November 2009")

    def test_preserves_other_hyphenated_employers(self):
        """Any hyphenated employer, not just the one that surfaced the bug."""
        for line, company in [
            ("Engineer at Hewlett-Packard — (2010 – 2012)", "Hewlett-Packard"),
            ("Tech at Rolls-Royce — (2015 – 2018)", "Rolls-Royce"),
            ("Dev at Coca-Cola Company — (2019 – 2021)", "Coca-Cola Company"),
        ]:
            with self.subTest(company=company):
                self.assertEqual(_parse_experience_entry(line)["company"], company)

    def test_em_dash_location_still_parses(self):
        """The real separator must keep working."""
        r = _parse_experience_entry(
            "Staff SRE at Confluent — [Toronto, CA] — (May 2025 – Present)"
        )
        self.assertEqual(r["company"], "Confluent")
        self.assertEqual(r["location"], "Toronto, CA")

    def test_spaced_hyphen_separator_still_parses(self):
        """A hyphen with spaces on both sides is still a separator."""
        r = _parse_experience_entry("Dev at Acme - Toronto, CA - (2020 – 2022)")
        self.assertEqual(r["company"], "Acme")
        self.assertEqual(r["location"], "Toronto, CA")

    def test_invalid_pattern1_falls_through_to_comma_form(self):
        """"Title at Company, dates" must not half-match the dashed pattern.

        It previously yielded company "Acme, 2020" / location "2023"; pattern 1
        now requires a real date range so the comma form reaches pattern 2.
        """
        r = _parse_experience_entry("Engineer at Acme, 2020-2023")
        self.assertEqual(r["company"], "Acme")
        self.assertEqual(r["start"], "2020")
        self.assertEqual(r["end"], "2023")


class TestLocationExtraction(unittest.TestCase):
    """Locations outside the US "City, ST" form were silently dropped."""

    def test_matches_non_us_location(self):
        """Regression: "Richmond Hill, Ontario, Canada" matched nothing."""
        m = _PAT_LOCATION.search(
            "brian@example.com | (416) 801-8094 | Richmond Hill, Ontario, Canada"
        )
        self.assertIsNotNone(m)
        self.assertEqual(m.group(0), "Richmond Hill, Ontario, Canada")

    def test_matches_us_state_abbreviation(self):
        """The original supported form must keep working."""
        m = _PAT_LOCATION.search("jane@example.com | (555) 010-0202 | Austin, TX")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(0), "Austin, TX")

    def test_matches_spelled_out_region(self):
        for line, expected in [
            ("a@b.com | London, England", "London, England"),
            ("a@b.com | San Jose, CA", "San Jose, CA"),
        ]:
            with self.subTest(line=line):
                self.assertEqual(_PAT_LOCATION.search(line).group(0), expected)

    def test_rejects_line_without_location(self):
        """No false positive on a line that carries no place name."""
        self.assertIsNone(_PAT_LOCATION.search("no location here at all"))


class TestBulletGlyphStripping(unittest.TestCase):
    """Leading list markers are formatting, not content."""

    def test_strips_common_glyphs(self):
        for raw, expected in [
            ("• Build and operate systems", "Build and operate systems"),
            ("·  Dot marker", "Dot marker"),
            ("▪ Square", "Square"),
            ("•••Triple", "Triple"),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(strip_bullet_glyph(raw), expected)

    def test_leaves_unmarked_text_untouched(self):
        self.assertEqual(strip_bullet_glyph("No marker here"), "No marker here")

    def test_rejects_stripping_interior_glyph(self):
        """Only a LEADING marker is formatting; an interior one is content."""
        self.assertEqual(
            strip_bullet_glyph("Python • Go • Rust"), "Python • Go • Rust"
        )


class TestSkillsParsing(unittest.TestCase):
    """A bulleted skills section is not a comma-separated inventory."""

    SECTION = [
        "AI & Automation",
        "• LLM-assisted development: manage AI code generation workflows; review, test, and integrate agent outputs",
        "• Agent orchestration: orchestrate multi-agent pipelines",
        "Platform",
        "• AWS: operate production workloads; IAM, EC2/EKS/S3",
    ]

    def test_rejects_splitting_prose_bullets_on_commas(self):
        """Regression: one bullet became fake skills "review" and "test".

        Joining the section then splitting on commas shredded prose. A bulleted
        line is one skill; its label is kept and the description dropped.
        """
        skills = _parse_skills(self.SECTION)
        self.assertIn("LLM-assisted development", skills)
        for fragment in ("review", "test", "and integrate agent outputs"):
            self.assertNotIn(fragment, skills)

    def test_parses_groups_with_titles(self):
        """Category headings must survive; a flat list discards them."""
        groups = parse_skill_groups(self.SECTION)
        self.assertEqual([g["title"] for g in groups], ["AI & Automation", "Platform"])
        self.assertEqual(len(groups[0]["items"]), 2)
        self.assertTrue(groups[0]["items"][0].startswith("LLM-assisted development:"))

    def test_flat_comma_list_still_splits(self):
        """A non-bulleted inventory line is still split on separators."""
        self.assertEqual(
            _parse_skills(["Python, Go, AWS"]), ["Python", "Go", "AWS"]
        )

    def test_invalid_section_without_bullets_yields_no_groups(self):
        """No heading/bullet shape means no groups — callers fall back to flat."""
        self.assertEqual(parse_skill_groups(["Python, Go, AWS"]), [])

    def test_rejects_empty_group_with_no_items(self):
        """A heading with nothing under it is not a group."""
        self.assertEqual(parse_skill_groups(["Platform", "Observability"]), [])

    def test_rejects_glyph_only_line_as_an_item(self):
        """A line holding only a bullet glyph is not a skill.

        strip_bullet_glyph("•") is "", which would render as an empty bullet
        and, worse, keep an otherwise-empty group alive past the non-empty
        filter.
        """
        groups = parse_skill_groups(
            ["Platform", "•", "• AWS: operate workloads", "   •   "]
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["items"], ["AWS: operate workloads"])

    def test_rejects_group_of_only_glyph_lines(self):
        """A heading followed only by empty glyphs yields no group at all."""
        self.assertEqual(parse_skill_groups(["Observability", "•", "  •  "]), [])

    def test_rejects_empty_skill_from_glyph_only_line(self):
        """The flat list must not gain an empty entry either."""
        skills = _parse_skills(["Platform", "•", "• AWS: operate", "  •  "])
        self.assertNotIn("", skills)
        self.assertIn("AWS", skills)


if __name__ == "__main__":
    unittest.main()
