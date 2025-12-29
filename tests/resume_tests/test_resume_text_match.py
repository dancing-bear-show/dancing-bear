"""Tests for resume/text_match.py re-exports."""

import unittest


class TestTextMatchExports(unittest.TestCase):
    """Test that text_match.py correctly re-exports from keyword_matcher."""

    def test_imports_normalize_text(self):
        from resume.text_match import normalize_text

        result = normalize_text("  Hello   World  ")
        self.assertEqual(result, "hello world")

    def test_imports_keyword_match(self):
        from resume.text_match import keyword_match

        self.assertTrue(keyword_match("Python developer", "python"))
        self.assertFalse(keyword_match("JavaScript developer", "python"))

    def test_imports_expand_keywords(self):
        from resume.text_match import expand_keywords

        synonyms = {"Python": ["py", "python3"]}
        result = expand_keywords(["Python"], synonyms)
        self.assertIn("Python", result)
        self.assertIn("py", result)
        self.assertIn("python3", result)

    def test_imports_keyword_matcher_class(self):
        from resume.text_match import KeywordMatcher

        matcher = KeywordMatcher()
        self.assertIsNotNone(matcher)
        matcher.add_keyword("Python", tier="required", weight=2)
        self.assertIn("Python", matcher.keywords)

    def test_all_exports_defined(self):
        from resume import text_match

        self.assertIn("normalize_text", text_match.__all__)
        self.assertIn("keyword_match", text_match.__all__)
        self.assertIn("expand_keywords", text_match.__all__)
        self.assertIn("KeywordMatcher", text_match.__all__)


if __name__ == "__main__":
    unittest.main(verbosity=2)
