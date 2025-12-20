import unittest

try:
    from resume_assistant.resume_assistant import experience_summary
    from resume_assistant.resume_assistant import priority
    from resume_assistant.resume_assistant import templating
except ModuleNotFoundError:
    from resume_assistant import experience_summary
    from resume_assistant import priority
    from resume_assistant import templating


class TestPriorityFilter(unittest.TestCase):
    def test_filter_by_min_priority(self):
        data = {
            "skills_groups": [
                {
                    "title": "Tech",
                    "items": [
                        {"name": "Python", "priority": 2},
                        {"name": "C", "priority": 1},
                        "Go",
                    ],
                }
            ],
            "technologies": [
                {"name": "Docker", "priority": 2},
                {"name": "Git", "priority": 1},
            ],
            "summary": [
                {"text": "Leadership", "priority": 2},
                "Fast learner",
            ],
            "experience": [
                {
                    "title": "Role 1",
                    "priority": 2,
                    "bullets": [
                        {"text": "Did A", "priority": 2},
                        {"text": "Did B", "priority": 1},
                    ],
                },
                {
                    "title": "Role 2",
                    "priority": 1,
                    "bullets": ["Did C"],
                },
            ],
        }

        result = priority.filter_by_min_priority(data, 2)

        self.assertEqual(result["skills_groups"][0]["items"], [{"name": "Python", "priority": 2}])
        self.assertEqual(result["technologies"], [{"name": "Docker", "priority": 2}])
        self.assertEqual(result["summary"], [{"text": "Leadership", "priority": 2}])
        self.assertEqual(len(result["experience"]), 1)
        self.assertEqual(result["experience"][0]["title"], "Role 1")
        self.assertEqual(result["experience"][0]["bullets"], [{"text": "Did A", "priority": 2}])


class TestTemplating(unittest.TestCase):
    def test_parse_seed_criteria(self):
        self.assertEqual(templating.parse_seed_criteria(None), {})
        self.assertEqual(
            templating.parse_seed_criteria('{"keywords": ["Go", "AWS"]}'),
            {"keywords": ["Go", "AWS"]},
        )
        out = templating.parse_seed_criteria("keywords=Go AWS,role=Engineer")
        self.assertEqual(out["keywords"], ["Go", "AWS"])
        self.assertEqual(out["role"], "Engineer")


class TestExperienceSummary(unittest.TestCase):
    def test_build_experience_summary(self):
        data = {
            "name": "Alex",
            "headline": "SRE",
            "experience": [
                {
                    "title": "Engineer",
                    "company": "Acme",
                    "start": "2020",
                    "end": "2022",
                    "location": "Remote",
                    "bullets": ["Did A", "Did B"],
                }
            ],
        }
        summary = experience_summary.build_experience_summary(data, max_bullets=1)
        self.assertEqual(summary["name"], "Alex")
        self.assertEqual(summary["headline"], "SRE")
        self.assertEqual(summary["experience"][0]["bullets"], ["Did A"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
