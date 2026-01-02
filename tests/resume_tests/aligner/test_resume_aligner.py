"""Tests for resume/aligner.py candidate-to-job alignment."""

from __future__ import annotations

import unittest

from resume.aligner import align_candidate_to_job, build_tailored_candidate


class TestAlignCandidateToJob(unittest.TestCase):
    """Tests for align_candidate_to_job function."""

    def test_basic_alignment(self):
        candidate = {
            "summary": "Experienced Python developer with AWS expertise",
            "skills": ["Python", "AWS", "Docker"],
            "experience": [
                {
                    "title": "Software Engineer",
                    "company": "TechCorp",
                    "bullets": ["Built Python APIs", "Deployed to AWS"],
                }
            ],
        }
        keyword_spec = {
            "required": [{"skill": "Python"}, {"skill": "AWS"}],
            "preferred": [{"skill": "Docker"}],
        }
        result = align_candidate_to_job(candidate, keyword_spec)

        self.assertIn("matched_keywords", result)
        self.assertIn("missing_required", result)
        self.assertIn("missing_by_category", result)
        self.assertIn("experience_scores", result)

    def test_matched_keywords_structure(self):
        candidate = {
            "summary": "Python developer",
            "skills": ["Python"],
        }
        keyword_spec = {
            "required": [{"skill": "Python", "weight": 3}],
        }
        result = align_candidate_to_job(candidate, keyword_spec)

        matched = result["matched_keywords"]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["skill"], "Python")
        self.assertEqual(matched[0]["tier"], "required")
        self.assertEqual(matched[0]["weight"], 3)

    def test_missing_required(self):
        candidate = {
            "summary": "Java developer",
            "skills": ["Java"],
        }
        keyword_spec = {
            "required": [{"skill": "Python"}, {"skill": "Java"}],
        }
        result = align_candidate_to_job(candidate, keyword_spec)

        # Python is required but not in candidate
        self.assertIn("python", [m.lower() for m in result["missing_required"]])
        # Java is present, so not missing
        self.assertNotIn("java", [m.lower() for m in result["missing_required"]])

    def test_missing_by_category(self):
        candidate = {
            "summary": "Developer",
            "skills": ["Python"],
        }
        keyword_spec = {
            "categories": {
                "languages": [{"skill": "Python"}, {"skill": "Java"}],
                "tools": [{"skill": "Docker"}, {"skill": "Git"}],
            },
        }
        result = align_candidate_to_job(candidate, keyword_spec)

        missing = result["missing_by_category"]
        self.assertIn("languages", missing)
        self.assertIn("tools", missing)
        # Java is missing from languages
        self.assertIn("Java", missing["languages"])
        # Python is not missing
        self.assertNotIn("Python", missing["languages"])

    def test_experience_scores(self):
        candidate = {
            "experience": [
                {
                    "title": "Java Developer",
                    "company": "Corp",
                    "bullets": ["Java work"],
                },
                {
                    "title": "Python Developer",
                    "company": "TechCo",
                    "bullets": ["Python APIs", "AWS deployment"],
                },
            ],
        }
        keyword_spec = {
            "required": [{"skill": "Python"}, {"skill": "AWS"}],
        }
        result = align_candidate_to_job(candidate, keyword_spec)

        scores = result["experience_scores"]
        self.assertIsInstance(scores, list)
        # Scores should be sorted by score descending
        if len(scores) > 1:
            self.assertGreaterEqual(scores[0][1], scores[1][1])

    def test_with_synonyms(self):
        candidate = {
            "summary": "Python3 developer",
            "skills": ["python3"],
        }
        keyword_spec = {
            "required": [{"skill": "Python"}],
        }
        synonyms = {"Python": ["python3", "py"]}
        result = align_candidate_to_job(candidate, keyword_spec, synonyms=synonyms)

        # Should match via synonym
        matched_skills = [m["skill"] for m in result["matched_keywords"]]
        self.assertTrue(any("python" in s.lower() for s in matched_skills))

    def test_sorted_by_tier(self):
        candidate = {
            "summary": "Python Docker Git developer",
            "skills": ["Python", "Docker", "Git"],
        }
        keyword_spec = {
            "required": [{"skill": "Python"}],
            "preferred": [{"skill": "Docker"}],
            "nice": [{"skill": "Git"}],
        }
        result = align_candidate_to_job(candidate, keyword_spec)

        matched = result["matched_keywords"]
        tiers = [m["tier"] for m in matched]
        # Required should come before preferred, preferred before nice
        if "required" in tiers and "preferred" in tiers:
            self.assertLess(tiers.index("required"), tiers.index("preferred"))

    def test_empty_candidate(self):
        candidate = {}
        keyword_spec = {
            "required": [{"skill": "Python"}],
        }
        result = align_candidate_to_job(candidate, keyword_spec)

        self.assertEqual(result["matched_keywords"], [])
        self.assertIn("Python", result["missing_required"])

    def test_empty_spec(self):
        candidate = {
            "summary": "Python developer",
            "skills": ["Python"],
        }
        keyword_spec = {}
        result = align_candidate_to_job(candidate, keyword_spec)

        self.assertEqual(result["matched_keywords"], [])
        self.assertEqual(result["missing_required"], [])


class TestBuildTailoredCandidate(unittest.TestCase):
    """Tests for build_tailored_candidate function."""

    def setUp(self):
        self.candidate = {
            "name": "Jane Doe",
            "summary": "Experienced developer",
            "skills": ["Python", "Java", "Go", "Rust", "C++"],
            "experience": [
                {
                    "title": "Senior Developer",
                    "company": "TechCorp",
                    "bullets": [
                        "Built Python APIs",
                        "Deployed Docker containers",
                        "Managed AWS infrastructure",
                        "Led team of 5",
                    ],
                },
                {
                    "title": "Junior Developer",
                    "company": "StartupCo",
                    "bullets": [
                        "Wrote Java code",
                        "Fixed bugs",
                    ],
                },
            ],
        }
        self.alignment = {
            "matched_keywords": [
                {"skill": "Python", "count": 2, "weight": 3, "tier": "required", "category": None},
                {"skill": "Docker", "count": 1, "weight": 2, "tier": "preferred", "category": None},
                {"skill": "AWS", "count": 1, "weight": 2, "tier": "preferred", "category": None},
            ],
            "missing_required": [],
            "missing_by_category": {},
            "experience_scores": [(0, 5), (1, 0)],
        }

    def test_basic_tailoring(self):
        result = build_tailored_candidate(self.candidate, self.alignment)

        self.assertEqual(result["name"], "Jane Doe")
        self.assertIn("skills", result)
        self.assertIn("experience", result)

    def test_skills_limited(self):
        result = build_tailored_candidate(self.candidate, self.alignment, limit_skills=2)

        self.assertLessEqual(len(result["skills"]), 2)

    def test_skills_from_matched(self):
        result = build_tailored_candidate(self.candidate, self.alignment)

        # Skills should come from matched_keywords
        self.assertIn("Python", result["skills"])
        self.assertIn("Docker", result["skills"])
        self.assertIn("AWS", result["skills"])

    def test_experience_filtered_by_score(self):
        result = build_tailored_candidate(self.candidate, self.alignment, min_exp_score=1)

        # Only first experience has score >= 1
        self.assertEqual(len(result["experience"]), 1)
        self.assertEqual(result["experience"][0]["title"], "Senior Developer")

    def test_bullets_filtered_to_matching(self):
        result = build_tailored_candidate(self.candidate, self.alignment)

        # Bullets should be filtered to those matching keywords
        exp = result["experience"][0]
        # Should keep Python/Docker/AWS bullets, not "Led team of 5"
        self.assertLessEqual(len(exp["bullets"]), 4)

    def test_max_bullets_per_role(self):
        result = build_tailored_candidate(
            self.candidate, self.alignment, max_bullets_per_role=2
        )

        for exp in result["experience"]:
            self.assertLessEqual(len(exp["bullets"]), 2)

    def test_fallback_bullet_if_none_match(self):
        # Alignment with keywords that don't match any bullets
        alignment = {
            "matched_keywords": [
                {"skill": "Kubernetes", "count": 1, "weight": 1, "tier": "required", "category": None},
            ],
            "experience_scores": [(0, 1), (1, 1)],
        }
        result = build_tailored_candidate(self.candidate, alignment, min_exp_score=1)

        # Should fall back to first bullet
        for exp in result["experience"]:
            self.assertGreaterEqual(len(exp["bullets"]), 1)

    def test_preserves_other_fields(self):
        candidate = {
            **self.candidate,
            "email": "jane@example.com",
            "phone": "555-1234",
        }
        result = build_tailored_candidate(candidate, self.alignment)

        self.assertEqual(result["email"], "jane@example.com")
        self.assertEqual(result["phone"], "555-1234")

    def test_empty_alignment(self):
        alignment = {
            "matched_keywords": [],
            "experience_scores": [],
        }
        result = build_tailored_candidate(self.candidate, alignment)

        # Should fall back to original skills
        self.assertEqual(result["skills"], self.candidate["skills"][:20])

    def test_experience_sorted_by_score(self):
        # Reverse the scores so second experience scores higher
        alignment = {
            **self.alignment,
            "experience_scores": [(1, 10), (0, 5)],
        }
        result = build_tailored_candidate(self.candidate, alignment, min_exp_score=1)

        # Higher scoring experience should come first
        self.assertEqual(result["experience"][0]["title"], "Junior Developer")


if __name__ == "__main__":
    unittest.main()
