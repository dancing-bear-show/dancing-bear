"""Tests for charts/renderer_line_area.py.

All matplotlib calls are intercepted via MagicMock objects.
numpy is imported lazily inside the functions under test; we allow real numpy
since it is installed in the test environment.
"""

from __future__ import annotations

import datetime
import unittest
from unittest.mock import MagicMock, patch

from tests.charts_tests.conftest_helpers import _fake_ax, _make_series


# ---------------------------------------------------------------------------
# Shared factories
# ---------------------------------------------------------------------------

def _make_line_spec(series, *, smooth=False, shade_weekends=False,
                    show_legend=True, x_label=None, y_label=None,
                    marker=None, line_width=1.5, date_format=None):
    from charts.types.line import LineChartSpec
    return LineChartSpec(
        title="Test Line",
        x_field="ts",
        series=series,
        smooth=smooth,
        shade_weekends=shade_weekends,
        show_legend=show_legend,
        x_label=x_label,
        y_label=y_label,
        marker=marker,
        line_width=line_width,
        date_format=date_format,
    )


def _make_area_spec(series, *, stacked=False, alpha=0.4, shade_weekends=False):
    from charts.types.area import AreaChartSpec
    return AreaChartSpec(
        title="Test Area",
        x_field="ts",
        series=series,
        stacked=stacked,
        alpha=alpha,
        shade_weekends=shade_weekends,
    )


def _make_dual_spec(series, *, left_names=None, right_names=None,
                    show_legend=True, y_right_label=None, shade_weekends=False):
    from charts.types.dual import DualAxisChartSpec
    kwargs: dict = dict(
        title="Test Dual",
        x_field="ts",
        series=series,
        show_legend=show_legend,
        shade_weekends=shade_weekends,
    )
    if left_names is not None:
        kwargs["left_series_names"] = left_names
    if right_names is not None:
        kwargs["right_series_names"] = right_names
    if y_right_label is not None:
        kwargs["y_right_label"] = y_right_label
    return DualAxisChartSpec(**kwargs)


def _fake_fig():
    return MagicMock()


def _dark_theme():
    from charts.theme import get_theme
    return get_theme("dark")


# ---------------------------------------------------------------------------
# _apply_theme
# ---------------------------------------------------------------------------

class TestApplyTheme(unittest.TestCase):
    def test_sets_background_and_axes_bg(self):
        from charts.renderer_line_area import _apply_theme
        theme = _dark_theme()
        fig = _fake_fig()
        ax = _fake_ax()
        _apply_theme(fig, ax, theme)
        fig.patch.set_facecolor.assert_called_once_with(theme.background)
        ax.set_facecolor.assert_called_once_with(theme.axes_bg)

    def test_sets_grid(self):
        from charts.renderer_line_area import _apply_theme
        theme = _dark_theme()
        fig = _fake_fig()
        ax = _fake_ax()
        _apply_theme(fig, ax, theme)
        ax.grid.assert_called_once()

    def test_sets_tick_params(self):
        from charts.renderer_line_area import _apply_theme
        theme = _dark_theme()
        fig = _fake_fig()
        ax = _fake_ax()
        _apply_theme(fig, ax, theme)
        ax.tick_params.assert_called_with(colors=theme.text_color, which="both")

    def test_spine_colors_set(self):
        from charts.renderer_line_area import _apply_theme
        theme = _dark_theme()
        fig = _fake_fig()
        ax = _fake_ax()
        _apply_theme(fig, ax, theme)
        for spine in ax.spines.values():
            spine.set_edgecolor.assert_called_with(theme.grid_color)


# ---------------------------------------------------------------------------
# _apply_labels
# ---------------------------------------------------------------------------

class TestApplyLabels(unittest.TestCase):
    def _make_spec(self, x_label=None, y_label=None, show_legend=True):
        s = _make_series("s", ["2024-01-01"])
        return _make_line_spec([s], x_label=x_label, y_label=y_label,
                               show_legend=show_legend)

    def test_title_always_set(self):
        from charts.renderer_line_area import _apply_labels
        ax = _fake_ax()
        spec = self._make_spec()
        _apply_labels(ax, spec, _dark_theme())
        ax.set_title.assert_called_once_with(spec.title)

    def test_x_label_set_when_provided(self):
        from charts.renderer_line_area import _apply_labels
        ax = _fake_ax()
        spec = self._make_spec(x_label="Date")
        _apply_labels(ax, spec, _dark_theme())
        ax.set_xlabel.assert_called_once_with("Date")

    def test_y_label_set_when_provided(self):
        from charts.renderer_line_area import _apply_labels
        ax = _fake_ax()
        spec = self._make_spec(y_label="Count")
        _apply_labels(ax, spec, _dark_theme())
        ax.set_ylabel.assert_called_once_with("Count")

    def test_no_x_label_when_absent(self):
        from charts.renderer_line_area import _apply_labels
        ax = _fake_ax()
        spec = self._make_spec(x_label=None)
        _apply_labels(ax, spec, _dark_theme())
        ax.set_xlabel.assert_not_called()

    def test_legend_created_when_handles_exist(self):
        from charts.renderer_line_area import _apply_labels
        ax = _fake_ax()
        mock_handle = MagicMock()
        mock_legend = MagicMock()
        mock_legend.get_frame.return_value = None
        ax.get_legend_handles_labels.return_value = ([mock_handle], ["series"])
        ax.legend.return_value = mock_legend
        spec = self._make_spec(show_legend=True)
        _apply_labels(ax, spec, _dark_theme())
        ax.legend.assert_called_once()

    def test_legend_not_created_when_no_handles(self):
        from charts.renderer_line_area import _apply_labels
        ax = _fake_ax()
        ax.get_legend_handles_labels.return_value = ([], [])
        spec = self._make_spec(show_legend=True)
        _apply_labels(ax, spec, _dark_theme())
        ax.legend.assert_not_called()

    def test_legend_not_created_when_show_legend_false(self):
        from charts.renderer_line_area import _apply_labels
        ax = _fake_ax()
        ax.get_legend_handles_labels.return_value = ([MagicMock()], ["s"])
        spec = self._make_spec(show_legend=False)
        _apply_labels(ax, spec, _dark_theme())
        ax.legend.assert_not_called()


# ---------------------------------------------------------------------------
# _series_color
# ---------------------------------------------------------------------------

class TestSeriesColor(unittest.TestCase):
    def test_uses_explicit_color_when_set(self):
        from charts.renderer_line_area import _series_color
        s = _make_series("s", ["2024-01-01"], color="#ff0000")
        result = _series_color(s, 0, _dark_theme())
        self.assertEqual(result, "#ff0000")

    def test_falls_back_to_theme_palette(self):
        from charts.renderer_line_area import _series_color
        s = _make_series("s", ["2024-01-01"])
        theme = _dark_theme()
        result = _series_color(s, 0, theme)
        self.assertEqual(result, theme.palette[0])

    def test_palette_wraps_on_high_index(self):
        from charts.renderer_line_area import _series_color
        s = _make_series("s", [])
        theme = _dark_theme()
        palette_len = len(theme.palette)
        result = _series_color(s, palette_len, theme)
        self.assertEqual(result, theme.palette[0])


# ---------------------------------------------------------------------------
# _build_row_map
# ---------------------------------------------------------------------------

class TestBuildRowMap(unittest.TestCase):
    def test_date_keys_parsed(self):
        from charts.renderer_line_area import _build_row_map
        s = _make_series("s", ["2024-01-01", "2024-01-02"], [10.0, 20.0])
        result = _build_row_map(s, "ts", is_dates=True)
        keys = list(result.keys())
        self.assertIsInstance(keys[0], datetime.datetime)
        self.assertEqual(result[keys[0]], 10.0)

    def test_numeric_keys_parsed(self):
        from charts.renderer_line_area import _build_row_map
        s = _make_series("s", [1, 2, 3], [5.0, 6.0, 7.0], x_field="x")
        result = _build_row_map(s, "x", is_dates=False)
        self.assertIn(1.0, result)
        self.assertEqual(result[1.0], 5.0)

    def test_string_keys_returned_as_is(self):
        from charts.renderer_line_area import _build_row_map
        s = _make_series("s", ["alpha", "beta"], [1.0, 2.0], x_field="x")
        result = _build_row_map(s, "x", is_dates=False)
        self.assertIn("alpha", result)
        self.assertIn("beta", result)

    def test_empty_data_returns_empty_map(self):
        from charts.renderer_line_area import _build_row_map
        from charts.types.base import SeriesSpec
        s = SeriesSpec(name="s", data=[])
        result = _build_row_map(s, "ts", is_dates=True)
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# _configure_date_axis
# ---------------------------------------------------------------------------

class TestConfigureDateAxis(unittest.TestCase):
    def test_calls_set_major_locator_and_formatter(self):
        from charts.renderer_line_area import _configure_date_axis
        ax = _fake_ax()
        s = _make_series("s", ["2024-01-01"])
        spec = _make_line_spec([s])

        mock_mdates = MagicMock()
        mock_plt = MagicMock()
        mock_plt.setp = MagicMock()
        with patch.dict("sys.modules", {
            "matplotlib.dates": mock_mdates,
            "matplotlib.pyplot": mock_plt,
        }):
            _configure_date_axis(ax, spec)
        ax.xaxis.set_major_locator.assert_called_once()
        ax.xaxis.set_major_formatter.assert_called_once()

    def test_uses_explicit_date_format(self):
        from charts.renderer_line_area import _configure_date_axis
        ax = _fake_ax()
        s = _make_series("s", ["2024-01-01"])
        spec = _make_line_spec([s], date_format="%Y-%m")
        # matplotlib may already be in sys.modules from a prior test; patch the
        # live module attribute directly so the local `import` inside the function
        # picks up the mock regardless of import-caching order.
        import matplotlib.dates as real_mdates
        import matplotlib.pyplot as real_plt
        with patch.object(real_mdates, "DateFormatter") as mock_fmt:
            with patch.object(real_plt, "setp"):
                _configure_date_axis(ax, spec)
        mock_fmt.assert_called_once_with("%Y-%m")


# ---------------------------------------------------------------------------
# _shade_weekends
# ---------------------------------------------------------------------------

class TestShadeWeekends(unittest.TestCase):
    def test_weekend_date_calls_axvspan(self):
        from charts.renderer_line_area import _shade_weekends
        # 2024-01-06 is Saturday
        saturday = datetime.datetime(2024, 1, 6, 0, 0, 0)
        ax = _fake_ax()
        theme = _dark_theme()
        mock_mdates = MagicMock()
        mock_mdates.date2num.return_value = 0.0
        with patch.dict("sys.modules", {"matplotlib.dates": mock_mdates}):
            _shade_weekends(ax, [saturday], theme)
        ax.axvspan.assert_called_once()

    def test_monday_calls_axvline(self):
        from charts.renderer_line_area import _shade_weekends
        # 2024-01-08 is Monday
        monday = datetime.datetime(2024, 1, 8, 0, 0, 0)
        ax = _fake_ax()
        theme = _dark_theme()
        mock_mdates = MagicMock()
        mock_mdates.date2num.return_value = 0.0
        with patch.dict("sys.modules", {"matplotlib.dates": mock_mdates}):
            _shade_weekends(ax, [monday], theme)
        ax.axvline.assert_called_once()

    def test_non_date_value_returns_immediately(self):
        from charts.renderer_line_area import _shade_weekends
        ax = _fake_ax()
        theme = _dark_theme()
        mock_mdates = MagicMock()
        with patch.dict("sys.modules", {"matplotlib.dates": mock_mdates}):
            _shade_weekends(ax, ["not-a-date"], theme)
        ax.axvspan.assert_not_called()
        ax.axvline.assert_not_called()

    def test_duplicate_dates_shaded_once(self):
        from charts.renderer_line_area import _shade_weekends
        # Saturday duplicated
        saturday = datetime.datetime(2024, 1, 6)
        ax = _fake_ax()
        theme = _dark_theme()
        mock_mdates = MagicMock()
        mock_mdates.date2num.return_value = 0.0
        with patch.dict("sys.modules", {"matplotlib.dates": mock_mdates}):
            _shade_weekends(ax, [saturday, saturday], theme)
        # called only once despite duplicated input
        self.assertEqual(ax.axvspan.call_count, 1)

    def test_weekday_neither_span_nor_vline(self):
        from charts.renderer_line_area import _shade_weekends
        # 2024-01-09 is Tuesday
        tuesday = datetime.datetime(2024, 1, 9)
        ax = _fake_ax()
        theme = _dark_theme()
        mock_mdates = MagicMock()
        with patch.dict("sys.modules", {"matplotlib.dates": mock_mdates}):
            _shade_weekends(ax, [tuesday], theme)
        ax.axvspan.assert_not_called()
        ax.axvline.assert_not_called()


# ---------------------------------------------------------------------------
# _plot_series_smooth
# ---------------------------------------------------------------------------

class TestPlotSeriesSmooth(unittest.TestCase):
    def test_returns_true_and_calls_plot_for_valid_data(self):
        from charts.renderer_line_area import _plot_series_smooth, LineSeriesStyle
        ax = _fake_ax()
        x_values = [datetime.datetime(2024, 1, i + 1) for i in range(5)]
        y_values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _plot_series_smooth(
            ax, x_values, y_values, is_dates=True,
            style=LineSeriesStyle(color="#ff0000", linewidth=1.5, label="series"),
        )
        self.assertTrue(result)
        ax.plot.assert_called_once()

    def test_returns_false_when_fewer_than_2_finite_values(self):
        from charts.renderer_line_area import _plot_series_smooth, LineSeriesStyle
        import math
        ax = _fake_ax()
        x_values = [1.0, 2.0, 3.0]
        y_values = [1.0, math.nan, math.nan]
        result = _plot_series_smooth(
            ax, x_values, y_values, is_dates=False,
            style=LineSeriesStyle(color="#ff0000", linewidth=1.5, label="s"),
        )
        self.assertFalse(result)
        ax.plot.assert_not_called()

    def test_non_date_x_values_passed_to_plot(self):
        from charts.renderer_line_area import _plot_series_smooth, LineSeriesStyle
        ax = _fake_ax()
        x_values = [1.0, 2.0, 3.0, 4.0]
        y_values = [10.0, 20.0, 30.0, 40.0]
        result = _plot_series_smooth(
            ax, x_values, y_values, is_dates=False,
            style=LineSeriesStyle(color="#00ff00", linewidth=2.0, label="data"),
        )
        self.assertTrue(result)
        ax.plot.assert_called_once()
        call_kwargs = ax.plot.call_args
        color_used = call_kwargs.kwargs.get("color") or call_kwargs[1].get("color")
        self.assertEqual(color_used, "#00ff00")


# ---------------------------------------------------------------------------
# _render_line
# ---------------------------------------------------------------------------

class TestRenderLine(unittest.TestCase):
    def test_single_series_calls_ax_plot(self):
        from charts.renderer_line_area import _render_line
        ax = _fake_ax()
        ax.get_xticklabels.return_value = []
        s = _make_series("requests", ["2024-01-01", "2024-01-02"], [10.0, 20.0])
        spec = _make_line_spec([s])
        mock_mdates = MagicMock()
        mock_plt = MagicMock()
        mock_plt.setp = MagicMock()
        with patch.dict("sys.modules", {
            "matplotlib.dates": mock_mdates,
            "matplotlib.pyplot": mock_plt,
        }):
            _render_line(ax, spec, _dark_theme())
        ax.plot.assert_called_once()

    def test_smooth_mode_uses_smooth_plotter(self):
        from charts.renderer_line_area import _render_line
        ax = _fake_ax()
        dates = [f"2024-01-0{i+1}" for i in range(5)]
        s = _make_series("s", dates, [1.0, 2.0, 3.0, 4.0, 5.0])
        spec = _make_line_spec([s], smooth=True)
        mock_mdates = MagicMock()
        mock_plt = MagicMock()
        mock_plt.setp = MagicMock()
        with patch.dict("sys.modules", {
            "matplotlib.dates": mock_mdates,
            "matplotlib.pyplot": mock_plt,
        }):
            _render_line(ax, spec, _dark_theme())
        ax.plot.assert_called_once()

    def test_smooth_falls_back_to_regular_plot_when_too_few_points(self):
        from charts.renderer_line_area import _render_line
        ax = _fake_ax()
        # Only 1 point - smooth requires >= 3
        s = _make_series("s", ["2024-01-01"], [5.0])
        spec = _make_line_spec([s], smooth=True)
        mock_mdates = MagicMock()
        mock_plt = MagicMock()
        mock_plt.setp = MagicMock()
        with patch.dict("sys.modules", {
            "matplotlib.dates": mock_mdates,
            "matplotlib.pyplot": mock_plt,
        }):
            _render_line(ax, spec, _dark_theme())
        # Falls back to regular plot since len(x_values) < 3
        ax.plot.assert_called_once()

    def test_shade_weekends_enabled_calls_axvspan_for_saturday(self):
        from charts.renderer_line_area import _render_line
        ax = _fake_ax()
        # 2024-01-06 is a Saturday
        s = _make_series("s", ["2024-01-06"], [5.0])
        spec = _make_line_spec([s], shade_weekends=True)
        mock_mdates = MagicMock()
        mock_mdates.date2num.return_value = 0.0
        mock_plt = MagicMock()
        mock_plt.setp = MagicMock()
        with patch.dict("sys.modules", {
            "matplotlib.dates": mock_mdates,
            "matplotlib.pyplot": mock_plt,
        }):
            _render_line(ax, spec, _dark_theme())
        ax.axvspan.assert_called_once()

    def test_multiple_series_each_plotted(self):
        from charts.renderer_line_area import _render_line
        ax = _fake_ax()
        s1 = _make_series("s1", ["2024-01-01", "2024-01-02"], [1.0, 2.0])
        s2 = _make_series("s2", ["2024-01-01", "2024-01-02"], [3.0, 4.0])
        spec = _make_line_spec([s1, s2])
        mock_mdates = MagicMock()
        mock_plt = MagicMock()
        mock_plt.setp = MagicMock()
        with patch.dict("sys.modules", {
            "matplotlib.dates": mock_mdates,
            "matplotlib.pyplot": mock_plt,
        }):
            _render_line(ax, spec, _dark_theme())
        self.assertEqual(ax.plot.call_count, 2)

    def test_label_used_when_set(self):
        from charts.renderer_line_area import _render_line
        ax = _fake_ax()
        s = _make_series("s", ["2024-01-01"], label="My Series")
        spec = _make_line_spec([s])
        mock_mdates = MagicMock()
        mock_plt = MagicMock()
        mock_plt.setp = MagicMock()
        with patch.dict("sys.modules", {
            "matplotlib.dates": mock_mdates,
            "matplotlib.pyplot": mock_plt,
        }):
            _render_line(ax, spec, _dark_theme())
        call_kwargs = ax.plot.call_args
        label_used = call_kwargs.kwargs.get("label") or call_kwargs[1].get("label")
        self.assertEqual(label_used, "My Series")

    def test_numeric_x_does_not_call_configure_date_axis(self):
        from charts.renderer_line_area import _render_line
        ax = _fake_ax()
        s = _make_series("s", [1, 2, 3], [10.0, 20.0, 30.0], x_field="x")
        from charts.types.line import LineChartSpec
        spec = LineChartSpec(title="T", x_field="x", series=[s])
        with patch("charts.renderer_line_area._configure_date_axis") as mock_cda:
            _render_line(ax, spec, _dark_theme())
        mock_cda.assert_not_called()


# ---------------------------------------------------------------------------
# _render_area
# ---------------------------------------------------------------------------

class TestRenderArea(unittest.TestCase):
    def test_fill_between_called_per_series(self):
        from charts.renderer_line_area import _render_area
        ax = _fake_ax()
        s = _make_series("s", ["2024-01-01", "2024-01-02"], [10.0, 20.0])
        spec = _make_area_spec([s])
        mock_mdates = MagicMock()
        mock_plt = MagicMock()
        mock_plt.setp = MagicMock()
        with patch.dict("sys.modules", {
            "matplotlib.dates": mock_mdates,
            "matplotlib.pyplot": mock_plt,
        }):
            _render_area(ax, spec, _dark_theme())
        ax.fill_between.assert_called_once()
        ax.plot.assert_called_once()

    def test_stacked_area_uses_accumulating_baseline(self):
        from charts.renderer_line_area import _render_area
        ax = _fake_ax()
        s1 = _make_series("s1", ["2024-01-01", "2024-01-02"], [10.0, 20.0])
        s2 = _make_series("s2", ["2024-01-01", "2024-01-02"], [5.0, 5.0])
        spec = _make_area_spec([s1, s2], stacked=True)
        mock_mdates = MagicMock()
        mock_plt = MagicMock()
        mock_plt.setp = MagicMock()
        with patch.dict("sys.modules", {
            "matplotlib.dates": mock_mdates,
            "matplotlib.pyplot": mock_plt,
        }):
            _render_area(ax, spec, _dark_theme())
        self.assertEqual(ax.fill_between.call_count, 2)

    def test_shade_weekends_called_when_enabled(self):
        from charts.renderer_line_area import _render_area
        ax = _fake_ax()
        # Saturday
        s = _make_series("s", ["2024-01-06"], [5.0])
        spec = _make_area_spec([s], shade_weekends=True)
        mock_mdates = MagicMock()
        mock_mdates.date2num.return_value = 0.0
        mock_plt = MagicMock()
        mock_plt.setp = MagicMock()
        with patch.dict("sys.modules", {
            "matplotlib.dates": mock_mdates,
            "matplotlib.pyplot": mock_plt,
        }):
            _render_area(ax, spec, _dark_theme())
        ax.axvspan.assert_called_once()

    def test_date_axis_configured_for_date_x(self):
        from charts.renderer_line_area import _render_area
        ax = _fake_ax()
        s = _make_series("s", ["2024-01-01", "2024-01-02"], [1.0, 2.0])
        spec = _make_area_spec([s])
        with patch("charts.renderer_line_area._configure_date_axis") as mock_cda:
            mock_mdates = MagicMock()
            mock_plt = MagicMock()
            with patch.dict("sys.modules", {
                "matplotlib.dates": mock_mdates,
                "matplotlib.pyplot": mock_plt,
            }):
                _render_area(ax, spec, _dark_theme())
        mock_cda.assert_called_once()

    def test_non_stacked_does_not_accumulate_baseline(self):
        from charts.renderer_line_area import _render_area
        ax = _fake_ax()
        s1 = _make_series("s1", ["2024-01-01", "2024-01-02"], [10.0, 20.0])
        s2 = _make_series("s2", ["2024-01-01", "2024-01-02"], [5.0, 5.0])
        spec = _make_area_spec([s1, s2], stacked=False)
        mock_mdates = MagicMock()
        mock_plt = MagicMock()
        mock_plt.setp = MagicMock()
        with patch.dict("sys.modules", {
            "matplotlib.dates": mock_mdates,
            "matplotlib.pyplot": mock_plt,
        }):
            _render_area(ax, spec, _dark_theme())
        # Both series rendered, no stacking — fill_between called twice
        self.assertEqual(ax.fill_between.call_count, 2)


# ---------------------------------------------------------------------------
# _plot_dual_series
# ---------------------------------------------------------------------------

class TestPlotDualSeries(unittest.TestCase):
    def test_each_series_plotted_with_correct_color(self):
        from charts.renderer_line_area import _plot_dual_series, DualSeriesContext
        ax = _fake_ax()
        mock_line = MagicMock()
        ax.plot.return_value = (mock_line,)
        s1 = _make_series("s1", ["2024-01-01", "2024-01-02"], [1.0, 2.0])
        s2 = _make_series("s2", ["2024-01-01", "2024-01-02"], [3.0, 4.0])
        from charts.renderer_line_area import _parse_x_values
        x_values, is_dates = _parse_x_values([s1, s2], "ts")
        handles, labels = _plot_dual_series(
            ax, [s1, s2],
            DualSeriesContext(x_values=x_values, x_field="ts", is_dates=is_dates),
            _dark_theme(),
        )
        self.assertEqual(len(handles), 2)
        self.assertEqual(labels, ["s1", "s2"])
        self.assertEqual(ax.plot.call_count, 2)

    def test_palette_offset_shifts_color_index(self):
        from charts.renderer_line_area import _plot_dual_series, _parse_x_values, DualSeriesContext
        ax = _fake_ax()
        mock_line = MagicMock()
        ax.plot.return_value = (mock_line,)
        s = _make_series("s", ["2024-01-01"], [10.0])
        x_values, is_dates = _parse_x_values([s], "ts")
        theme = _dark_theme()
        _plot_dual_series(
            ax, [s],
            DualSeriesContext(x_values=x_values, x_field="ts", is_dates=is_dates, palette_offset=2),
            theme,
        )
        call_kwargs = ax.plot.call_args
        color_used = call_kwargs.kwargs.get("color") or call_kwargs[1].get("color")
        self.assertEqual(color_used, theme.palette[2])

    def test_custom_linestyle_forwarded(self):
        from charts.renderer_line_area import _plot_dual_series, _parse_x_values, DualSeriesContext
        ax = _fake_ax()
        mock_line = MagicMock()
        ax.plot.return_value = (mock_line,)
        s = _make_series("s", ["2024-01-01"], [5.0])
        x_values, is_dates = _parse_x_values([s], "ts")
        _plot_dual_series(
            ax, [s],
            DualSeriesContext(x_values=x_values, x_field="ts", is_dates=is_dates, linestyle="--"),
            _dark_theme(),
        )
        call_kwargs = ax.plot.call_args
        ls = call_kwargs.kwargs.get("linestyle") or call_kwargs[1].get("linestyle")
        self.assertEqual(ls, "--")

    def test_empty_series_list_returns_empty_handles(self):
        from charts.renderer_line_area import _plot_dual_series, _parse_x_values, DualSeriesContext
        ax = _fake_ax()
        s = _make_series("s", ["2024-01-01"], [1.0])
        x_values, is_dates = _parse_x_values([s], "ts")
        handles, labels = _plot_dual_series(
            ax, [],
            DualSeriesContext(x_values=x_values, x_field="ts", is_dates=is_dates),
            _dark_theme(),
        )
        self.assertEqual(handles, [])
        self.assertEqual(labels, [])
        ax.plot.assert_not_called()


# ---------------------------------------------------------------------------
# _apply_secondary_axis_style
# ---------------------------------------------------------------------------

class TestApplySecondaryAxisStyle(unittest.TestCase):
    def test_y_right_label_set_when_provided(self):
        from charts.renderer_line_area import _apply_secondary_axis_style
        ax2 = _fake_ax()
        s = _make_series("s", ["2024-01-01"])
        spec = _make_dual_spec([s], y_right_label="Rate")
        _apply_secondary_axis_style(ax2, spec, _dark_theme())
        ax2.set_ylabel.assert_called_once_with("Rate")

    def test_y_right_label_not_called_when_absent(self):
        from charts.renderer_line_area import _apply_secondary_axis_style
        ax2 = _fake_ax()
        s = _make_series("s", ["2024-01-01"])
        spec = _make_dual_spec([s])
        _apply_secondary_axis_style(ax2, spec, _dark_theme())
        ax2.set_ylabel.assert_not_called()

    def test_tick_params_and_spine_colors_set(self):
        from charts.renderer_line_area import _apply_secondary_axis_style
        ax2 = _fake_ax()
        s = _make_series("s", ["2024-01-01"])
        spec = _make_dual_spec([s])
        theme = _dark_theme()
        _apply_secondary_axis_style(ax2, spec, theme)
        ax2.tick_params.assert_called_with(colors=theme.text_color, which="both")
        for spine in ax2.spines.values():
            spine.set_edgecolor.assert_called_with(theme.grid_color)


# ---------------------------------------------------------------------------
# _render_dual
# ---------------------------------------------------------------------------

class TestRenderDual(unittest.TestCase):
    def _ax_with_twinx(self):
        ax = _fake_ax()
        ax2 = _fake_ax()
        mock_line = MagicMock()
        ax.plot.return_value = (mock_line,)
        ax2.plot.return_value = (mock_line,)
        ax.twinx.return_value = ax2
        return ax, ax2

    def test_twinx_called(self):
        from charts.renderer_line_area import _render_dual
        ax, _ = self._ax_with_twinx()
        fig = _fake_fig()
        s_left = _make_series("left", ["2024-01-01", "2024-01-02"], [1.0, 2.0], y_axis="left")
        s_right = _make_series("right", ["2024-01-01", "2024-01-02"], [3.0, 4.0], y_axis="right")
        spec = _make_dual_spec([s_left, s_right])
        mock_mdates = MagicMock()
        mock_plt = MagicMock()
        mock_plt.setp = MagicMock()
        with patch.dict("sys.modules", {
            "matplotlib.dates": mock_mdates,
            "matplotlib.pyplot": mock_plt,
        }):
            _render_dual(fig, ax, spec, _dark_theme())
        ax.twinx.assert_called_once()

    def test_legend_created_when_show_legend_and_handles(self):
        from charts.renderer_line_area import _render_dual
        ax, _ = self._ax_with_twinx()
        fig = _fake_fig()
        s = _make_series("s", ["2024-01-01"], [1.0])
        spec = _make_dual_spec([s], show_legend=True)
        mock_mdates = MagicMock()
        mock_plt = MagicMock()
        mock_plt.setp = MagicMock()
        with patch.dict("sys.modules", {
            "matplotlib.dates": mock_mdates,
            "matplotlib.pyplot": mock_plt,
        }):
            _render_dual(fig, ax, spec, _dark_theme())
        ax.legend.assert_called_once()

    def test_legend_not_created_when_show_legend_false(self):
        from charts.renderer_line_area import _render_dual
        ax, _ = self._ax_with_twinx()
        fig = _fake_fig()
        s = _make_series("s", ["2024-01-01"], [1.0])
        spec = _make_dual_spec([s], show_legend=False)
        mock_mdates = MagicMock()
        mock_plt = MagicMock()
        mock_plt.setp = MagicMock()
        with patch.dict("sys.modules", {
            "matplotlib.dates": mock_mdates,
            "matplotlib.pyplot": mock_plt,
        }):
            _render_dual(fig, ax, spec, _dark_theme())
        ax.legend.assert_not_called()

    def test_shade_weekends_triggered_for_saturday(self):
        from charts.renderer_line_area import _render_dual
        ax, _ = self._ax_with_twinx()
        fig = _fake_fig()
        s = _make_series("s", ["2024-01-06"], [5.0])  # Saturday
        spec = _make_dual_spec([s], shade_weekends=True)
        mock_mdates = MagicMock()
        mock_mdates.date2num.return_value = 0.0
        mock_plt = MagicMock()
        mock_plt.setp = MagicMock()
        with patch.dict("sys.modules", {
            "matplotlib.dates": mock_mdates,
            "matplotlib.pyplot": mock_plt,
        }):
            _render_dual(fig, ax, spec, _dark_theme())
        ax.axvspan.assert_called()

    def test_date_axis_configured_for_date_x(self):
        from charts.renderer_line_area import _render_dual
        ax, _ = self._ax_with_twinx()
        fig = _fake_fig()
        s = _make_series("s", ["2024-01-01", "2024-01-02"], [1.0, 2.0])
        spec = _make_dual_spec([s])
        with patch("charts.renderer_line_area._configure_date_axis") as mock_cda:
            mock_mdates = MagicMock()
            mock_plt = MagicMock()
            mock_plt.setp = MagicMock()
            with patch.dict("sys.modules", {
                "matplotlib.dates": mock_mdates,
                "matplotlib.pyplot": mock_plt,
            }):
                _render_dual(fig, ax, spec, _dark_theme())
        mock_cda.assert_called_once()


# ---------------------------------------------------------------------------
# _split_by_name_lists
# ---------------------------------------------------------------------------

class TestSplitByNameLists(unittest.TestCase):
    def test_unassigned_series_land_on_left(self):
        from charts.renderer_line_area import _split_by_name_lists
        s1 = _make_series("a", [])
        s2 = _make_series("b", [])
        s3 = _make_series("c", [])
        left, right = _split_by_name_lists([s1, s2, s3], {"a"}, {"b"})
        self.assertIn("a", [s.name for s in left])
        self.assertIn("c", [s.name for s in left])
        self.assertIn("b", [s.name for s in right])

    def test_exact_split(self):
        from charts.renderer_line_area import _split_by_name_lists
        s1 = _make_series("x", [])
        s2 = _make_series("y", [])
        left, right = _split_by_name_lists([s1, s2], {"x"}, {"y"})
        self.assertEqual([s.name for s in left], ["x"])
        self.assertEqual([s.name for s in right], ["y"])

    def test_empty_inputs(self):
        from charts.renderer_line_area import _split_by_name_lists
        left, right = _split_by_name_lists([], set(), set())
        self.assertEqual(left, [])
        self.assertEqual(right, [])


if __name__ == "__main__":
    unittest.main()
