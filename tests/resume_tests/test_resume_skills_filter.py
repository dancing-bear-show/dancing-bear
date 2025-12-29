"""Tests for resume/skills_filter.py keyword-based filtering."""

from __future__ import annotations

import copy
import unittest

from resume.skills_filter import (
    _extract_item_name,
    _flatten_keywords,
    filter_skills_by_keywords,
)
from tests.resume_tests.fixtures import (
    SAMPLE_CANDIDATE_WITH_GROUPS,
    SAMPLE_SKILLS_GROUPS,
    make_candidate,
    make_keyword_spec,
)


class TestExtractItemName(unittest.TestCase):
    """Tests for _extract_item_name function."""

    def test_extract_from_dict_with_skill_key(self):
        item = {"skill": "Python", "weight": 2}
        self.assertEqual(_extract_item_name(item), "Python")

    def test_extract_from_dict_with_name_key(self):
        item = {"name": "JavaScript", "level": "expert"}
        self.assertEqual(_extract_item_name(item), "JavaScript")

    def test_skill_takes_precedence_over_name(self):
        item = {"skill": "Python", "name": "JavaScript"}
        self.assertEqual(_extract_item_name(item), "Python")

    def test_extract_from_string(self):
        self.assertEqual(_extract_item_name("Docker"), "Docker")

    def test_returns_none_for_empty_dict(self):
        self.assertIsNone(_extract_item_name({}))

    def test_returns_none_for_dict_without_skill_or_name(self):
        item = {"level": "expert", "years": 5}
        self.assertIsNone(_extract_item_name(item))

    def test_returns_none_for_other_types(self):
        self.assertIsNone(_extract_item_name(123))
        self.assertIsNone(_extract_item_name(None))
        self.assertIsNone(_extract_item_name([]))


class TestFlattenKeywords(unittest.TestCase):
    """Tests for _flatten_keywords function."""

    def test_flatten_required_tier(self):
        spec = make_keyword_spec(required=["Python", "Java"])
        result = _flatten_keywords(spec)
        self.assertIn("Python", result)
        self.assertIn("Java", result)

    def test_flatten_preferred_tier(self):
        spec = make_keyword_spec(preferred=["Docker", "Kubernetes"])
        result = _flatten_keywords(spec)
        self.assertIn("Docker", result)
        self.assertIn("Kubernetes", result)

    def test_flatten_nice_tier(self):
        spec = make_keyword_spec(nice=["Go", "Rust"])
        result = _flatten_keywords(spec)
        self.assertIn("Go", result)
        self.assertIn("Rust", result)

    def test_flatten_all_tiers(self):
        spec = make_keyword_spec(required=["Python"], preferred=["Docker"], nice=["Go"])
        result = _flatten_keywords(spec)
        self.assertEqual(len(result), 3)

    def test_flatten_categories(self):
        spec = make_keyword_spec(
            categories={"languages": ["Python", "Java"], "tools": ["Docker", "Git"]}
        )
        result = _flatten_keywords(spec)
        self.assertIn("Python", result)
        self.assertIn("Java", result)
        self.assertIn("Docker", result)
        self.assertIn("Git", result)

    def test_flatten_dict_items(self):
        spec = {
            "required": [
                {"skill": "Python", "weight": 2},
                {"name": "Java"},
            ],
            "preferred": [],
            "nice": [],
        }
        result = _flatten_keywords(spec)
        self.assertIn("Python", result)
        self.assertIn("Java", result)

    def test_empty_spec(self):
        result = _flatten_keywords({})
        self.assertEqual(result, [])

    def test_none_values_in_tiers(self):
        spec = {"required": None, "preferred": ["Docker"], "nice": []}
        result = _flatten_keywords(spec)
        self.assertIn("Docker", result)


class TestFilterSkillsByKeywords(unittest.TestCase):
    """Tests for filter_skills_by_keywords function."""

    def setUp(self):
        # Use shared fixtures with deep copy to avoid mutation
        self.candidate_with_groups = copy.deepcopy(SAMPLE_CANDIDATE_WITH_GROUPS)
        self.candidate_with_flat_skills = make_candidate(
            name="Jane Doe",
            skills=["Python", "JavaScript", "React", "Docker"],
        )

    def test_filters_groups_by_keyword(self):
        result = filter_skills_by_keywords(
            self.candidate_with_groups, ["Python", "Docker"]
        )
        # Should keep Python and Docker
        all_items = []
        for group in result["skills_groups"]:
            all_items.extend(group["items"])
        names = [it.get("name") for it in all_items]
        self.assertIn("Python", names)
        self.assertIn("Docker", names)
        self.assertNotIn("Java", names)
        self.assertNotIn("Go", names)

    def test_drops_empty_groups(self):
        result = filter_skills_by_keywords(
            self.candidate_with_groups, ["RandomSkillNotPresent"]
        )
        # All groups should be empty and dropped
        self.assertEqual(result["skills_groups"], [])

    def test_filters_flat_skills(self):
        result = filter_skills_by_keywords(
            self.candidate_with_flat_skills, ["Python", "Docker"]
        )
        self.assertIn("Python", result["skills"])
        self.assertIn("Docker", result["skills"])
        self.assertNotIn("JavaScript", result["skills"])
        self.assertNotIn("React", result["skills"])

    def test_uses_synonyms(self):
        synonyms = {"Python": ["python3", "py"]}
        candidate = {"skills": ["python3", "JavaScript"]}
        result = filter_skills_by_keywords(candidate, ["Python"], synonyms=synonyms)
        self.assertIn("python3", result["skills"])

    def test_matches_in_description(self):
        candidate = {
            "skills_groups": [
                {
                    "title": "Tools",
                    "items": [
                        {"name": "K8s", "desc": "Kubernetes orchestration"},
                    ],
                }
            ]
        }
        result = filter_skills_by_keywords(candidate, ["Kubernetes"])
        self.assertEqual(len(result["skills_groups"]), 1)
        self.assertEqual(len(result["skills_groups"][0]["items"]), 1)

    def test_returns_copy_of_data(self):
        result = filter_skills_by_keywords(self.candidate_with_groups, ["Python"])
        self.assertIsNot(result, self.candidate_with_groups)

    def test_empty_keywords_returns_empty_skills(self):
        result = filter_skills_by_keywords(self.candidate_with_flat_skills, [])
        self.assertEqual(result["skills"], [])

    def test_preserves_other_fields(self):
        result = filter_skills_by_keywords(self.candidate_with_groups, ["Python"])
        self.assertEqual(result["name"], "John Doe")

    def test_handles_string_items_in_groups(self):
        candidate = {
            "skills_groups": [
                {
                    "title": "Languages",
                    "items": ["Python", "Java", "Go"],
                }
            ]
        }
        result = filter_skills_by_keywords(candidate, ["Python"])
        self.assertEqual(len(result["skills_groups"]), 1)
        self.assertIn("Python", result["skills_groups"][0]["items"])

    def test_no_groups_uses_flat_skills(self):
        candidate = {"skills": ["Python", "Java"]}
        result = filter_skills_by_keywords(candidate, ["Python"])
        self.assertEqual(result["skills"], ["Python"])

    def test_preserves_group_title(self):
        result = filter_skills_by_keywords(self.candidate_with_groups, ["Python"])
        if result["skills_groups"]:
            self.assertEqual(result["skills_groups"][0]["title"], "Languages")


if __name__ == "__main__":
    unittest.main()
