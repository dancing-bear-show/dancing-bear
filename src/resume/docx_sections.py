"""DOCX section renderers for resume content.

Provides section-specific renderers for different resume sections.

This module is a re-export shim. Implementation lives in:
  - docx_sections_list: simple list renderers
  - docx_sections_exp: complex entry renderers (_ExperienceRenderOpts, Experience, Education)
"""
from __future__ import annotations

from .docx_renderers import BulletRenderer, HeaderRenderer, ListSectionRenderer  # noqa: F401
from .docx_sections_list import (  # noqa: F401
    CertificationsSectionRenderer,
    CourseworkSectionRenderer,
    InterestsSectionRenderer,
    LanguagesSectionRenderer,
    PresentationsSectionRenderer,
    SkillsSectionRenderer,
    SummarySectionRenderer,
    TeachingSectionRenderer,
    TechnologiesSectionRenderer,
)
from .docx_sections_exp import (  # noqa: F401
    EducationSectionRenderer,
    ExperienceSectionRenderer,
)

# Re-export base renderers for backward compatibility
__all__ = [
    "BulletRenderer",
    "HeaderRenderer",
    "ListSectionRenderer",
    "InterestsSectionRenderer",
    "TeachingSectionRenderer",
    "LanguagesSectionRenderer",
    "CourseworkSectionRenderer",
    "CertificationsSectionRenderer",
    "PresentationsSectionRenderer",
    "SummarySectionRenderer",
    "SkillsSectionRenderer",
    "TechnologiesSectionRenderer",
    "ExperienceSectionRenderer",
    "EducationSectionRenderer",
]
