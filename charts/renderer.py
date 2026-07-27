"""matplotlib rendering engine for the charts domain.

matplotlib is lazily imported at call time so this module is always
importable in headless/CI environments even if matplotlib is not installed.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from charts.config import GridConfig
from charts.theme import ChartTheme, get_theme
from charts.types.area import AreaChartSpec
from charts.types.bar import BarChartSpec
from charts.types.base import ChartKind, ChartSpec, SeriesSpec
from charts.types.dual import DualAxisChartSpec
from charts.types.line import LineChartSpec

_SUPPORTED_FORMATS = {"png", "svg"}
_RIGHT_AXIS = "right"


def _require_matplotlib() -> None:
    """Raise ImportError with a helpful message if matplotlib is not installed."""
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        raise ImportError(
            "matplotlib is not installed. Run: pip install matplotlib"
        )


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


def _normalize_axes_grid(axes: object, rows: int, cols: int) -> list[list[object]]:
    """Normalise matplotlib axes output to a 2-D list regardless of grid shape."""
    import numpy as np
    if rows == 1 and cols == 1:
        return [[axes]]
    if rows == 1:
        return [list(axes)]  # type: ignore[arg-type]
    if cols == 1:
        return [[row] for row in axes]
    return [list(row) for row in axes]  # type: ignore[union-attr]


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
    import numpy as np
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


def _x_key(v: object) -> str:
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
    ax: object,
    spec: BarChartSpec,
    theme: ChartTheme,
    x_values: list[object],
    x_indices: object,
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
            ax.barh(x_indices, y, left=baseline, color=color, label=label, height=spec.bar_width)  # type: ignore[union-attr]
        else:
            ax.bar(x_indices, y, bottom=baseline, color=color, label=label, width=spec.bar_width)  # type: ignore[union-attr]
        baseline += y


def _render_grouped_bars(
    ax: object,
    spec: BarChartSpec,
    theme: ChartTheme,
    x_values: list[object],
    x_indices: object,
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
            ax.barh(bar_positions, y, color=color, label=label, height=group_width)  # type: ignore[union-attr]
        else:
            ax.bar(bar_positions, y, color=color, label=label, width=group_width)  # type: ignore[union-attr]


def _render_bar(ax: object, spec: BarChartSpec, theme: ChartTheme) -> None:
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
        ax.set_yticks(x_indices)  # type: ignore[union-attr]
        ax.set_yticklabels(x_labels)  # type: ignore[union-attr]
    else:
        n = len(x_indices)
        step = max(1, n // 20)
        ax.set_xticks(x_indices[::step])  # type: ignore[union-attr]
        ax.set_xticklabels(x_labels[::step], rotation=30, ha="right", fontsize=8)  # type: ignore[union-attr]


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
