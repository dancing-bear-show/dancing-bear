import unittest

try:
    from resume.resume import experience_filter
    from resume.resume import skills_filter
except ModuleNotFoundError:
    from resume import experience_filter
    from resume import skills_filter


class TestExperienceFilter(unittest.TestCase):
    def test_filter_experience_by_keywords(self):
        data = {
            "experience": [
                {
                    "title": "Python Dev",
                    "company": "Acme",
                    "bullets": ["Built APIs", "Used Django"],
                },
                {
                    "title": "Ops",
                    "company": "Other",
                    "bullets": ["Maintained servers"],
                },
                {
                    "title": "K8s Engineer",
                    "company": "Cloud",
                    "bullets": ["Kubernetes cluster", "Other"],
                },
            ]
        }
        result = experience_filter.filter_experience_by_keywords(
            data,
            matched_keywords=["Python", "Kubernetes"],
            synonyms={"Kubernetes": ["k8s"]},
            max_roles=2,
            max_bullets_per_role=1,
            min_score=2,
        )
        exp = result["experience"]
        self.assertEqual(len(exp), 2)
        self.assertEqual(exp[0]["title"], "Python Dev")
        self.assertEqual(exp[1]["title"], "K8s Engineer")
        self.assertEqual(exp[0]["bullets"], ["Built APIs"])
        self.assertEqual(exp[1]["bullets"], ["Kubernetes cluster"])


class TestSkillsFilter(unittest.TestCase):
    def test_filter_skills_groups(self):
        data = {
            "skills_groups": [
                {"title": "Platform", "items": ["Kubernetes", "AWS"]},
                {"title": "Languages", "items": ["Python", "Go"]},
            ]
        }
        result = skills_filter.filter_skills_by_keywords(
            data,
            matched_keywords=["Kubernetes"],
            synonyms={"Kubernetes": ["k8s"]},
        )
        self.assertEqual(len(result["skills_groups"]), 1)
        self.assertEqual(result["skills_groups"][0]["items"], ["Kubernetes"])

    def test_filter_flat_skills(self):
        data = {"skills": ["Python", "Go", "AWS"]}
        result = skills_filter.filter_skills_by_keywords(data, matched_keywords=["Go"])
        self.assertEqual(result["skills"], ["Go"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
