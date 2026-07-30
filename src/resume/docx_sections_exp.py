"""Complex entry section renderers for DOCX resume output.

Extracted from docx_sections. Provides:
  - _ExperienceRenderOpts: bundled rendering options dataclass
  - ExperienceSectionRenderer: experience/work history renderer
  - EducationSectionRenderer: education section renderer
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .docx_renderers import HeaderRenderer, ListSectionRenderer

_DEFAULT_BULLET_STYLE = "List Bullet"


@dataclass
class _ExperienceRenderOpts:
    """Bundled rendering options for experience entries."""

    role_style: str = "Normal"
    bullet_style: str = _DEFAULT_BULLET_STYLE
    max_bullets: int = 999
    recent_roles_count: int = 0
    recent_max_bullets: int = 999
    prior_max_bullets: int = 999

    @classmethod
    def from_cfg(cls, cfg: Dict[str, Any]) -> "_ExperienceRenderOpts":
        """Build from a section config dict."""
        max_bullets = int(cfg.get("max_bullets", 999))
        return cls(
            role_style=str(cfg.get("role_style", "Normal")),
            bullet_style=str(cfg.get("bullet_style", _DEFAULT_BULLET_STYLE)),
            max_bullets=max_bullets,
            recent_roles_count=int(cfg.get("recent_roles_count", 0) or 0),
            recent_max_bullets=int(cfg.get("recent_max_bullets", max_bullets)),
            prior_max_bullets=int(cfg.get("prior_max_bullets", max_bullets)),
        )


class ExperienceSectionRenderer(ListSectionRenderer):
    """Renders experience/work history section."""

    def __init__(self, doc, page_cfg: Optional[Dict[str, Any]] = None):
        super().__init__(doc, page_cfg)
        self.headers = HeaderRenderer(doc)

    def render(
        self,
        data: Dict[str, Any],
        sec: Optional[Dict[str, Any]] = None,
        keywords: Optional[List[str]] = None,
    ):
        items = data.get("experience") or []
        cfg = sec or {}
        max_items = int(cfg.get("max_items", 999))
        opts = _ExperienceRenderOpts.from_cfg(cfg)

        for idx, e in enumerate(items[:max_items]):
            self._render_experience_entry(e, idx, cfg, keywords, opts)

    def _render_experience_entry(
        self,
        e: Dict[str, Any],
        idx: int,
        cfg: Dict[str, Any],
        keywords: Optional[List[str]],
        opts: _ExperienceRenderOpts,
    ):
        """Render a single experience entry."""
        title = str(e.get("title") or "").strip()
        company = str(e.get("company") or "").strip()
        loc_txt = str(e.get("location") or "").strip()
        span = self._format_date_span(e)

        if title or company:
            self.headers.add_header_line(
                title_text=title,
                company_text=company,
                loc_text=loc_txt,
                span_text=span,
                sec=cfg,
                style=opts.role_style,
            )

        # Determine per-role bullet limit
        per_role_limit = self._calculate_bullet_limit(
            idx, opts.max_bullets, opts.recent_roles_count,
            opts.recent_max_bullets, opts.prior_max_bullets,
        )

        # Render bullets
        bullets = self._normalize_bullets(e.get("bullets") or [], per_role_limit)
        if bullets:
            plain, glyph = self.bullets.get_bullet_config(cfg)
            self.bullets.add_bullets(
                bullets, keywords=keywords, plain=plain, glyph=glyph,
                list_style=opts.bullet_style,
            )

    def _format_date_span(self, e: Dict[str, Any]) -> str:
        """Format the date span for an experience entry."""
        start_txt = str(e.get("start", "") or "")
        end_txt = str(e.get("end", "") or "")

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

    def _normalize_bullets(self, bullets: List[Any], limit: int) -> List[str]:
        """Normalize bullet items to strings."""
        result: List[str] = []
        for b in bullets[:limit]:
            if isinstance(b, dict):
                bt = str(b.get("text") or b.get("line") or b.get("name") or "").strip()
            else:
                bt = str(b).strip()
            if bt:
                result.append(self.text.normalize_bullet(bt))
        return result


class EducationSectionRenderer(ListSectionRenderer):
    """Renders education section."""

    def __init__(self, doc, page_cfg: Optional[Dict[str, Any]] = None):
        super().__init__(doc, page_cfg)
        self.headers = HeaderRenderer(doc)

    def render(self, data: Dict[str, Any], sec: Optional[Dict[str, Any]] = None):
        for ed in data.get("education") or []:
            degree = str(ed.get("degree") or "").strip()
            institution = str(ed.get("institution") or "").strip()
            year = str(ed.get("year") or "").strip()

            if degree or institution or year:
                self.headers.add_header_line(
                    title_text=degree,
                    company_text=institution,
                    loc_text="",
                    span_text=year,
                    sec=sec,
                    style="Normal",
                )
