"""Tests for resume/experience_summary.py — in tests/ discovery path."""

from __future__ import annotations

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
        self.assertEqual(exp["bullets"], ["Built APIs", "Led team"])

    def test_max_bullets_limits_output(self):
        data = {
            "experience": [
                {"title": "Dev", "bullets": ["One", "Two", "Three", "Four"]},
            ]
        }
        result = build_experience_summary(data, max_bullets=2)
        self.assertEqual(result["experience"][0]["bullets"], ["One", "Two"])

    def test_max_bullets_zero_returns_empty(self):
        data = {"experience": [{"title": "Dev", "bullets": ["A", "B"]}]}
        result = build_experience_summary(data, max_bullets=0)
        self.assertEqual(result["experience"][0]["bullets"], [])

    def test_max_bullets_none_keeps_all(self):
        data = {"experience": [{"title": "Dev", "bullets": ["A", "B", "C"]}]}
        result = build_experience_summary(data, max_bullets=None)
        self.assertEqual(len(result["experience"][0]["bullets"]), 3)

    def test_converts_bullets_to_strings(self):
        data = {"experience": [{"title": "Dev", "bullets": [123, True]}]}
        result = build_experience_summary(data)
        self.assertEqual(result["experience"][0]["bullets"], ["123", "True"])

    def test_drops_bullets_with_no_text(self):
        # item_text() yields "" for a priority dict carrying no text key and for
        # an empty string, and the comprehension filters those out entirely.
        data = {
            "experience": [
                {
                    "title": "Dev",
                    "bullets": [{"priority": 1}, {"text": "Alpha"}, "", {"text": "Beta"}],
                }
            ]
        }
        result = build_experience_summary(data)
        self.assertEqual(result["experience"][0]["bullets"], ["Alpha", "Beta"])

    def test_empty_bullet_does_not_consume_a_max_bullets_slot(self):
        # This site slices AFTER filtering, so a dropped bullet costs no slot:
        # max_bullets=2 still yields two real bullets despite the leading empty.
        # summarizer._experience_highlight_lines and the candidate-init skeleton
        # slice BEFORE filtering and behave differently -- see
        # test_leading_empty_bullet_consumes_a_slice_slot in
        # tests/resume_tests/summarizer/test_summarizer.py.
        data = {
            "experience": [
                {
                    "title": "Dev",
                    "bullets": [{"priority": 1}, {"text": "Alpha"}, {"text": "Beta"}],
                }
            ]
        }
        result = build_experience_summary(data, max_bullets=2)
        self.assertEqual(result["experience"][0]["bullets"], ["Alpha", "Beta"])

    def test_drops_empty_bullets_among_dict_and_string_forms(self):
        data = {
            "experience": [
                {
                    "title": "Dev",
                    "bullets": [
                        "Bare string bullet",
                        {"priority": 0.9},
                        {"text": "Dict bullet", "priority": 0.5},
                        "",
                        {"line": "Line-keyed bullet"},
                    ],
                }
            ]
        }
        result = build_experience_summary(data)
        self.assertEqual(
            result["experience"][0]["bullets"],
            ["Bare string bullet", "Dict bullet", "Line-keyed bullet"],
        )

    def test_handles_missing_fields(self):
        data = {"experience": [{"title": "Dev"}]}
        result = build_experience_summary(data)
        exp = result["experience"][0]
        self.assertEqual(exp["company"], "")
        self.assertEqual(exp["start"], "")
        self.assertEqual(exp["end"], "")
        self.assertEqual(exp["location"], "")
        self.assertEqual(exp["bullets"], [])

    def test_none_experience_list(self):
        data = {"name": "Test", "experience": None}
        result = build_experience_summary(data)
        self.assertEqual(result["experience"], [])

    def test_multiple_experiences(self):
        data = {
            "experience": [
                {"title": "Role 1", "company": "Co1", "bullets": []},
                {"title": "Role 2", "company": "Co2", "bullets": []},
            ]
        }
        result = build_experience_summary(data)
        self.assertEqual(len(result["experience"]), 2)


if __name__ == "__main__":
    unittest.main()
