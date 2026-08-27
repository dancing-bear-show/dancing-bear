"""Complex entry section renderers for DOCX resume output.

Extracted from docx_sections. Provides:
  - _ExperienceRenderOpts: bundled rendering options dataclass
  - ExperienceSectionRenderer: experience/work history renderer
  - EducationSectionRenderer: education section renderer
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from .docx_renderers import HeaderRenderer, ListSectionRenderer
from .render_config import DEFAULT_BULLET_STYLE, HeaderLineConfig
from .schema import ExperienceEntry, PriorityItem, Resume


def _warn(msg: str) -> None:
    """Emit a renderer warning to stderr."""
    print(f"resume: {msg}", file=sys.stderr)


@dataclass
class _ExperienceRenderOpts:
    """Bundled rendering options for experience entries."""

    role_style: str = "Normal"
    bullet_style: str = DEFAULT_BULLET_STYLE
    max_bullets: int = 999
    recent_roles_count: int = 0
    recent_max_bullets: int = 999
    prior_max_bullets: int = 999

    @classmethod
    def from_cfg(cls, cfg: dict[str, Any]) -> "_ExperienceRenderOpts":
        """Build from a section config dict."""
        max_bullets = int(cfg.get("max_bullets", 999))
        return cls(
            role_style=str(cfg.get("role_style", "Normal")),
            bullet_style=str(cfg.get("bullet_style", DEFAULT_BULLET_STYLE)),
            max_bullets=max_bullets,
            recent_roles_count=int(cfg.get("recent_roles_count", 0) or 0),
            recent_max_bullets=int(cfg.get("recent_max_bullets", max_bullets)),
            prior_max_bullets=int(cfg.get("prior_max_bullets", max_bullets)),
        )


class ExperienceSectionRenderer(ListSectionRenderer):
    """Renders experience/work history section."""

    def __init__(self, doc, page_cfg: dict[str, Any] | None = None):
        super().__init__(doc, page_cfg)
        self.headers = HeaderRenderer(doc)

    def render(
        self,
        resume: Resume,
        sec: dict[str, Any] | None = None,
        keywords: list[str] | None = None,
    ) -> None:
        items = resume.experience
        cfg = sec or {}
        max_items = int(cfg.get("max_items", 999))
        opts = _ExperienceRenderOpts.from_cfg(cfg)

        if len(items) > max_items:
            dropped = items[max_items:]
            names = ", ".join(
                str(e.company or e.title or f"entry {max_items + i + 1}")
                for i, e in enumerate(dropped)
            )
            _warn(
                f"template max_items={max_items} dropped {len(dropped)} of"
                f" {len(items)} experience entries: {names}"
            )

        for idx, e in enumerate(items[:max_items]):
            self._render_experience_entry(e, idx, cfg, keywords, opts)

    def _render_experience_entry(
        self,
        e: ExperienceEntry,
        idx: int,
        cfg: dict[str, Any],
        keywords: list[str] | None,
        opts: _ExperienceRenderOpts,
    ):
        """Render a single experience entry."""
        title = str(e.title or "").strip()
        company = str(e.company or "").strip()
        loc_txt = str(e.location or "").strip()
        span = self._format_date_span(e)

        if title or company:
            self.headers.add_header_line(
                HeaderLineConfig(
                    title_text=title,
                    company_text=company,
                    loc_text=loc_txt,
                    span_text=span,
                    style=opts.role_style,
                ),
                sec=cfg,
            )

        # Determine per-role bullet limit
        per_role_limit = self._calculate_bullet_limit(
            idx, opts.max_bullets, opts.recent_roles_count,
            opts.recent_max_bullets, opts.prior_max_bullets,
        )

        # Warn when bullets will be truncated. Name the setting that actually
        # applied to THIS role — recent roles are capped by recent_max_bullets
        # and older ones by prior_max_bullets, so reporting a fixed name would
        # send someone editing the wrong knob.
        raw_bullets = e.bullets
        if len(raw_bullets) > per_role_limit:
            role_name = company or title or f"role at index {idx}"
            limit_name = (
                "recent_max_bullets"
                if idx < opts.recent_roles_count
                else "prior_max_bullets"
            )
            _warn(
                f"template {limit_name}={per_role_limit} truncated"
                f" {role_name} from {len(raw_bullets)} to {per_role_limit} bullets"
            )

        # Render bullets
        bullets = self._normalize_bullets(raw_bullets, per_role_limit)
        if bullets:
            plain, glyph = self.bullets.get_bullet_config(cfg)
            self.bullets.add_bullets(
                bullets, keywords=keywords, plain=plain, glyph=glyph,
                list_style=opts.bullet_style,
            )

    def _format_date_span(self, e: ExperienceEntry) -> str:
        """Format the date span for an experience entry."""
        start_txt = str(e.start or "")
        end_txt = str(e.end or "")

        if start_txt and end_txt:
            return f"{self._normalize_present(start_txt)} – {self._normalize_present(end_txt)}"
        elif start_txt:
            return f"{self._normalize_present(start_txt)} – Present"
        elif end_txt:
            return self._normalize_present(end_txt)
        return ""

    def _normalize_present(self, text: str) -> str:
        """Normalize 'present' variants to consistent format."""
        if text.lower() in ("present", "current", "now"):
            return "Present"
        return text

    def _calculate_bullet_limit(
        self,
        idx: int,
        max_bullets: int,
        recent_roles_count: int,
        recent_max_bullets: int,
        prior_max_bullets: int,
    ) -> int:
        """Calculate the bullet limit for this role based on recency."""
        if not recent_roles_count:
            return max_bullets
        if idx < recent_roles_count:
            return min(max_bullets, recent_max_bullets)
        return min(max_bullets, prior_max_bullets)

    def _normalize_bullets(self, bullets: list[PriorityItem], limit: int) -> list[str]:
        """Normalize bullet items to strings, dropping blanks.

        All three spellings the dict path searched -- ``text``, ``line`` and
        ``name`` -- are ``PriorityItem``'s aliases for ``text``, so the schema
        resolves them at from_dict time and only the canonical field is read.
        """
        result: list[str] = []
        for b in bullets[:limit]:
            bt = str(b.text or "").strip()
            if bt:
                result.append(self.text.normalize_bullet(bt))
        return result


class EducationSectionRenderer(ListSectionRenderer):
    """Renders education section."""

    def __init__(self, doc, page_cfg: dict[str, Any] | None = None):
        super().__init__(doc, page_cfg)
        self.headers = HeaderRenderer(doc)

    def render(self, resume: Resume, sec: dict[str, Any] | None = None):
        for ed in resume.education:
            degree = str(ed.degree or "").strip()
            institution = str(ed.institution or "").strip()
            # `year` is an int in real data; str() here matches the dict path,
            # and the schema stores it uncoerced so the value is unchanged.
            year = str(ed.year or "").strip()

            if degree or institution or year:
                self.headers.add_header_line(
                    HeaderLineConfig(
                        title_text=degree,
                        company_text=institution,
                        span_text=year,
                    ),
                    sec=sec,
                )
