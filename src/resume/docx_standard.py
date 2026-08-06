"""Standard single-column DOCX resume writer.

Provides the default single-column resume layout.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .docx_base import ResumeWriterBase
from .docx_links import add_hyperlink, normalize_link_url
from .docx_styles import (
    _parse_hex_color,
    _tight_paragraph,
    _flush_left,
    _apply_paragraph_shading,
    _format_phone_display,
)
from .docx_sections import (
    InterestsSectionRenderer,
    LanguagesSectionRenderer,
    CourseworkSectionRenderer,
    CertificationsSectionRenderer,
    PresentationsSectionRenderer,
    SummarySectionRenderer,
    SkillsSectionRenderer,
    TechnologiesSectionRenderer,
    ExperienceSectionRenderer,
    EducationSectionRenderer,
    TeachingSectionRenderer,
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


class StandardResumeWriter(ResumeWriterBase):
    """Standard single-column resume writer."""

    def _render_content(self, seed: Optional[Dict[str, Any]] = None) -> None:
        """Render standard single-column resume content."""
        self._render_document_header()

        # Extract keywords from seed
        keywords = []
        if seed and isinstance(seed.get("keywords"), list):
            keywords = [str(k) for k in seed.get("keywords", [])]

        # Resolve and render sections
        sections = self._resolve_sections()

        for sec in sections:
            key = sec.get("key")
            if not key:
                continue
            title = sec.get("title") or (key.title() if isinstance(key, str) else "")
            self._render_section_heading(title)

            renderer_class = SECTION_RENDERERS.get(key)
            if renderer_class:
                renderer = renderer_class(self.doc, self.page_cfg)
                if key in SECTIONS_WITH_KEYWORDS:
                    renderer.render(self.data, sec, keywords)
                else:
                    renderer.render(self.data, sec)

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
        plain_parts: List[str],
        link_items: List[tuple[str, str]],
    ) -> None:
        """Build the contact-line paragraph run-by-run with hyperlinks.

        Email renders as a mailto: hyperlink. URL link extras render as external
        hyperlinks. Phone and location remain plain text. Falls back to plain text
        for any part that fails.
        """
        first = True

        def _sep() -> None:
            nonlocal first
            if not first:
                paragraph.add_run(" | ")
            first = False

        if email:
            _sep()
            add_hyperlink(paragraph, normalize_link_url(email), email)

        for part in plain_parts:
            _sep()
            paragraph.add_run(part)

        for display, url in link_items:
            _sep()
            add_hyperlink(paragraph, url, display)

    def _resolve_sections(self) -> List[Dict[str, Any]]:
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
