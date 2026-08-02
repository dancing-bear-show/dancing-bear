"""matplotlib rendering engine for the charts domain.

Implementation is split across two sibling modules:

* charts.renderer_line_area -- shared x-value parsing, series utilities,
  theme/label helpers, and line/area/dual rendering.
* charts.renderer_bar -- bar chart rendering (simple, grouped, stacked,
  horizontal).

This module re-exports every public and private symbol from those siblings
for backwards compatibility, and contains only the top-level orchestration
functions (render_chart, render_grid, _dispatch) that wire them together.

matplotlib is lazily imported at call time so this module is always
importable in headless/CI environments even if matplotlib is not installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from charts.config import GridConfig
from charts.theme import ChartTheme, get_theme
from charts.types.area import AreaChartSpec
from charts.types.bar import BarChartSpec
from charts.types.base import ChartKind, ChartSpec
from charts.types.dual import DualAxisChartSpec
from charts.types.line import LineChartSpec

# ---------------------------------------------------------------------------
# Re-exports from renderer_line_area (backwards-compatible shim)
# ---------------------------------------------------------------------------
from charts.renderer_line_area import (  # noqa: F401
    _RIGHT_AXIS,
    DualSeriesContext,
    LineSeriesStyle,
    _apply_labels,
    _apply_secondary_axis_style,
    _apply_theme,
    _build_row_map,
    _configure_date_axis,
    _parse_iso_to_datetime,
    _parse_x_values,
    _plot_dual_series,
    _plot_series_smooth,
    _render_area,
    _render_dual,
    _render_line,
    _series_color,
    _shade_weekends,
    _split_by_name_lists,
    _split_dual_series,
)

# ---------------------------------------------------------------------------
# Re-exports from renderer_bar (backwards-compatible shim)
# ---------------------------------------------------------------------------
from charts.renderer_bar import (  # noqa: F401
    _render_bar,
    _render_grouped_bars,
    _render_stacked_bars,
    _x_key,
)

# ---------------------------------------------------------------------------
# Orchestration-only symbols (no sibling home; coordinate the siblings above)
# ---------------------------------------------------------------------------

_SUPPORTED_FORMATS = {"png", "svg"}


def _require_matplotlib() -> None:
    """Raise ImportError with a helpful message if matplotlib is not installed."""
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        raise ImportError(
            "matplotlib is not installed. Run: pip install matplotlib"
        )


def _normalize_axes_grid(axes: Any, rows: int, cols: int) -> list[list[object]]:
    """Normalise matplotlib axes output to a 2-D list regardless of grid shape."""
    if rows == 1 and cols == 1:
        return [[axes]]
    if rows == 1:
        return [list(axes)]
    if cols == 1:
        return [[row] for row in axes]
    return [list(row) for row in axes]


def _hide_unused_axes(
    axes_grid: list[list[object]],
    rows: int,
    cols: int,
    used_cells: set[tuple[int, int]],
) -> None:
    for r in range(rows):
        for c in range(cols):
            if (r, c) not in used_cells:
                axes_grid[r][c].set_visible(False)  # type: ignore[union-attr]


def _base_kwargs(spec: ChartSpec) -> dict[str, object]:
    return {
        "title": spec.title,
        "x_field": spec.x_field,
        "series": spec.series,
        "kind": spec.kind,
        "width_px": spec.width_px,
        "height_px": spec.height_px,
        "dpi": spec.dpi,
        "x_label": spec.x_label,
        "y_label": spec.y_label,
        "y_right_label": spec.y_right_label,
        "show_legend": spec.show_legend,
        "date_format": spec.date_format,
        "shade_weekends": spec.shade_weekends,
    }


def _dispatch(fig: object, ax: object, spec: ChartSpec, theme: ChartTheme) -> None:
    if spec.kind == ChartKind.line:
        line_spec = spec if isinstance(spec, LineChartSpec) else LineChartSpec(**_base_kwargs(spec))  # type: ignore[arg-type]
        _render_line(ax, line_spec, theme)
    elif spec.kind == ChartKind.bar:
        bar_spec = spec if isinstance(spec, BarChartSpec) else BarChartSpec(**_base_kwargs(spec))  # type: ignore[arg-type]
        _render_bar(ax, bar_spec, theme)
    elif spec.kind == ChartKind.area:
        area_spec = spec if isinstance(spec, AreaChartSpec) else AreaChartSpec(**_base_kwargs(spec))  # type: ignore[arg-type]
        _render_area(ax, area_spec, theme)
    elif spec.kind == ChartKind.dual:
        dual_spec = spec if isinstance(spec, DualAxisChartSpec) else DualAxisChartSpec(**_base_kwargs(spec))  # type: ignore[arg-type]
        _render_dual(fig, ax, dual_spec, theme)
    else:
        raise ValueError(f"Unknown chart kind: {spec.kind!r}")


def render_chart(
    spec: ChartSpec,
    output: str,
    theme: str = "dark",
    dpi: int | None = None,
) -> Path:
    """Render a single ChartSpec to a file.

    Returns the resolved output path. Creates parent directories if needed.
    Raises ValueError if the output format is not supported (only png/svg).
    """
    _require_matplotlib()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = Path(output)
    suffix = out.suffix.lstrip(".").lower()
    if suffix not in _SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported output format {out.suffix!r}. Supported: {sorted(_SUPPORTED_FORMATS)}"
        )

    out.parent.mkdir(parents=True, exist_ok=True)

    chart_theme = get_theme(theme)
    effective_dpi = dpi if dpi is not None else spec.dpi
    if effective_dpi <= 0:
        raise ValueError(f"dpi must be positive, got {effective_dpi}")
    figsize = (spec.width_px / effective_dpi, spec.height_px / effective_dpi)

    fig, ax = plt.subplots(figsize=figsize, dpi=effective_dpi)
    _apply_theme(fig, ax, chart_theme)
    _dispatch(fig, ax, spec, chart_theme)
    _apply_labels(ax, spec, chart_theme)

    fig.savefig(str(out), dpi=effective_dpi, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    return out


def render_grid(
    grid_cfg: GridConfig,
    specs: list[ChartSpec],
) -> Path:
    """Render a multi-panel grid to the path specified in grid_cfg.output.

    specs must be ordered to match grid_cfg.panels (index correspondence).
    """
    _require_matplotlib()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if len(specs) != len(grid_cfg.panels):
        raise ValueError(f"Expected {len(grid_cfg.panels)} spec(s), got {len(specs)}")

    if grid_cfg.dpi <= 0:
        raise ValueError(f"dpi must be positive, got {grid_cfg.dpi}")
    if grid_cfg.width_px <= 0 or grid_cfg.height_px <= 0:
        raise ValueError("width_px and height_px must be positive")

    out = Path(grid_cfg.output)
    suffix = out.suffix.lstrip(".").lower()
    if suffix not in _SUPPORTED_FORMATS:
        raise ValueError(f"unsupported output format {out.suffix!r}; use .png or .svg")

    out.parent.mkdir(parents=True, exist_ok=True)

    chart_theme = get_theme(grid_cfg.theme)
    figsize = (grid_cfg.width_px / grid_cfg.dpi, grid_cfg.height_px / grid_cfg.dpi)

    fig, axes = plt.subplots(
        nrows=grid_cfg.rows,
        ncols=grid_cfg.cols,
        figsize=figsize,
        dpi=grid_cfg.dpi,
    )
    fig.patch.set_facecolor(chart_theme.background)

    axes_grid = _normalize_axes_grid(axes, grid_cfg.rows, grid_cfg.cols)

    for panel, spec in zip(grid_cfg.panels, specs):
        ax = axes_grid[panel.row][panel.col]
        _apply_theme(fig, ax, chart_theme)  # type: ignore[arg-type]
        _dispatch(fig, ax, spec, chart_theme)  # type: ignore[arg-type]
        _apply_labels(ax, spec, chart_theme)  # type: ignore[arg-type]

    used_cells = {(panel.row, panel.col) for panel in grid_cfg.panels}
    _hide_unused_axes(axes_grid, grid_cfg.rows, grid_cfg.cols, used_cells)

    if grid_cfg.title:
        fig.suptitle(
            grid_cfg.title,
            color=chart_theme.text_color,
            fontsize=14,
            fontweight="bold",
        )

    fig.tight_layout()
    fig.savefig(str(out), dpi=grid_cfg.dpi, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    return out
