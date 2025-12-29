"""Tests for resume/job.py keyword normalization and spec building."""

import tempfile
import unittest
from pathlib import Path

from resume.job import _normalize_keywords, build_keyword_spec, load_job_config


class TestNormalizeKeywords(unittest.TestCase):
    """Tests for _normalize_keywords function."""

    def test_normalize_empty_list(self):
        result = _normalize_keywords([])
        self.assertEqual(result, [])

    def test_normalize_none(self):
        result = _normalize_keywords(None)
        self.assertEqual(result, [])

    def test_normalize_string_items(self):
        result = _normalize_keywords(["Python", "Java", "SQL"])
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], {"skill": "Python", "weight": 1})
        self.assertEqual(result[1], {"skill": "Java", "weight": 1})
        self.assertEqual(result[2], {"skill": "SQL", "weight": 1})

    def test_normalize_dict_items_with_skill_key(self):
        result = _normalize_keywords([{"skill": "Python", "weight": 3}])
        self.assertEqual(result, [{"skill": "Python", "weight": 3}])

    def test_normalize_dict_items_with_name_key(self):
        result = _normalize_keywords([{"name": "JavaScript", "weight": 2}])
        self.assertEqual(result, [{"skill": "JavaScript", "weight": 2}])

    def test_normalize_dict_items_with_key_key(self):
        result = _normalize_keywords([{"key": "Docker", "weight": 1}])
        self.assertEqual(result, [{"skill": "Docker", "weight": 1}])

    def test_normalize_dict_default_weight(self):
        result = _normalize_keywords([{"skill": "Kubernetes"}])
        self.assertEqual(result, [{"skill": "Kubernetes", "weight": 1}])

    def test_normalize_mixed_items(self):
        result = _normalize_keywords([
            "Python",
            {"skill": "Java", "weight": 2},
            {"name": "Go"},
        ])
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], {"skill": "Python", "weight": 1})
        self.assertEqual(result[1], {"skill": "Java", "weight": 2})
        self.assertEqual(result[2], {"skill": "Go", "weight": 1})

    def test_normalize_skips_dict_without_skill_name_key(self):
        result = _normalize_keywords([{"other": "value"}])
        self.assertEqual(result, [])

    def test_normalize_non_list_returns_empty(self):
        result = _normalize_keywords("not a list")
        self.assertEqual(result, [])


class TestBuildKeywordSpec(unittest.TestCase):
    """Tests for build_keyword_spec function."""

    def test_build_empty_config(self):
        spec, synonyms = build_keyword_spec({})
        self.assertEqual(spec["required"], [])
        self.assertEqual(spec["preferred"], [])
        self.assertEqual(spec["nice"], [])
        self.assertEqual(synonyms, {})

    def test_build_with_required_keywords(self):
        cfg = {"keywords": {"required": ["Python", "AWS"]}}
        spec, synonyms = build_keyword_spec(cfg)
        self.assertEqual(len(spec["required"]), 2)
        self.assertEqual(spec["required"][0]["skill"], "Python")

    def test_build_with_preferred_keywords(self):
        cfg = {"keywords": {"preferred": ["Docker", "Kubernetes"]}}
        spec, synonyms = build_keyword_spec(cfg)
        self.assertEqual(len(spec["preferred"]), 2)

    def test_build_with_nice_to_have(self):
        cfg = {"keywords": {"nice_to_have": ["GraphQL"]}}
        spec, synonyms = build_keyword_spec(cfg)
        self.assertEqual(len(spec["nice"]), 1)
        self.assertEqual(spec["nice"][0]["skill"], "GraphQL")

    def test_build_with_nice_shorthand(self):
        cfg = {"keywords": {"nice": ["Redis"]}}
        spec, synonyms = build_keyword_spec(cfg)
        self.assertEqual(len(spec["nice"]), 1)
        self.assertEqual(spec["nice"][0]["skill"], "Redis")

    def test_build_with_categories(self):
        cfg = {
            "keywords": {
                "soft_skills": ["Leadership", "Communication"],
                "tech_skills": ["Python", "Java"],
                "technologies": ["AWS", "GCP"],
            }
        }
        spec, synonyms = build_keyword_spec(cfg)
        self.assertEqual(len(spec["categories"]["soft_skills"]), 2)
        self.assertEqual(len(spec["categories"]["tech_skills"]), 2)
        self.assertEqual(len(spec["categories"]["technologies"]), 2)

    def test_build_with_technical_skills_alias(self):
        cfg = {"keywords": {"technical_skills": ["React", "Vue"]}}
        spec, synonyms = build_keyword_spec(cfg)
        self.assertEqual(len(spec["categories"]["tech_skills"]), 2)

    def test_build_with_technology_reference_aliases(self):
        cfg = {"keywords": {"individual_technology_reference": ["PostgreSQL"]}}
        spec, synonyms = build_keyword_spec(cfg)
        self.assertEqual(len(spec["categories"]["technologies"]), 1)

        cfg2 = {"keywords": {"individual_technology_references": ["MySQL"]}}
        spec2, _ = build_keyword_spec(cfg2)
        self.assertEqual(len(spec2["categories"]["technologies"]), 1)

    def test_build_with_synonyms_dict(self):
        cfg = {
            "keywords": {
                "synonyms": {
                    "JS": ["JavaScript", "ECMAScript"],
                    "K8s": ["Kubernetes"],
                }
            }
        }
        spec, synonyms = build_keyword_spec(cfg)
        self.assertEqual(synonyms["JS"], ["JavaScript", "ECMAScript"])
        self.assertEqual(synonyms["K8s"], ["Kubernetes"])

    def test_build_with_synonyms_string_value(self):
        cfg = {"keywords": {"synonyms": {"DB": "Database"}}}
        spec, synonyms = build_keyword_spec(cfg)
        self.assertEqual(synonyms["DB"], ["Database"])

    def test_build_with_none_keywords(self):
        cfg = {"keywords": None}
        spec, synonyms = build_keyword_spec(cfg)
        self.assertEqual(spec["required"], [])
        self.assertEqual(synonyms, {})


class TestLoadJobConfig(unittest.TestCase):
    """Tests for load_job_config function."""

    def test_load_yaml_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "job.yaml"
            cfg_path.write_text(
                "title: Software Engineer\n"
                "company: TechCorp\n"
                "keywords:\n"
                "  required:\n"
                "    - Python\n"
            )
            result = load_job_config(str(cfg_path))
            self.assertEqual(result["title"], "Software Engineer")
            self.assertEqual(result["company"], "TechCorp")
            self.assertIn("keywords", result)

    def test_load_json_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "job.json"
            cfg_path.write_text('{"title": "DevOps Engineer", "keywords": {"required": ["AWS"]}}')
            result = load_job_config(str(cfg_path))
            self.assertEqual(result["title"], "DevOps Engineer")


if __name__ == "__main__":
    unittest.main()
