"""Low-level text styling helpers for slide generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from slides.constants import (
    BULLET_CHARS,
    BULLET_HANGING_INDENT_EMU,
    BULLET_MARGIN_BY_LEVEL_EMU,
    EXISTING_BULLET_CHARS,
    highlight_theme_color,
    link_blue,
)

if TYPE_CHECKING:
    from pptx.enum.dml import MSO_THEME_COLOR
    from pptx.util import Pt

# DrawingML XML namespace — shared by _suppress_bullet and _apply_native_bullet
_DRAWINGML_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_DRAWINGML_NSMAP = {"a": _DRAWINGML_NS}


@dataclass(frozen=True)
class TextStyle:
    """How one run of text should be rendered.

    Bundles the five styling fields every _add_text_to_paragraph call site
    already assembles together. Defaults reproduce the previous signature's
    defaults exactly, so a call passing only theme_color and font_size behaves
    as it did when those were positional parameters.
    """

    theme_color: MSO_THEME_COLOR | int | None = None
    font_size: Pt | int | None = None
    # True forces bold; the styling layer maps False to None so the template's
    # own weight is inherited rather than explicitly unset.
    bold: bool = False
    highlights: list[str] | None = None
    # When set, every run in the paragraph gets link styling.
    url: str | None = None


class StylingMixin:
    """Mixin providing low-level text run and bullet styling methods."""

    def _style_run(
        self,
        run,
        *,
        font_size: Pt | None = None,
        theme_color: MSO_THEME_COLOR | None = None,
        bold: bool | None = None,
    ) -> None:
        """Apply styling to a text run.

        Args:
            run: The text run to style
            font_size: Font size in Pt
            theme_color: Theme color to apply
            bold: Whether to make text bold
        """
        if font_size is not None:
            run.font.size = font_size
        if theme_color is not None:
            run.font.color.theme_color = theme_color
        if bold is not None:
            run.font.bold = bold

    def _format_bullet_text(self, text: str, level: int) -> str:
        """Clean bullet text (remove existing bullet chars if present).

        Native PowerPoint bullets are applied via XML, not text characters.

        Args:
            text: The bullet text
            level: Indentation level (0=top, 1=sub, 2=sub-sub)

        Returns:
            Cleaned text without bullet characters
        """
        if not text or not text.strip():
            return text

        text = text.strip()

        # Strip existing bullet characters from text (we use native PPT bullets)
        if text.startswith(EXISTING_BULLET_CHARS):
            text = text.lstrip("•◦▪‣-* ").strip()

        return text

    @staticmethod
    def _split_by_highlights(text: str, highlights: list[str]) -> list[str]:
        """Split text into segments around highlight terms, longest-first."""
        sorted_highlights = sorted(highlights, key=len, reverse=True)
        pattern = '(' + '|'.join(re.escape(h) for h in sorted_highlights) + ')'
        return [s for s in re.split(pattern, text) if s]

    def _style_highlighted_run(
        self,
        run,
        segment: str,
        highlights: list[str],
        font_size: Pt | int | None,
        theme_color: MSO_THEME_COLOR | int | None,
        bold: bool,
    ) -> None:
        """Style a single run, applying accent color when segment is highlighted."""
        if segment in highlights:
            # Highlighted segment — bold always, accent color only when
            # theme_color is explicitly set (legacy mode). In template
            # style mode (theme_color=None), bold alone provides emphasis
            # without risking a light accent on a light background.
            self._style_run(
                run,
                font_size=font_size,
                theme_color=highlight_theme_color() if theme_color is not None else None,
                bold=True,
            )
        else:
            self._style_run(
                run,
                font_size=font_size,
                theme_color=theme_color,
                bold=True if bold else None,  # True = force bold, None = inherit template
            )

    @staticmethod
    def _apply_hyperlink(run, url: str, preserve_color: bool = False) -> None:
        """Apply hyperlink styling and address to a text run.

        Args:
            run: The text run to add the hyperlink to
            url: The target URL
            preserve_color: If True, keep the existing font color (e.g., for highlighted runs)
        """
        run.hyperlink.address = url
        if not preserve_color:
            run.font.color.rgb = link_blue()
        run.font.underline = True

    def _suppress_bullet(self, paragraph) -> None:
        """Explicitly remove any bullet formatting from a paragraph."""
        from lxml import etree

        p_pr = paragraph._p.find("a:pPr", _DRAWINGML_NSMAP)
        if p_pr is None:
            p_pr = etree.SubElement(paragraph._p, f"{{{_DRAWINGML_NS}}}pPr")
            paragraph._p.insert(0, p_pr)

        # Remove any existing bullet definitions
        for tag in ["a:buChar", "a:buAutoNum", "a:buFont"]:
            existing = p_pr.find(tag, _DRAWINGML_NSMAP)
            if existing is not None:
                p_pr.remove(existing)

        # Add buNone to explicitly suppress bullets
        existing_none = p_pr.find("a:buNone", _DRAWINGML_NSMAP)
        if existing_none is None:
            etree.SubElement(p_pr, f"{{{_DRAWINGML_NS}}}buNone")

    def _apply_native_bullet(self, paragraph, level: int) -> None:
        """Apply native PowerPoint bullet formatting via XML.

        Uses buChar for proper bullet rendering instead of text characters.
        """
        from lxml import etree

        # Get or create p_pr element
        p_pr = paragraph._p.find("a:pPr", _DRAWINGML_NSMAP)
        if p_pr is None:
            p_pr = etree.SubElement(paragraph._p, f"{{{_DRAWINGML_NS}}}pPr")
            # Insert p_pr as first child
            paragraph._p.insert(0, p_pr)

        p_pr.set("lvl", str(level))

        # Hanging indent is level-independent; only the left margin steps.
        margin = (
            BULLET_MARGIN_BY_LEVEL_EMU[level]
            if 0 <= level < len(BULLET_MARGIN_BY_LEVEL_EMU)
            else BULLET_MARGIN_BY_LEVEL_EMU[0]
        )
        p_pr.set("indent", str(-BULLET_HANGING_INDENT_EMU))
        p_pr.set("marL", str(margin))

        # Remove any existing bullet definitions
        for tag in ["a:buNone", "a:buChar", "a:buAutoNum"]:
            existing = p_pr.find(tag, _DRAWINGML_NSMAP)
            if existing is not None:
                p_pr.remove(existing)

        # Add bullet character — BULLET_CHARS = [•, ◦, ▪] (level-indexed)
        char = BULLET_CHARS[level] if level < len(BULLET_CHARS) else BULLET_CHARS[0]
        bu = etree.SubElement(p_pr, f"{{{_DRAWINGML_NS}}}buChar")
        bu.set("char", char)

    def _add_text_to_paragraph(
        self,
        paragraph,
        text: str,
        style: TextStyle,
    ) -> None:
        """Add text to paragraph with optional highlighted segments and hyperlink.

        Args:
            paragraph: The paragraph to add text to
            text: The text content
            style: How to render it — see TextStyle.
        """
        theme_color = style.theme_color
        font_size = style.font_size
        bold = style.bold
        highlights = style.highlights
        url = style.url

        if not highlights:
            run = paragraph.add_run()
            run.text = text
            self._style_run(
                run,
                font_size=font_size,
                theme_color=theme_color,
                bold=True if bold else None,  # True = force bold, None = inherit template
            )
            if url:
                self._apply_hyperlink(run, url)
            return

        segments = self._split_by_highlights(text, highlights)
        for segment in segments:
            run = paragraph.add_run()
            run.text = segment
            is_highlighted = any(segment.lower() == h.lower() for h in highlights)
            self._style_highlighted_run(
                run, segment, highlights, font_size, theme_color, bold,
            )
            if url:
                self._apply_hyperlink(run, url, preserve_color=is_highlighted)
