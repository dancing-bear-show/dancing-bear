"""charts — time-series chart rendering.

Public surface: render_chart, render_grid, ChartSpec, SeriesSpec.
Internal modules (theme, reshape, config) are implementation details.
"""

# renderer.py guards its own matplotlib import and raises a clear ImportError
# at call time via _require_matplotlib(); the module itself is always importable.
from charts.renderer import render_chart, render_grid
from charts.types.base import ChartSpec, SeriesSpec

__all__ = ["ChartSpec", "SeriesSpec", "render_chart", "render_grid"]
