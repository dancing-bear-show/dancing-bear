"""Line, area, and dual-axis rendering helpers.

Shared x-value parsing, series utilities, and theme/label helpers are also
housed here and re-exported via charts.renderer for backwards compatibility.
"""

from __future__ import annotations

import datetime

from charts.theme import ChartTheme
from charts.types.area import AreaChartSpec
from charts.types.base import ChartSpec, SeriesSpec
from charts.types.dual import DualAxisChartSpec
from charts.types.line import LineChartSpec

_RIGHT_AXIS = "right"


# ---------------------------------------------------------------------------
# Theme / label helpers (shared by all chart kinds)
# ---------------------------------------------------------------------------

def _apply_theme(fig: object, ax: object, theme: ChartTheme) -> None:
    fig.patch.set_facecolor(theme.background)  # type: ignore[union-attr]
    ax.set_facecolor(theme.axes_bg)  # type: ignore[union-attr]

    for spine in ax.spines.values():  # type: ignore[union-attr]
        spine.set_edgecolor(theme.grid_color)

    ax.tick_params(colors=theme.text_color, which="both")  # type: ignore[union-attr]
    ax.xaxis.label.set_color(theme.text_color)  # type: ignore[union-attr]
    ax.yaxis.label.set_color(theme.text_color)  # type: ignore[union-attr]
    ax.title.set_color(theme.text_color)  # type: ignore[union-attr]

    ax.grid(True, color=theme.grid_color, linewidth=0.5, linestyle="--", alpha=0.7)  # type: ignore[union-attr]
    ax.set_axisbelow(True)  # type: ignore[union-attr]


def _apply_labels(ax: object, spec: ChartSpec, theme: ChartTheme) -> None:
    ax.set_title(spec.title)  # type: ignore[union-attr]
    if spec.x_label:
        ax.set_xlabel(spec.x_label)  # type: ignore[union-attr]
    if spec.y_label:
        ax.set_ylabel(spec.y_label)  # type: ignore[union-attr]

    if spec.show_legend:
        handles, labels = ax.get_legend_handles_labels()  # type: ignore[union-attr]
        if handles:
            legend = ax.legend(  # type: ignore[union-attr]
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


def _parse_x_values(series: list[SeriesSpec], x_field: str) -> tuple[list[object], bool]:
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


def _build_row_map(
    series: SeriesSpec, x_field: str, is_dates: bool
) -> dict[object, float]:
    m: dict[object, float] = {}
    for row in series.data:
        raw_key = row[x_field]
        if is_dates:
            key: object = _parse_iso_to_datetime(str(raw_key))
        else:
            try:
                key = float(str(raw_key))
            except (ValueError, TypeError):
                key = raw_key
        m[key] = float(row["value"])  # type: ignore[arg-type]
    return m


def _configure_date_axis(ax: object, spec: ChartSpec) -> None:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    locator = mdates.AutoDateLocator(minticks=15, maxticks=30)
    ax.xaxis.set_major_locator(locator)  # type: ignore[union-attr]
    if spec.date_format:
        formatter: object = mdates.DateFormatter(spec.date_format)
    else:
        formatter = mdates.AutoDateFormatter(locator)
    ax.xaxis.set_major_formatter(formatter)  # type: ignore[union-attr]
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Line / area / dual rendering
# ---------------------------------------------------------------------------

def _shade_weekends(ax: object, x_values: list[object], theme: ChartTheme) -> None:
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
            ax.axvspan(  # type: ignore[union-attr]
                mdates.date2num(day) - 0.5,
                mdates.date2num(day) + 0.5,
                color=theme.grid_color,
                alpha=0.3,
                zorder=0,
            )
        elif day.weekday() == 0:
            ax.axvline(  # type: ignore[union-attr]
                mdates.date2num(day) - 0.5,
                color=theme.grid_color,
                linewidth=0.8,
                linestyle=":",
                alpha=0.6,
                zorder=1,
            )


def _plot_series_smooth(
    ax: object,
    x_values: list[object],
    y_values: list[float],
    is_dates: bool,
    color: str,
    linewidth: float,
    label: str,
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
    ax.plot(plot_x, y_smooth, color=color, linewidth=linewidth, label=label)  # type: ignore[union-attr]
    return True


def _render_line(ax: object, spec: LineChartSpec, theme: ChartTheme) -> None:
    x_values, is_dates = _parse_x_values(spec.series, spec.x_field)

    if is_dates and spec.shade_weekends:
        _shade_weekends(ax, x_values, theme)

    for idx, series in enumerate(spec.series):
        color = _series_color(series, idx, theme)
        row_map = _build_row_map(series, spec.x_field, is_dates)
        y_values = [row_map.get(x, float("nan")) for x in x_values]
        label = series.label or series.name

        if spec.smooth and len(x_values) >= 3:
            if _plot_series_smooth(ax, x_values, y_values, is_dates, color, spec.line_width, label):
                continue

        ax.plot(  # type: ignore[union-attr]
            x_values, y_values,
            color=color,
            linewidth=spec.line_width,
            marker=spec.marker,
            label=label,
        )

    if is_dates:
        _configure_date_axis(ax, spec)


def _render_area(ax: object, spec: AreaChartSpec, theme: ChartTheme) -> None:
    import numpy as np
    x_values, is_dates = _parse_x_values(spec.series, spec.x_field)

    if is_dates and spec.shade_weekends:
        _shade_weekends(ax, x_values, theme)

    baseline = np.zeros(len(x_values))

    for idx, series in enumerate(spec.series):
        color = _series_color(series, idx, theme)
        row_map = _build_row_map(series, spec.x_field, is_dates)
        y_raw = np.array([row_map.get(x, 0.0) for x in x_values])
        y_top = baseline + y_raw if spec.stacked else y_raw
        fill_bottom = baseline if spec.stacked else np.zeros(len(x_values))

        ax.fill_between(x_values, fill_bottom, y_top, color=color, alpha=spec.alpha)  # type: ignore[union-attr]
        ax.plot(x_values, y_top, color=color, linewidth=1.5, label=series.label or series.name)  # type: ignore[union-attr]

        if spec.stacked:
            baseline = y_top

    if is_dates:
        _configure_date_axis(ax, spec)


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
    ax: object,
    series_list: list[SeriesSpec],
    x_values: list[object],
    x_field: str,
    is_dates: bool,
    theme: ChartTheme,
    palette_offset: int,
    linestyle: str = "-",
) -> tuple[list[object], list[str]]:
    handles: list[object] = []
    labels: list[str] = []
    for idx, series in enumerate(series_list):
        color = _series_color(series, palette_offset + idx, theme)
        row_map = _build_row_map(series, x_field, is_dates)
        y = [row_map.get(x, float("nan")) for x in x_values]
        label = series.label or series.name
        (line,) = ax.plot(x_values, y, color=color, linewidth=2.0, linestyle=linestyle, label=label)  # type: ignore[union-attr]
        handles.append(line)
        labels.append(label)
    return handles, labels


def _apply_secondary_axis_style(
    ax2: object, spec: DualAxisChartSpec, theme: ChartTheme
) -> None:
    if spec.y_right_label:
        ax2.set_ylabel(spec.y_right_label)  # type: ignore[union-attr]
        ax2.yaxis.label.set_color(theme.text_color)  # type: ignore[union-attr]
    ax2.tick_params(colors=theme.text_color, which="both")  # type: ignore[union-attr]
    for spine in ax2.spines.values():  # type: ignore[union-attr]
        spine.set_edgecolor(theme.grid_color)


def _render_dual(fig: object, ax: object, spec: DualAxisChartSpec, theme: ChartTheme) -> None:
    ax2 = ax.twinx()  # type: ignore[union-attr]
    _apply_theme(fig, ax2, theme)
    ax2.grid(False)

    left_series, right_series = _split_dual_series(spec)
    x_values, is_dates = _parse_x_values(spec.series, spec.x_field)

    if is_dates and spec.shade_weekends:
        _shade_weekends(ax, x_values, theme)

    left_handles, left_labels = _plot_dual_series(
        ax, left_series, x_values, spec.x_field, is_dates, theme, palette_offset=0
    )
    right_handles, right_labels = _plot_dual_series(
        ax2, right_series, x_values, spec.x_field, is_dates, theme,
        palette_offset=len(left_series), linestyle="--"
    )

    _apply_secondary_axis_style(ax2, spec, theme)

    if is_dates:
        _configure_date_axis(ax, spec)

    all_handles = left_handles + right_handles
    all_labels = left_labels + right_labels
    if spec.show_legend and all_handles:
        ax.legend(all_handles, all_labels, loc="best", facecolor=theme.legend_color, framealpha=0.8)  # type: ignore[union-attr]
