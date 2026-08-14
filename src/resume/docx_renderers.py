"""Base DOCX renderers for resume content.

Provides BulletRenderer, HeaderRenderer, and ListSectionRenderer base classes.
"""
from __future__ import annotations

from typing import Any

from .docx_styles import StyleManager, TextFormatter
from .render_config import HeaderLineConfig, MetaRunConfig


class BulletRenderer:
    """Renders bullet lists with various styles."""

    def __init__(self, doc, page_cfg: dict[str, Any] | None = None):
        self.doc = doc
        self.page_cfg = page_cfg or {}
        self.styles = StyleManager()
        self.text = TextFormatter()

    def _apply_page_bullet_config(self, style, glyph):
        """Apply page-level bullet config if style not already set."""
        if not style and isinstance(self.page_cfg.get("bullets"), dict):
            bulp = self.page_cfg.get("bullets") or {}
            style = bulp.get("style") or style
            glyph = bulp.get("glyph") or glyph
        return style, glyph

    def get_bullet_config(self, sec: dict[str, Any] | None) -> tuple:
        """Determine bullet style and glyph from config.

        Returns:
            Tuple of (use_plain: bool, glyph: str)
        """
        glyph = "•"
        style = None
        if sec:
            bul = sec.get("bullets") if isinstance(sec.get("bullets"), dict) else {}
            if bul:
                style = bul.get("style") or style
                glyph = bul.get("glyph") or glyph
            if sec.get("plain_bullets") is True:
                style = "plain"
        style, glyph = self._apply_page_bullet_config(style, glyph)
        return (style == "plain" or (sec and sec.get("plain_bullets") is True), glyph)

    def _new_glyph_paragraph(self, glyph: str):
        """Start a new tight, flush-left paragraph with a leading glyph run."""
        p = self.doc.add_paragraph()
        self.styles.tight_paragraph(p, after_pt=0)
        self.styles.flush_left(p)
        p.add_run(f"{glyph} ")
        return p

    def _add_text_with_optional_keywords(self, p, text: str, keywords: list[str] | None) -> None:
        """Add text to a paragraph, bolding keyword matches if any are given."""
        if keywords:
            self._bold_keywords(p, text, keywords)
        else:
            p.add_run(text)

    def add_bullet_line(
        self,
        text: str,
        *,
        keywords: list[str] | None = None,
        glyph: str = "•",
    ):
        """Add a plain bullet line (glyph + text)."""
        p = self._new_glyph_paragraph(glyph)
        self._add_text_with_optional_keywords(p, text, keywords)
        return p

    def add_named_bullet(
        self,
        name: str,
        desc: str,
        *,
        sec: dict[str, Any] | None = None,
        glyph: str = "•",
        sep: str = ": ",
    ):
        """Add a bullet with bold name and description."""
        p = self._new_glyph_paragraph(glyph)

        cfg = sec or {}
        name_color = cfg.get("name_color") or cfg.get("item_color") or cfg.get("title_color")

        r_name = p.add_run(name)
        r_name.bold = True
        self.styles.apply_run_color(r_name, name_color)

        p.add_run(sep)
        p.add_run(desc)
        return p

    def add_bullets(
        self,
        items: list[str],
        *,
        keywords: list[str] | None = None,
        plain: bool = True,
        glyph: str = "•",
        list_style: str = "List Bullet",
    ):
        """Render a list of bullet items."""
        if plain:
            for it in items:
                self.add_bullet_line(it, keywords=keywords, glyph=glyph)
            return

        for it in items:
            p = self.doc.add_paragraph(style=list_style)
            self.styles.tight_paragraph(p, after_pt=0)
            self.styles.compact_bullet(p)
            self._add_text_with_optional_keywords(p, it, keywords)

    @staticmethod
    def _find_earliest_keyword(lowered: str, text: str, keywords: list[str], from_idx: int):
        """Find the earliest occurring keyword in text from from_idx. Returns (pos, matched_text) or (None, None)."""
        match_pos = None
        match_kw = None
        for kw in keywords:
            if not kw:
                continue
            pos = lowered.find(kw.lower(), from_idx)
            if pos != -1 and (match_pos is None or pos < match_pos):
                match_pos = pos
                match_kw = text[pos:pos + len(kw)]
        return match_pos, match_kw

    def _bold_keywords(self, paragraph, text: str, keywords: list[str]):
        """Add text with keywords bolded."""
        lowered = text.lower()
        idx = 0
        found_any = False

        while idx < len(text):
            match_pos, match_kw = self._find_earliest_keyword(lowered, text, keywords, idx)

            if match_pos is None:
                paragraph.add_run(text[idx:])
                break

            if match_pos > idx:
                paragraph.add_run(text[idx:match_pos])

            br = paragraph.add_run(match_kw or "")
            br.bold = True
            found_any = True
            idx = match_pos + len(match_kw or "")

        if not found_any and idx == 0:
            paragraph.add_run(text)


class HeaderRenderer:
    """Renders header lines for experience and education entries."""

    def __init__(self, doc):
        self.doc = doc
        self.styles = StyleManager()

    def _parse_meta_pt(self, cfg: dict[str, Any]) -> float | None:
        """Parse meta_pt from config, returning None if invalid."""
        val = cfg.get("meta_pt")
        if not val:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _add_bold_colored_run(self, p, text: str, color: str | None):
        """Add a bold run with an optional color applied."""
        r = p.add_run(text)
        r.bold = True
        self.styles.apply_run_color(r, color)
        return r

    def _add_meta_run(self, p, text: str, cfg: MetaRunConfig):
        """Add a metadata run (location or duration) with optional brackets."""
        p.add_run(" — ")
        if cfg.brackets:
            p.add_run(cfg.open_br)
        r = p.add_run(text)
        if cfg.italic:
            r.italic = True
        self.styles.apply_run_size(r, cfg.meta_pt)
        self.styles.apply_run_color(r, cfg.color)
        if cfg.brackets:
            p.add_run(cfg.close_br)

    def add_header_line(
        self,
        content: HeaderLineConfig | None = None,
        *,
        sec: dict[str, Any] | None = None,
    ):
        """Add a formatted header line.

        Format: Title at Company — [Location] — (Duration)

        Args:
            content: Text and style fields for the header. Defaults to HeaderLineConfig().
            sec: Section config dict (colors, bracket flags, etc.).
        """
        c = content or HeaderLineConfig()
        cfg = sec or {}
        p = self.doc.add_paragraph(style=c.style)
        self.styles.tight_paragraph(p, after_pt=0)
        self.styles.flush_left(p)

        item_color = cfg.get("item_color") or cfg.get("header_color")
        loc_color = cfg.get("location_color") or item_color
        dur_color = cfg.get("duration_color") or cfg.get("location_color") or item_color
        meta_pt = self._parse_meta_pt(cfg)

        # Title
        if c.title_text:
            self._add_bold_colored_run(p, c.title_text, item_color)

        # Company
        if c.title_text and c.company_text:
            p.add_run(" at ")
        if c.company_text:
            self._add_bold_colored_run(p, c.company_text, item_color)

        # Location
        if c.loc_text:
            self._add_meta_run(p, c.loc_text, MetaRunConfig(
                brackets=cfg.get("location_brackets", True),
                open_br="[", close_br="]",
                meta_pt=meta_pt, color=loc_color, italic=True,
            ))

        # Duration
        if c.span_text:
            self._add_meta_run(p, c.span_text, MetaRunConfig(
                brackets=cfg.get("duration_brackets", True),
                open_br="(", close_br=")",
                meta_pt=meta_pt, color=dur_color,
            ))

        return p

    def add_group_title(
        self,
        title: str,
        sec: dict[str, Any] | None = None,
    ):
        """Add a group/category title with optional background."""
        title = (title or "").strip()
        if not title:
            return None

        cfg = sec or {}
        p = self.doc.add_paragraph()
        self.styles.tight_paragraph(p, after_pt=0)
        self.styles.flush_left(p)

        gt_color = cfg.get("group_title_color")
        gt_bg = cfg.get("group_title_bg") or cfg.get("title_bg")

        r = p.add_run(title)
        r.bold = True

        # Apply background shading
        bg_rgb = self.styles.parse_hex_color(gt_bg)
        if bg_rgb:
            self.styles.apply_shading(p, bg_rgb)
            if not gt_color:
                gt_color = self.styles.auto_contrast_color(bg_rgb)

        # Apply text color
        txt_color = gt_color or cfg.get("item_color") or cfg.get("title_color")
        self.styles.apply_run_color(r, txt_color)

        return p


class ListSectionRenderer:
    """Renders simple list sections (interests, languages, etc.)."""

    def __init__(self, doc, page_cfg: dict[str, Any] | None = None):
        self.doc = doc
        self.bullets = BulletRenderer(doc, page_cfg)
        self.text = TextFormatter()

    def _extract_item_text(
        self, it: Any, name_keys: tuple, desc_key: str | None, desc_sep: str
    ) -> str | None:
        """Extract and format text from a single item."""
        if isinstance(it, dict):
            name = next((str(it.get(k) or "").strip() for k in name_keys if it.get(k)), "")
            if desc_key and name:
                desc = str(it.get(desc_key) or "").strip()
                if desc:
                    name = f"{name}{desc_sep}{desc}"
            return self.text.clean_inline(name) if name else None
        s = str(it).strip()
        return self.text.clean_inline(s) if s else None

    def render_simple_list(
        self,
        items: list[Any],
        sec: dict[str, Any] | None = None,
        *,
        name_keys: tuple = ("name", "title", "label", "text"),
        desc_key: str | None = None,
        desc_sep: str = " — ",
    ) -> list[str]:
        """Normalize and render a simple list section."""
        cfg = sec or {}
        lines = [
            txt for it in items
            if (txt := self._extract_item_text(it, name_keys, desc_key, desc_sep))
        ]

        if lines:
            if cfg.get("bullets", True):
                plain, glyph = self.bullets.get_bullet_config(sec)
                self.bullets.add_bullets(lines, plain=plain, glyph=glyph)
            else:
                from .docx_styles import StyleManager
                sep = cfg.get("separator") or " • "
                p = self.doc.add_paragraph(sep.join(lines))
                StyleManager.tight_paragraph(p, after_pt=2)

        return lines
