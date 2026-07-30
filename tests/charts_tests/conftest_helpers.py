"""Shared test factories for charts renderer test modules.

Consolidates the near-identical `_make_series` / `_fake_ax` helpers that were
duplicated across test_renderer.py, test_renderer_bar.py, and
test_renderer_line_area.py. Each caller's optional kwargs are supported here
as a superset so no test behavior changes.
"""

from __future__ import annotations

from unittest.mock import MagicMock


def _make_series(name: str, x_values, y_values=None, *, x_field="ts",
                  color=None, label=None, y_axis="left"):
    from charts.types.base import SeriesSpec
    if y_values is None:
        y_values = [float(i + 1) for i in range(len(x_values))]
    data = [{x_field: x, "value": v} for x, v in zip(x_values, y_values)]
    return SeriesSpec(name=name, data=data, color=color, label=label, y_axis=y_axis)


def _fake_ax(**extra_attrs):
    ax = MagicMock()
    ax.spines = {"top": MagicMock(), "bottom": MagicMock(),
                 "left": MagicMock(), "right": MagicMock()}
    ax.get_legend_handles_labels.return_value = ([], [])
    ax.get_xticklabels.return_value = []
    mock_line = MagicMock()
    ax.plot.return_value = (mock_line,)
    ax2 = MagicMock()
    ax2.spines = {"top": MagicMock(), "bottom": MagicMock(),
                  "left": MagicMock(), "right": MagicMock()}
    ax2.plot.return_value = (mock_line,)
    ax.twinx.return_value = ax2
    for key, value in extra_attrs.items():
        setattr(ax, key, value)
    return ax
