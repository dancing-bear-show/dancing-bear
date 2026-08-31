"""Line, area, and dual-axis rendering helpers.

Shared x-value parsing, series utilities, and theme/label helpers are also
housed here and re-exported via charts.renderer for backwards compatibility.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from charts.theme import ChartTheme
from charts.types.area import AreaChartSpec
from charts.types.base import ChartSpec, SeriesSpec
from charts.types.dual import DualAxisChartSpec
from charts.types.line import LineChartSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

_RIGHT_AXIS = "right"

# Alias for the x-axis value type returned by _parse_x_values and used throughout.
_XValue = datetime.datetime | float | str


@dataclass(frozen=True)
class LineSeriesStyle:
    """Visual style for a single line series."""

    color: str
    linewidth: float
    label: str


@dataclass(frozen=True)
class DualSeriesContext:
    """Shared x-axis context for dual-axis series rendering."""

    x_values: list[_XValue]
    x_field: str
    is_dates: bool
    palette_offset: int = 0
    linestyle: str = "-"


# ---------------------------------------------------------------------------
# Theme / label helpers (shared by all chart kinds)
# ---------------------------------------------------------------------------

def _apply_theme(fig: Figure, ax: Axes, theme: ChartTheme) -> None:
    fig.patch.set_facecolor(theme.background)
    ax.set_facecolor(theme.axes_bg)

    for spine in ax.spines.values():
        spine.set_edgecolor(theme.grid_color)

    ax.tick_params(colors=theme.text_color, which="both")
    ax.xaxis.label.set_color(theme.text_color)
    ax.yaxis.label.set_color(theme.text_color)
    ax.title.set_color(theme.text_color)

    ax.grid(True, color=theme.grid_color, linewidth=0.5, linestyle="--", alpha=0.7)
    ax.set_axisbelow(True)


def _apply_labels(ax: Axes, spec: ChartSpec, theme: ChartTheme) -> None:
    ax.set_title(spec.title)
    if spec.x_label:
        ax.set_xlabel(spec.x_label)
    if spec.y_label:
        ax.set_ylabel(spec.y_label)

    if spec.show_legend:
        _apply_legend(ax, theme)


def _apply_legend(ax: Axes, theme: ChartTheme) -> None:
    handles, labels = ax.get_legend_handles_labels()
    if not handles:
        return
    legend = ax.legend(
        handles, labels,
        loc="best",
        facecolor=theme.legend_color,
        framealpha=0.8,
        labelcolor=theme.text_color,
    )
    if legend.get_frame() is not None:
        legend.get_frame().set_facecolor(theme.legend_color)


# ---------------------------------------------------------------------------
# Shared x-value / series utilities (used by bar, line, area, dual)
# ---------------------------------------------------------------------------

def _parse_iso_to_datetime(value: str) -> datetime.datetime:
    try:
        dt = datetime.datetime.fromisoformat(value)
        if dt.tzinfo is not None:
            dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        pass
    return datetime.datetime.combine(datetime.date.fromisoformat(value), datetime.time.min)


def _parse_x_values(series: list[SeriesSpec], x_field: str) -> tuple[list[_XValue], bool]:
    unique_raw = list(dict.fromkeys(
        str(row[x_field]) for s in series for row in s.data
    ))

    if not unique_raw:
        return [], False

    try:
        parsed = [_parse_iso_to_datetime(v) for v in unique_raw]
        return sorted(parsed), True
    except ValueError:
        pass

    try:
        nums = [float(v) for v in unique_raw]
        return sorted(nums), False
    except ValueError:
        pass

    return sorted(unique_raw), False


def _series_color(series: SeriesSpec, idx: int, theme: ChartTheme) -> str:
    if series.color:
        return series.color
    return theme.palette[idx % len(theme.palette)]


def _row_key(raw_key: Any, is_dates: bool) -> _XValue:
    if is_dates:
        return _parse_iso_to_datetime(str(raw_key))
    try:
        return float(str(raw_key))
    except (ValueError, TypeError):
        return str(raw_key)


def _build_row_map(
    series: SeriesSpec, x_field: str, is_dates: bool
) -> dict[_XValue, float]:
    m: dict[_XValue, float] = {}
    for row in series.data:
        m[_row_key(row[x_field], is_dates)] = float(row["value"])  # type: ignore[arg-type]
    return m


def _configure_date_axis(ax: Axes, spec: ChartSpec) -> None:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    locator = mdates.AutoDateLocator(minticks=15, maxticks=30)
    ax.xaxis.set_major_locator(locator)
    if spec.date_format:
        formatter: mdates.DateFormatter | mdates.AutoDateFormatter = mdates.DateFormatter(spec.date_format)
    else:
        formatter = mdates.AutoDateFormatter(locator)
    ax.xaxis.set_major_formatter(formatter)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")


def _maybe_shade_weekends(
    ax: Axes, x_values: list[_XValue], is_dates: bool, spec: ChartSpec, theme: ChartTheme
) -> None:
    if is_dates and spec.shade_weekends:
        _shade_weekends(ax, x_values, theme)


def _maybe_configure_date_axis(ax: Axes, is_dates: bool, spec: ChartSpec) -> None:
    if is_dates:
        _configure_date_axis(ax, spec)


# ---------------------------------------------------------------------------
# Line / area / dual rendering
# ---------------------------------------------------------------------------

def _shade_weekends(ax: Axes, x_values: list[_XValue], theme: ChartTheme) -> None:
    import matplotlib.dates as mdates
    seen: set[datetime.date] = set()
    for val in x_values:
        if not isinstance(val, datetime.date):
            return
        day = val.date() if isinstance(val, datetime.datetime) else val
        if day in seen:
            continue
        seen.add(day)
        if day.weekday() >= 5:
            ax.axvspan(
                mdates.date2num(day) - 0.5,
                mdates.date2num(day) + 0.5,
                color=theme.grid_color,
                alpha=0.3,
                zorder=0,
            )
        elif day.weekday() == 0:
            ax.axvline(
                mdates.date2num(day) - 0.5,
                color=theme.grid_color,
                linewidth=0.8,
                linestyle=":",
                alpha=0.6,
                zorder=1,
            )


def _plot_series_smooth(
    ax: Axes,
    x_values: list[_XValue],
    y_values: list[float],
    is_dates: bool,
    style: LineSeriesStyle,
) -> bool:
    import numpy as np
    x_num = np.arange(len(x_values), dtype=float)
    x_dense = np.linspace(0, len(x_values) - 1, len(x_values) * 4)
    finite_mask = np.isfinite(y_values)
    if finite_mask.sum() < 2:
        return False
    x_finite = x_num[finite_mask]
    y_finite = np.array(y_values)[finite_mask]
    y_smooth = np.interp(x_dense, x_finite, y_finite)
    plot_x = x_dense if not is_dates else [
        x_values[int(round(min(xi, len(x_values) - 1)))] for xi in x_dense
    ]
    ax.plot(plot_x, y_smooth, color=style.color, linewidth=style.linewidth, label=style.label)
    return True


def _render_line(ax: Axes, spec: LineChartSpec, theme: ChartTheme) -> None:
    x_values, is_dates = _parse_x_values(spec.series, spec.x_field)

    _maybe_shade_weekends(ax, x_values, is_dates, spec, theme)

    for idx, series in enumerate(spec.series):
        color = _series_color(series, idx, theme)
        row_map = _build_row_map(series, spec.x_field, is_dates)
        y_values = [row_map.get(x, float("nan")) for x in x_values]
        label = series.label or series.name

        if spec.smooth and len(x_values) >= 3:
            if _plot_series_smooth(ax, x_values, y_values, is_dates, LineSeriesStyle(color, spec.line_width, label)):
                continue

        ax.plot(
            x_values, y_values,
            color=color,
            linewidth=spec.line_width,
            marker=spec.marker,
            label=label,
        )

    _maybe_configure_date_axis(ax, is_dates, spec)


def _render_area(ax: Axes, spec: AreaChartSpec, theme: ChartTheme) -> None:
    import numpy as np
    x_values, is_dates = _parse_x_values(spec.series, spec.x_field)

    _maybe_shade_weekends(ax, x_values, is_dates, spec, theme)

    baseline = np.zeros(len(x_values))

    for idx, series in enumerate(spec.series):
        color = _series_color(series, idx, theme)
        row_map = _build_row_map(series, spec.x_field, is_dates)
        y_raw = np.array([row_map.get(x, 0.0) for x in x_values])
        y_top = baseline + y_raw if spec.stacked else y_raw
        fill_bottom = baseline if spec.stacked else np.zeros(len(x_values))

        ax.fill_between(x_values, fill_bottom, y_top, color=color, alpha=spec.alpha)
        ax.plot(x_values, y_top, color=color, linewidth=1.5, label=series.label or series.name)

        if spec.stacked:
            baseline = y_top

    _maybe_configure_date_axis(ax, is_dates, spec)


def _split_by_name_lists(
    series: list[SeriesSpec],
    left_names: set[str],
    right_names: set[str],
) -> tuple[list[SeriesSpec], list[SeriesSpec]]:
    assigned = left_names | right_names
    left = [s for s in series if s.name in left_names]
    right = [s for s in series if s.name in right_names]
    left += [s for s in series if s.name not in assigned]
    return left, right


def _split_dual_series(
    spec: DualAxisChartSpec,
) -> tuple[list[SeriesSpec], list[SeriesSpec]]:
    if spec.left_series_names or spec.right_series_names:
        return _split_by_name_lists(
            spec.series,
            set(spec.left_series_names),
            set(spec.right_series_names),
        )
    return (
        [s for s in spec.series if s.y_axis != _RIGHT_AXIS],
        [s for s in spec.series if s.y_axis == _RIGHT_AXIS],
    )


def _plot_dual_series(
    ax: Axes,
    series_list: list[SeriesSpec],
    ctx: DualSeriesContext,
    theme: ChartTheme,
) -> tuple[list[Any], list[str]]:
    handles: list[Any] = []
    labels: list[str] = []
    for idx, series in enumerate(series_list):
        color = _series_color(series, ctx.palette_offset + idx, theme)
        row_map = _build_row_map(series, ctx.x_field, ctx.is_dates)
        y = [row_map.get(x, float("nan")) for x in ctx.x_values]
        label = series.label or series.name
        (line,) = ax.plot(ctx.x_values, y, color=color, linewidth=2.0, linestyle=ctx.linestyle, label=label)
        handles.append(line)
        labels.append(label)
    return handles, labels


def _apply_secondary_axis_style(
    ax2: Axes, spec: DualAxisChartSpec, theme: ChartTheme
) -> None:
    if spec.y_right_label:
        ax2.set_ylabel(spec.y_right_label)
        ax2.yaxis.label.set_color(theme.text_color)
    ax2.tick_params(colors=theme.text_color, which="both")
    for spine in ax2.spines.values():
        spine.set_edgecolor(theme.grid_color)


def _render_dual(fig: Figure, ax: Axes, spec: DualAxisChartSpec, theme: ChartTheme) -> None:
    ax2 = ax.twinx()
    _apply_theme(fig, ax2, theme)
    ax2.grid(False)

    left_series, right_series = _split_dual_series(spec)
    x_values, is_dates = _parse_x_values(spec.series, spec.x_field)

    _maybe_shade_weekends(ax, x_values, is_dates, spec, theme)

    left_handles, left_labels = _plot_dual_series(
        ax, left_series,
        DualSeriesContext(x_values=x_values, x_field=spec.x_field, is_dates=is_dates),
        theme,
    )
    right_handles, right_labels = _plot_dual_series(
        ax2, right_series,
        DualSeriesContext(
            x_values=x_values, x_field=spec.x_field, is_dates=is_dates,
            palette_offset=len(left_series), linestyle="--",
        ),
        theme,
    )

    _apply_secondary_axis_style(ax2, spec, theme)

    _maybe_configure_date_axis(ax, is_dates, spec)

    all_handles = left_handles + right_handles
    all_labels = left_labels + right_labels
    if spec.show_legend and all_handles:
        ax.legend(all_handles, all_labels, loc="best", facecolor=theme.legend_color, framealpha=0.8)
