"""Tests for resume keyword matching entry points."""

from __future__ import annotations

import unittest


class TestTextMatchExports(unittest.TestCase):
    """Test the resume keyword normalize/match/matcher public entry points."""

    def test_imports_normalize_text(self):
        from resume.keyword_normalize import normalize_text

        result = normalize_text("  Hello   World  ")
        self.assertEqual(result, "hello world")

    def test_imports_keyword_match(self):
        from resume.keyword_match import keyword_match

        self.assertTrue(keyword_match("Python developer", "python"))
        self.assertFalse(keyword_match("JavaScript developer", "python"))

    def test_imports_expand_keywords(self):
        from resume.keyword_matcher import expand_keywords

        synonyms = {"Python": ["py", "python3"]}
        result = expand_keywords(["Python"], synonyms)
        self.assertIn("Python", result)
        self.assertIn("py", result)
        self.assertIn("python3", result)

    def test_imports_keyword_matcher_class(self):
        from resume.keyword_matcher import KeywordMatcher

        matcher = KeywordMatcher()
        self.assertIsNotNone(matcher)
        matcher.add_keyword("Python", tier="required", weight=2)
        self.assertIn("Python", matcher.keywords)


if __name__ == "__main__":
    unittest.main(verbosity=2)
