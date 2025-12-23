"""FilterPipeline: Chainable data transformation pipeline for resume processing.

Consolidates the common pattern of:
1. Load data
2. Apply profile overlays
3. Filter skills by alignment keywords
4. Filter experience by alignment keywords
5. Filter by priority/usefulness threshold

Usage:
    from resume_assistant.pipeline import FilterPipeline

    data = (FilterPipeline(raw_data)
        .with_profile_overlays("my_profile")
        .with_skill_filter("alignment.json", job_path="job.yaml")
        .with_experience_filter("alignment.json", job_path="job.yaml")
        .with_priority_filter(0.5)
        .execute())
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .io_utils import read_yaml_or_json
from .job import build_keyword_spec, load_job_config
from .overlays import apply_profile_overlays
from .priority import filter_by_min_priority
from .skills_filter import filter_skills_by_keywords
from .experience_filter import filter_experience_by_keywords


class FilterPipeline:
    """Chainable pipeline for applying filters to resume/candidate data."""

    def __init__(self, data: Dict[str, Any]):
        """Initialize pipeline with candidate data.

        Args:
            data: The candidate/resume data dictionary to transform.
        """
        self._data = dict(data)  # shallow copy to avoid mutating original
        self._synonyms: Dict[str, List[str]] = {}

    def with_profile_overlays(self, profile: Optional[str]) -> "FilterPipeline":
        """Apply profile-specific config overlays from config/ directory.

        Args:
            profile: Profile name (e.g., 'personal', 'work'). If None, no-op.

        Returns:
            Self for chaining.
        """
        if profile:
            self._data = apply_profile_overlays(self._data, profile)
        return self

    def with_synonyms_from_job(
        self,
        job_path: Optional[Union[str, Path]],
    ) -> "FilterPipeline":
        """Load synonyms from a job config file to use in subsequent filters.

        Args:
            job_path: Path to job config (YAML/JSON). If None, no-op.

        Returns:
            Self for chaining.
        """
        if job_path:
            try:
                spec, syn = build_keyword_spec(load_job_config(str(job_path)))
                if syn:
                    self._synonyms.update(syn)
            except Exception:
                pass
        return self

    def with_skill_filter(
        self,
        alignment_path: Optional[Union[str, Path]],
        job_path: Optional[Union[str, Path]] = None,
    ) -> "FilterPipeline":
        """Filter skills to only those matching keywords from alignment report.

        Args:
            alignment_path: Path to alignment JSON with matched_keywords.
            job_path: Optional job config for additional synonyms.

        Returns:
            Self for chaining.
        """
        if not alignment_path:
            return self

        # Load job synonyms if provided
        if job_path:
            self.with_synonyms_from_job(job_path)

        try:
            matched = self._extract_matched_keywords(alignment_path)
            if matched:
                self._data = filter_skills_by_keywords(
                    self._data,
                    matched_keywords=matched,
                    synonyms=self._synonyms,
                )
        except Exception:
            pass

        return self

    def with_experience_filter(
        self,
        alignment_path: Optional[Union[str, Path]],
        job_path: Optional[Union[str, Path]] = None,
        max_roles: Optional[int] = None,
        max_bullets_per_role: Optional[int] = None,
        min_score: int = 1,
    ) -> "FilterPipeline":
        """Filter experience entries to those matching alignment keywords.

        Args:
            alignment_path: Path to alignment JSON with matched_keywords.
            job_path: Optional job config for additional synonyms.
            max_roles: Maximum number of roles to keep.
            max_bullets_per_role: Maximum bullets per role.
            min_score: Minimum keyword match score to keep a role.

        Returns:
            Self for chaining.
        """
        if not alignment_path:
            return self

        # Load job synonyms if provided
        if job_path:
            self.with_synonyms_from_job(job_path)

        try:
            matched = self._extract_matched_keywords(alignment_path)
            if matched:
                self._data = filter_experience_by_keywords(
                    self._data,
                    matched_keywords=matched,
                    synonyms=self._synonyms,
                    max_roles=max_roles,
                    max_bullets_per_role=max_bullets_per_role,
                    min_score=min_score,
                )
        except Exception:
            pass

        return self

    def with_priority_filter(
        self,
        min_priority: Optional[float],
    ) -> "FilterPipeline":
        """Filter items by priority/usefulness threshold.

        Applies to: skills_groups, technologies, interests, presentations,
        languages, coursework, summary, and experience.

        Args:
            min_priority: Minimum priority/usefulness score. If None, no-op.

        Returns:
            Self for chaining.
        """
        if min_priority is not None:
            self._data = filter_by_min_priority(self._data, float(min_priority))
        return self

    def execute(self) -> Dict[str, Any]:
        """Execute the pipeline and return the transformed data.

        Returns:
            The filtered/transformed data dictionary.
        """
        return self._data

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    def _extract_matched_keywords(
        self,
        alignment_path: Union[str, Path],
    ) -> List[str]:
        """Extract matched keyword names from an alignment report.

        Args:
            alignment_path: Path to alignment JSON/YAML.

        Returns:
            List of matched keyword strings.
        """
        al = read_yaml_or_json(str(alignment_path))
        matched_kw = al.get("matched_keywords") or []
        return [
            m.get("skill")
            for m in matched_kw
            if isinstance(m, dict) and m.get("skill")
        ]

    @property
    def data(self) -> Dict[str, Any]:
        """Access the current data state (read-only snapshot)."""
        return dict(self._data)

    @property
    def synonyms(self) -> Dict[str, List[str]]:
        """Access the current synonyms map (read-only snapshot)."""
        return dict(self._synonyms)


# -----------------------------------------------------------------------------
# Convenience factory functions
# -----------------------------------------------------------------------------


def create_pipeline(data: Dict[str, Any]) -> FilterPipeline:
    """Create a new FilterPipeline instance.

    Args:
        data: The candidate/resume data dictionary.

    Returns:
        A new FilterPipeline instance.
    """
    return FilterPipeline(data)


def apply_filters_from_args(
    data: Dict[str, Any],
    profile: Optional[str] = None,
    filter_skills_alignment: Optional[str] = None,
    filter_skills_job: Optional[str] = None,
    filter_exp_alignment: Optional[str] = None,
    filter_exp_job: Optional[str] = None,
    min_priority: Optional[float] = None,
) -> Dict[str, Any]:
    """Apply all filters using explicit arguments (convenience function).

    This mirrors the common CLI pattern but with explicit args instead of
    argparse.Namespace, making it easier to use programmatically.

    Args:
        data: The candidate/resume data.
        profile: Profile name for overlays.
        filter_skills_alignment: Path to alignment for skills filter.
        filter_skills_job: Path to job config for skills synonyms.
        filter_exp_alignment: Path to alignment for experience filter.
        filter_exp_job: Path to job config for experience synonyms.
        min_priority: Minimum priority threshold.

    Returns:
        The filtered data dictionary.
    """
    return (
        FilterPipeline(data)
        .with_profile_overlays(profile)
        .with_skill_filter(filter_skills_alignment, filter_skills_job)
        .with_experience_filter(filter_exp_alignment, filter_exp_job)
        .with_priority_filter(min_priority)
        .execute()
    )
