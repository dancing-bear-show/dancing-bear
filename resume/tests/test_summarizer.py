import unittest

try:
    from resume.resume import summarizer
except ModuleNotFoundError:
    from resume import summarizer


class TestSummarizer(unittest.TestCase):
    def test_build_summary_prioritizes_keywords(self):
        data = {
            "name": "Taylor Example",
            "headline": "SRE",
            "skills": ["Python", "AWS", "Go"],
            "experience": [
                {
                    "title": "SRE",
                    "company": "Acme",
                    "bullets": ["Built Kubernetes clusters", "Improved monitoring"],
                },
                {
                    "title": "Developer",
                    "company": "Other",
                    "bullets": ["Built web apps"],
                },
            ],
        }
        seed = {"keywords": ["AWS", "Kubernetes"]}

        summary = summarizer.build_summary(data, seed=seed)

        self.assertEqual(summary["name"], "Taylor Example")
        self.assertEqual(summary["headline"], "SRE")
        self.assertEqual(summary["top_skills"][0], "AWS")
        self.assertIn("SRE at Acme", summary["experience_highlights"])
        self.assertIn("Built Kubernetes clusters", summary["experience_highlights"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
