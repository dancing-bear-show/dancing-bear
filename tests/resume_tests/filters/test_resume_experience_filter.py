"""Tests for resume/experience_filter.py keyword-based filtering."""

from __future__ import annotations

import copy
import unittest

from resume.experience_filter import filter_experience_by_keywords
from tests.resume_tests.fixtures import SAMPLE_CANDIDATE, SAMPLE_EXPERIENCE_ENTRIES


class TestFilterExperienceByKeywords(unittest.TestCase):
    """Tests for filter_experience_by_keywords function."""

    def setUp(self):
        # Use shared fixture with deep copy to avoid mutation
        self.candidate = {
            "name": SAMPLE_CANDIDATE["name"],
            "experience": copy.deepcopy(SAMPLE_EXPERIENCE_ENTRIES),
        }

    def test_filters_by_keyword_in_title(self):
        result = filter_experience_by_keywords(self.candidate, ["Python"])
        # Python role should be kept with higher score
        titles = [e["title"] for e in result["experience"]]
        self.assertIn("Senior Python Developer", titles)

    def test_filters_by_keyword_in_bullets(self):
        result = filter_experience_by_keywords(self.candidate, ["React"])
        titles = [e["title"] for e in result["experience"]]
        self.assertIn("Frontend Developer", titles)

    def test_keeps_only_matching_bullets(self):
        result = filter_experience_by_keywords(self.candidate, ["Python", "FastAPI"])
        python_role = next(e for e in result["experience"] if "Python" in e["title"])
        # Should keep bullets with Python or FastAPI
        self.assertTrue(any("Python" in b or "FastAPI" in b for b in python_role["bullets"]))

    def test_fallback_keeps_first_bullet_if_none_match(self):
        # Match on title only, no bullet matches
        result = filter_experience_by_keywords(self.candidate, ["Java"])
        java_role = next(e for e in result["experience"] if "Java" in e["title"])
        # Should have at least one bullet (the fallback)
        self.assertGreaterEqual(len(java_role["bullets"]), 1)

    def test_respects_max_roles(self):
        result = filter_experience_by_keywords(
            self.candidate, ["Developer"], max_roles=2
        )
        self.assertEqual(len(result["experience"]), 2)

    def test_respects_max_bullets_per_role(self):
        result = filter_experience_by_keywords(
            self.candidate, ["Python", "API", "PostgreSQL"], max_bullets_per_role=1
        )
        for exp in result["experience"]:
            self.assertLessEqual(len(exp["bullets"]), 1)

    def test_respects_min_score(self):
        # With min_score=3, only roles with 3+ keyword hits should remain
        result = filter_experience_by_keywords(
            self.candidate, ["Python", "API", "FastAPI", "PostgreSQL"], min_score=3
        )
        # Python role has multiple matches in title and bullets
        self.assertGreater(len(result["experience"]), 0)

    def test_min_score_filters_low_scoring_roles(self):
        # Use high min_score to filter out everything
        result = filter_experience_by_keywords(
            self.candidate, ["RandomKeyword"], min_score=10
        )
        self.assertEqual(len(result["experience"]), 0)

    def test_sorts_by_score_descending(self):
        result = filter_experience_by_keywords(
            self.candidate, ["Python", "API", "FastAPI"]
        )
        # Python role should be first due to most matches
        if result["experience"]:
            self.assertIn("Python", result["experience"][0]["title"])

    def test_uses_synonyms(self):
        synonyms = {"Python": ["python3", "py"]}
        candidate = {
            "experience": [
                {
                    "title": "Developer",
                    "company": "Startup",
                    "bullets": ["Wrote python3 scripts"],
                }
            ]
        }
        result = filter_experience_by_keywords(
            candidate, ["Python"], synonyms=synonyms
        )
        self.assertEqual(len(result["experience"]), 1)

    def test_returns_copy_of_data(self):
        result = filter_experience_by_keywords(self.candidate, ["Python"])
        self.assertIsNot(result, self.candidate)

    def test_empty_keywords_returns_data_unchanged(self):
        result = filter_experience_by_keywords(self.candidate, [])
        self.assertEqual(result["experience"], self.candidate["experience"])

    def test_empty_experience_returns_data(self):
        data = {"name": "Jane", "experience": []}
        result = filter_experience_by_keywords(data, ["Python"])
        self.assertEqual(result["experience"], [])

    def test_none_experience_returns_data(self):
        data = {"name": "Jane"}
        result = filter_experience_by_keywords(data, ["Python"])
        self.assertNotIn("experience", result)

    def test_preserves_other_fields(self):
        result = filter_experience_by_keywords(self.candidate, ["Python"])
        self.assertEqual(result["name"], "John Doe")


if __name__ == "__main__":
    unittest.main()
