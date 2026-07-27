"""Chart color themes and named palette for all chart types."""

from __future__ import annotations

from dataclasses import dataclass, field

# Ordered hex colors used by the renderer to assign series colors by index.
# Dark palette uses GitHub's dark-mode syntax highlight colors for familiarity.
PALETTE_DARK: tuple[str, ...] = (
    "#ffa657", "#79c0ff", "#7ee787", "#ff7b72",
    "#d2a8ff", "#ffa198", "#56d364",
)
PALETTE_LIGHT: tuple[str, ...] = (
    "#d4691e", "#1565c0", "#2e7d32", "#c62828",
    "#6a1b9a", "#ad1457", "#00695c",
)


@dataclass(frozen=True)
class ChartTheme:
    name: str
    background: str
    axes_bg: str
    text_color: str
    grid_color: str
    legend_color: str
    palette: tuple[str, ...] = field(default_factory=tuple)


DARK_THEME: ChartTheme = ChartTheme(
    name="dark",
    background="#0d1117",
    axes_bg="#161b22",
    text_color="#e6edf3",
    grid_color="#30363d",
    legend_color="#21262d",
    palette=PALETTE_DARK,
)

LIGHT_THEME: ChartTheme = ChartTheme(
    name="light",
    background="#ffffff",
    axes_bg="#f6f8fa",
    text_color="#24292f",
    grid_color="#d8dee4",
    legend_color="#f6f8fa",
    palette=PALETTE_LIGHT,
)

_THEMES: dict[str, ChartTheme] = {
    "dark": DARK_THEME,
    "light": LIGHT_THEME,
}


def get_theme(name: str) -> ChartTheme:
    """Return the named theme; raise ValueError for unknown names."""
    if name not in _THEMES:
        valid = ", ".join(_THEMES)
        raise ValueError(f"Unknown theme {name!r}. Valid options: {valid}")
    return _THEMES[name]
