"""Skills, summary, and technologies section renderers for DOCX resume output.

Provides:
  - SummarySectionRenderer: summary/profile section (string or list)
  - SkillsSectionRenderer: skills with groups or flat list
  - TechnologiesSectionRenderer: technologies (extends SkillsSectionRenderer)
"""
from __future__ import annotations

from typing import Any

from .docx_renderers import HeaderRenderer, ListSectionRenderer

_DEFAULT_BULLET_STYLE = "List Bullet"


class SummarySectionRenderer(ListSectionRenderer):
    """Renders summary/profile section."""

    def render(
        self,
        data: dict,
        sec: dict | None = None,
        keywords: list[str] | None = None,
    ) -> None:
        summary = data.get("summary") or data.get("headline") or ""
        cfg = sec or {}

        if isinstance(summary, list) and summary:
            items = self._normalize_list_items(summary)
            if items:
                norm_items = [self.text.normalize_bullet(it) for it in items]
                plain, glyph = self.bullets.get_bullet_config(sec)
                self.bullets.add_bullets(
                    norm_items, keywords=keywords, plain=plain, glyph=glyph
                )
        elif isinstance(summary, str) and summary.strip():
            self._render_string_summary(summary, cfg, keywords)

    def _normalize_list_items(self, summary: list[Any]) -> list[str]:
        """Extract text items from a list of strings or dicts."""
        items: list[str] = []
        for it in summary:
            if isinstance(it, dict):
                s = str(it.get("text") or it.get("line") or it.get("desc") or "").strip()
            else:
                s = str(it).strip()
            if s:
                items.append(s)
        return items

    def _render_string_summary(
        self,
        text: str,
        cfg: dict,
        keywords: list[str] | None,
    ) -> None:
        """Render a string summary (optionally as bullets)."""
        if cfg.get("bulleted"):
            self._render_bulleted_string(text, cfg, keywords)
        else:
            p = self.doc.add_paragraph()
            self.bullets.styles.tight_paragraph(p, after_pt=2)
            if keywords:
                self.bullets._bold_keywords(p, text, keywords)
            else:
                p.add_run(text)

    def _render_bulleted_string(
        self,
        text: str,
        cfg: dict,
        keywords: list[str] | None,
    ) -> None:
        """Split a string summary into bullet sentences."""
        raw_items = [s.strip() for s in text.replace("\n", " ").split(".")]
        items = [s for s in raw_items if s]
        try:
            max_sent = int(cfg.get("max_sentences", 0) or 0)
        except Exception:  # nosec B110 - invalid config value; fall back to no limit
            max_sent = 0
        if max_sent > 0:
            items = items[:max_sent]
        norm_items = [self.text.normalize_bullet(it) for it in items]
        plain, glyph = self.bullets.get_bullet_config(cfg)
        self.bullets.add_bullets(
            norm_items, keywords=keywords, plain=plain, glyph=glyph
        )


class SkillsSectionRenderer(ListSectionRenderer):
    """Renders skills section with groups or flat list."""

    def __init__(self, doc: Any, page_cfg: dict | None = None) -> None:
        super().__init__(doc, page_cfg)
        self.headers = HeaderRenderer(doc)

    def render(
        self,
        data: dict,
        sec: dict | None = None,
    ) -> None:
        groups = data.get("skills_groups") or []
        skills = [self.text.clean_inline(str(s)) for s in (data.get("skills") or [])]
        cfg = sec or {}

        if groups:
            self._render_groups(groups, cfg)
        elif skills:
            self._render_flat_skills(skills, cfg)

    def _render_groups(self, groups: list[dict], cfg: dict) -> None:
        """Render skills organized by groups."""
        as_bullets = bool(cfg.get("bullets", False))
        sep = cfg.get("separator") or " • "
        max_groups = int(cfg.get("max_groups", 999))
        max_items_per_group = int(cfg.get("max_items_per_group", 999))
        show_desc = bool(cfg.get("show_desc", True))
        desc_sep = str(cfg.get("desc_separator") or " — ")

        for g in groups[:max_groups]:
            title = str(g.get("title") or "").strip()
            raw_items = g.get("items") or []
            items = self._normalize_group_items(raw_items, show_desc, desc_sep)[:max_items_per_group]

            if not items:
                continue

            if as_bullets:
                if title:
                    self.headers.add_group_title(title, cfg)
                self._render_bullet_items(items, cfg)
            else:
                self._render_inline_items(title, items, cfg, sep)

    def _normalize_group_items(
        self, raw_items: list[Any], show_desc: bool, desc_sep: str
    ) -> list[str]:
        """Normalize items from a skills group."""
        result: list[str] = []
        for x in raw_items:
            if isinstance(x, dict):
                name = x.get("name") or x.get("title") or x.get("label") or ""
                desc = x.get("desc") or x.get("description") or ""
                s = name.strip()
                if desc and show_desc:
                    s = f"{s}{desc_sep}{desc.strip()}"
                result.append(self.text.clean_inline(s))
            else:
                result.append(self.text.clean_inline(str(x)))
        return result

    def _render_bullet_items(self, items: list[str], cfg: dict) -> None:
        """Render items as bullets."""
        plain, glyph = self.bullets.get_bullet_config(cfg)
        desc_sep = str(cfg.get("desc_separator") or ": ")

        for it in items:
            if plain and cfg.get("show_desc") and desc_sep in it:
                left, right = it.split(desc_sep, 1)
                self.bullets.add_named_bullet(left, right, sec=cfg, glyph=glyph, sep=desc_sep)
            elif plain:
                self.bullets.add_bullet_line(it, glyph=glyph)
            else:
                p = self.doc.add_paragraph(style=_DEFAULT_BULLET_STYLE)
                self.bullets.styles.tight_paragraph(p, after_pt=0)
                self.bullets.styles.compact_bullet(p)
                p.add_run(it)

    def _render_inline_items(
        self, title: str, items: list[str], cfg: dict, sep: str
    ) -> None:
        """Render items inline with optional title."""
        compact = bool(cfg.get("compact", True))
        if title:
            text = f"{title}: {sep.join(items)}" if compact else (title + ":\n" + "\n".join(items))
        else:
            text = sep.join(items) if compact else "\n".join(items)
        p = self.doc.add_paragraph(text)
        self.bullets.styles.tight_paragraph(p, after_pt=0)

    def _render_flat_skills(self, skills: list[str], cfg: dict) -> None:
        """Render a flat list of skills."""
        as_bullets = bool(cfg.get("bullets", False))
        sep = cfg.get("separator") or " • "
        max_items = int(cfg.get("max_items", 999))
        skills = skills[:max_items]

        if as_bullets:
            self._render_bullet_items(skills, cfg)
        else:
            p = self.doc.add_paragraph(sep.join(skills))
            self.bullets.styles.tight_paragraph(p, after_pt=2)


class TechnologiesSectionRenderer(SkillsSectionRenderer):
    """Renders technologies section (similar to skills)."""

    def render(self, data: dict, sec: dict | None = None) -> None:
        tech_items = self._collect_tech_items(data, sec)
        if not tech_items:
            return

        cfg = sec or {}
        try:
            max_items = int(cfg.get("max_items", 0) or 0)
        except Exception:  # nosec B110 - invalid config value; fall back to no limit
            max_items = 0
        if max_items > 0:
            tech_items = tech_items[:max_items]

        as_bullets = bool(cfg.get("bullets", True))
        sep = cfg.get("separator") or " • "

        if as_bullets:
            self._render_bullet_items(tech_items, cfg)
        else:
            p = self.doc.add_paragraph(sep.join(tech_items))
            self.bullets.styles.tight_paragraph(p, after_pt=2)

    def _collect_tech_items(
        self, data: dict, sec: dict | None
    ) -> list[str]:
        """Collect technology items from data sources."""
        cfg = sec or {}
        desc_sep = str(cfg.get("desc_separator") or ": ")
        show_desc = bool(cfg.get("show_desc", False))
        tech_items: list[str] = []

        for t in data.get("technologies") or []:
            item = self._normalize_tech_item(t, show_desc, desc_sep)
            if item:
                tech_items.append(item)

        if not tech_items:
            tech_items = self._extract_from_skills_groups(data, show_desc, desc_sep)

        return tech_items

    def _normalize_tech_item(
        self, t: Any, show_desc: bool, desc_sep: str
    ) -> str | None:
        """Normalize a single technology item."""
        if isinstance(t, dict):
            nm = t.get("name") or t.get("title") or t.get("label") or ""
            ds = t.get("desc") or t.get("description") or ""
            s = nm.strip()
            if show_desc and ds:
                s = f"{s}{desc_sep}{ds.strip()}"
            return self.text.clean_inline(s) if s else None
        return self.text.clean_inline(str(t))

    def _extract_from_skills_groups(
        self, data: dict, show_desc: bool, desc_sep: str
    ) -> list[str]:
        """Extract tech items from skills_groups with technology titles."""
        tech_titles = {"technology", "technologies", "tooling", "tools"}
        items: list[str] = []

        for g in data.get("skills_groups") or []:
            title = str(g.get("title") or "").strip().lower()
            if title in tech_titles:
                for x in g.get("items") or []:
                    item = self._normalize_tech_item(x, show_desc, desc_sep)
                    if item:
                        items.append(item)
                break

        return items
