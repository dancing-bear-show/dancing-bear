"""Tests for FilterPipeline execute, keyword extraction, factory, and apply_filters_from_args."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from resume.pipeline import FilterConfig, FilterPipeline, apply_filters_from_args, create_pipeline


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

    def _write_alignment_json(self, data: dict) -> str:
        """Write alignment data to temp JSON file and return path.

        Args:
            data: Dict to write as JSON

        Returns:
            Path to temp file (caller must unlink after use)
        """
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(data, f)
        f.flush()
        f.close()
        return f.name

    def test_extracts_skill_names(self):
        """Extracts skill names from matched_keywords list."""
        path = self._write_alignment_json({
            "matched_keywords": [
                {"skill": "Python", "tier": "required"},
                {"skill": "AWS", "tier": "preferred"},
            ]
        })

        pipeline = FilterPipeline({})
        result = pipeline._extract_matched_keywords(path)

        self.assertEqual(result, ["Python", "AWS"])
        Path(path).unlink()

    def test_handles_missing_skill_key(self):
        """Filters out entries without skill key."""
        path = self._write_alignment_json({
            "matched_keywords": [
                {"skill": "Python"},
                {"other": "data"},
                {"skill": "AWS"},
            ]
        })

        pipeline = FilterPipeline({})
        result = pipeline._extract_matched_keywords(path)

        self.assertEqual(result, ["Python", "AWS"])
        Path(path).unlink()

    def test_handles_non_dict_entries(self):
        """Filters out non-dict entries."""
        path = self._write_alignment_json({
            "matched_keywords": [
                {"skill": "Python"},
                "string_entry",
                None,
                {"skill": "AWS"},
            ]
        })

        pipeline = FilterPipeline({})
        result = pipeline._extract_matched_keywords(path)

        self.assertEqual(result, ["Python", "AWS"])
        Path(path).unlink()

    def test_handles_empty_matched_keywords(self):
        """Returns empty list for empty matched_keywords."""
        path = self._write_alignment_json({"matched_keywords": []})

        pipeline = FilterPipeline({})
        result = pipeline._extract_matched_keywords(path)

        self.assertEqual(result, [])
        Path(path).unlink()

    def test_handles_missing_matched_keywords_key(self):
        """Returns empty list when matched_keywords key missing."""
        path = self._write_alignment_json({"other": "data"})

        pipeline = FilterPipeline({})
        result = pipeline._extract_matched_keywords(path)

        self.assertEqual(result, [])
        Path(path).unlink()


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

        result = apply_filters_from_args({"name": "John"}, config=FilterConfig(min_priority=0.5))

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
            config=FilterConfig(filter_skills_alignment="/alignment.json"),
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
            config=FilterConfig(filter_exp_alignment="/alignment.json"),
        )

        mock_filter.assert_called_once()


if __name__ == "__main__":
    unittest.main()
