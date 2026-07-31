"""Tests for FilterPipeline initialization, chaining, and filter methods."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from resume.pipeline import FilterPipeline


class TestFilterPipelineInit(unittest.TestCase):
    """Tests for FilterPipeline initialization."""

    def test_init_stores_shallow_copy(self):
        """Initial data is shallow copied to avoid mutation."""
        original = {"name": "John", "skills": ["Python"]}
        pipeline = FilterPipeline(original)
        # Modify pipeline data
        pipeline._data["name"] = "Jane"
        # Original should be unchanged
        self.assertEqual(original["name"], "John")

    def test_init_synonyms_empty(self):
        """Synonyms start empty."""
        pipeline = FilterPipeline({"name": "Test"})
        self.assertEqual(pipeline._synonyms, {})

    def test_data_property_returns_copy(self):
        """data property returns a copy."""
        pipeline = FilterPipeline({"name": "John"})
        data = pipeline.data
        data["name"] = "Jane"
        self.assertEqual(pipeline._data["name"], "John")

    def test_synonyms_property_returns_copy(self):
        """synonyms property returns a copy."""
        pipeline = FilterPipeline({"name": "John"})
        pipeline._synonyms = {"py": ["python"]}
        syns = pipeline.synonyms
        syns["js"] = ["javascript"]
        self.assertNotIn("js", pipeline._synonyms)


class TestFilterPipelineChaining(unittest.TestCase):
    """Tests for method chaining."""

    def test_with_profile_overlays_returns_self(self):
        """with_profile_overlays returns self for chaining."""
        pipeline = FilterPipeline({"name": "Test"})
        with patch("resume.pipeline.apply_profile_overlays", return_value={"name": "Test"}):
            result = pipeline.with_profile_overlays("profile")
        self.assertIs(result, pipeline)

    def test_with_synonyms_from_job_returns_self(self):
        """with_synonyms_from_job returns self for chaining."""
        pipeline = FilterPipeline({"name": "Test"})
        result = pipeline.with_synonyms_from_job(None)
        self.assertIs(result, pipeline)

    def test_with_skill_filter_returns_self(self):
        """with_skill_filter returns self for chaining."""
        pipeline = FilterPipeline({"name": "Test"})
        result = pipeline.with_skill_filter(None)
        self.assertIs(result, pipeline)

    def test_with_experience_filter_returns_self(self):
        """with_experience_filter returns self for chaining."""
        pipeline = FilterPipeline({"name": "Test"})
        result = pipeline.with_experience_filter(None)
        self.assertIs(result, pipeline)

    def test_with_priority_filter_returns_self(self):
        """with_priority_filter returns self for chaining."""
        pipeline = FilterPipeline({"name": "Test"})
        result = pipeline.with_priority_filter(None)
        self.assertIs(result, pipeline)

    def test_full_chain(self):
        """Full method chain works."""
        pipeline = FilterPipeline({"name": "Test"})
        with patch("resume.pipeline.apply_profile_overlays", return_value={"name": "Test"}), \
             patch("resume.pipeline.filter_by_min_priority", return_value={"name": "Test"}):
            result = (
                pipeline
                .with_profile_overlays("profile")
                .with_skill_filter(None)
                .with_experience_filter(None)
                .with_priority_filter(0.5)
                .execute()
            )
        self.assertIsInstance(result, dict)


class TestWithProfileOverlays(unittest.TestCase):
    """Tests for with_profile_overlays method."""

    def test_none_profile_is_noop(self):
        """None profile does nothing."""
        original = {"name": "John"}
        pipeline = FilterPipeline(original)
        pipeline.with_profile_overlays(None)
        self.assertEqual(pipeline._data, {"name": "John"})

    def test_empty_string_profile_is_noop(self):
        """Empty string profile does nothing (falsy)."""
        original = {"name": "John"}
        pipeline = FilterPipeline(original)
        pipeline.with_profile_overlays("")
        self.assertEqual(pipeline._data, {"name": "John"})

    @patch("resume.pipeline.apply_profile_overlays")
    def test_calls_apply_profile_overlays(self, mock_apply):
        """Calls apply_profile_overlays with data and profile."""
        mock_apply.return_value = {"name": "John", "profile": "work"}
        pipeline = FilterPipeline({"name": "John"})
        pipeline.with_profile_overlays("work")
        mock_apply.assert_called_once_with({"name": "John"}, "work")
        self.assertEqual(pipeline._data, {"name": "John", "profile": "work"})


class TestWithSynonymsFromJob(unittest.TestCase):
    """Tests for with_synonyms_from_job method."""

    def test_none_job_path_is_noop(self):
        """None job_path does nothing."""
        pipeline = FilterPipeline({"name": "Test"})
        pipeline.with_synonyms_from_job(None)
        self.assertEqual(pipeline._synonyms, {})

    @patch("resume.pipeline.load_job_config")
    @patch("resume.pipeline.build_keyword_spec")
    def test_loads_synonyms_from_job(self, mock_build, mock_load):
        """Loads and stores synonyms from job config."""
        mock_load.return_value = {"title": "Software Engineer"}
        mock_build.return_value = ({"required": []}, {"py": ["python", "python3"]})

        pipeline = FilterPipeline({"name": "Test"})
        pipeline.with_synonyms_from_job("/path/to/job.yaml")

        mock_load.assert_called_once_with("/path/to/job.yaml")
        self.assertEqual(pipeline._synonyms, {"py": ["python", "python3"]})

    @patch("resume.pipeline.load_job_config")
    @patch("resume.pipeline.build_keyword_spec")
    def test_updates_existing_synonyms(self, mock_build, mock_load):
        """Updates existing synonyms dict."""
        mock_load.return_value = {}
        mock_build.return_value = ({}, {"js": ["javascript"]})

        pipeline = FilterPipeline({"name": "Test"})
        pipeline._synonyms = {"py": ["python"]}
        pipeline.with_synonyms_from_job("/path/to/job.yaml")

        self.assertIn("py", pipeline._synonyms)
        self.assertIn("js", pipeline._synonyms)

    @patch("resume.pipeline.load_job_config")
    def test_handles_load_exception(self, mock_load):
        """Silently handles job config load failures."""
        mock_load.side_effect = FileNotFoundError("not found")

        pipeline = FilterPipeline({"name": "Test"})
        pipeline.with_synonyms_from_job("/nonexistent/job.yaml")

        self.assertEqual(pipeline._synonyms, {})


class TestWithSkillFilter(unittest.TestCase):
    """Tests for with_skill_filter method."""

    def test_none_alignment_path_is_noop(self):
        """None alignment_path does nothing."""
        pipeline = FilterPipeline({"skills": ["Python"]})
        pipeline.with_skill_filter(None)
        self.assertEqual(pipeline._data, {"skills": ["Python"]})

    @patch("resume.pipeline.read_yaml_or_json")
    @patch("resume.pipeline.filter_skills_by_keywords")
    def test_filters_skills_by_alignment(self, mock_filter, mock_read):
        """Filters skills using alignment keywords."""
        mock_read.return_value = {
            "matched_keywords": [{"skill": "Python"}, {"skill": "AWS"}]
        }
        mock_filter.return_value = {"skills": ["Python", "AWS"]}

        pipeline = FilterPipeline({"skills": ["Python", "AWS", "Java"]})
        pipeline.with_skill_filter("/path/to/alignment.json")

        mock_filter.assert_called_once()
        self.assertEqual(pipeline._data, {"skills": ["Python", "AWS"]})

    @patch("resume.pipeline.read_yaml_or_json")
    @patch("resume.pipeline.filter_skills_by_keywords")
    @patch("resume.pipeline.load_job_config")
    @patch("resume.pipeline.build_keyword_spec")
    def test_loads_job_synonyms_when_provided(self, mock_build, mock_load, mock_filter, mock_read):
        """Loads job synonyms when job_path provided."""
        mock_read.return_value = {"matched_keywords": [{"skill": "Python"}]}
        mock_filter.return_value = {"skills": ["Python"]}
        mock_load.return_value = {}
        mock_build.return_value = ({}, {"py": ["python"]})

        pipeline = FilterPipeline({"skills": ["Python"]})
        pipeline.with_skill_filter("/alignment.json", job_path="/job.yaml")

        mock_load.assert_called()
        self.assertIn("py", pipeline._synonyms)

    @patch("resume.pipeline.read_yaml_or_json")
    def test_propagates_read_exception(self, mock_read):
        """Alignment file read failures now propagate (C2: exception-swallowing removed)."""
        mock_read.side_effect = FileNotFoundError("not found")

        pipeline = FilterPipeline({"skills": ["Python"]})
        with self.assertRaises(FileNotFoundError):
            pipeline.with_skill_filter("/nonexistent.json")

    @patch("resume.pipeline.read_yaml_or_json")
    def test_handles_empty_matched_keywords(self, mock_read):
        """Handles alignment with no matched keywords."""
        mock_read.return_value = {"matched_keywords": []}

        pipeline = FilterPipeline({"skills": ["Python"]})
        pipeline.with_skill_filter("/alignment.json")

        # Data unchanged when no keywords matched
        self.assertEqual(pipeline._data, {"skills": ["Python"]})


class TestWithExperienceFilter(unittest.TestCase):
    """Tests for with_experience_filter method."""

    def test_none_alignment_path_is_noop(self):
        """None alignment_path does nothing."""
        pipeline = FilterPipeline({"experience": [{"title": "Dev"}]})
        pipeline.with_experience_filter(None)
        self.assertEqual(pipeline._data, {"experience": [{"title": "Dev"}]})

    @patch("resume.pipeline.read_yaml_or_json")
    @patch("resume.pipeline.filter_experience_by_keywords")
    def test_filters_experience_by_alignment(self, mock_filter, mock_read):
        """Filters experience using alignment keywords."""
        mock_read.return_value = {
            "matched_keywords": [{"skill": "Python"}]
        }
        mock_filter.return_value = {"experience": [{"title": "Python Dev"}]}

        pipeline = FilterPipeline({"experience": [{"title": "Dev"}, {"title": "Python Dev"}]})
        pipeline.with_experience_filter("/alignment.json")

        mock_filter.assert_called_once()

    @patch("resume.pipeline.read_yaml_or_json")
    @patch("resume.pipeline.filter_experience_by_keywords")
    def test_passes_optional_params(self, mock_filter, mock_read):
        """Passes optional params to filter function via ExperienceFilterConfig."""
        from resume.render_config import ExperienceFilterConfig
        mock_read.return_value = {"matched_keywords": [{"skill": "Python"}]}
        mock_filter.return_value = {"experience": []}

        cfg = ExperienceFilterConfig(max_roles=3, max_bullets_per_role=5, min_score=2)
        pipeline = FilterPipeline({"experience": []})
        pipeline.with_experience_filter("/alignment.json", filter_cfg=cfg)

        call_kwargs = mock_filter.call_args[1]
        passed_cfg = call_kwargs["filter_cfg"]
        self.assertEqual(passed_cfg.max_roles, 3)
        self.assertEqual(passed_cfg.max_bullets_per_role, 5)
        self.assertEqual(passed_cfg.min_score, 2)

    @patch("resume.pipeline.read_yaml_or_json")
    def test_propagates_read_exception(self, mock_read):
        """Alignment file read failures now propagate (C2: exception-swallowing removed)."""
        mock_read.side_effect = FileNotFoundError("not found")

        pipeline = FilterPipeline({"experience": [{"title": "Dev"}]})
        with self.assertRaises(FileNotFoundError):
            pipeline.with_experience_filter("/nonexistent.json")


class TestWithPriorityFilter(unittest.TestCase):
    """Tests for with_priority_filter method."""

    def test_none_priority_is_noop(self):
        """None min_priority does nothing."""
        pipeline = FilterPipeline({"skills": ["Python"]})
        pipeline.with_priority_filter(None)
        self.assertEqual(pipeline._data, {"skills": ["Python"]})

    @patch("resume.pipeline.filter_by_min_priority")
    def test_applies_priority_filter(self, mock_filter):
        """Applies priority filter with threshold."""
        mock_filter.return_value = {"skills_groups": []}

        pipeline = FilterPipeline({"skills_groups": [{"priority": 0.8}]})
        pipeline.with_priority_filter(0.5)

        mock_filter.assert_called_once_with({"skills_groups": [{"priority": 0.8}]}, 0.5)

    @patch("resume.pipeline.filter_by_min_priority")
    def test_converts_to_float(self, mock_filter):
        """Converts min_priority to float."""
        mock_filter.return_value = {}

        pipeline = FilterPipeline({})
        pipeline.with_priority_filter(1)  # int

        call_args = mock_filter.call_args[0]
        self.assertIsInstance(call_args[1], float)

    @patch("resume.pipeline.filter_by_min_priority")
    def test_zero_priority_applies_filter(self, mock_filter):
        """Zero priority still applies filter (is not None)."""
        mock_filter.return_value = {}

        pipeline = FilterPipeline({})
        pipeline.with_priority_filter(0.0)

        mock_filter.assert_called_once()


if __name__ == "__main__":
    unittest.main()
