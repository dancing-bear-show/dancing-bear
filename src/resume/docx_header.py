"""Header rendering for resume DOCX output.

Provides HeaderRenderer for experience and education entry headers.
"""
from __future__ import annotations

import logging
from typing import Any

from .docx_styles import StyleManager
from .render_config import HeaderLineConfig, MetaRunConfig

_logger = logging.getLogger(__name__)


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
