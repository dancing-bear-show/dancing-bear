"""Tests for charts/renderer_bar.py.

All numpy and matplotlib calls use real numpy (installed) but intercept
ax.bar / ax.barh / ax.set_xticks / etc. via MagicMock objects so no
actual plot is produced.
"""

from __future__ import annotations

import datetime
import unittest
from unittest.mock import patch

from tests.charts_tests.conftest_helpers import _fake_ax, _make_series


# ---------------------------------------------------------------------------
# Shared factories
# ---------------------------------------------------------------------------

def _make_bar_spec(series, *, stacked=False, orientation="vertical",
                   bar_width=0.8, date_format=None, x_field="ts"):
    from charts.types.bar import BarChartSpec
    kwargs: dict = dict(
        title="Test Bar",
        x_field=x_field,
        series=series,
        stacked=stacked,
        orientation=orientation,
        bar_width=bar_width,
    )
    if date_format is not None:
        kwargs["date_format"] = date_format
    return BarChartSpec(**kwargs)


def _dark_theme():
    from charts.theme import get_theme
    return get_theme("dark")


# ---------------------------------------------------------------------------
# _x_key
# ---------------------------------------------------------------------------

class TestXKey(unittest.TestCase):
    def test_datetime_returns_isoformat(self):
        from charts.renderer_bar import _x_key
        dt = datetime.datetime(2024, 1, 15, 10, 30, 0)
        result = _x_key(dt)
        self.assertEqual(result, dt.isoformat())

    def test_date_returns_datetime_isoformat(self):
        from charts.renderer_bar import _x_key
        d = datetime.date(2024, 1, 15)
        result = _x_key(d)
        self.assertIn("2024-01-15", result)

    def test_iso_string_parsed_to_datetime_iso(self):
        from charts.renderer_bar import _x_key
        result = _x_key("2024-01-15")
        self.assertIn("2024-01-15", result)

    def test_integer_float_returns_int_string(self):
        from charts.renderer_bar import _x_key
        # 5.0 → int representation
        result = _x_key(5.0)
        self.assertEqual(result, "5")

    def test_non_integer_float_returns_float_string(self):
        from charts.renderer_bar import _x_key
        result = _x_key(3.14)
        self.assertEqual(result, "3.14")

    def test_plain_string_returned_as_is(self):
        from charts.renderer_bar import _x_key
        result = _x_key("category_a")
        self.assertEqual(result, "category_a")

    def test_none_falls_through_to_str(self):
        from charts.renderer_bar import _x_key
        result = _x_key(None)
        self.assertEqual(result, "None")


# ---------------------------------------------------------------------------
# _render_stacked_bars
# ---------------------------------------------------------------------------

class TestRenderStackedBars(unittest.TestCase):
    def _x_indices(self, n):
        import numpy as np
        return np.arange(n, dtype=float)

    def test_happy_path_vertical_bar_called(self):
        from charts.renderer_bar import _render_stacked_bars
        ax = _fake_ax()
        s1 = _make_series("s1", ["a", "b"], [1.0, 2.0], x_field="x")
        s2 = _make_series("s2", ["a", "b"], [3.0, 4.0], x_field="x")
        spec = _make_bar_spec([s1, s2], stacked=True, x_field="x")
        x_values = ["a", "b"]
        x_indices = self._x_indices(2)
        _render_stacked_bars(ax, spec, _dark_theme(), x_values, x_indices)
        self.assertEqual(ax.bar.call_count, 2)
        ax.barh.assert_not_called()

    def test_happy_path_horizontal_barh_called(self):
        from charts.renderer_bar import _render_stacked_bars
        ax = _fake_ax()
        s1 = _make_series("s1", ["a", "b"], [1.0, 2.0], x_field="x")
        s2 = _make_series("s2", ["a", "b"], [3.0, 4.0], x_field="x")
        spec = _make_bar_spec([s1, s2], stacked=True, orientation="horizontal", x_field="x")
        x_values = ["a", "b"]
        x_indices = self._x_indices(2)
        _render_stacked_bars(ax, spec, _dark_theme(), x_values, x_indices)
        self.assertEqual(ax.barh.call_count, 2)
        ax.bar.assert_not_called()

    def test_mismatched_x_values_raises(self):
        from charts.renderer_bar import _render_stacked_bars
        ax = _fake_ax()
        # s1 has "a","b" but s2 has "a","c" — mismatched
        s1 = _make_series("s1", ["a", "b"], [1.0, 2.0], x_field="x")
        s2 = _make_series("s2", ["a", "c"], [3.0, 4.0], x_field="x")
        spec = _make_bar_spec([s1, s2], stacked=True, x_field="x")
        x_values = ["a", "b"]
        x_indices = self._x_indices(2)
        with self.assertRaises(ValueError) as cm:
            _render_stacked_bars(ax, spec, _dark_theme(), x_values, x_indices)
        self.assertIn("stacked bars require identical x-values", str(cm.exception))

    def test_baseline_accumulates_across_series(self):
        """Two bar() calls are made (one per series) when stacking."""
        from charts.renderer_bar import _render_stacked_bars
        ax = _fake_ax()
        s1 = _make_series("s1", ["a"], [5.0], x_field="x")
        s2 = _make_series("s2", ["a"], [3.0], x_field="x")
        spec = _make_bar_spec([s1, s2], stacked=True, x_field="x")
        x_values = ["a"]
        x_indices = self._x_indices(1)
        _render_stacked_bars(ax, spec, _dark_theme(), x_values, x_indices)
        # Two bar calls should have been made (one per series in the stack)
        self.assertEqual(ax.bar.call_count, 2)
        # The second call receives a `bottom` kwarg (stacking requires it)
        second_call = ax.bar.call_args_list[1]
        self.assertIn("bottom", second_call.kwargs)

    def test_single_series_one_bar_call(self):
        from charts.renderer_bar import _render_stacked_bars
        ax = _fake_ax()
        s1 = _make_series("s1", ["a", "b"], [1.0, 2.0], x_field="x")
        spec = _make_bar_spec([s1], stacked=True, x_field="x")
        x_values = ["a", "b"]
        x_indices = self._x_indices(2)
        _render_stacked_bars(ax, spec, _dark_theme(), x_values, x_indices)
        self.assertEqual(ax.bar.call_count, 1)


# ---------------------------------------------------------------------------
# _render_grouped_bars
# ---------------------------------------------------------------------------

class TestRenderGroupedBars(unittest.TestCase):
    def _x_indices(self, n):
        import numpy as np
        return np.arange(n, dtype=float)

    def test_single_series_calls_bar_once(self):
        from charts.renderer_bar import _render_grouped_bars
        ax = _fake_ax()
        s = _make_series("s", ["a", "b"], [1.0, 2.0], x_field="x")
        spec = _make_bar_spec([s], x_field="x")
        x_values = ["a", "b"]
        x_indices = self._x_indices(2)
        _render_grouped_bars(ax, spec, _dark_theme(), x_values, x_indices)
        ax.bar.assert_called_once()

    def test_two_series_calls_bar_twice(self):
        from charts.renderer_bar import _render_grouped_bars
        ax = _fake_ax()
        s1 = _make_series("s1", ["a", "b"], [1.0, 2.0], x_field="x")
        s2 = _make_series("s2", ["a", "b"], [3.0, 4.0], x_field="x")
        spec = _make_bar_spec([s1, s2], x_field="x")
        x_values = ["a", "b"]
        x_indices = self._x_indices(2)
        _render_grouped_bars(ax, spec, _dark_theme(), x_values, x_indices)
        self.assertEqual(ax.bar.call_count, 2)

    def test_horizontal_orientation_calls_barh(self):
        from charts.renderer_bar import _render_grouped_bars
        ax = _fake_ax()
        s = _make_series("s", ["a", "b"], [1.0, 2.0], x_field="x")
        spec = _make_bar_spec([s], orientation="horizontal", x_field="x")
        x_values = ["a", "b"]
        x_indices = self._x_indices(2)
        _render_grouped_bars(ax, spec, _dark_theme(), x_values, x_indices)
        ax.barh.assert_called_once()
        ax.bar.assert_not_called()

    def test_custom_label_on_series_forwarded(self):
        from charts.renderer_bar import _render_grouped_bars
        ax = _fake_ax()
        s = _make_series("s", ["a"], [1.0], label="Custom Label", x_field="x")
        spec = _make_bar_spec([s], x_field="x")
        x_values = ["a"]
        x_indices = self._x_indices(1)
        _render_grouped_bars(ax, spec, _dark_theme(), x_values, x_indices)
        call_kwargs = ax.bar.call_args
        label_used = call_kwargs.kwargs.get("label") or call_kwargs[1].get("label")
        self.assertEqual(label_used, "Custom Label")


# ---------------------------------------------------------------------------
# _render_bar (integration: calls _render_grouped_bars or _render_stacked_bars)
# ---------------------------------------------------------------------------

class TestRenderBar(unittest.TestCase):
    def test_grouped_vertical_sets_xticks(self):
        from charts.renderer_bar import _render_bar
        ax = _fake_ax()
        s = _make_series("s", ["a", "b", "c"], [1.0, 2.0, 3.0], x_field="x")
        spec = _make_bar_spec([s], x_field="x")
        _render_bar(ax, spec, _dark_theme())
        ax.set_xticks.assert_called_once()
        ax.set_xticklabels.assert_called_once()

    def test_grouped_horizontal_sets_yticks(self):
        from charts.renderer_bar import _render_bar
        ax = _fake_ax()
        s = _make_series("s", ["a", "b"], [1.0, 2.0], x_field="x")
        spec = _make_bar_spec([s], orientation="horizontal", x_field="x")
        _render_bar(ax, spec, _dark_theme())
        ax.set_yticks.assert_called_once()
        ax.set_yticklabels.assert_called_once()

    def test_stacked_dispatches_to_stacked_renderer(self):
        from charts.renderer_bar import _render_bar
        ax = _fake_ax()
        s1 = _make_series("s1", ["a", "b"], [1.0, 2.0], x_field="x")
        s2 = _make_series("s2", ["a", "b"], [3.0, 4.0], x_field="x")
        spec = _make_bar_spec([s1, s2], stacked=True, x_field="x")
        with patch("charts.renderer_bar._render_stacked_bars") as mock_stacked:
            _render_bar(ax, spec, _dark_theme())
        mock_stacked.assert_called_once()

    def test_grouped_dispatches_to_grouped_renderer(self):
        from charts.renderer_bar import _render_bar
        ax = _fake_ax()
        s = _make_series("s", ["a", "b"], [1.0, 2.0], x_field="x")
        spec = _make_bar_spec([s], stacked=False, x_field="x")
        with patch("charts.renderer_bar._render_grouped_bars") as mock_grouped:
            _render_bar(ax, spec, _dark_theme())
        mock_grouped.assert_called_once()

    def test_date_x_values_formatted_as_labels(self):
        from charts.renderer_bar import _render_bar
        ax = _fake_ax()
        # Use date strings so x_values are parsed as datetimes
        s = _make_series("s", ["2024-01-01", "2024-01-02"], [10.0, 20.0])
        spec = _make_bar_spec([s], date_format="%b %d")
        _render_bar(ax, spec, _dark_theme())
        # set_xticklabels should have been called with formatted date strings
        ax.set_xticklabels.assert_called_once()
        call_args = ax.set_xticklabels.call_args
        labels_used = call_args[0][0]
        # Both labels should be date-formatted strings matching the exact format
        self.assertEqual(labels_used, ["Jan 01", "Jan 02"])

    def test_string_x_values_use_x_key_as_labels(self):
        from charts.renderer_bar import _render_bar
        ax = _fake_ax()
        s = _make_series("s", ["alpha", "beta"], [1.0, 2.0], x_field="x")
        spec = _make_bar_spec([s], x_field="x")
        _render_bar(ax, spec, _dark_theme())
        ax.set_xticklabels.assert_called_once()
        call_args = ax.set_xticklabels.call_args
        labels_used = call_args[0][0]
        self.assertIn("alpha", labels_used)
        self.assertIn("beta", labels_used)

    def test_many_x_values_step_applied(self):
        """With 40+ x-values the step should reduce tick count."""
        from charts.renderer_bar import _render_bar
        ax = _fake_ax()
        # 40 x-values → step = max(1, 40 // 20) = 2
        x_values = [f"cat{i}" for i in range(40)]
        y_values = [float(i) for i in range(40)]
        s = _make_series("s", x_values, y_values, x_field="x")
        spec = _make_bar_spec([s], x_field="x")
        _render_bar(ax, spec, _dark_theme())
        set_xticks_call = ax.set_xticks.call_args
        ticks_set = set_xticks_call[0][0]
        # With step=2, should have 20 ticks from 40 values
        self.assertEqual(len(ticks_set), 20)


# ---------------------------------------------------------------------------
# _render_bar — error path (stacked with mismatched x)
# ---------------------------------------------------------------------------

class TestRenderBarErrors(unittest.TestCase):
    def test_stacked_with_mismatched_x_raises(self):
        from charts.renderer_bar import _render_bar
        ax = _fake_ax()
        s1 = _make_series("s1", ["a", "b"], [1.0, 2.0], x_field="x")
        s2 = _make_series("s2", ["a", "c"], [3.0, 4.0], x_field="x")
        spec = _make_bar_spec([s1, s2], stacked=True, x_field="x")
        with self.assertRaises(ValueError):
            _render_bar(ax, spec, _dark_theme())


if __name__ == "__main__":
    unittest.main()
