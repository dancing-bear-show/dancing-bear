"""Tests for resume/summarizer.py summary building utilities."""

import unittest

from resume.summarizer import _keyword_hits, build_summary


class TestKeywordHits(unittest.TestCase):
    """Tests for _keyword_hits function."""

    def test_counts_matching_keywords(self):
        text = "Python and Java developer with SQL experience"
        keywords = ["Python", "Java", "SQL"]
        result = _keyword_hits(text, keywords)
        self.assertEqual(result, 3)

    def test_case_insensitive_matching(self):
        text = "PYTHON and python and PyThOn"
        keywords = ["python"]
        result = _keyword_hits(text, keywords)
        self.assertEqual(result, 1)  # Counts keyword once

    def test_no_matches_returns_zero(self):
        text = "No matching keywords here"
        keywords = ["Python", "Java"]
        result = _keyword_hits(text, keywords)
        self.assertEqual(result, 0)

    def test_empty_keywords_returns_zero(self):
        text = "Some text"
        keywords = []
        result = _keyword_hits(text, keywords)
        self.assertEqual(result, 0)

    def test_empty_text_returns_zero(self):
        text = ""
        keywords = ["Python"]
        result = _keyword_hits(text, keywords)
        self.assertEqual(result, 0)

    def test_partial_match_counts(self):
        text = "JavaScript developer"
        keywords = ["Java"]
        result = _keyword_hits(text, keywords)
        self.assertEqual(result, 1)  # "Java" is in "JavaScript"


class TestBuildSummary(unittest.TestCase):
    """Tests for build_summary function."""

    def test_returns_basic_structure(self):
        data = {"name": "John Doe", "headline": "Software Engineer"}
        result = build_summary(data)
        self.assertEqual(result["name"], "John Doe")
        self.assertEqual(result["headline"], "Software Engineer")
        self.assertIn("top_skills", result)
        self.assertIn("experience_highlights", result)

    def test_empty_data_returns_empty_fields(self):
        data = {}
        result = build_summary(data)
        self.assertEqual(result["name"], "")
        self.assertEqual(result["headline"], "")
        self.assertEqual(result["top_skills"], [])
        self.assertEqual(result["experience_highlights"], [])

    def test_extracts_top_skills_from_data(self):
        data = {
            "name": "Jane",
            "skills": ["Python", "Java", "SQL", "Docker", "Kubernetes"],
        }
        result = build_summary(data)
        self.assertEqual(len(result["top_skills"]), 5)
        self.assertIn("Python", result["top_skills"])

    def test_limits_skills_to_ten(self):
        data = {
            "skills": [f"Skill{i}" for i in range(15)],
        }
        result = build_summary(data)
        self.assertEqual(len(result["top_skills"]), 10)

    def test_prioritizes_skills_matching_keywords(self):
        data = {
            "skills": ["JavaScript", "Python", "Ruby", "Go"],
        }
        seed = {"keywords": ["Python", "Go"]}
        result = build_summary(data, seed=seed)
        # Python and Go should be first
        self.assertEqual(result["top_skills"][0], "Python")
        self.assertEqual(result["top_skills"][1], "Go")

    def test_handles_keyword_list_in_seed(self):
        data = {"skills": ["Python", "Java"]}
        seed = {"keywords": ["Python"]}
        result = build_summary(data, seed=seed)
        self.assertEqual(result["top_skills"][0], "Python")

    def test_handles_keyword_string_in_seed(self):
        data = {"skills": ["Python", "Java", "SQL"]}
        seed = {"keywords": "Python, SQL"}
        result = build_summary(data, seed=seed)
        # Python and SQL should be prioritized
        self.assertIn("Python", result["top_skills"][:2])
        self.assertIn("SQL", result["top_skills"][:2])

    def test_extracts_experience_highlights(self):
        data = {
            "experience": [
                {
                    "title": "Senior Engineer",
                    "company": "TechCorp",
                    "bullets": ["Built scalable systems", "Led team of 5"],
                },
            ],
        }
        result = build_summary(data)
        self.assertIn("Senior Engineer at TechCorp", result["experience_highlights"])
        self.assertIn("Built scalable systems", result["experience_highlights"])

    def test_limits_highlights_reasonably(self):
        data = {
            "experience": [
                {
                    "title": f"Role{i}",
                    "company": f"Company{i}",
                    "bullets": [f"Bullet{j}" for j in range(5)],
                }
                for i in range(10)
            ],
        }
        result = build_summary(data)
        # The loop breaks when highlights >= 8, so it may be slightly more
        # due to title + 2 bullets per entry before the check
        self.assertLessEqual(len(result["experience_highlights"]), 12)

    def test_scores_experience_by_keywords(self):
        data = {
            "experience": [
                {
                    "title": "Backend Developer",
                    "company": "StartupA",
                    "bullets": ["Used Ruby on Rails"],
                },
                {
                    "title": "Python Developer",
                    "company": "TechB",
                    "bullets": ["Built Python services", "Python APIs"],
                },
            ],
        }
        seed = {"keywords": ["Python"]}
        result = build_summary(data, seed=seed)
        # Python Developer should be first due to keyword matches
        self.assertTrue(
            result["experience_highlights"][0].startswith("Python Developer")
        )

    def test_handles_missing_experience(self):
        data = {"name": "John", "experience": None}
        result = build_summary(data)
        self.assertEqual(result["experience_highlights"], [])

    def test_handles_empty_experience(self):
        data = {"name": "John", "experience": []}
        result = build_summary(data)
        self.assertEqual(result["experience_highlights"], [])

    def test_handles_experience_without_title_or_company(self):
        data = {
            "experience": [
                {"bullets": ["Did some work"]},
                {"title": "Engineer"},
                {"company": "Corp"},
            ],
        }
        result = build_summary(data)
        # Should extract available data - each generates "title at company" format
        highlights = result["experience_highlights"]
        # "at" is added for formatting even if title or company empty
        self.assertTrue(len(highlights) > 0)

    def test_none_seed_defaults_to_empty(self):
        data = {"name": "Test", "skills": ["Python"]}
        result = build_summary(data, seed=None)
        self.assertEqual(result["top_skills"], ["Python"])

    def test_handles_none_skills(self):
        data = {"name": "Test", "skills": None}
        result = build_summary(data)
        self.assertEqual(result["top_skills"], [])


if __name__ == "__main__":
    unittest.main()
