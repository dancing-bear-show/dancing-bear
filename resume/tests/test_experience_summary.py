"""Tests for resume/experience_summary.py."""
import unittest

from resume.experience_summary import build_experience_summary


class TestBuildExperienceSummary(unittest.TestCase):
    """Tests for build_experience_summary function."""

    def test_empty_data(self):
        result = build_experience_summary({})
        self.assertEqual(result["name"], "")
        self.assertEqual(result["headline"], "")
        self.assertEqual(result["experience"], [])

    def test_extracts_name_and_headline(self):
        data = {"name": "John Doe", "headline": "Senior Engineer"}
        result = build_experience_summary(data)
        self.assertEqual(result["name"], "John Doe")
        self.assertEqual(result["headline"], "Senior Engineer")

    def test_extracts_experience(self):
        data = {
            "name": "Jane",
            "experience": [
                {
                    "title": "Engineer",
                    "company": "TechCorp",
                    "start": "2020",
                    "end": "Present",
                    "location": "NYC",
                    "bullets": ["Built APIs", "Led team"],
                }
            ],
        }
        result = build_experience_summary(data)
        self.assertEqual(len(result["experience"]), 1)
        exp = result["experience"][0]
        self.assertEqual(exp["title"], "Engineer")
        self.assertEqual(exp["company"], "TechCorp")
        self.assertEqual(exp["start"], "2020")
        self.assertEqual(exp["end"], "Present")
        self.assertEqual(exp["location"], "NYC")
        self.assertEqual(exp["bullets"], ["Built APIs", "Led team"])

    def test_multiple_experiences(self):
        data = {
            "experience": [
                {"title": "Role 1", "company": "Co1", "bullets": []},
                {"title": "Role 2", "company": "Co2", "bullets": []},
                {"title": "Role 3", "company": "Co3", "bullets": []},
            ]
        }
        result = build_experience_summary(data)
        self.assertEqual(len(result["experience"]), 3)
        self.assertEqual(result["experience"][0]["title"], "Role 1")
        self.assertEqual(result["experience"][2]["title"], "Role 3")

    def test_max_bullets_limits_output(self):
        data = {
            "experience": [
                {
                    "title": "Dev",
                    "bullets": ["One", "Two", "Three", "Four", "Five"],
                }
            ]
        }
        result = build_experience_summary(data, max_bullets=3)
        self.assertEqual(len(result["experience"][0]["bullets"]), 3)
        self.assertEqual(result["experience"][0]["bullets"], ["One", "Two", "Three"])

    def test_max_bullets_none_keeps_all(self):
        data = {
            "experience": [
                {"title": "Dev", "bullets": ["A", "B", "C", "D"]}
            ]
        }
        result = build_experience_summary(data, max_bullets=None)
        self.assertEqual(len(result["experience"][0]["bullets"]), 4)

    def test_max_bullets_zero_returns_empty(self):
        data = {
            "experience": [
                {"title": "Dev", "bullets": ["A", "B", "C"]}
            ]
        }
        result = build_experience_summary(data, max_bullets=0)
        self.assertEqual(result["experience"][0]["bullets"], [])

    def test_handles_missing_fields(self):
        data = {
            "experience": [
                {"title": "Dev"}  # Missing other fields
            ]
        }
        result = build_experience_summary(data)
        exp = result["experience"][0]
        self.assertEqual(exp["title"], "Dev")
        self.assertEqual(exp["company"], "")
        self.assertEqual(exp["start"], "")
        self.assertEqual(exp["end"], "")
        self.assertEqual(exp["location"], "")
        self.assertEqual(exp["bullets"], [])

    def test_converts_bullets_to_strings(self):
        data = {
            "experience": [
                {"title": "Dev", "bullets": [123, 456, True]}
            ]
        }
        result = build_experience_summary(data)
        bullets = result["experience"][0]["bullets"]
        self.assertEqual(bullets, ["123", "456", "True"])

    def test_none_experience_list(self):
        data = {"name": "Test", "experience": None}
        result = build_experience_summary(data)
        self.assertEqual(result["experience"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
