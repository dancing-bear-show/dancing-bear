"""DOCX styling utilities for resume rendering.

Provides StyleManager for handling colors, shading, and paragraph formatting.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional, Tuple

from docx.shared import Pt, RGBColor  # type: ignore
from docx.enum.text import WD_ALIGN_PARAGRAPH  # type: ignore
from docx.oxml import OxmlElement  # type: ignore
from docx.oxml.ns import qn  # type: ignore


# Type alias for RGB tuples
RGB = Tuple[int, int, int]


class StyleManager:
    """Manages DOCX paragraph and run styling."""

    # -------------------------------------------------------------------------
    # Color utilities
    # -------------------------------------------------------------------------

    @staticmethod
    @lru_cache(maxsize=256)
    def parse_hex_color(hex_str: Optional[str]) -> Optional[RGB]:
        """Parse a hex color string to RGB tuple.

        Args:
            hex_str: Color string like "#RRGGBB" or "RRGGBB".

        Returns:
            Tuple of (r, g, b) or None if invalid.
        """
        if not hex_str:
            return None
        v = hex_str.strip().lstrip('#')
        if len(v) != 6:
            return None
        try:
            r = int(v[0:2], 16)
            g = int(v[2:4], 16)
            b = int(v[4:6], 16)
            return (r, g, b)
        except Exception:
            return None

    @staticmethod
    def hex_fill(rgb: RGB) -> str:
        """Convert RGB tuple to hex string for DOCX shading (no #)."""
        r, g, b = rgb
        return f"{r:02X}{g:02X}{b:02X}"

    @staticmethod
    def is_dark(rgb: RGB) -> bool:
        """Check if a color is dark (for contrast calculation).

        Uses perceived luminance formula.
        """
        r, g, b = rgb
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return luminance < 140

    @staticmethod
    def auto_contrast_color(bg_rgb: RGB) -> str:
        """Get contrasting text color (white or black) for background."""
        return "#FFFFFF" if StyleManager.is_dark(bg_rgb) else "#000000"

    # -------------------------------------------------------------------------
    # Paragraph formatting
    # -------------------------------------------------------------------------

    @staticmethod
    def tight_paragraph(
        paragraph,
        before_pt: int = 0,
        after_pt: int = 0,
        line_spacing: float = 1.0,
    ) -> None:
        """Apply tight spacing to a paragraph."""
        try:
            pf = paragraph.paragraph_format
            pf.space_before = Pt(before_pt)
            pf.space_after = Pt(after_pt)
            pf.line_spacing = line_spacing
        except Exception:
            pass  # nosec B110 - paragraph format failure

    @staticmethod
    def compact_bullet(paragraph) -> None:
        """Apply compact bullet formatting (no indent, tight spacing)."""
        try:
            pf = paragraph.paragraph_format
            pf.left_indent = Pt(0)
            pf.hanging_indent = Pt(0)
            pf.space_before = Pt(0)
            pf.space_after = Pt(0)
            pf.line_spacing = 1.0
        except Exception:
            pass  # nosec B110 - bullet format failure

    @staticmethod
    def flush_left(paragraph) -> None:
        """Remove indentation and align paragraph left."""
        try:
            pf = paragraph.paragraph_format
            pf.left_indent = Pt(0)
            pf.first_line_indent = Pt(0)
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        except Exception:
            pass  # nosec B110 - alignment failure

    @staticmethod
    def center_paragraph(paragraph) -> None:
        """Center align a paragraph with no indentation."""
        try:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            pf = paragraph.paragraph_format
            pf.left_indent = Pt(0)
            pf.first_line_indent = Pt(0)
        except Exception:
            pass  # nosec B110 - center alignment failure

    # -------------------------------------------------------------------------
    # Shading and colors
    # -------------------------------------------------------------------------

    @staticmethod
    def apply_shading(paragraph, bg_rgb: RGB) -> None:
        """Apply background shading to a paragraph."""
        try:
            p = paragraph._p  # low-level OXML paragraph
            pPr = p.get_or_add_pPr()
            shd = OxmlElement('w:shd')
            shd.set(qn('w:val'), 'clear')
            shd.set(qn('w:color'), 'auto')
            shd.set(qn('w:fill'), StyleManager.hex_fill(bg_rgb))
            # Remove existing shd if present to avoid duplicates
            for child in list(pPr):
                if child.tag == qn('w:shd'):
                    pPr.remove(child)
            pPr.append(shd)
        except Exception:
            pass  # nosec B110 - shading failure

    @staticmethod
    def apply_run_color(run, hex_color: Optional[str]) -> None:
        """Apply color to a text run."""
        if not hex_color:
            return
        rgb = StyleManager.parse_hex_color(hex_color)
        if rgb:
            try:
                run.font.color.rgb = RGBColor(*rgb)
            except Exception:
                pass  # nosec B110 - color apply failure

    @staticmethod
    def apply_run_size(run, size_pt: Optional[float]) -> None:
        """Apply font size to a text run."""
        if size_pt:
            try:
                run.font.size = Pt(size_pt)
            except Exception:
                pass  # nosec B110 - font size failure


class TextFormatter:
    """Text formatting utilities for resume content."""

    @staticmethod
    def normalize_present(val: str) -> str:
        """Normalize date values like 'now', 'current' to 'Present'."""
        v = (val or "").strip()
        if not v:
            return v
        if v.lower() in {"now", "present", "current", "to date", "today"}:
            return "Present"
        return v

    @staticmethod
    def format_date_span(start: str, end: str) -> str:
        """Format a date range as 'Start – End'."""
        start_n = TextFormatter.normalize_present(start)
        end_n = TextFormatter.normalize_present(end)
        if start_n and end_n:
            return f"{start_n} – {end_n}"
        elif start_n and not end_n:
            return f"{start_n} – Present"
        elif end_n and not start_n:
            return end_n
        return ""

    @staticmethod
    def format_date_location(start: str, end: str, location: str) -> str:
        """Format date span and location with separator."""
        span = TextFormatter.format_date_span(start, end)
        parts = [p for p in [span, location] if p]
        return " · ".join(parts)

    @staticmethod
    def format_phone(phone: str) -> str:
        """Format phone number for display."""
        p = (phone or "").strip()
        digits = re.sub(r"\D+", "", p)
        if len(digits) == 11 and digits.startswith("1"):
            return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        if len(digits) == 10:
            return f"({digits[0:3]}) {digits[3:6]}-{digits[6:]}"
        return p

    @staticmethod
    def format_link(url: str) -> str:
        """Format URL for compact display (strip scheme, www)."""
        u = (url or "").strip()
        if not u:
            return ""
        u = re.sub(r"^https?://", "", u, flags=re.I)
        u = re.sub(r"^www\.", "", u, flags=re.I)
        return u.rstrip("/")

    @staticmethod
    def clean_inline(text: str) -> str:
        """Clean inline text (remove bullets, collapse whitespace)."""
        s = text.replace("•", " ")
        s = re.sub(r"\s+", " ", s)
        return s.strip()

    @staticmethod
    def normalize_bullet(text: str, strip_terminal_period: bool = True) -> str:
        """Normalize bullet text for consistent style.

        - Cleans inline text
        - Optionally strips terminal period for fragment style
        """
        s = TextFormatter.clean_inline(text)
        if strip_terminal_period and s.endswith('.'):
            s = s.rstrip()[:-1].rstrip()
        return s


# Convenience aliases for backward compatibility
_parse_hex_color = StyleManager.parse_hex_color
_hex_fill = StyleManager.hex_fill
_is_dark = StyleManager.is_dark
_tight_paragraph = StyleManager.tight_paragraph
_compact_bullet = StyleManager.compact_bullet
_flush_left = StyleManager.flush_left
_apply_paragraph_shading = StyleManager.apply_shading
_normalize_present = TextFormatter.normalize_present
_format_date_location = TextFormatter.format_date_location
_format_phone_display = TextFormatter.format_phone
_format_link_display = TextFormatter.format_link
_clean_inline_text = TextFormatter.clean_inline
_normalize_bullet_text = TextFormatter.normalize_bullet
