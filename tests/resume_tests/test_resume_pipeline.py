"""Tests for resume/pipeline.py FilterPipeline class."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from resume.pipeline import FilterPipeline, apply_filters_from_args, create_pipeline


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
    def test_handles_read_exception(self, mock_read):
        """Silently handles alignment file read failures."""
        mock_read.side_effect = FileNotFoundError("not found")

        pipeline = FilterPipeline({"skills": ["Python"]})
        pipeline.with_skill_filter("/nonexistent.json")

        # Data unchanged
        self.assertEqual(pipeline._data, {"skills": ["Python"]})

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
        """Passes optional params to filter function."""
        mock_read.return_value = {"matched_keywords": [{"skill": "Python"}]}
        mock_filter.return_value = {"experience": []}

        pipeline = FilterPipeline({"experience": []})
        pipeline.with_experience_filter(
            "/alignment.json",
            max_roles=3,
            max_bullets_per_role=5,
            min_score=2,
        )

        call_kwargs = mock_filter.call_args[1]
        self.assertEqual(call_kwargs["max_roles"], 3)
        self.assertEqual(call_kwargs["max_bullets_per_role"], 5)
        self.assertEqual(call_kwargs["min_score"], 2)

    @patch("resume.pipeline.read_yaml_or_json")
    def test_handles_read_exception(self, mock_read):
        """Silently handles alignment file read failures."""
        mock_read.side_effect = FileNotFoundError("not found")

        pipeline = FilterPipeline({"experience": [{"title": "Dev"}]})
        pipeline.with_experience_filter("/nonexistent.json")

        # Data unchanged
        self.assertEqual(pipeline._data, {"experience": [{"title": "Dev"}]})


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


class TestExecute(unittest.TestCase):
    """Tests for execute method."""

    def test_returns_current_data(self):
        """Returns the current data state."""
        pipeline = FilterPipeline({"name": "John", "skills": ["Python"]})
        result = pipeline.execute()
        self.assertEqual(result, {"name": "John", "skills": ["Python"]})

    def test_returns_same_dict_object(self):
        """Returns the actual internal dict (not a copy)."""
        pipeline = FilterPipeline({"name": "John"})
        result = pipeline.execute()
        self.assertIs(result, pipeline._data)


class TestExtractMatchedKeywords(unittest.TestCase):
    """Tests for _extract_matched_keywords helper."""

    def test_extracts_skill_names(self):
        """Extracts skill names from matched_keywords list."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "matched_keywords": [
                    {"skill": "Python", "tier": "required"},
                    {"skill": "AWS", "tier": "preferred"},
                ]
            }, f)
            f.flush()

            pipeline = FilterPipeline({})
            result = pipeline._extract_matched_keywords(f.name)

            self.assertEqual(result, ["Python", "AWS"])
            Path(f.name).unlink()

    def test_handles_missing_skill_key(self):
        """Filters out entries without skill key."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "matched_keywords": [
                    {"skill": "Python"},
                    {"other": "data"},
                    {"skill": "AWS"},
                ]
            }, f)
            f.flush()

            pipeline = FilterPipeline({})
            result = pipeline._extract_matched_keywords(f.name)

            self.assertEqual(result, ["Python", "AWS"])
            Path(f.name).unlink()

    def test_handles_non_dict_entries(self):
        """Filters out non-dict entries."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "matched_keywords": [
                    {"skill": "Python"},
                    "string_entry",
                    None,
                    {"skill": "AWS"},
                ]
            }, f)
            f.flush()

            pipeline = FilterPipeline({})
            result = pipeline._extract_matched_keywords(f.name)

            self.assertEqual(result, ["Python", "AWS"])
            Path(f.name).unlink()

    def test_handles_empty_matched_keywords(self):
        """Returns empty list for empty matched_keywords."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"matched_keywords": []}, f)
            f.flush()

            pipeline = FilterPipeline({})
            result = pipeline._extract_matched_keywords(f.name)

            self.assertEqual(result, [])
            Path(f.name).unlink()

    def test_handles_missing_matched_keywords_key(self):
        """Returns empty list when matched_keywords key missing."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"other": "data"}, f)
            f.flush()

            pipeline = FilterPipeline({})
            result = pipeline._extract_matched_keywords(f.name)

            self.assertEqual(result, [])
            Path(f.name).unlink()


class TestCreatePipeline(unittest.TestCase):
    """Tests for create_pipeline factory function."""

    def test_creates_filter_pipeline(self):
        """Returns a FilterPipeline instance."""
        result = create_pipeline({"name": "Test"})
        self.assertIsInstance(result, FilterPipeline)

    def test_passes_data_to_pipeline(self):
        """Data is passed to the pipeline."""
        result = create_pipeline({"name": "John", "skills": ["Python"]})
        self.assertEqual(result._data, {"name": "John", "skills": ["Python"]})


class TestApplyFiltersFromArgs(unittest.TestCase):
    """Tests for apply_filters_from_args convenience function."""

    def test_returns_data_without_filters(self):
        """Returns data when no filters specified."""
        data = {"name": "John", "skills": ["Python"]}
        result = apply_filters_from_args(data)
        self.assertEqual(result["name"], "John")
        self.assertEqual(result["skills"], ["Python"])

    @patch("resume.pipeline.apply_profile_overlays")
    def test_applies_profile_overlay(self, mock_overlay):
        """Applies profile overlay when specified."""
        mock_overlay.return_value = {"name": "John", "profile": "work"}

        result = apply_filters_from_args({"name": "John"}, profile="work")

        mock_overlay.assert_called_once()
        self.assertEqual(result["profile"], "work")

    @patch("resume.pipeline.filter_by_min_priority")
    def test_applies_priority_filter(self, mock_filter):
        """Applies priority filter when specified."""
        mock_filter.return_value = {"name": "John", "filtered": True}

        result = apply_filters_from_args({"name": "John"}, min_priority=0.5)

        mock_filter.assert_called_once()
        self.assertTrue(result["filtered"])

    @patch("resume.pipeline.read_yaml_or_json")
    @patch("resume.pipeline.filter_skills_by_keywords")
    def test_applies_skill_filter(self, mock_filter, mock_read):
        """Applies skill filter when alignment specified."""
        mock_read.return_value = {"matched_keywords": [{"skill": "Python"}]}
        mock_filter.return_value = {"skills": ["Python"]}

        apply_filters_from_args(
            {"skills": ["Python", "Java"]},
            filter_skills_alignment="/alignment.json",
        )

        mock_filter.assert_called_once()

    @patch("resume.pipeline.read_yaml_or_json")
    @patch("resume.pipeline.filter_experience_by_keywords")
    def test_applies_experience_filter(self, mock_filter, mock_read):
        """Applies experience filter when alignment specified."""
        mock_read.return_value = {"matched_keywords": [{"skill": "Python"}]}
        mock_filter.return_value = {"experience": []}

        apply_filters_from_args(
            {"experience": []},
            filter_exp_alignment="/alignment.json",
        )

        mock_filter.assert_called_once()


if __name__ == "__main__":
    unittest.main()
