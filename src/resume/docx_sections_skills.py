"""Skills, summary, and technologies section renderers for DOCX resume output.

Provides:
  - SummarySectionRenderer: summary/profile section (string or list)
  - SkillsSectionRenderer: skills with groups or flat list
  - TechnologiesSectionRenderer: technologies (extends SkillsSectionRenderer)
"""
from __future__ import annotations

from typing import Any

from .docx_renderers import HeaderRenderer, ListSectionRenderer
from .render_config import DEFAULT_BULLET_STYLE
from .schema import Resume


def _safe_int_limit(cfg: dict, key: str) -> int:
    """Read an int limit from config, falling back to 0 (no limit) on bad values."""
    try:
        return int(cfg.get(key, 0) or 0)
    except Exception:  # nosec B110 - invalid config value; fall back to no limit
        return 0


def _labeled_item_text(item: Any, show_desc: bool, desc_sep: str) -> str:
    """Extract 'name[desc_sep]desc' text from a dict item, or str() a scalar item."""
    if not isinstance(item, dict):
        return str(item)
    name = item.get("name") or item.get("title") or item.get("label") or ""
    desc = item.get("desc") or item.get("description") or ""
    text = name.strip()
    if desc and show_desc:
        text = f"{text}{desc_sep}{desc.strip()}"
    return text


class SummarySectionRenderer(ListSectionRenderer):
    """Renders summary/profile section."""

    def render(
        self,
        resume: Resume,
        sec: dict | None = None,
        keywords: list[str] | None = None,
    ) -> None:
        # Not yet migrated: this renderer still reads candidate data as a
        # mapping. The dispatcher hands over the typed Resume, so lower it here
        # until this module's own migration step lands.
        data = resume.to_dict()
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
        """Split a string summary into bullets.

        Newlines win when present: the docx parser joins each source profile
        bullet with "\\n", so those are the real item boundaries. Splitting such
        a summary on "." instead would break every bullet containing an
        abbreviation, a version number, or a trailing period. Sentence
        splitting remains the fallback for single-line summaries.
        """
        if "\n" in text:
            items = [s.strip() for s in text.split("\n") if s.strip()]
        else:
            items = [s.strip() for s in text.split(".") if s.strip()]
        max_sent = _safe_int_limit(cfg, "max_sentences")
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
        resume: Resume,
        sec: dict | None = None,
    ) -> None:
        # Not yet migrated: this renderer still reads candidate data as a
        # mapping. The dispatcher hands over the typed Resume, so lower it here
        # until this module's own migration step lands.
        data = resume.to_dict()
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
        return [
            self.text.clean_inline(_labeled_item_text(x, show_desc, desc_sep))
            for x in raw_items
        ]

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
                p = self.doc.add_paragraph(style=DEFAULT_BULLET_STYLE)
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

    def _render_bullets_or_joined(self, items: list[str], cfg: dict, sep: str) -> None:
        """Render items as bullets, or as a single sep-joined inline paragraph."""
        if bool(cfg.get("bullets", False)):
            self._render_bullet_items(items, cfg)
        else:
            p = self.doc.add_paragraph(sep.join(items))
            self.bullets.styles.tight_paragraph(p, after_pt=2)

    def _render_flat_skills(self, skills: list[str], cfg: dict) -> None:
        """Render a flat list of skills."""
        sep = cfg.get("separator") or " • "
        max_items = int(cfg.get("max_items", 999))
        self._render_bullets_or_joined(skills[:max_items], cfg, sep)


class TechnologiesSectionRenderer(SkillsSectionRenderer):
    """Renders technologies section (similar to skills)."""

    def render(self, resume: Resume, sec: dict | None = None) -> None:
        # Not yet migrated: this renderer still reads candidate data as a
        # mapping. The dispatcher hands over the typed Resume, so lower it here
        # until this module's own migration step lands.
        data = resume.to_dict()
        tech_items = self._collect_tech_items(data, sec)
        if not tech_items:
            return

        cfg = sec or {}
        max_items = _safe_int_limit(cfg, "max_items")
        if max_items > 0:
            tech_items = tech_items[:max_items]

        sep = cfg.get("separator") or " • "
        if bool(cfg.get("bullets", True)):
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
        text = _labeled_item_text(t, show_desc, desc_sep)
        if isinstance(t, dict) and not text:
            return None
        return self.text.clean_inline(text)

    def _normalize_group_tech_items(
        self, raw_items: list, show_desc: bool, desc_sep: str
    ) -> list[str]:
        """Normalize every item in a single skills group, dropping empties."""
        items: list[str] = []
        for x in raw_items:
            item = self._normalize_tech_item(x, show_desc, desc_sep)
            if item:
                items.append(item)
        return items

    def _extract_from_skills_groups(
        self, data: dict, show_desc: bool, desc_sep: str
    ) -> list[str]:
        """Extract tech items from skills_groups with technology titles."""
        tech_titles = {"technology", "technologies", "tooling", "tools"}

        for g in data.get("skills_groups") or []:
            title = str(g.get("title") or "").strip().lower()
            if title in tech_titles:
                return self._normalize_group_tech_items(g.get("items") or [], show_desc, desc_sep)

        return []
