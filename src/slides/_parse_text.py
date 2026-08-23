"""Shared text, regex, and chunking helpers for the slide deck input parsers.

Used by both the markdown/outline loaders and the CSV loader.
"""

from __future__ import annotations

import re

from slides.schema import BulletItem, SlideContent, TableSlide

# Maximum bullets per slide before auto-pagination
DEFAULT_BULLET_LIMIT = 8

# Regex for inline markdown bold: **text**
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
# Regex for inline markdown code: `text`
_CODE_RE = re.compile(r"`(.+?)`")
# Regex for bullet lines (-, *, •, numbered)
_BULLET_RE = re.compile(r"^(\s*)([-*•]|\d+\.)\s+(.*)$")
# Regex to strip "Slide N:" prefixes
_SLIDE_PREFIX_RE = re.compile(r"^\s*Slide\s+\d+\s*[:\-—–]\s*", re.IGNORECASE)


def _normalize_title(title: str) -> str:
    """Strip 'Slide N:' prefixes from titles."""
    if not title:
        return title
    return _SLIDE_PREFIX_RE.sub("", title).strip()


def _extract_highlights(text: str) -> tuple[str, list[str]]:
    """Extract bold/code segments as highlights, return cleaned text and highlights list."""
    highlights: list[str] = []

    for match in _BOLD_RE.finditer(text):
        highlights.append(match.group(1))

    for match in _CODE_RE.finditer(text):
        highlights.append(match.group(1))

    # Remove markdown formatting, keep inner text
    cleaned = _BOLD_RE.sub(r"\1", text)
    cleaned = _CODE_RE.sub(r"\1", cleaned)

    return cleaned, highlights


def _parse_bullet_line(line: str) -> BulletItem | None:
    """Parse a single line as a bullet item with level detection."""
    m = _BULLET_RE.match(line)
    if not m:
        return None

    indent = len(m.group(1))
    raw_text = m.group(3).strip()
    if not raw_text:
        return None

    # Determine indent level from whitespace (0, 1, 2)
    level = min(indent // 2, 2) if indent > 0 else 0

    cleaned, highlights = _extract_highlights(raw_text)
    return BulletItem(text=cleaned, level=level, highlight=highlights)


def _split_slide_into_chunks(
    slide: SlideContent, bullet_limit: int,
) -> list[SlideContent]:
    """Split a single slide into continuation slides at the bullet limit."""
    chunks: list[SlideContent] = []
    for i in range(0, len(slide.bullets), bullet_limit):
        is_first = i == 0
        chunks.append(SlideContent(
            title=slide.title if is_first else f"{slide.title} (cont.)",
            subtitle=slide.subtitle if is_first else None,
            bullets=slide.bullets[i : i + bullet_limit],
            notes=slide.notes if is_first else None,
            layout=slide.layout,
        ))
    return chunks


def _chunk_slides(
    slides: list[SlideContent],
    bullet_limit: int = DEFAULT_BULLET_LIMIT,
) -> list[SlideContent]:
    """Split slides with too many bullets into continuation slides."""
    if bullet_limit <= 0:
        return list(slides)
    result: list[SlideContent] = []
    for slide in slides:
        # Table slides are not bullet-based; pass through unchanged
        if isinstance(slide, TableSlide):
            result.append(slide)
            continue
        if len(slide.bullets) <= bullet_limit:
            result.append(slide)
            continue
        result.extend(_split_slide_into_chunks(slide, bullet_limit))

    return result
