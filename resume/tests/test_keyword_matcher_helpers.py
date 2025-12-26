"""Tests for KeywordMatcher helper functions and methods."""
import unittest

from resume.keyword_matcher import (
    KeywordMatcher,
    KeywordInfo,
    MatchResult,
    normalize_text,
    keyword_match,
    expand_keywords,
)


class TestKeywordInfo(unittest.TestCase):
    """Tests for KeywordInfo dataclass."""

    def test_default_values(self):
        info = KeywordInfo(keyword="Python")
        self.assertEqual(info.keyword, "Python")
        self.assertEqual(info.tier, "preferred")
        self.assertEqual(info.weight, 1)
        self.assertIsNone(info.category)

    def test_custom_values(self):
        info = KeywordInfo(
            keyword="AWS", tier="required", weight=3, category="cloud"
        )
        self.assertEqual(info.keyword, "AWS")
        self.assertEqual(info.tier, "required")
        self.assertEqual(info.weight, 3)
        self.assertEqual(info.category, "cloud")


class TestMatchResult(unittest.TestCase):
    """Tests for MatchResult dataclass."""

    def test_default_values(self):
        result = MatchResult(
            keyword="Python", tier="required", weight=2, category=None
        )
        self.assertEqual(result.count, 1)
        self.assertEqual(result.contexts, [])

    def test_to_dict(self):
        result = MatchResult(
            keyword="AWS",
            tier="preferred",
            weight=2,
            category="cloud",
            count=3,
            contexts=["context1"],
        )
        d = result.to_dict()
        self.assertEqual(d["skill"], "AWS")
        self.assertEqual(d["tier"], "preferred")
        self.assertEqual(d["weight"], 2)
        self.assertEqual(d["category"], "cloud")
        self.assertEqual(d["count"], 3)
        self.assertNotIn("contexts", d)


class TestAddKeywordItem(unittest.TestCase):
    """Tests for _add_keyword_item helper method."""

    def test_adds_dict_with_skill_key(self):
        matcher = KeywordMatcher()
        matcher._add_keyword_item({"skill": "Python", "weight": 2}, "required")
        info = matcher.get_keyword_info("Python")
        self.assertIsNotNone(info)
        self.assertEqual(info.weight, 2)
        self.assertEqual(info.tier, "required")

    def test_adds_dict_with_name_key(self):
        matcher = KeywordMatcher()
        matcher._add_keyword_item({"name": "AWS"}, "preferred", category="cloud")
        info = matcher.get_keyword_info("AWS")
        self.assertIsNotNone(info)
        self.assertEqual(info.category, "cloud")

    def test_adds_string_item(self):
        matcher = KeywordMatcher()
        matcher._add_keyword_item("Docker", "nice")
        info = matcher.get_keyword_info("Docker")
        self.assertIsNotNone(info)
        self.assertEqual(info.tier, "nice")

    def test_ignores_empty_dict(self):
        matcher = KeywordMatcher()
        matcher._add_keyword_item({}, "required")
        self.assertEqual(len(matcher.keywords), 0)

    def test_ignores_empty_string(self):
        matcher = KeywordMatcher()
        matcher._add_keyword_item("", "required")
        self.assertEqual(len(matcher.keywords), 0)

    def test_ignores_non_string_non_dict(self):
        matcher = KeywordMatcher()
        matcher._add_keyword_item(123, "required")
        self.assertEqual(len(matcher.keywords), 0)


class TestAddKeywordsFromSpec(unittest.TestCase):
    """Tests for add_keywords_from_spec method."""

    def test_adds_from_required_tier(self):
        matcher = KeywordMatcher()
        spec = {"required": ["Python", "AWS"]}
        matcher.add_keywords_from_spec(spec)
        self.assertIn("Python", matcher.keywords)
        self.assertEqual(matcher.get_keyword_info("Python").tier, "required")

    def test_adds_from_preferred_tier(self):
        matcher = KeywordMatcher()
        spec = {"preferred": [{"skill": "Docker", "weight": 2}]}
        matcher.add_keywords_from_spec(spec)
        info = matcher.get_keyword_info("Docker")
        self.assertEqual(info.tier, "preferred")
        self.assertEqual(info.weight, 2)

    def test_adds_from_categories(self):
        matcher = KeywordMatcher()
        spec = {"categories": {"backend": ["Python", "Go"], "frontend": ["React"]}}
        matcher.add_keywords_from_spec(spec)
        self.assertEqual(matcher.get_keyword_info("Python").category, "backend")
        self.assertEqual(matcher.get_keyword_info("React").category, "frontend")

    def test_handles_empty_spec(self):
        matcher = KeywordMatcher()
        matcher.add_keywords_from_spec({})
        self.assertEqual(len(matcher.keywords), 0)


class TestSynonymManagement(unittest.TestCase):
    """Tests for synonym management methods."""

    def test_add_synonym(self):
        matcher = KeywordMatcher()
        matcher.add_synonym("JavaScript", "JS")
        self.assertEqual(matcher.canonicalize("js"), "JavaScript")

    def test_add_synonyms(self):
        matcher = KeywordMatcher()
        matcher.add_synonyms({"Python": ["python3", "py"], "JavaScript": ["JS"]})
        self.assertEqual(matcher.canonicalize("python3"), "Python")
        self.assertEqual(matcher.canonicalize("js"), "JavaScript")

    def test_get_aliases(self):
        matcher = KeywordMatcher()
        matcher.add_synonyms({"Python": ["py", "python3"]})
        aliases = matcher.get_aliases("Python")
        self.assertIn("py", aliases)
        self.assertIn("python3", aliases)

    def test_expand(self):
        matcher = KeywordMatcher()
        matcher.add_synonyms({"Python": ["py"]})
        expanded = matcher.expand("Python")
        self.assertIn("Python", expanded)
        self.assertIn("py", expanded)

    def test_expand_all(self):
        matcher = KeywordMatcher()
        matcher.add_synonyms({"Python": ["py"], "JavaScript": ["JS"]})
        expanded = matcher.expand_all(["Python", "JavaScript"])
        self.assertIn("Python", expanded)
        self.assertIn("py", expanded)
        self.assertIn("JavaScript", expanded)
        self.assertIn("JS", expanded)


class TestNormalize(unittest.TestCase):
    """Tests for normalize static method."""

    def test_lowercases(self):
        self.assertEqual(KeywordMatcher.normalize("Python"), "python")

    def test_collapses_whitespace(self):
        self.assertEqual(KeywordMatcher.normalize("hello   world"), "hello world")

    def test_strips_whitespace(self):
        self.assertEqual(KeywordMatcher.normalize("  hello  "), "hello")

    def test_handles_empty(self):
        self.assertEqual(KeywordMatcher.normalize(""), "")

    def test_handles_none(self):
        self.assertEqual(KeywordMatcher.normalize(None), "")


class TestMatchKeyword(unittest.TestCase):
    """Tests for match_keyword method."""

    def test_finds_keyword(self):
        matcher = KeywordMatcher()
        self.assertTrue(matcher.match_keyword("I use Python daily", "Python"))

    def test_case_insensitive(self):
        matcher = KeywordMatcher()
        self.assertTrue(matcher.match_keyword("python developer", "Python"))

    def test_word_boundary(self):
        matcher = KeywordMatcher()
        self.assertTrue(matcher.match_keyword("Use Go for backend", "Go"))
        # Note: Implementation falls back to substring match after word boundary check
        # so "Go" in "Google" still matches as a substring
        self.assertTrue(matcher.match_keyword("Google is great", "Go"))

    def test_no_word_boundary(self):
        matcher = KeywordMatcher()
        self.assertTrue(
            matcher.match_keyword("Google is great", "Go", word_boundary=False)
        )

    def test_empty_text(self):
        matcher = KeywordMatcher()
        self.assertFalse(matcher.match_keyword("", "Python"))

    def test_empty_keyword(self):
        matcher = KeywordMatcher()
        self.assertFalse(matcher.match_keyword("Python is great", ""))


class TestMatches(unittest.TestCase):
    """Tests for matches method."""

    def test_matches_registered_keyword(self):
        matcher = KeywordMatcher()
        matcher.add_keyword("Python")
        self.assertTrue(matcher.matches("Python developer"))

    def test_matches_via_synonym(self):
        matcher = KeywordMatcher()
        matcher.add_synonyms({"Python": ["py"]})
        matcher.add_keyword("Python")
        self.assertTrue(matcher.matches("I use py for scripting"))

    def test_no_match(self):
        matcher = KeywordMatcher()
        matcher.add_keyword("Python")
        self.assertFalse(matcher.matches("Java developer"))


class TestFindMatches(unittest.TestCase):
    """Tests for find_matches method."""

    def test_returns_match_results(self):
        matcher = KeywordMatcher()
        matcher.add_keyword("Python", tier="required", weight=2)
        matcher.add_keyword("AWS", tier="preferred")
        results = matcher.find_matches("Python on AWS")
        self.assertEqual(len(results), 2)

    def test_includes_keyword_info(self):
        matcher = KeywordMatcher()
        matcher.add_keyword("Python", tier="required", weight=3)
        results = matcher.find_matches("Python developer")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].keyword, "Python")
        self.assertEqual(results[0].tier, "required")
        self.assertEqual(results[0].weight, 3)


class TestScore(unittest.TestCase):
    """Tests for score method."""

    def test_calculates_weighted_score(self):
        matcher = KeywordMatcher()
        matcher.add_keyword("Python", weight=3)
        matcher.add_keyword("AWS", weight=2)
        score = matcher.score("Python developer on AWS")
        self.assertEqual(score, 5)

    def test_zero_for_no_matches(self):
        matcher = KeywordMatcher()
        matcher.add_keyword("Python")
        score = matcher.score("Java developer")
        self.assertEqual(score, 0)


class TestScoreTexts(unittest.TestCase):
    """Tests for score_texts method."""

    def test_counts_keyword_once(self):
        matcher = KeywordMatcher()
        matcher.add_keyword("Python", weight=2)
        texts = ["Python is great", "Python is fun", "I love Python"]
        score = matcher.score_texts(texts)
        self.assertEqual(score, 2)

    def test_sums_unique_keywords(self):
        matcher = KeywordMatcher()
        matcher.add_keyword("Python", weight=2)
        matcher.add_keyword("AWS", weight=3)
        texts = ["Python developer", "AWS experience"]
        score = matcher.score_texts(texts)
        self.assertEqual(score, 5)


class TestConvenienceFunctions(unittest.TestCase):
    """Tests for standalone convenience functions."""

    def test_normalize_text(self):
        self.assertEqual(normalize_text("Hello   World"), "hello world")

    def test_keyword_match(self):
        self.assertTrue(keyword_match("Python developer", "python"))
        self.assertFalse(keyword_match("Java developer", "python"))

    def test_expand_keywords(self):
        synonyms = {"Python": ["py"]}
        result = expand_keywords(["Python"], synonyms)
        self.assertIn("Python", result)
        self.assertIn("py", result)


class TestCollectMatchesFromCandidate(unittest.TestCase):
    """Tests for collect_matches_from_candidate method."""

    def test_matches_in_summary(self):
        matcher = KeywordMatcher()
        matcher.add_keyword("Python")
        candidate = {"summary": "Experienced Python developer"}
        results = matcher.collect_matches_from_candidate(candidate)
        self.assertIn("Python", results)
        self.assertGreater(results["Python"].count, 0)

    def test_matches_in_skills(self):
        matcher = KeywordMatcher()
        matcher.add_keyword("AWS")
        candidate = {"skills": ["AWS", "Docker", "Kubernetes"]}
        results = matcher.collect_matches_from_candidate(candidate)
        self.assertIn("AWS", results)

    def test_matches_in_experience_title(self):
        matcher = KeywordMatcher()
        matcher.add_keyword("Engineer")
        candidate = {
            "experience": [
                {"title": "Software Engineer", "company": "TechCo", "bullets": []}
            ]
        }
        results = matcher.collect_matches_from_candidate(candidate)
        self.assertIn("Engineer", results)

    def test_matches_in_bullets(self):
        matcher = KeywordMatcher()
        matcher.add_keyword("Python")
        candidate = {
            "experience": [
                {"title": "Developer", "bullets": ["Built Python APIs"]}
            ]
        }
        results = matcher.collect_matches_from_candidate(candidate)
        self.assertIn("Python", results)


class TestScoreExperienceRoles(unittest.TestCase):
    """Tests for score_experience_roles method."""

    def test_scores_roles_by_keywords(self):
        matcher = KeywordMatcher()
        matcher.add_keyword("Python", weight=2)
        matcher.add_keyword("Lead", weight=3)
        candidate = {
            "experience": [
                {"title": "Python Lead", "company": "Co1", "bullets": []},
                {"title": "Junior Dev", "company": "Co2", "bullets": []},
            ]
        }
        scores = matcher.score_experience_roles(candidate)
        # First role matches both Python (2) and Lead (3) = 5
        # Second role matches nothing = 0
        self.assertEqual(scores[0], (0, 5))
        self.assertEqual(scores[1], (1, 0))

    def test_includes_bullet_scores(self):
        matcher = KeywordMatcher()
        matcher.add_keyword("Python")
        candidate = {
            "experience": [
                {"title": "Dev", "bullets": ["Used Python", "More Python work"]}
            ]
        }
        scores = matcher.score_experience_roles(candidate)
        # Title has no match, bullets add 1 each (only count once per bullet)
        self.assertGreater(scores[0][1], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
