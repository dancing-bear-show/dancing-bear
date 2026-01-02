"""Base DOCX renderers for resume content.

Provides BulletRenderer, HeaderRenderer, and ListSectionRenderer base classes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .docx_styles import StyleManager, TextFormatter


class BulletRenderer:
    """Renders bullet lists with various styles."""

    def __init__(self, doc, page_cfg: Optional[Dict[str, Any]] = None):
        self.doc = doc
        self.page_cfg = page_cfg or {}
        self.styles = StyleManager()
        self.text = TextFormatter()

    def get_bullet_config(self, sec: Optional[Dict[str, Any]]) -> tuple:
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
        if not style and isinstance(self.page_cfg.get("bullets"), dict):
            bulp = self.page_cfg.get("bullets") or {}
            style = bulp.get("style") or style
            glyph = bulp.get("glyph") or glyph
        return (style == "plain" or (sec and sec.get("plain_bullets") is True), glyph)

    def add_bullet_line(
        self,
        text: str,
        *,
        keywords: Optional[List[str]] = None,
        glyph: str = "•",
    ):
        """Add a plain bullet line (glyph + text)."""
        p = self.doc.add_paragraph()
        self.styles.tight_paragraph(p, after_pt=0)
        self.styles.flush_left(p)
        p.add_run(f"{glyph} ")
        if keywords:
            self._bold_keywords(p, text, keywords)
        else:
            p.add_run(text)
        return p

    def add_named_bullet(
        self,
        name: str,
        desc: str,
        *,
        sec: Optional[Dict[str, Any]] = None,
        glyph: str = "•",
        sep: str = ": ",
    ):
        """Add a bullet with bold name and description."""
        p = self.doc.add_paragraph()
        self.styles.tight_paragraph(p, after_pt=0)
        self.styles.flush_left(p)
        p.add_run(f"{glyph} ")

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
        items: List[str],
        *,
        sec: Optional[Dict[str, Any]] = None,
        keywords: Optional[List[str]] = None,
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
            if keywords:
                self._bold_keywords(p, it, keywords)
            else:
                p.add_run(it)

    def _bold_keywords(self, paragraph, text: str, keywords: List[str]):
        """Add text with keywords bolded."""
        lowered = text.lower()
        idx = 0
        found_any = False

        while idx < len(text):
            match_pos = None
            match_kw = None
            for kw in keywords:
                if not kw:
                    continue
                pos = lowered.find(kw.lower(), idx)
                if pos != -1 and (match_pos is None or pos < match_pos):
                    match_pos = pos
                    match_kw = text[pos:pos + len(kw)]

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

    def _parse_meta_pt(self, cfg: Dict[str, Any]) -> Optional[float]:
        """Parse meta_pt from config, returning None if invalid."""
        val = cfg.get("meta_pt")
        if not val:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _add_meta_run(self, p, text: str, brackets: bool, open_br: str, close_br: str,
                      meta_pt: Optional[float], color: Optional[str], italic: bool = False):
        """Add a metadata run (location or duration) with optional brackets."""
        p.add_run(" — ")
        if brackets:
            p.add_run(open_br)
        r = p.add_run(text)
        if italic:
            r.italic = True
        self.styles.apply_run_size(r, meta_pt)
        self.styles.apply_run_color(r, color)
        if brackets:
            p.add_run(close_br)

    def add_header_line(
        self,
        *,
        title_text: str = "",
        company_text: str = "",
        loc_text: str = "",
        span_text: str = "",
        sec: Optional[Dict[str, Any]] = None,
        style: str = "Normal",
    ):
        """Add a formatted header line.

        Format: Title at Company — [Location] — (Duration)
        """
        cfg = sec or {}
        p = self.doc.add_paragraph(style=style)
        self.styles.tight_paragraph(p, after_pt=0)
        self.styles.flush_left(p)

        item_color = cfg.get("item_color") or cfg.get("header_color")
        loc_color = cfg.get("location_color") or item_color
        dur_color = cfg.get("duration_color") or cfg.get("location_color") or item_color
        meta_pt = self._parse_meta_pt(cfg)

        # Title
        if title_text:
            r_title = p.add_run(title_text)
            r_title.bold = True
            self.styles.apply_run_color(r_title, item_color)

        # Company
        if title_text and company_text:
            p.add_run(" at ")
        if company_text:
            r_comp = p.add_run(company_text)
            r_comp.bold = True
            self.styles.apply_run_color(r_comp, item_color)

        # Location
        if loc_text:
            self._add_meta_run(p, loc_text, cfg.get("location_brackets", True),
                               "[", "]", meta_pt, loc_color, italic=True)

        # Duration
        if span_text:
            self._add_meta_run(p, span_text, cfg.get("duration_brackets", True),
                               "(", ")", meta_pt, dur_color)

        return p

    def add_group_title(
        self,
        title: str,
        sec: Optional[Dict[str, Any]] = None,
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

    def __init__(self, doc, page_cfg: Optional[Dict[str, Any]] = None):
        self.doc = doc
        self.bullets = BulletRenderer(doc, page_cfg)
        self.text = TextFormatter()

    def _extract_item_text(
        self, it: Any, name_keys: tuple, desc_key: Optional[str], desc_sep: str
    ) -> Optional[str]:
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
        items: List[Any],
        sec: Optional[Dict[str, Any]] = None,
        *,
        name_keys: tuple = ("name", "title", "label", "text"),
        desc_key: Optional[str] = None,
        desc_sep: str = " — ",
    ) -> List[str]:
        """Normalize and render a simple list section."""
        cfg = sec or {}
        lines = [
            txt for it in items
            if (txt := self._extract_item_text(it, name_keys, desc_key, desc_sep))
        ]

        if lines:
            if cfg.get("bullets", True):
                plain, glyph = self.bullets.get_bullet_config(sec)
                self.bullets.add_bullets(lines, sec=sec, plain=plain, glyph=glyph)
            else:
                from .docx_styles import StyleManager
                sep = cfg.get("separator") or " • "
                p = self.doc.add_paragraph(sep.join(lines))
                StyleManager.tight_paragraph(p, after_pt=2)

        return lines
