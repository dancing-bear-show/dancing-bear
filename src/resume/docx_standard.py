"""Standard single-column DOCX resume writer.

Provides the default single-column resume layout.
"""
from __future__ import annotations

from typing import Any

from .docx_base import ResumeWriterBase
from .schema import Resume
from .docx_links import render_contact_runs
from .docx_styles import (
    _parse_hex_color,
    _tight_paragraph,
    _flush_left,
    _apply_paragraph_shading,
    _format_phone_display,
)
from .docx_sections_simple import (
    InterestsSectionRenderer,
    LanguagesSectionRenderer,
    CourseworkSectionRenderer,
    CertificationsSectionRenderer,
    PresentationsSectionRenderer,
    TeachingSectionRenderer,
)
from .docx_sections_skills import (
    SummarySectionRenderer,
    SkillsSectionRenderer,
    TechnologiesSectionRenderer,
)
from .docx_sections_exp import (
    ExperienceSectionRenderer,
    EducationSectionRenderer,
)


# Section renderer registry
SECTION_RENDERERS = {
    "summary": SummarySectionRenderer,
    "skills": SkillsSectionRenderer,
    "technologies": TechnologiesSectionRenderer,
    "interests": InterestsSectionRenderer,
    "presentations": PresentationsSectionRenderer,
    "languages": LanguagesSectionRenderer,
    "coursework": CourseworkSectionRenderer,
    "certifications": CertificationsSectionRenderer,
    "experience": ExperienceSectionRenderer,
    "education": EducationSectionRenderer,
    "teaching": TeachingSectionRenderer,
}

# Sections that need keywords passed to render()
SECTIONS_WITH_KEYWORDS = {"summary", "experience"}

# Maps each registered section key to the data key(s) it reads.
# A section is considered empty when ALL of its data keys are absent or falsy.
# "summary" reads summary OR headline (SummarySectionRenderer fallback).
# "skills" reads skills_groups OR skills (SkillsSectionRenderer).
# "technologies" reads technologies OR falls back to skills_groups.
_SECTION_DATA_KEYS: dict[str, tuple[str, ...]] = {
    "summary": ("summary", "headline"),
    "skills": ("skills_groups", "skills"),
    "technologies": ("technologies", "skills_groups"),
    "interests": ("interests",),
    "presentations": ("presentations",),
    "languages": ("languages",),
    "coursework": ("coursework",),
    "certifications": ("certifications",),
    "experience": ("experience",),
    "education": ("education",),
    "teaching": ("teaching",),
}


def _section_has_data(key: str, resume: Resume) -> bool:
    """Return True when the section has at least one non-empty data key.

    Sections not in _SECTION_DATA_KEYS are treated as always having data
    (conservative: better to show an empty heading than to suppress real content).

    Every name in _SECTION_DATA_KEYS is a declared ``Resume`` field, so the
    attribute read below cannot silently miss one the way a dict lookup could.
    """
    data_keys = _SECTION_DATA_KEYS.get(key)
    if data_keys is None:
        return True
    return any(bool(getattr(resume, k, None)) for k in data_keys)


def _seed_keywords(seed: dict[str, Any] | None) -> list[str]:
    """Return the seed's keyword list as strings, or [] when absent/malformed."""
    if not seed or not isinstance(seed.get("keywords"), list):
        return []
    return [str(k) for k in seed["keywords"]]


class StandardResumeWriter(ResumeWriterBase):
    """Standard single-column resume writer."""

    def _render_content(self, seed: dict[str, Any] | None = None) -> None:
        """Render standard single-column resume content."""
        self._render_document_header()
        keywords = _seed_keywords(seed)
        for sec in self._resolve_sections():
            self._render_section(sec, keywords)

    def _render_section(self, sec: dict[str, Any], keywords: list[str]) -> None:
        """Render one configured section, skipping unrenderable or empty ones."""
        key = sec.get("key")
        if not key:
            return

        # Skip sections with no registered renderer (e.g. "projects").
        renderer_class = SECTION_RENDERERS.get(key)
        if renderer_class is None:
            return

        # Skip sections whose data is absent or empty.
        if not _section_has_data(key, self.resume):
            return

        title = sec.get("title") or (key.title() if isinstance(key, str) else "")
        self._render_section_heading(title)

        # Section renderers take the typed Resume and read candidate data as
        # attributes; none of them lower it back to a mapping.
        renderer = renderer_class(self.doc, self.page_cfg)
        if key in SECTIONS_WITH_KEYWORDS:
            renderer.render(self.resume, sec, keywords)
        else:
            renderer.render(self.resume, sec)

    def _render_document_header(self) -> None:
        """Render the name, headline, and contact line at the top of the resume."""
        name = self._get_contact_field("name")
        headline = self._get_contact_field("headline")
        email = self._get_contact_field("email")
        phone = self._get_contact_field("phone")
        display_phone = _format_phone_display(phone) if phone else ""
        location = self._get_contact_field("location")

        # Name heading
        if name:
            self.doc.add_heading(name, level=0)
            _tight_paragraph(self.doc.paragraphs[-1], after_pt=2)
            self._center_paragraph(self.doc.paragraphs[-1])

        # Headline
        if headline:
            p_head = self.doc.add_paragraph(str(headline))
            _tight_paragraph(p_head, after_pt=2)
            self._center_paragraph(p_head)

        # Contact line: email (mailto: hyperlink) | phone | location | link extras
        plain_parts = [p for p in [display_phone, location] if p]
        link_items = self._collect_link_extra_items()

        has_content = email or plain_parts or link_items
        if has_content:
            p = self.doc.add_paragraph()
            _tight_paragraph(p, after_pt=6)
            self._center_paragraph(p)
            self._render_contact_runs(p, email, plain_parts, link_items)

    def _render_contact_runs(
        self,
        paragraph,
        email: str,
        plain_parts: list[str],
        link_items: list[tuple[str, str]],
    ) -> None:
        """Build the contact-line paragraph run-by-run with hyperlinks."""
        render_contact_runs(paragraph, email, plain_parts, link_items)

    def _resolve_sections(self) -> list[dict[str, Any]]:
        """Resolve section order and configuration from template."""
        sections = self.template.get("sections") or []
        return sections

    def _render_section_heading(self, title: str) -> None:
        """Render a section heading with optional shading."""
        if not title:
            return
        self.doc.add_heading(str(title), level=1)
        _tight_paragraph(self.doc.paragraphs[-1], before_pt=6, after_pt=2)
        _flush_left(self.doc.paragraphs[-1])
        page_h1_bg = self.page_cfg.get("h1_bg") or self.page_cfg.get("heading_bg")
        bg_rgb = _parse_hex_color(page_h1_bg)
        if bg_rgb:
            _apply_paragraph_shading(self.doc.paragraphs[-1], bg_rgb)
