"""Tests for resume/priority.py priority-based filtering."""

from __future__ import annotations

import unittest

from resume.priority import (
    _score,
    _filter_items,
    _filter_skills_groups,
    _filter_experience,
    filter_by_min_priority,
)


class TestScore(unittest.TestCase):
    """Tests for _score function."""

    def test_score_integer(self):
        self.assertEqual(_score(5), 5.0)

    def test_score_float(self):
        self.assertEqual(_score(3.5), 3.5)

    def test_score_string_number(self):
        self.assertEqual(_score("2.5"), 2.5)

    def test_score_invalid_returns_default(self):
        self.assertEqual(_score("invalid"), 1.0)

    def test_score_none_returns_default(self):
        self.assertEqual(_score(None), 1.0)


class TestFilterItems(unittest.TestCase):
    """Tests for _filter_items function."""

    def test_filter_dict_items_by_priority(self):
        items = [
            {"name": "A", "priority": 3},
            {"name": "B", "priority": 1},
            {"name": "C", "priority": 2},
        ]
        result = _filter_items(items, cutoff=2)
        names = [it["name"] for it in result]
        self.assertIn("A", names)
        self.assertIn("C", names)
        self.assertNotIn("B", names)

    def test_filter_dict_items_by_usefulness(self):
        items = [
            {"name": "A", "usefulness": 3},
            {"name": "B", "usefulness": 1},
        ]
        result = _filter_items(items, cutoff=2)
        names = [it["name"] for it in result]
        self.assertIn("A", names)
        self.assertNotIn("B", names)

    def test_priority_takes_precedence_over_usefulness(self):
        items = [
            {"name": "A", "priority": 1, "usefulness": 5},
        ]
        result = _filter_items(items, cutoff=2)
        self.assertEqual(len(result), 0)

    def test_dict_without_priority_defaults_to_1(self):
        items = [{"name": "A"}]
        result_low = _filter_items(items, cutoff=0.5)
        result_high = _filter_items(items, cutoff=2)
        self.assertEqual(len(result_low), 1)
        self.assertEqual(len(result_high), 0)

    def test_string_items_kept_when_cutoff_lte_1(self):
        items = ["A", "B", "C"]
        result = _filter_items(items, cutoff=1.0)
        self.assertEqual(result, ["A", "B", "C"])

    def test_string_items_dropped_when_cutoff_gt_1(self):
        items = ["A", "B", "C"]
        result = _filter_items(items, cutoff=1.5)
        self.assertEqual(result, [])

    def test_empty_items(self):
        self.assertEqual(_filter_items([], cutoff=1), [])

    def test_none_items(self):
        self.assertEqual(_filter_items(None, cutoff=1), [])


class TestFilterSkillsGroups(unittest.TestCase):
    """Tests for _filter_skills_groups function."""

    def test_filters_items_within_groups(self):
        groups = [
            {
                "title": "Languages",
                "items": [
                    {"name": "Python", "priority": 3},
                    {"name": "Go", "priority": 1},
                ],
            }
        ]
        result = _filter_skills_groups(groups, cutoff=2)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["items"]), 1)
        self.assertEqual(result[0]["items"][0]["name"], "Python")

    def test_drops_empty_groups(self):
        groups = [
            {
                "title": "Languages",
                "items": [{"name": "Go", "priority": 1}],
            }
        ]
        result = _filter_skills_groups(groups, cutoff=2)
        self.assertEqual(result, [])

    def test_preserves_group_metadata(self):
        groups = [
            {
                "title": "Languages",
                "description": "Programming languages",
                "items": [{"name": "Python", "priority": 3}],
            }
        ]
        result = _filter_skills_groups(groups, cutoff=1)
        self.assertEqual(result[0]["title"], "Languages")
        self.assertEqual(result[0]["description"], "Programming languages")

    def test_handles_groups_without_items_list(self):
        groups = [{"title": "Empty"}]
        result = _filter_skills_groups(groups, cutoff=1)
        self.assertEqual(len(result), 1)

    def test_handles_non_dict_groups(self):
        groups = ["string_group"]
        result = _filter_skills_groups(groups, cutoff=1)
        self.assertEqual(result, ["string_group"])

    def test_empty_groups(self):
        self.assertEqual(_filter_skills_groups([], cutoff=1), [])

    def test_none_groups(self):
        self.assertEqual(_filter_skills_groups(None, cutoff=1), [])


class TestFilterExperience(unittest.TestCase):
    """Tests for _filter_experience function."""

    def test_filters_roles_by_priority(self):
        exp = [
            {"title": "Senior Dev", "priority": 3},
            {"title": "Junior Dev", "priority": 1},
        ]
        result = _filter_experience(exp, cutoff=2)
        titles = [e["title"] for e in result]
        self.assertIn("Senior Dev", titles)
        self.assertNotIn("Junior Dev", titles)

    def test_filters_bullets_by_priority(self):
        exp = [
            {
                "title": "Developer",
                "priority": 3,  # Role passes cutoff
                "bullets": [
                    {"text": "Important task", "priority": 3},
                    {"text": "Minor task", "priority": 1},
                ],
            }
        ]
        result = _filter_experience(exp, cutoff=2)
        self.assertEqual(len(result[0]["bullets"]), 1)

    def test_role_without_priority_defaults_to_1(self):
        exp = [{"title": "Developer"}]
        result_low = _filter_experience(exp, cutoff=0.5)
        result_high = _filter_experience(exp, cutoff=2)
        self.assertEqual(len(result_low), 1)
        self.assertEqual(len(result_high), 0)

    def test_skips_non_dict_items(self):
        exp = [{"title": "Developer"}, "string_item", None]
        result = _filter_experience(exp, cutoff=1)
        self.assertEqual(len(result), 1)

    def test_preserves_role_metadata(self):
        exp = [
            {
                "title": "Developer",
                "company": "TechCorp",
                "start": "2020",
                "end": "2023",
                "priority": 3,
            }
        ]
        result = _filter_experience(exp, cutoff=1)
        self.assertEqual(result[0]["company"], "TechCorp")
        self.assertEqual(result[0]["start"], "2020")

    def test_empty_experience(self):
        self.assertEqual(_filter_experience([], cutoff=1), [])

    def test_none_experience(self):
        self.assertEqual(_filter_experience(None, cutoff=1), [])


class TestFilterByMinPriority(unittest.TestCase):
    """Tests for filter_by_min_priority function."""

    def setUp(self):
        self.candidate = {
            "name": "John Doe",
            "skills_groups": [
                {
                    "title": "Languages",
                    "items": [
                        {"name": "Python", "priority": 3},
                        {"name": "Go", "priority": 1},
                    ],
                }
            ],
            "technologies": [
                {"name": "Docker", "priority": 2},
                {"name": "Vagrant", "priority": 1},
            ],
            "interests": [
                {"topic": "AI", "priority": 3},
                {"topic": "Blockchain", "priority": 1},
            ],
            "experience": [
                {"title": "Senior Dev", "priority": 3, "bullets": []},
                {"title": "Junior Dev", "priority": 1, "bullets": []},
            ],
        }

    def test_filters_skills_groups(self):
        result = filter_by_min_priority(self.candidate, 2)
        items = result["skills_groups"][0]["items"]
        names = [it["name"] for it in items]
        self.assertIn("Python", names)
        self.assertNotIn("Go", names)

    def test_filters_technologies(self):
        result = filter_by_min_priority(self.candidate, 2)
        names = [it["name"] for it in result["technologies"]]
        self.assertIn("Docker", names)
        self.assertNotIn("Vagrant", names)

    def test_filters_interests(self):
        result = filter_by_min_priority(self.candidate, 2)
        topics = [it["topic"] for it in result["interests"]]
        self.assertIn("AI", topics)
        self.assertNotIn("Blockchain", topics)

    def test_filters_experience(self):
        result = filter_by_min_priority(self.candidate, 2)
        titles = [e["title"] for e in result["experience"]]
        self.assertIn("Senior Dev", titles)
        self.assertNotIn("Junior Dev", titles)

    def test_returns_copy_of_data(self):
        result = filter_by_min_priority(self.candidate, 1)
        self.assertIsNot(result, self.candidate)

    def test_preserves_other_fields(self):
        result = filter_by_min_priority(self.candidate, 1)
        self.assertEqual(result["name"], "John Doe")

    def test_handles_missing_keys(self):
        data = {"name": "Jane"}
        result = filter_by_min_priority(data, 2)
        self.assertEqual(result["name"], "Jane")

    def test_filters_all_known_list_keys(self):
        data = {
            "languages": [{"name": "English", "priority": 1}],
            "presentations": [{"title": "Talk", "priority": 1}],
            "coursework": [{"course": "CS101", "priority": 1}],
            "summary": [{"text": "Summary", "priority": 1}],
        }
        result = filter_by_min_priority(data, 2)
        for key in ["languages", "presentations", "coursework", "summary"]:
            self.assertEqual(result[key], [])


if __name__ == "__main__":
    unittest.main()
