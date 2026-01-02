"""Tests for resume/keyword_matcher.py unified keyword matching."""

from __future__ import annotations

import unittest

from resume.keyword_matcher import (
    KeywordInfo,
    MatchResult,
    KeywordMatcher,
    normalize_text,
    keyword_match,
    expand_keywords,
)
from tests.resume_tests.fixtures import KeywordMatcherTestMixin


class TestKeywordInfo(unittest.TestCase):
    """Tests for KeywordInfo dataclass."""

    def test_default_values(self):
        info = KeywordInfo(keyword="Python")
        self.assertEqual(info.keyword, "Python")
        self.assertEqual(info.tier, "preferred")
        self.assertEqual(info.weight, 1)
        self.assertIsNone(info.category)

    def test_with_values(self):
        info = KeywordInfo(
            keyword="Python",
            tier="required",
            weight=3,
            category="languages",
        )
        self.assertEqual(info.tier, "required")
        self.assertEqual(info.weight, 3)
        self.assertEqual(info.category, "languages")


class TestMatchResult(unittest.TestCase):
    """Tests for MatchResult dataclass."""

    def test_default_values(self):
        result = MatchResult(
            keyword="Python",
            tier="required",
            weight=2,
            category="languages",
        )
        self.assertEqual(result.count, 1)
        self.assertEqual(result.contexts, [])

    def test_to_dict(self):
        result = MatchResult(
            keyword="Python",
            tier="required",
            weight=2,
            category="languages",
            count=3,
        )
        d = result.to_dict()
        self.assertEqual(d["skill"], "Python")
        self.assertEqual(d["tier"], "required")
        self.assertEqual(d["weight"], 2)
        self.assertEqual(d["category"], "languages")
        self.assertEqual(d["count"], 3)


class TestKeywordMatcherSynonyms(KeywordMatcherTestMixin, unittest.TestCase):
    """Tests for KeywordMatcher synonym management."""

    def test_add_synonym(self):
        self.matcher.add_synonym("Python", "python3")
        self.assertEqual(self.matcher.canonicalize("python3"), "Python")

    def test_add_synonyms(self):
        self.matcher.add_synonyms({"Python": ["python3", "py"]})
        self.assertEqual(self.matcher.canonicalize("py"), "Python")
        self.assertEqual(self.matcher.canonicalize("python3"), "Python")

    def test_canonicalize_returns_original_if_not_found(self):
        self.assertEqual(self.matcher.canonicalize("Unknown"), "Unknown")

    def test_get_aliases(self):
        self.matcher.add_synonyms({"Python": ["python3", "py"]})
        aliases = self.matcher.get_aliases("Python")
        self.assertIn("python3", aliases)
        self.assertIn("py", aliases)

    def test_get_aliases_empty(self):
        aliases = self.matcher.get_aliases("Unknown")
        self.assertEqual(aliases, [])

    def test_expand(self):
        self.matcher.add_synonyms({"Python": ["python3", "py"]})
        expanded = self.matcher.expand("Python")
        self.assertIn("Python", expanded)
        self.assertIn("python3", expanded)
        self.assertIn("py", expanded)

    def test_expand_alias(self):
        self.matcher.add_synonyms({"Python": ["python3", "py"]})
        expanded = self.matcher.expand("py")
        self.assertIn("Python", expanded)

    def test_expand_all(self):
        self.matcher.add_synonyms({"Python": ["py"], "JavaScript": ["JS"]})
        expanded = self.matcher.expand_all(["Python", "JavaScript"])
        self.assertIn("Python", expanded)
        self.assertIn("py", expanded)
        self.assertIn("JavaScript", expanded)
        self.assertIn("JS", expanded)

    def test_expand_all_deduplicates(self):
        self.matcher.add_synonyms({"Python": ["py"]})
        expanded = self.matcher.expand_all(["Python", "Python"])
        count = sum(1 for k in expanded if k.lower() == "python")
        self.assertEqual(count, 1)

    def test_chaining(self):
        result = self.matcher.add_synonym("A", "a").add_synonyms({"B": ["b"]})
        self.assertIsInstance(result, KeywordMatcher)


class TestKeywordMatcherKeywordRegistration(KeywordMatcherTestMixin, unittest.TestCase):
    """Tests for KeywordMatcher keyword registration."""

    def test_add_keyword(self):
        self.matcher.add_keyword("Python", tier="required", weight=2)
        self.assertIn("Python", self.matcher.keywords)
        info = self.matcher.get_keyword_info("Python")
        self.assertEqual(info.tier, "required")
        self.assertEqual(info.weight, 2)

    def test_add_keywords(self):
        self.matcher.add_keywords(["Python", "Java"], tier="required")
        self.assertIn("Python", self.matcher.keywords)
        self.assertIn("Java", self.matcher.keywords)

    def test_add_keywords_from_spec(self):
        spec = {
            "required": ["Python", {"skill": "Java", "weight": 2}],
            "preferred": ["Docker"],
            "categories": {
                "tools": ["Git", "VSCode"],
            },
        }
        self.matcher.add_keywords_from_spec(spec)
        self.assertIn("Python", self.matcher.keywords)
        self.assertIn("Java", self.matcher.keywords)
        self.assertIn("Docker", self.matcher.keywords)
        self.assertIn("Git", self.matcher.keywords)

    def test_get_keyword_info_not_found(self):
        info = self.matcher.get_keyword_info("Unknown")
        self.assertIsNone(info)

    def test_keyword_with_category(self):
        self.matcher.add_keyword("Python", category="languages")
        info = self.matcher.get_keyword_info("Python")
        self.assertEqual(info.category, "languages")

    def test_chaining(self):
        result = self.matcher.add_keyword("A").add_keywords(["B", "C"])
        self.assertIsInstance(result, KeywordMatcher)


class TestKeywordMatcherTextMatching(KeywordMatcherTestMixin, unittest.TestCase):
    """Tests for KeywordMatcher text matching."""

    def test_normalize(self):
        self.assertEqual(KeywordMatcher.normalize("  Hello  World  "), "hello world")
        self.assertEqual(KeywordMatcher.normalize(""), "")

    def test_match_keyword(self):
        self.assertTrue(self.matcher.match_keyword("I love Python", "Python"))
        self.assertFalse(self.matcher.match_keyword("I love Java", "Python"))

    def test_match_keyword_case_insensitive(self):
        self.assertTrue(self.matcher.match_keyword("I love PYTHON", "python"))

    def test_match_keyword_word_boundary(self):
        # word_boundary=True still falls back to substring if boundary check fails
        # So "Java" matches "JavaScript" via substring
        self.assertTrue(self.matcher.match_keyword("JavaScript developer", "Java", word_boundary=True))
        # But "Java" also matches as a standalone word
        self.assertTrue(self.matcher.match_keyword("Java and Python", "Java", word_boundary=True))

    def test_match_keyword_empty(self):
        self.assertFalse(self.matcher.match_keyword("", "Python"))
        self.assertFalse(self.matcher.match_keyword("Python", ""))

    def test_matches(self):
        self.matcher.add_keyword("Python")
        self.assertTrue(self.matcher.matches("Experience with Python"))
        self.assertFalse(self.matcher.matches("Experience with Java"))

    def test_matches_with_synonyms(self):
        self.matcher.add_synonyms({"Python": ["python3"]})
        self.matcher.add_keyword("Python")
        self.assertTrue(self.matcher.matches("Experience with python3"))

    def test_matches_any(self):
        self.assertTrue(self.matcher.matches_any("Python developer", ["Python", "Java"]))
        self.assertFalse(self.matcher.matches_any("Go developer", ["Python", "Java"]))

    def test_matches_any_with_synonyms(self):
        self.matcher.add_synonyms({"Python": ["py"]})
        self.assertTrue(self.matcher.matches_any("py developer", ["Python"]))


class TestKeywordMatcherFindMatches(KeywordMatcherTestMixin, unittest.TestCase):
    """Tests for KeywordMatcher find_matches."""

    def setUp(self):
        super().setUp()
        self.matcher.add_keyword("Python", tier="required", weight=2)
        self.matcher.add_keyword("Docker", tier="preferred", weight=1)

    def test_find_matches(self):
        results = self.matcher.find_matches("Python and Docker experience")
        keywords = [r.keyword for r in results]
        self.assertIn("Python", keywords)
        self.assertIn("Docker", keywords)

    def test_find_matches_empty(self):
        results = self.matcher.find_matches("Java experience")
        self.assertEqual(results, [])

    def test_find_matching_keywords(self):
        matched = self.matcher.find_matching_keywords(
            "Python and Docker",
            ["Python", "Docker", "Java"],
        )
        self.assertIn("Python", matched)
        self.assertIn("Docker", matched)
        self.assertNotIn("Java", matched)


class TestKeywordMatcherScoring(KeywordMatcherTestMixin, unittest.TestCase):
    """Tests for KeywordMatcher scoring."""

    def setUp(self):
        super().setUp()
        self.matcher.add_keyword("Python", weight=3)
        self.matcher.add_keyword("Docker", weight=2)
        self.matcher.add_keyword("Git", weight=1)

    def test_score_single_match(self):
        score = self.matcher.score("Python developer")
        self.assertEqual(score, 3)

    def test_score_multiple_matches(self):
        score = self.matcher.score("Python and Docker experience")
        self.assertEqual(score, 5)

    def test_score_no_matches(self):
        score = self.matcher.score("Java developer")
        self.assertEqual(score, 0)

    def test_score_texts_deduplicates(self):
        # Same keyword in multiple texts should only count once
        score = self.matcher.score_texts([
            "Python developer",
            "More Python experience",
        ])
        self.assertEqual(score, 3)  # Not 6

    def test_score_texts_multiple_keywords(self):
        score = self.matcher.score_texts([
            "Python developer",
            "Docker expert",
        ])
        self.assertEqual(score, 5)


class TestKeywordMatcherBulkOperations(KeywordMatcherTestMixin, unittest.TestCase):
    """Tests for KeywordMatcher bulk operations."""

    def setUp(self):
        super().setUp()
        self.matcher.add_keyword("Python", tier="required", weight=2)
        self.matcher.add_keyword("API", tier="preferred", weight=1)

    def test_collect_matches_from_candidate(self):
        candidate = {
            "summary": "Experienced Python developer",
            "skills": ["Python", "Java"],
            "experience": [
                {
                    "title": "Python Developer",
                    "company": "TechCorp",
                    "bullets": ["Built APIs with Python"],
                }
            ],
        }
        results = self.matcher.collect_matches_from_candidate(candidate)
        self.assertIn("Python", results)
        self.assertIn("API", results)
        # Python appears in summary, skills, title, and bullet
        self.assertGreater(results["Python"].count, 1)

    def test_score_experience_roles(self):
        candidate = {
            "experience": [
                {
                    "title": "Java Developer",
                    "company": "Corp",
                    "bullets": ["Java things"],
                },
                {
                    "title": "Python Developer",
                    "company": "TechCo",
                    "bullets": ["Built APIs", "Python scripts"],
                },
            ],
        }
        scores = self.matcher.score_experience_roles(candidate)
        # Second role (index 1) should score higher
        self.assertEqual(scores[0][0], 1)  # Index of highest scoring role
        self.assertGreater(scores[0][1], scores[1][1])  # Higher score


class TestConvenienceFunctions(unittest.TestCase):
    """Tests for standalone convenience functions."""

    def test_normalize_text(self):
        self.assertEqual(normalize_text("  Hello  World  "), "hello world")

    def test_keyword_match(self):
        self.assertTrue(keyword_match("Python developer", "Python"))
        self.assertFalse(keyword_match("Java developer", "Python"))

    def test_expand_keywords(self):
        expanded = expand_keywords(
            ["Python"],
            synonyms={"Python": ["python3", "py"]},
        )
        self.assertIn("Python", expanded)
        self.assertIn("python3", expanded)
        self.assertIn("py", expanded)

    def test_expand_keywords_no_synonyms(self):
        expanded = expand_keywords(["Python", "Java"])
        self.assertIn("Python", expanded)
        self.assertIn("Java", expanded)


if __name__ == "__main__":
    unittest.main()
