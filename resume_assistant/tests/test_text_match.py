import unittest

try:
    from resume_assistant.resume_assistant import text_match
except ModuleNotFoundError:
    from resume_assistant import text_match


class TestTextMatch(unittest.TestCase):
    def test_keyword_match_normalized(self):
        self.assertTrue(text_match.keyword_match("  Python  ", "python", normalize=True))
        self.assertTrue(text_match.keyword_match("Kubernetes-based systems", "Kubernetes", normalize=True))
        self.assertFalse(text_match.keyword_match("", "python"))

    def test_expand_keywords_with_synonyms(self):
        result = text_match.expand_keywords(
            ["AWS", "", "GCP"],
            synonyms={"AWS": ["amazon web services", ""], "GCP": ["google cloud"]},
        )
        self.assertEqual(result, ["AWS", "amazon web services", "GCP", "google cloud"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
