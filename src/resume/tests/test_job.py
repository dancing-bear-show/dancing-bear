import unittest

try:
    from resume.resume import job
except ModuleNotFoundError:
    from resume import job


class TestJobKeywords(unittest.TestCase):
    def test_build_keyword_spec_and_synonyms(self):
        job_cfg = {
            "keywords": {
                "required": ["Python", {"skill": "AWS", "weight": 3}, {"name": "Kubernetes"}],
                "preferred": [{"skill": "Terraform", "weight": 2}],
                "nice_to_have": ["Prometheus"],
                "soft_skills": ["Communication", {"skill": "Leadership", "weight": 2}],
                "tech_skills": [{"name": "Docker"}],
                "technologies": [{"key": "Linux", "weight": 2}],
                "synonyms": {
                    "Kubernetes": ["k8s", "EKS"],
                    "AWS": "Amazon Web Services",
                },
            }
        }

        spec, syn = job.build_keyword_spec(job_cfg)

        self.assertEqual([x["skill"] for x in spec["required"]], ["Python", "AWS", "Kubernetes"])
        weights = {x["skill"]: x["weight"] for x in spec["required"]}
        self.assertEqual(weights["Python"], 1)
        self.assertEqual(weights["AWS"], 3)
        self.assertEqual(weights["Kubernetes"], 1)
        self.assertEqual([x["skill"] for x in spec["preferred"]], ["Terraform"])
        self.assertEqual([x["skill"] for x in spec["nice"]], ["Prometheus"])
        self.assertEqual([x["skill"] for x in spec["categories"]["soft_skills"]], ["Communication", "Leadership"])
        self.assertEqual([x["skill"] for x in spec["categories"]["tech_skills"]], ["Docker"])
        self.assertEqual([x["skill"] for x in spec["categories"]["technologies"]], ["Linux"])
        self.assertEqual(syn["Kubernetes"], ["k8s", "EKS"])
        self.assertEqual(syn["AWS"], ["Amazon Web Services"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
