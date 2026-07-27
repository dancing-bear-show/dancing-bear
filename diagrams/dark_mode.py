"""Dark-mode preprocessing for Mermaid source.

Mermaid's dark theme renders white text, but two common diagram patterns
produce hard-to-read output against dark backgrounds:

1. Sequence diagram ``rect rgb(R, G, B)`` blocks fill the area with a fully
   saturated color, washing out the white text inside. The fix is to use
   ``rgba(R, G, B, 0.15)`` so the rect is a tint, not a wash.
2. Timeline charts use Mermaid's auto-assigned ``cScale*`` section colors,
   which default to near-invisible greys on a dark background. The fix is to
   inject a ``themeVariables`` init directive overriding ``cScale0..cScale2``
   with high-contrast hues.

``apply_dark_mode_fixes()`` rewrites Mermaid source to apply both fixes. The
renderer calls it automatically whenever ``theme="dark"``; callers writing
mermaid by hand can opt out by passing the source through as-is to mmdc.

These fixes are dark-mode-specific. Light-mode renders are untouched.
"""

from __future__ import annotations

import json
import re

# Alpha value for sequence-diagram rect tints. 0.15 was chosen empirically:
# enough hue to signal grouping, light enough that white text reads cleanly.
RECT_ALPHA = 0.15

# Default override palette for timeline sections in dark mode. These hues
# match the dark palette in the mermaid README "Styling" section.
DEFAULT_TIMELINE_PALETTE: dict[str, str] = {
    "cScale0": "#1d4ed8",  # blue
    "cScale1": "#7e22ce",  # purple
    "cScale2": "#b45309",  # amber
}

# Regex for `rect rgb(R, G, B)` — matches the opening rect of a sequence-
# diagram block. The capture group preserves the rgb triple so we can
# rewrite it as rgba with our chosen alpha.
_RECT_RGB_PATTERN = re.compile(
    r"\brect\s+rgb\(\s*(\d+\s*,\s*\d+\s*,\s*\d+)\s*\)",
    re.IGNORECASE,
)

# Regex for an existing init directive — we need to detect whether the
# author has already configured themeVariables so we don't overwrite them.
_INIT_DIRECTIVE_PATTERN = re.compile(r"%%\{\s*init\s*:\s*.*?\}%%", re.DOTALL)

# UTF-8 BOM that some editors prepend; Python's str.strip() doesn't remove it.
_BOM = "﻿"


def _rewrite_rect_rgb_to_rgba(source: str) -> str:
    """Convert saturated ``rect rgb(...)`` to alpha-blended ``rect rgba(..., 0.15)``.

    Only rewrites the rgb form. Existing rgba(...) calls are left alone, so
    authors who explicitly chose a different alpha keep their choice.
    """
    return _RECT_RGB_PATTERN.sub(
        lambda m: f"rect rgba({m.group(1)}, {RECT_ALPHA})",
        source,
    )


def _is_timeline(source: str) -> bool:
    """Detect a timeline diagram by its declaration keyword.

    Skips a BOM, blank lines, ``%%`` comments, and a leading ``---``-delimited
    YAML frontmatter block (Mermaid 10+ syntax). The first remaining content
    line is treated as the diagram-type declaration.
    """
    if source.startswith(_BOM):
        source = source[len(_BOM):]

    in_frontmatter = False
    saw_frontmatter_open = False
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("%%"):
            continue
        if stripped == "---":
            if not saw_frontmatter_open:
                in_frontmatter = True
                saw_frontmatter_open = True
            else:
                in_frontmatter = False
            continue
        if in_frontmatter:
            continue
        first_token = stripped.split(None, 1)[0]
        return first_token == "timeline"
    return False


def _has_init_directive(source: str) -> bool:
    """Check whether the source already has an init directive."""
    return _INIT_DIRECTIVE_PATTERN.search(source) is not None


def _inject_timeline_palette(source: str) -> str:
    """Prepend a themeVariables init directive overriding cScale0..cScale2.

    No-op if the diagram isn't a timeline, or if the author already wrote
    their own init directive (we don't want to clobber explicit choices).
    """
    if not _is_timeline(source):
        return source
    if _has_init_directive(source):
        return source

    config = json.dumps({"theme": "dark", "themeVariables": DEFAULT_TIMELINE_PALETTE})
    directive = f"%%{{init: {config}}}%%"
    return f"{directive}\n{source}"


def apply_dark_mode_fixes(source: str) -> str:
    """Apply dark-mode legibility fixes to Mermaid source.

    Idempotent: running this on already-fixed source is a no-op.
    Safe for non-dark themes (it doesn't introduce light-mode regressions),
    but only worth calling when the renderer is going to use the dark theme.

    Args:
        source: Raw Mermaid diagram source.

    Returns:
        Source with rect rgb() blocks blended and timeline palette injected.
    """
    out = _rewrite_rect_rgb_to_rgba(source)
    out = _inject_timeline_palette(out)
    return out
