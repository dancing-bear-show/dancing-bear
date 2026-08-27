"""FilterPipeline: Chainable data transformation pipeline for resume processing.

Consolidates the common pattern of:
1. Load data
2. Apply profile overlays
3. Filter skills by alignment keywords
4. Filter experience by alignment keywords
5. Filter by priority/usefulness threshold

Typed boundary, dict-domain interior
------------------------------------
`FilterPipeline` accepts and returns a :class:`~resume.schema.Resume`, but its
interior is **permanently** a dict domain: `__init__` does ``resume.to_dict()``
and :meth:`FilterPipeline.execute` does ``Resume.from_dict(...)``. Everything in
between -- `overlays`, `skills_filter`, `experience_filter`, `priority` -- keeps
operating on plain dicts and is not migrated to the schema.

That is a deliberate, approved boundary, not an unfinished migration. The filters
rebuild candidate data with dict spreads (``{**e, "bullets": ...}``) and fresh
dict literals, neither of which has a safe dataclass equivalent: a spread is
key-agnostic, and `dataclasses.replace` does not update the schema's ``_present``
set, so writing a previously-absent field would silently drop it on save. Keeping
the conversion at this class's own edges confines it to one place instead of
making it every caller's obligation.

The sandwich is lossless. ``Resume.from_dict(d).to_dict() == d`` holds exactly,
so converting in and back out is a no-op; the filters see, and produce, the same
dicts they always did.

Usage:
    from resume.pipeline import FilterPipeline
    from resume.schema import Resume

    resume = (FilterPipeline(Resume.from_dict(raw_data))
        .with_profile_overlays("my_profile")
        .with_skill_filter("alignment.json", job_path="job.yaml")
        .with_experience_filter("alignment.json", job_path="job.yaml")
        .with_priority_filter(0.5)
        .execute())
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .io_utils import read_yaml_or_json
from .job import build_keyword_spec, load_job_config
from .overlays import apply_profile_overlays
from .priority import filter_by_min_priority
from .schema import Resume
from .skills_filter import filter_skills_by_keywords
from .experience_filter import filter_experience_by_keywords
from .render_config import ExperienceFilterConfig


@dataclass(frozen=True)
class FilterConfig:
    """Bundled filter-configuration params for apply_filters_from_args."""

    filter_skills_alignment: str | None = None
    filter_skills_job: str | None = None
    filter_exp_alignment: str | None = None
    filter_exp_job: str | None = None
    min_priority: float | None = None


class FilterPipeline:
    """Chainable pipeline for applying filters to resume/candidate data.

    Typed at the boundary, dict-domain inside: see the module docstring.
    """

    def __init__(self, resume: Resume) -> None:
        """Initialize pipeline with a typed resume.

        The resume is lowered to a dict here, and the filters work on that dict.
        ``to_dict()`` returns a fresh top-level mapping, so rebinding keys on it
        cannot reach the caller's ``Resume`` -- the same guarantee the previous
        ``dict(data)`` shallow copy gave, and no stronger: values that are plain
        containers (``contact``, unknown ``extra`` keys) are still shared, so
        mutating one in place would be visible on both sides. No filter does.

        Args:
            resume: The candidate/resume document to transform.
        """
        self._data: dict[str, Any] = resume.to_dict()
        self._synonyms: dict[str, list[str]] = {}

    def with_profile_overlays(self, profile: str | None) -> "FilterPipeline":
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
        job_path: str | Path | None,
    ) -> "FilterPipeline":
        """Load synonyms from a job config file to use in subsequent filters.

        Args:
            job_path: Path to job config (YAML/JSON). If None, no-op.

        Returns:
            Self for chaining.
        """
        if job_path:
            try:
                _, syn = build_keyword_spec(load_job_config(str(job_path)))
                if syn:
                    self._synonyms.update(syn)
            except Exception:  # nosec B110 - job config load failure
                pass
        return self

    def with_skill_filter(
        self,
        alignment_path: str | Path | None,
        job_path: str | Path | None = None,
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

        matched = self._extract_matched_keywords(alignment_path)
        if matched:
            self._data = filter_skills_by_keywords(
                self._data,
                matched_keywords=matched,
                synonyms=self._synonyms,
            )

        return self

    def with_experience_filter(
        self,
        alignment_path: str | Path | None,
        job_path: str | Path | None = None,
        filter_cfg: ExperienceFilterConfig | None = None,
    ) -> "FilterPipeline":
        """Filter experience entries to those matching alignment keywords.

        Args:
            alignment_path: Path to alignment JSON with matched_keywords.
            job_path: Optional job config for additional synonyms.
            filter_cfg: Filtering limits (max_roles, max_bullets_per_role, min_score).

        Returns:
            Self for chaining.
        """
        if not alignment_path:
            return self

        # Load job synonyms if provided
        if job_path:
            self.with_synonyms_from_job(job_path)

        matched = self._extract_matched_keywords(alignment_path)
        if matched:
            self._data = filter_experience_by_keywords(
                self._data,
                matched_keywords=matched,
                synonyms=self._synonyms,
                filter_cfg=filter_cfg,
            )

        return self

    def with_priority_filter(
        self,
        min_priority: float | None,
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

    def execute(self) -> Resume:
        """Execute the pipeline and return the transformed resume.

        Re-raises the dict interior into the typed domain. This is lossless with
        respect to what the filters produced -- but note the filters themselves
        may have dropped keys: ``skills_filter`` rebuilds each group as a fresh
        ``{"title": ..., "items": ...}`` literal, so a group-level unknown key
        does not survive that filter. That is pre-existing dict-domain behaviour
        and identical with or without this conversion.

        Returns:
            The filtered/transformed resume.
        """
        return Resume.from_dict(self._data)

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    def _extract_matched_keywords(
        self,
        alignment_path: str | Path,
    ) -> list[str]:
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
    def data(self) -> dict[str, Any]:
        """Access the current data state (read-only snapshot)."""
        return dict(self._data)

    @property
    def synonyms(self) -> dict[str, list[str]]:
        """Access the current synonyms map (read-only snapshot)."""
        return dict(self._synonyms)


# -----------------------------------------------------------------------------
# Convenience factory functions
# -----------------------------------------------------------------------------


def create_pipeline(resume: Resume) -> FilterPipeline:
    """Create a new FilterPipeline instance.

    Args:
        resume: The candidate/resume document.

    Returns:
        A new FilterPipeline instance.
    """
    return FilterPipeline(resume)


def apply_filters_from_args(
    resume: Resume,
    profile: str | None = None,
    config: FilterConfig | None = None,
) -> Resume:
    """Apply all filters using a FilterConfig (convenience function).

    Args:
        resume: The candidate/resume document.
        profile: Profile name for overlays.
        config: Bundled filter configuration; defaults to no-op if None.

    Returns:
        The filtered resume.
    """
    cfg = config or FilterConfig()
    return (
        FilterPipeline(resume)
        .with_profile_overlays(profile)
        .with_skill_filter(cfg.filter_skills_alignment, cfg.filter_skills_job)
        .with_experience_filter(cfg.filter_exp_alignment, cfg.filter_exp_job)
        .with_priority_filter(cfg.min_priority)
        .execute()
    )
