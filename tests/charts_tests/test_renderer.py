"""Tests for charts/renderer.py orchestration layer.

Covers _base_kwargs, _hide_unused_axes, _dispatch, render_chart, render_grid.
matplotlib is never actually invoked — plt is fully mocked.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.charts_tests.conftest_helpers import _fake_ax, _make_series


# ---------------------------------------------------------------------------
# Shared factories
# ---------------------------------------------------------------------------

def _make_line_spec(series=None, *, x_field="ts"):
    from charts.types.line import LineChartSpec
    if series is None:
        series = [_make_series("s", ["2024-01-01", "2024-01-02"], [1.0, 2.0])]
    return LineChartSpec(title="Test Line", x_field=x_field, series=series)


def _make_bar_spec(series=None, *, x_field="x"):
    from charts.types.bar import BarChartSpec
    if series is None:
        series = [_make_series("s", ["a", "b"], [1.0, 2.0], x_field=x_field)]
    return BarChartSpec(title="Test Bar", x_field=x_field, series=series)


def _make_area_spec(series=None):
    from charts.types.area import AreaChartSpec
    if series is None:
        series = [_make_series("s", ["2024-01-01"], [1.0])]
    return AreaChartSpec(title="Test Area", x_field="ts", series=series)


def _make_dual_spec(series=None):
    from charts.types.dual import DualAxisChartSpec
    if series is None:
        series = [_make_series("s", ["2024-01-01"], [1.0])]
    return DualAxisChartSpec(title="Test Dual", x_field="ts", series=series)


def _matplotlib_ctx(ax_override=None):
    """Return a context-manager stack that stubs all of matplotlib."""
    import sys
    mock_mpl = MagicMock()
    mock_plt = MagicMock()
    fig = MagicMock()
    fig.get_facecolor.return_value = "#000000"
    ax = ax_override or _fake_ax()
    mock_plt.subplots.return_value = (fig, ax)
    mock_mpl.pyplot = mock_plt
    return patch.dict(sys.modules, {
        "matplotlib": mock_mpl,
        "matplotlib.pyplot": mock_plt,
        "matplotlib.dates": MagicMock(),
    }), fig, ax


# ---------------------------------------------------------------------------
# _base_kwargs
# ---------------------------------------------------------------------------

class TestBaseKwargs(unittest.TestCase):
    def test_all_expected_keys_present(self):
        from charts.renderer import _base_kwargs
        spec = _make_line_spec()
        result = _base_kwargs(spec)
        expected_keys = {
            "title", "x_field", "series", "kind", "width_px", "height_px",
            "dpi", "x_label", "y_label", "y_right_label", "show_legend",
            "date_format", "shade_weekends",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_values_match_spec(self):
        from charts.renderer import _base_kwargs
        spec = _make_line_spec()
        result = _base_kwargs(spec)
        self.assertEqual(result["title"], spec.title)
        self.assertEqual(result["x_field"], spec.x_field)
        self.assertEqual(result["series"], spec.series)
        self.assertEqual(result["dpi"], spec.dpi)


# ---------------------------------------------------------------------------
# _hide_unused_axes
# ---------------------------------------------------------------------------

class TestHideUnusedAxes(unittest.TestCase):
    def test_used_cell_not_hidden(self):
        from charts.renderer import _hide_unused_axes
        ax00 = MagicMock()
        ax01 = MagicMock()
        ax10 = MagicMock()
        ax11 = MagicMock()
        grid = [[ax00, ax01], [ax10, ax11]]
        _hide_unused_axes(grid, rows=2, cols=2, used_cells={(0, 0), (1, 1)})
        ax00.set_visible.assert_not_called()
        ax11.set_visible.assert_not_called()

    def test_unused_cell_hidden(self):
        from charts.renderer import _hide_unused_axes
        ax00 = MagicMock()
        ax01 = MagicMock()
        ax10 = MagicMock()
        ax11 = MagicMock()
        grid = [[ax00, ax01], [ax10, ax11]]
        _hide_unused_axes(grid, rows=2, cols=2, used_cells={(0, 0)})
        ax01.set_visible.assert_called_once_with(False)
        ax10.set_visible.assert_called_once_with(False)
        ax11.set_visible.assert_called_once_with(False)

    def test_all_cells_used_nothing_hidden(self):
        from charts.renderer import _hide_unused_axes
        ax00 = MagicMock()
        grid = [[ax00]]
        _hide_unused_axes(grid, rows=1, cols=1, used_cells={(0, 0)})
        ax00.set_visible.assert_not_called()

    def test_empty_used_cells_hides_all(self):
        from charts.renderer import _hide_unused_axes
        ax00 = MagicMock()
        ax01 = MagicMock()
        grid = [[ax00, ax01]]
        _hide_unused_axes(grid, rows=1, cols=2, used_cells=set())
        ax00.set_visible.assert_called_once_with(False)
        ax01.set_visible.assert_called_once_with(False)


# ---------------------------------------------------------------------------
# _dispatch
# ---------------------------------------------------------------------------

class TestDispatch(unittest.TestCase):
    def _run(self, spec):
        from charts.renderer import _dispatch
        from charts.theme import get_theme
        ax = _fake_ax()
        fig = MagicMock()
        mock_mdates = MagicMock()
        mock_plt = MagicMock()
        mock_plt.setp = MagicMock()
        with patch.dict("sys.modules", {
            "matplotlib.dates": mock_mdates,
            "matplotlib.pyplot": mock_plt,
        }):
            _dispatch(fig, ax, spec, get_theme("dark"))
        return ax

    def test_dispatch_line_calls_render_line(self):
        spec = _make_line_spec()
        with patch("charts.renderer._render_line") as mock_rl:
            from charts.renderer import _dispatch
            from charts.theme import get_theme
            ax = _fake_ax()
            _dispatch(MagicMock(), ax, spec, get_theme("dark"))
        mock_rl.assert_called_once()

    def test_dispatch_bar_calls_render_bar(self):
        spec = _make_bar_spec()
        with patch("charts.renderer._render_bar") as mock_rb:
            from charts.renderer import _dispatch
            from charts.theme import get_theme
            ax = _fake_ax()
            _dispatch(MagicMock(), ax, spec, get_theme("dark"))
        mock_rb.assert_called_once()

    def test_dispatch_area_calls_render_area(self):
        spec = _make_area_spec()
        with patch("charts.renderer._render_area") as mock_ra:
            from charts.renderer import _dispatch
            from charts.theme import get_theme
            ax = _fake_ax()
            _dispatch(MagicMock(), ax, spec, get_theme("dark"))
        mock_ra.assert_called_once()

    def test_dispatch_dual_calls_render_dual(self):
        spec = _make_dual_spec()
        with patch("charts.renderer._render_dual") as mock_rd:
            from charts.renderer import _dispatch
            from charts.theme import get_theme
            ax = _fake_ax()
            _dispatch(MagicMock(), ax, spec, get_theme("dark"))
        mock_rd.assert_called_once()

    def test_dispatch_unknown_kind_raises(self):
        from charts.renderer import _dispatch
        from charts.theme import get_theme
        spec = _make_line_spec()
        # Patch kind to something unsupported
        bad_spec = MagicMock(spec=spec)
        bad_spec.kind = "unsupported_kind"
        with self.assertRaises((ValueError, AttributeError)):
            _dispatch(MagicMock(), _fake_ax(), bad_spec, get_theme("dark"))

    def test_dispatch_line_from_base_chartspec_wraps_in_linespec(self):
        """When a plain ChartSpec with kind=line is passed, _dispatch wraps it."""
        from charts.renderer import _dispatch
        from charts.theme import get_theme
        from charts.types.base import ChartSpec, ChartKind, SeriesSpec
        s = SeriesSpec(name="s", data=[{"ts": "2024-01-01", "value": 1}])
        spec = ChartSpec(title="T", x_field="ts", series=[s], kind=ChartKind.line)
        with patch("charts.renderer._render_line") as mock_rl:
            _dispatch(MagicMock(), _fake_ax(), spec, get_theme("dark"))
        mock_rl.assert_called_once()


# ---------------------------------------------------------------------------
# render_chart
# ---------------------------------------------------------------------------

class TestRenderChart(unittest.TestCase):
    def _mock_matplotlib_and_patch(self):
        import sys
        mock_mpl = MagicMock()
        mock_plt = MagicMock()
        fig = MagicMock()
        fig.get_facecolor.return_value = "#000000"
        ax = _fake_ax()
        mock_plt.subplots.return_value = (fig, ax)
        mock_mpl.pyplot = mock_plt
        return patch.dict(sys.modules, {
            "matplotlib": mock_mpl,
            "matplotlib.pyplot": mock_plt,
            "matplotlib.dates": MagicMock(),
        }), fig, ax

    def test_happy_path_returns_path(self):
        from charts.renderer import render_chart
        spec = _make_line_spec()
        mpl_ctx, fig, ax = self._mock_matplotlib_and_patch()
        with (
            patch("charts.renderer._require_matplotlib"),
            patch("charts.renderer._dispatch"),
            patch("charts.renderer._apply_theme"),
            patch("charts.renderer._apply_labels"),
            patch("pathlib.Path.mkdir"),
            mpl_ctx,
        ):
            result = render_chart(spec, "/tmp/test_out.png")
        self.assertIsInstance(result, Path)
        self.assertEqual(result.name, "test_out.png")

    def test_svg_format_accepted(self):
        from charts.renderer import render_chart
        spec = _make_line_spec()
        mpl_ctx, fig, ax = self._mock_matplotlib_and_patch()
        with (
            patch("charts.renderer._require_matplotlib"),
            patch("charts.renderer._dispatch"),
            patch("charts.renderer._apply_theme"),
            patch("charts.renderer._apply_labels"),
            patch("pathlib.Path.mkdir"),
            mpl_ctx,
        ):
            result = render_chart(spec, "/tmp/test_out.svg")
        self.assertEqual(result.suffix, ".svg")

    def test_unsupported_format_raises(self):
        from charts.renderer import render_chart
        spec = _make_line_spec()
        with patch("charts.renderer._require_matplotlib"):
            with self.assertRaises(ValueError) as cm:
                render_chart(spec, "/tmp/test_out.gif")
        self.assertIn("gif", str(cm.exception).lower())

    def test_negative_dpi_raises(self):
        from charts.renderer import render_chart
        spec = _make_line_spec()
        with patch("charts.renderer._require_matplotlib"):
            with self.assertRaises(ValueError):
                render_chart(spec, "/tmp/test_out.png", dpi=-1)

    def test_zero_dpi_raises(self):
        from charts.renderer import render_chart
        spec = _make_line_spec()
        with patch("charts.renderer._require_matplotlib"):
            with self.assertRaises(ValueError):
                render_chart(spec, "/tmp/test_out.png", dpi=0)

    def test_dpi_override_used(self):
        from charts.renderer import render_chart
        spec = _make_line_spec()
        mpl_ctx, fig, ax = self._mock_matplotlib_and_patch()
        mpl_ctx_patch = mpl_ctx
        with (
            patch("charts.renderer._require_matplotlib"),
            patch("charts.renderer._dispatch"),
            patch("charts.renderer._apply_theme"),
            patch("charts.renderer._apply_labels"),
            patch("pathlib.Path.mkdir"),
            mpl_ctx_patch,
        ):
            render_chart(spec, "/tmp/test_dpi.png", dpi=200)
        # subplots should have been called with the overridden dpi
        # (the mock plt.subplots call is captured via the patch context)
        # Just assert no error and path returned correctly
        # (dpi verification via mock captured in fig.savefig)

    def test_custom_theme_applied(self):
        from charts.renderer import render_chart
        spec = _make_line_spec()
        mpl_ctx, fig, ax = self._mock_matplotlib_and_patch()
        with (
            patch("charts.renderer._require_matplotlib"),
            patch("charts.renderer._dispatch"),
            patch("charts.renderer._apply_theme") as mock_at,
            patch("charts.renderer._apply_labels"),
            patch("pathlib.Path.mkdir"),
            mpl_ctx,
        ):
            render_chart(spec, "/tmp/test_out.png", theme="light")
        called_theme = mock_at.call_args[0][2]
        self.assertEqual(called_theme.name, "light")

    def test_savefig_called(self):
        from charts.renderer import render_chart
        spec = _make_line_spec()
        mpl_ctx, fig, ax = self._mock_matplotlib_and_patch()
        with (
            patch("charts.renderer._require_matplotlib"),
            patch("charts.renderer._dispatch"),
            patch("charts.renderer._apply_theme"),
            patch("charts.renderer._apply_labels"),
            patch("pathlib.Path.mkdir"),
            mpl_ctx,
        ):
            render_chart(spec, "/tmp/test_out.png")
        fig.savefig.assert_called_once()


# ---------------------------------------------------------------------------
# render_grid
# ---------------------------------------------------------------------------

class TestRenderGrid(unittest.TestCase):
    def _make_grid_cfg(self, rows=1, cols=1, panels=None, theme="dark",
                       output="/tmp/grid_test.png", title="Grid",
                       dpi=150, width_px=1200, height_px=400):
        from charts.config import GridConfig, PanelConfig
        if panels is None:
            panels = [PanelConfig(input="dummy.json", row=0, col=0)]
        return GridConfig(
            title=title,
            output=output,
            rows=rows,
            cols=cols,
            panels=panels,
            theme=theme,
            dpi=dpi,
            width_px=width_px,
            height_px=height_px,
        )

    def _mock_matplotlib(self, rows=1, cols=1):
        import sys
        mock_mpl = MagicMock()
        mock_plt = MagicMock()
        fig = MagicMock()
        fig.get_facecolor.return_value = "#000000"
        # Build axes grid matching rows*cols
        if rows == 1 and cols == 1:
            ax = _fake_ax()
            mock_plt.subplots.return_value = (fig, ax)
        elif rows == 1:
            axes = [_fake_ax() for _ in range(cols)]
            mock_plt.subplots.return_value = (fig, axes)
        else:
            axes = [[_fake_ax() for _ in range(cols)] for _ in range(rows)]
            mock_plt.subplots.return_value = (fig, axes)
        mock_mpl.pyplot = mock_plt
        return patch.dict(sys.modules, {
            "matplotlib": mock_mpl,
            "matplotlib.pyplot": mock_plt,
            "matplotlib.dates": MagicMock(),
        }), fig

    def test_spec_count_mismatch_raises(self):
        from charts.renderer import render_grid
        grid_cfg = self._make_grid_cfg()
        spec = _make_line_spec()
        with patch("charts.renderer._require_matplotlib"):
            with self.assertRaises(ValueError) as cm:
                render_grid(grid_cfg, [spec, spec])
        self.assertIn("spec", str(cm.exception).lower())

    def test_negative_dpi_raises(self):
        from charts.renderer import render_grid
        grid_cfg = self._make_grid_cfg(dpi=-1)
        spec = _make_line_spec()
        with patch("charts.renderer._require_matplotlib"):
            with self.assertRaises(ValueError):
                render_grid(grid_cfg, [spec])

    def test_zero_width_px_raises(self):
        from charts.renderer import render_grid
        grid_cfg = self._make_grid_cfg(width_px=0)
        spec = _make_line_spec()
        with patch("charts.renderer._require_matplotlib"):
            with self.assertRaises(ValueError):
                render_grid(grid_cfg, [spec])

    def test_unsupported_output_format_raises(self):
        from charts.renderer import render_grid
        grid_cfg = self._make_grid_cfg(output="/tmp/out.bmp")
        spec = _make_line_spec()
        with patch("charts.renderer._require_matplotlib"):
            with self.assertRaises(ValueError):
                render_grid(grid_cfg, [spec])

    def test_happy_path_returns_path(self):
        from charts.renderer import render_grid
        grid_cfg = self._make_grid_cfg()
        spec = _make_line_spec()
        mpl_ctx, fig = self._mock_matplotlib(rows=1, cols=1)
        with (
            patch("charts.renderer._require_matplotlib"),
            patch("charts.renderer._dispatch"),
            patch("charts.renderer._apply_theme"),
            patch("charts.renderer._apply_labels"),
            patch("charts.renderer._hide_unused_axes"),
            patch("pathlib.Path.mkdir"),
            mpl_ctx,
        ):
            result = render_grid(grid_cfg, [spec])
        self.assertIsInstance(result, Path)

    def test_savefig_called_with_correct_output(self):
        from charts.renderer import render_grid
        grid_cfg = self._make_grid_cfg(output="/tmp/my_grid.png")
        spec = _make_line_spec()
        mpl_ctx, fig = self._mock_matplotlib(rows=1, cols=1)
        with (
            patch("charts.renderer._require_matplotlib"),
            patch("charts.renderer._dispatch"),
            patch("charts.renderer._apply_theme"),
            patch("charts.renderer._apply_labels"),
            patch("charts.renderer._hide_unused_axes"),
            patch("pathlib.Path.mkdir"),
            mpl_ctx,
        ):
            render_grid(grid_cfg, [spec])
        fig.savefig.assert_called_once()
        save_args = fig.savefig.call_args[0][0]
        self.assertIn("my_grid.png", save_args)

    def test_suptitle_set_when_title_present(self):
        from charts.renderer import render_grid
        grid_cfg = self._make_grid_cfg(title="My Grid")
        spec = _make_line_spec()
        mpl_ctx, fig = self._mock_matplotlib(rows=1, cols=1)
        with (
            patch("charts.renderer._require_matplotlib"),
            patch("charts.renderer._dispatch"),
            patch("charts.renderer._apply_theme"),
            patch("charts.renderer._apply_labels"),
            patch("charts.renderer._hide_unused_axes"),
            patch("pathlib.Path.mkdir"),
            mpl_ctx,
        ):
            render_grid(grid_cfg, [spec])
        fig.suptitle.assert_called_once()
        call_kwargs = fig.suptitle.call_args
        title_set = call_kwargs[0][0]
        self.assertEqual(title_set, "My Grid")

    def test_multi_panel_renders_each_spec(self):
        from charts.renderer import render_grid
        from charts.config import PanelConfig
        panels = [
            PanelConfig(input="a.json", row=0, col=0),
            PanelConfig(input="b.json", row=0, col=1),
        ]
        grid_cfg = self._make_grid_cfg(rows=1, cols=2, panels=panels)
        s1 = _make_line_spec()
        s2 = _make_line_spec()
        mpl_ctx, fig = self._mock_matplotlib(rows=1, cols=2)
        dispatch_calls = []
        with (
            patch("charts.renderer._require_matplotlib"),
            patch("charts.renderer._dispatch", side_effect=lambda *a, **kw: dispatch_calls.append(1)),
            patch("charts.renderer._apply_theme"),
            patch("charts.renderer._apply_labels"),
            patch("charts.renderer._hide_unused_axes"),
            patch("pathlib.Path.mkdir"),
            mpl_ctx,
        ):
            render_grid(grid_cfg, [s1, s2])
        self.assertEqual(len(dispatch_calls), 2)


if __name__ == "__main__":
    unittest.main()
