"""Bar chart rendering helpers (simple, grouped, stacked, horizontal)."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from charts.theme import ChartTheme
from charts.types.bar import BarChartSpec
from charts.renderer_line_area import (
    _parse_iso_to_datetime,
    _parse_x_values,
    _series_color,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes


def _x_key(v: Any) -> str:
    if isinstance(v, datetime.datetime):
        return v.isoformat()
    if isinstance(v, datetime.date):
        return datetime.datetime.combine(v, datetime.time.min).isoformat()
    try:
        return _parse_iso_to_datetime(str(v)).isoformat()
    except ValueError:
        pass
    try:
        f = float(str(v))
        return str(int(f)) if f == int(f) else str(f)
    except (ValueError, TypeError, OverflowError):
        return str(v)


def _render_stacked_bars(
    ax: Axes,
    spec: BarChartSpec,
    theme: ChartTheme,
    x_values: list[Any],
    x_indices: Any,
) -> None:
    import numpy as np
    all_x = {_x_key(v) for v in x_values}
    for idx, series in enumerate(spec.series):
        if {_x_key(row[spec.x_field]) for row in series.data} != all_x:
            raise ValueError(
                f"series[{idx}] '{series.name}': stacked bars require identical x-values across all series"
            )

    baseline = np.zeros(len(x_values))
    for idx, series in enumerate(spec.series):
        color = _series_color(series, idx, theme)
        label = series.label or series.name
        row_map = {_x_key(row[spec.x_field]): float(row["value"]) for row in series.data}  # type: ignore[arg-type]
        y = np.array([row_map.get(_x_key(v), 0.0) for v in x_values])
        if spec.orientation == "horizontal":
            ax.barh(x_indices, y, left=baseline, color=color, label=label, height=spec.bar_width)
        else:
            ax.bar(x_indices, y, bottom=baseline, color=color, label=label, width=spec.bar_width)
        baseline += y


def _render_grouped_bars(
    ax: Axes,
    spec: BarChartSpec,
    theme: ChartTheme,
    x_values: list[Any],
    x_indices: Any,
) -> None:
    import numpy as np
    n_series = len(spec.series)
    group_width = spec.bar_width / n_series if n_series > 0 else spec.bar_width
    offsets = (
        np.linspace(
            -(spec.bar_width / 2) + group_width / 2,
            (spec.bar_width / 2) - group_width / 2,
            n_series,
        )
        if n_series > 1
        else np.array([0.0])
    )
    for idx, series in enumerate(spec.series):
        color = _series_color(series, idx, theme)
        label = series.label or series.name
        row_map = {_x_key(row[spec.x_field]): float(row["value"]) for row in series.data}  # type: ignore[arg-type]
        y = np.array([row_map.get(_x_key(v), 0.0) for v in x_values])
        bar_positions = x_indices + offsets[idx]
        if spec.orientation == "horizontal":
            ax.barh(bar_positions, y, color=color, label=label, height=group_width)
        else:
            ax.bar(bar_positions, y, color=color, label=label, width=group_width)


def _render_bar(ax: Axes, spec: BarChartSpec, theme: ChartTheme) -> None:
    import numpy as np
    x_values, is_dates = _parse_x_values(spec.series, spec.x_field)
    x_indices = np.arange(len(x_values), dtype=float)

    if spec.stacked:
        _render_stacked_bars(ax, spec, theme, x_values, x_indices)
    else:
        _render_grouped_bars(ax, spec, theme, x_values, x_indices)

    if is_dates:
        fmt = spec.date_format or "%b %d"
        x_labels = [
            v.strftime(fmt) if isinstance(v, datetime.datetime) else str(v)
            for v in x_values
        ]
    else:
        x_labels = [_x_key(v) for v in x_values]

    if spec.orientation == "horizontal":
        ax.set_yticks(x_indices)
        ax.set_yticklabels(x_labels)
    else:
        n = len(x_indices)
        step = max(1, n // 20)
        ax.set_xticks(x_indices[::step])
        ax.set_xticklabels(x_labels[::step], rotation=30, ha="right", fontsize=8)
