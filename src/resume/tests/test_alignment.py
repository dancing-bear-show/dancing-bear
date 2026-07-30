import unittest

try:
    from resume.resume import aligner
except ModuleNotFoundError:
    from resume import aligner


class TestAligner(unittest.TestCase):
    def test_align_candidate_with_synonyms_and_categories(self):
        candidate = {
            "summary": "Platform engineer with k8s and AWS.",
            "skills": ["Python", "Docker"],
            "experience": [
                {
                    "title": "SRE",
                    "company": "Example",
                    "bullets": ["Built k8s clusters", "Reduced AWS costs"],
                },
                {
                    "title": "Developer",
                    "company": "Other",
                    "bullets": ["Built web apps"],
                },
            ],
        }
        keyword_spec = {
            "required": [{"skill": "Kubernetes", "weight": 3}],
            "preferred": [{"skill": "AWS", "weight": 2}],
            "nice": [{"skill": "Terraform", "weight": 1}],
            "categories": {"cloud": [{"skill": "AWS"}, {"skill": "GCP"}]},
        }
        synonyms = {"Kubernetes": ["k8s"]}

        result = aligner.align_candidate_to_job(candidate, keyword_spec, synonyms=synonyms)
        matched_skills = {m["skill"] for m in result["matched_keywords"]}
        self.assertIn("Kubernetes", matched_skills)
        self.assertIn("AWS", matched_skills)
        self.assertNotIn("Terraform", matched_skills)
        self.assertEqual(result["missing_required"], [])
        self.assertIn("cloud", result["missing_by_category"])
        self.assertIn("GCP", result["missing_by_category"]["cloud"])
        self.assertEqual(result["experience_scores"][0][0], 0)
        self.assertGreaterEqual(result["experience_scores"][0][1], result["experience_scores"][1][1])

    def test_build_tailored_candidate_filters_bullets(self):
        candidate = {
            "name": "Test Person",
            "skills": ["AWS", "Python"],
            "experience": [
                {
                    "title": "Role 1",
                    "company": "A",
                    "bullets": ["Led AWS migration", "Other work"],
                },
                {
                    "title": "Role 2",
                    "company": "B",
                    "bullets": ["Did stuff", "More work"],
                },
            ],
        }
        alignment = {
            "matched_keywords": [{"skill": "AWS"}],
            "experience_scores": [(0, 2), (1, 1)],
        }

        tailored = aligner.build_tailored_candidate(
            candidate,
            alignment,
            limit_skills=1,
            max_bullets_per_role=1,
            min_exp_score=1,
        )

        self.assertEqual(tailored["skills"], ["AWS"])
        self.assertEqual(tailored["experience"][0]["title"], "Role 1")
        self.assertEqual(tailored["experience"][0]["bullets"], ["Led AWS migration"])
        self.assertEqual(tailored["experience"][1]["bullets"], ["Did stuff"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
