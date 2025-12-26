"""Tests for resume/pipeline.py."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from resume.pipeline import (
    FilterPipeline,
    create_pipeline,
    apply_filters_from_args,
)


class TestFilterPipelineInit(unittest.TestCase):
    """Tests for FilterPipeline initialization."""

    def test_creates_shallow_copy(self):
        original = {"name": "Test", "skills": ["Python"]}
        pipeline = FilterPipeline(original)
        # Modifying pipeline data shouldn't affect original
        pipeline._data["name"] = "Modified"
        self.assertEqual(original["name"], "Test")

    def test_initializes_empty_synonyms(self):
        pipeline = FilterPipeline({})
        self.assertEqual(pipeline._synonyms, {})


class TestFilterPipelineChaining(unittest.TestCase):
    """Tests for FilterPipeline method chaining."""

    def test_with_profile_overlays_returns_self(self):
        pipeline = FilterPipeline({"name": "Test"})
        result = pipeline.with_profile_overlays(None)
        self.assertIs(result, pipeline)

    def test_with_priority_filter_returns_self(self):
        pipeline = FilterPipeline({"name": "Test"})
        result = pipeline.with_priority_filter(None)
        self.assertIs(result, pipeline)

    def test_with_skill_filter_returns_self(self):
        pipeline = FilterPipeline({"name": "Test"})
        result = pipeline.with_skill_filter(None)
        self.assertIs(result, pipeline)

    def test_with_experience_filter_returns_self(self):
        pipeline = FilterPipeline({"name": "Test"})
        result = pipeline.with_experience_filter(None)
        self.assertIs(result, pipeline)

    def test_full_chain(self):
        data = {"name": "Test"}
        result = (
            FilterPipeline(data)
            .with_profile_overlays(None)
            .with_skill_filter(None)
            .with_experience_filter(None)
            .with_priority_filter(None)
            .execute()
        )
        self.assertEqual(result["name"], "Test")


class TestFilterPipelineProfileOverlays(unittest.TestCase):
    """Tests for with_profile_overlays method."""

    def test_none_profile_is_noop(self):
        data = {"name": "Original"}
        pipeline = FilterPipeline(data)
        pipeline.with_profile_overlays(None)
        self.assertEqual(pipeline._data["name"], "Original")

    @patch("resume.pipeline.apply_profile_overlays")
    def test_applies_overlays_when_profile_set(self, mock_apply):
        mock_apply.return_value = {"name": "Modified"}
        data = {"name": "Original"}
        pipeline = FilterPipeline(data)
        pipeline.with_profile_overlays("work")
        mock_apply.assert_called_once()
        self.assertEqual(pipeline._data["name"], "Modified")


class TestFilterPipelinePriorityFilter(unittest.TestCase):
    """Tests for with_priority_filter method."""

    def test_none_priority_is_noop(self):
        data = {"skills": ["Python"]}
        pipeline = FilterPipeline(data)
        pipeline.with_priority_filter(None)
        self.assertEqual(pipeline._data["skills"], ["Python"])

    @patch("resume.pipeline.filter_by_min_priority")
    def test_applies_filter_when_priority_set(self, mock_filter):
        mock_filter.return_value = {"skills": ["Filtered"]}
        data = {"skills": ["Python"]}
        pipeline = FilterPipeline(data)
        pipeline.with_priority_filter(0.5)
        mock_filter.assert_called_once()


class TestFilterPipelineSkillFilter(unittest.TestCase):
    """Tests for with_skill_filter method."""

    def test_none_alignment_is_noop(self):
        data = {"skills": ["Python"]}
        pipeline = FilterPipeline(data)
        result = pipeline.with_skill_filter(None)
        self.assertEqual(pipeline._data["skills"], ["Python"])

    def test_with_alignment_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            alignment_path = Path(tmpdir) / "alignment.json"
            alignment_path.write_text(json.dumps({
                "matched_keywords": [
                    {"skill": "Python", "tier": "required"},
                    {"skill": "AWS", "tier": "preferred"},
                ]
            }))

            data = {"skills": ["Python", "Java", "AWS"]}
            pipeline = FilterPipeline(data)
            # The filter is applied, but actual filtering depends on filter_skills_by_keywords
            result = pipeline.with_skill_filter(str(alignment_path))
            self.assertIsNotNone(result)


class TestFilterPipelineExperienceFilter(unittest.TestCase):
    """Tests for with_experience_filter method."""

    def test_none_alignment_is_noop(self):
        data = {"experience": [{"title": "Dev"}]}
        pipeline = FilterPipeline(data)
        pipeline.with_experience_filter(None)
        self.assertEqual(len(pipeline._data["experience"]), 1)


class TestFilterPipelineExtractMatchedKeywords(unittest.TestCase):
    """Tests for _extract_matched_keywords method."""

    def test_extracts_skills_from_alignment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "alignment.json"
            path.write_text(json.dumps({
                "matched_keywords": [
                    {"skill": "Python", "tier": "required"},
                    {"skill": "AWS", "tier": "preferred"},
                ]
            }))

            pipeline = FilterPipeline({})
            keywords = pipeline._extract_matched_keywords(str(path))
            self.assertEqual(keywords, ["Python", "AWS"])

    def test_handles_empty_matched_keywords(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "alignment.json"
            path.write_text(json.dumps({"matched_keywords": []}))

            pipeline = FilterPipeline({})
            keywords = pipeline._extract_matched_keywords(str(path))
            self.assertEqual(keywords, [])

    def test_filters_non_dict_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "alignment.json"
            path.write_text(json.dumps({
                "matched_keywords": [
                    {"skill": "Python"},
                    "invalid",  # Not a dict
                    {"no_skill_key": True},  # Missing skill key
                ]
            }))

            pipeline = FilterPipeline({})
            keywords = pipeline._extract_matched_keywords(str(path))
            self.assertEqual(keywords, ["Python"])


class TestFilterPipelineProperties(unittest.TestCase):
    """Tests for pipeline properties."""

    def test_data_property_returns_copy(self):
        original = {"name": "Test"}
        pipeline = FilterPipeline(original)
        data = pipeline.data
        data["name"] = "Modified"
        self.assertEqual(pipeline._data["name"], "Test")

    def test_synonyms_property_returns_copy(self):
        pipeline = FilterPipeline({})
        pipeline._synonyms["Python"] = ["py"]
        synonyms = pipeline.synonyms
        # Adding a new key to the copy doesn't affect internal state
        synonyms["Java"] = ["java"]
        self.assertNotIn("Java", pipeline._synonyms)


class TestFilterPipelineExecute(unittest.TestCase):
    """Tests for execute method."""

    def test_returns_data(self):
        data = {"name": "Test", "skills": ["Python"]}
        result = FilterPipeline(data).execute()
        self.assertEqual(result["name"], "Test")
        self.assertEqual(result["skills"], ["Python"])


class TestCreatePipeline(unittest.TestCase):
    """Tests for create_pipeline factory function."""

    def test_creates_pipeline(self):
        data = {"name": "Test"}
        pipeline = create_pipeline(data)
        self.assertIsInstance(pipeline, FilterPipeline)
        self.assertEqual(pipeline._data["name"], "Test")


class TestApplyFiltersFromArgs(unittest.TestCase):
    """Tests for apply_filters_from_args convenience function."""

    def test_with_no_filters(self):
        data = {"name": "Test", "skills": ["Python"]}
        result = apply_filters_from_args(data)
        self.assertEqual(result["name"], "Test")

    def test_returns_dict(self):
        data = {"name": "Test"}
        result = apply_filters_from_args(data)
        self.assertIsInstance(result, dict)

    @patch("resume.pipeline.apply_profile_overlays")
    def test_applies_profile_when_provided(self, mock_apply):
        mock_apply.return_value = {"name": "Overlaid"}
        data = {"name": "Original"}
        result = apply_filters_from_args(data, profile="work")
        mock_apply.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
