"""Tests for pure/near-pure functions in charts/renderer.py.

No matplotlib needed: functions under test are called directly or
matplotlib axes are replaced with MagicMock objects.
"""

from __future__ import annotations

import datetime
import unittest
from unittest.mock import MagicMock, patch


class TestParseIsoToDatetime(unittest.TestCase):
    def test_timezone_aware_iso_returns_naive_utc(self):
        from charts.renderer import _parse_iso_to_datetime

        result = _parse_iso_to_datetime("2024-01-15T10:00:00+00:00")
        self.assertIsInstance(result, datetime.datetime)
        self.assertIsNone(result.tzinfo)
        self.assertEqual(result, datetime.datetime(2024, 1, 15, 10, 0, 0))

    def test_date_only_string_returns_midnight(self):
        from charts.renderer import _parse_iso_to_datetime

        result = _parse_iso_to_datetime("2024-01-15")
        self.assertIsInstance(result, datetime.datetime)
        self.assertEqual(result, datetime.datetime(2024, 1, 15, 0, 0, 0))

    def test_non_date_string_raises_value_error(self):
        from charts.renderer import _parse_iso_to_datetime

        with self.assertRaises(ValueError):
            _parse_iso_to_datetime("not-a-date")


class TestParseXValues(unittest.TestCase):
    def _make_series(self, x_field, x_values, values=None):
        """Build a minimal list[SeriesSpec] for testing."""
        from charts.types.base import SeriesSpec

        if values is None:
            values = [1.0] * len(x_values)
        data = [{x_field: x, "value": v} for x, v in zip(x_values, values)]
        return [SeriesSpec(name="s", data=data)]

    def test_all_datetime_series_returns_datetimes(self):
        from charts.renderer import _parse_x_values

        series = self._make_series("ts", ["2024-01-15", "2024-01-16"])
        import numpy as np  # needed by the function
        with patch.dict("sys.modules", {"numpy": np}):
            result, is_dates = _parse_x_values(series, "ts")
        self.assertTrue(is_dates)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], datetime.datetime)

    def test_all_numeric_series_returns_floats(self):
        from charts.renderer import _parse_x_values

        series = self._make_series("x", ["1", "2", "3"])
        import numpy as np
        with patch.dict("sys.modules", {"numpy": np}):
            result, is_dates = _parse_x_values(series, "x")
        self.assertFalse(is_dates)
        self.assertEqual(len(result), 3)
        self.assertIsInstance(result[0], float)

    def test_string_series_returns_original_strings(self):
        from charts.renderer import _parse_x_values

        series = self._make_series("x", ["alpha", "beta", "gamma"])
        import numpy as np
        with patch.dict("sys.modules", {"numpy": np}):
            result, is_dates = _parse_x_values(series, "x")
        self.assertFalse(is_dates)
        self.assertEqual(set(result), {"alpha", "beta", "gamma"})

    def test_empty_series_returns_empty_list(self):
        from charts.renderer import _parse_x_values
        from charts.types.base import SeriesSpec

        series = [SeriesSpec(name="s", data=[])]
        import numpy as np
        with patch.dict("sys.modules", {"numpy": np}):
            result, is_dates = _parse_x_values(series, "ts")
        self.assertEqual(result, [])
        self.assertFalse(is_dates)


class TestNormalizeAxesGrid(unittest.TestCase):
    """_normalize_axes_grid with mock matplotlib axes objects."""

    def test_single_cell_scalar_ax_wrapped_in_2d_list(self):
        from charts.renderer import _normalize_axes_grid

        mock_ax = MagicMock()
        import numpy as np
        with patch.dict("sys.modules", {"numpy": np}):
            result = _normalize_axes_grid(mock_ax, rows=1, cols=1)
        self.assertEqual(result, [[mock_ax]])

    def test_one_row_multiple_cols_returns_single_row_list(self):
        from charts.renderer import _normalize_axes_grid

        ax1, ax2, ax3 = MagicMock(), MagicMock(), MagicMock()
        import numpy as np
        with patch.dict("sys.modules", {"numpy": np}):
            result = _normalize_axes_grid([ax1, ax2, ax3], rows=1, cols=3)
        self.assertEqual(result, [[ax1, ax2, ax3]])

    def test_multiple_rows_one_col_wraps_each_ax_in_sublist(self):
        from charts.renderer import _normalize_axes_grid

        ax1, ax2, ax3 = MagicMock(), MagicMock(), MagicMock()
        import numpy as np
        with patch.dict("sys.modules", {"numpy": np}):
            result = _normalize_axes_grid([ax1, ax2, ax3], rows=3, cols=1)
        self.assertEqual(result, [[ax1], [ax2], [ax3]])

    def test_2x2_grid_returns_grid_as_is(self):
        from charts.renderer import _normalize_axes_grid

        ax1, ax2, ax3, ax4 = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        grid = [[ax1, ax2], [ax3, ax4]]
        import numpy as np
        with patch.dict("sys.modules", {"numpy": np}):
            result = _normalize_axes_grid(grid, rows=2, cols=2)
        self.assertEqual(result, [[ax1, ax2], [ax3, ax4]])


class TestSplitDualSeries(unittest.TestCase):
    def _make_spec(self, series, left_names=None, right_names=None):
        from charts.types.dual import DualAxisChartSpec

        kwargs = {
            "title": "T",
            "x_field": "ts",
            "series": series,
        }
        if left_names is not None:
            kwargs["left_series_names"] = left_names
        if right_names is not None:
            kwargs["right_series_names"] = right_names
        return DualAxisChartSpec(**kwargs)

    def _make_series(self, name, y_axis="left"):
        from charts.types.base import SeriesSpec

        return SeriesSpec(name=name, data=[{"ts": "2024-01-01", "value": 1}], y_axis=y_axis)

    def test_split_by_left_right_name_lists(self):
        from charts.renderer import _split_dual_series

        s1 = self._make_series("requests")
        s2 = self._make_series("errors")
        spec = self._make_spec([s1, s2], left_names=["requests"], right_names=["errors"])
        left, right = _split_dual_series(spec)
        self.assertEqual([s.name for s in left], ["requests"])
        self.assertEqual([s.name for s in right], ["errors"])

    def test_split_by_y_axis_attribute(self):
        from charts.renderer import _split_dual_series

        s_left = self._make_series("requests", y_axis="left")
        s_right = self._make_series("errors", y_axis="right")
        spec = self._make_spec([s_left, s_right])
        left, right = _split_dual_series(spec)
        self.assertEqual([s.name for s in left], ["requests"])
        self.assertEqual([s.name for s in right], ["errors"])

    def test_all_left_when_no_right_axis(self):
        from charts.renderer import _split_dual_series

        s1 = self._make_series("a")
        s2 = self._make_series("b")
        spec = self._make_spec([s1, s2])
        left, right = _split_dual_series(spec)
        self.assertEqual(len(left), 2)
        self.assertEqual(len(right), 0)

    def test_name_list_takes_precedence_over_y_axis(self):
        """When left_series_names is set, y_axis on SeriesSpec is ignored."""
        from charts.renderer import _split_dual_series

        # Series has y_axis='right' but left_series_names overrides it
        s1 = self._make_series("requests", y_axis="right")
        s2 = self._make_series("errors")
        spec = self._make_spec([s1, s2], left_names=["requests"], right_names=[])
        left, _ = _split_dual_series(spec)
        # requests lands on left because of name list; errors has no assignment → also left
        left_names = [s.name for s in left]
        self.assertIn("requests", left_names)


if __name__ == "__main__":
    unittest.main()
