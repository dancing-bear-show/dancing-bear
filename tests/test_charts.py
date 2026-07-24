"""Tests for charts/ domain — ChartSpec, SeriesSpec, reshape, config, theme.

No matplotlib needed: renderer is mocked via unittest.mock.patch.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch


class TestSeriesSpec(unittest.TestCase):
    def test_basic_construction(self):
        from charts.types.base import SeriesSpec
        s = SeriesSpec(name="requests", data=[{"ts": "2024-01-01", "value": 42}])
        self.assertEqual(s.name, "requests")
        self.assertEqual(len(s.data), 1)
        self.assertIsNone(s.color)
        self.assertIsNone(s.label)
        self.assertEqual(s.y_axis, "left")

    def test_optional_fields(self):
        from charts.types.base import SeriesSpec
        s = SeriesSpec(
            name="errors",
            data=[],
            color="#ff0000",
            label="Error rate",
            y_axis="right",
        )
        self.assertEqual(s.color, "#ff0000")
        self.assertEqual(s.label, "Error rate")
        self.assertEqual(s.y_axis, "right")

    def test_frozen(self):
        from charts.types.base import SeriesSpec
        s = SeriesSpec(name="x", data=[])
        with self.assertRaises((AttributeError, TypeError)):
            s.name = "y"  # type: ignore[misc]


class TestChartSpec(unittest.TestCase):
    def _make_series(self):
        from charts.types.base import SeriesSpec
        return [SeriesSpec(name="s1", data=[{"ts": "2024-01-01", "value": 1}])]

    def test_basic_construction(self):
        from charts.types.base import ChartSpec
        spec = ChartSpec(title="My Chart", x_field="ts", series=self._make_series())
        self.assertEqual(spec.title, "My Chart")
        self.assertEqual(spec.x_field, "ts")
        self.assertEqual(spec.width_px, 1200)
        self.assertEqual(spec.height_px, 400)
        self.assertEqual(spec.dpi, 150)

    def test_empty_title_raises(self):
        from charts.types.base import ChartSpec
        with self.assertRaises(ValueError):
            ChartSpec(title="", x_field="ts", series=self._make_series())

    def test_empty_x_field_raises(self):
        from charts.types.base import ChartSpec
        with self.assertRaises(ValueError):
            ChartSpec(title="T", x_field="", series=self._make_series())

    def test_empty_series_raises(self):
        from charts.types.base import ChartSpec
        with self.assertRaises(ValueError):
            ChartSpec(title="T", x_field="ts", series=[])

    def test_frozen(self):
        from charts.types.base import ChartSpec
        spec = ChartSpec(title="T", x_field="ts", series=self._make_series())
        with self.assertRaises((AttributeError, TypeError)):
            spec.title = "X"  # type: ignore[misc]


class TestChartKind(unittest.TestCase):
    def test_kind_values(self):
        from charts.types.base import ChartKind
        self.assertEqual(ChartKind.line.value, "line")
        self.assertEqual(ChartKind.bar.value, "bar")
        self.assertEqual(ChartKind.area.value, "area")
        self.assertEqual(ChartKind.dual.value, "dual")

    def test_kind_is_str_enum(self):
        from charts.types.base import ChartKind
        self.assertEqual(ChartKind.line.value, "line")


class TestLineChartSpec(unittest.TestCase):
    def _make_series(self):
        from charts.types.base import SeriesSpec
        return [SeriesSpec(name="s", data=[{"x": 1, "value": 2}])]

    def test_default_kind(self):
        from charts.types.line import LineChartSpec
        from charts.types.base import ChartKind
        spec = LineChartSpec(title="T", x_field="x", series=self._make_series())
        self.assertEqual(spec.kind, ChartKind.line)

    def test_line_specific_fields(self):
        from charts.types.line import LineChartSpec
        spec = LineChartSpec(
            title="T", x_field="x", series=self._make_series(),
            line_width=3.0, marker="o", smooth=True,
        )
        self.assertEqual(spec.line_width, 3.0)
        self.assertEqual(spec.marker, "o")
        self.assertTrue(spec.smooth)


class TestBarChartSpec(unittest.TestCase):
    def _make_series(self):
        from charts.types.base import SeriesSpec
        return [SeriesSpec(name="s", data=[{"x": "a", "value": 1}])]

    def test_default_kind(self):
        from charts.types.bar import BarChartSpec
        from charts.types.base import ChartKind
        spec = BarChartSpec(title="T", x_field="x", series=self._make_series())
        self.assertEqual(spec.kind, ChartKind.bar)
        self.assertEqual(spec.orientation, "vertical")
        self.assertFalse(spec.stacked)
        self.assertEqual(spec.bar_width, 0.8)


class TestAreaChartSpec(unittest.TestCase):
    def _make_series(self):
        from charts.types.base import SeriesSpec
        return [SeriesSpec(name="s", data=[{"x": 1, "value": 2}])]

    def test_default_kind(self):
        from charts.types.area import AreaChartSpec
        from charts.types.base import ChartKind
        spec = AreaChartSpec(title="T", x_field="x", series=self._make_series())
        self.assertEqual(spec.kind, ChartKind.area)
        self.assertEqual(spec.alpha, 0.4)
        self.assertFalse(spec.stacked)


class TestDualAxisChartSpec(unittest.TestCase):
    def _make_series(self):
        from charts.types.base import SeriesSpec
        return [SeriesSpec(name="s", data=[{"x": 1, "value": 2}])]

    def test_default_kind(self):
        from charts.types.dual import DualAxisChartSpec
        from charts.types.base import ChartKind
        spec = DualAxisChartSpec(title="T", x_field="x", series=self._make_series())
        self.assertEqual(spec.kind, ChartKind.dual)
        self.assertEqual(spec.left_series_names, [])
        self.assertEqual(spec.right_series_names, [])


class TestJsonToSpec(unittest.TestCase):
    def _raw(self, **kwargs):
        base = {
            "title": "Test",
            "x_field": "ts",
            "series": [
                {"name": "requests", "data": [{"ts": "2024-01-01", "value": 10}]}
            ],
        }
        base.update(kwargs)
        return base

    def test_basic_line_spec(self):
        from charts.reshape import json_to_spec
        from charts.types.base import ChartKind
        spec = json_to_spec(self._raw())
        self.assertEqual(spec.title, "Test")
        self.assertEqual(spec.x_field, "ts")
        self.assertEqual(spec.kind, ChartKind.line)

    def test_explicit_kind_bar(self):
        from charts.reshape import json_to_spec
        from charts.types.base import ChartKind
        spec = json_to_spec(self._raw(kind="bar"))
        self.assertEqual(spec.kind, ChartKind.bar)

    def test_missing_title_raises(self):
        from charts.reshape import json_to_spec
        raw = {"x_field": "ts", "series": [{"name": "s", "data": []}]}
        with self.assertRaises(ValueError):
            json_to_spec(raw)

    def test_missing_x_field_raises(self):
        from charts.reshape import json_to_spec
        raw = {"title": "T", "series": [{"name": "s", "data": []}]}
        with self.assertRaises(ValueError):
            json_to_spec(raw)

    def test_missing_series_raises(self):
        from charts.reshape import json_to_spec
        raw = {"title": "T", "x_field": "ts"}
        with self.assertRaises(ValueError):
            json_to_spec(raw)

    def test_series_data_missing_value_raises(self):
        from charts.reshape import json_to_spec
        raw = {
            "title": "T", "x_field": "ts",
            "series": [{"name": "s", "data": [{"ts": "2024-01-01"}]}],
        }
        with self.assertRaises(ValueError):
            json_to_spec(raw)

    def test_series_data_non_numeric_value_raises(self):
        from charts.reshape import json_to_spec
        raw = {
            "title": "T", "x_field": "ts",
            "series": [{"name": "s", "data": [{"ts": "2024-01-01", "value": "not_a_number"}]}],
        }
        with self.assertRaises(ValueError):
            json_to_spec(raw)

    def test_unknown_kind_raises(self):
        from charts.reshape import json_to_spec
        with self.assertRaises(ValueError):
            json_to_spec(self._raw(kind="unknown"))

    def test_type_alias_for_kind(self):
        from charts.reshape import json_to_spec
        from charts.types.base import ChartKind
        spec = json_to_spec(self._raw(type="area"))
        self.assertEqual(spec.kind, ChartKind.area)

    def test_optional_fields_propagated(self):
        from charts.reshape import json_to_spec
        spec = json_to_spec(self._raw(x_label="Date", y_label="Count", show_legend=False))
        self.assertEqual(spec.x_label, "Date")
        self.assertEqual(spec.y_label, "Count")
        self.assertFalse(spec.show_legend)

    def test_bar_stacked_field(self):
        from charts.reshape import json_to_spec
        from charts.types.bar import BarChartSpec
        spec = json_to_spec(self._raw(kind="bar", stacked=True))
        self.assertIsInstance(spec, BarChartSpec)
        self.assertTrue(spec.stacked)

    def test_bar_orientation_horizontal(self):
        from charts.reshape import json_to_spec
        from charts.types.bar import BarChartSpec
        spec = json_to_spec(self._raw(kind="bar", orientation="horizontal"))
        self.assertIsInstance(spec, BarChartSpec)
        self.assertEqual(spec.orientation, "horizontal")

    def test_area_alpha_field(self):
        from charts.reshape import json_to_spec
        from charts.types.area import AreaChartSpec
        spec = json_to_spec(self._raw(kind="area", alpha=0.7))
        self.assertIsInstance(spec, AreaChartSpec)
        self.assertEqual(spec.alpha, 0.7)


class TestJsonToSpecList(unittest.TestCase):
    def test_empty_list(self):
        from charts.reshape import json_to_spec_list
        self.assertEqual(json_to_spec_list([]), [])

    def test_two_specs(self):
        from charts.reshape import json_to_spec_list
        raw_list = [
            {"title": "A", "x_field": "ts", "series": [{"name": "s", "data": [{"ts": "2024-01-01", "value": 1}]}]},
            {"title": "B", "x_field": "ts", "series": [{"name": "s", "data": [{"ts": "2024-01-02", "value": 2}]}]},
        ]
        specs = json_to_spec_list(raw_list)
        self.assertEqual(len(specs), 2)
        self.assertEqual(specs[0].title, "A")
        self.assertEqual(specs[1].title, "B")


class TestTheme(unittest.TestCase):
    def test_dark_theme(self):
        from charts.theme import get_theme
        t = get_theme("dark")
        self.assertEqual(t.name, "dark")
        self.assertTrue(t.palette)

    def test_light_theme(self):
        from charts.theme import get_theme
        t = get_theme("light")
        self.assertEqual(t.name, "light")

    def test_unknown_theme_raises(self):
        from charts.theme import get_theme
        with self.assertRaises(ValueError):
            get_theme("neon")

    def test_theme_is_frozen(self):
        from charts.theme import get_theme
        t = get_theme("dark")
        with self.assertRaises((AttributeError, TypeError)):
            t.name = "foo"  # type: ignore[misc]


class TestGridConfig(unittest.TestCase):
    def _make_raw(self, **overrides):
        raw = {
            "title": "Grid",
            "output": "out/grid.png",
            "rows": 2,
            "cols": 2,
            "charts": [
                {"input": "panel0.json", "row": 0, "col": 0},
                {"input": "panel1.json", "row": 1, "col": 1},
            ],
        }
        raw.update(overrides)
        return raw

    def _load_from_raw(self, raw):
        """Helper: write raw to a tmp file and load it."""
        import tempfile
        try:
            import yaml
            content = yaml.dump(raw)
        except ImportError:
            content = json.dumps(raw)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(content)
            path = f.name
        from charts.config import load_grid_config
        return load_grid_config(path)

    def test_basic_load(self):
        cfg = self._load_from_raw(self._make_raw())
        self.assertEqual(cfg.title, "Grid")
        self.assertEqual(cfg.rows, 2)
        self.assertEqual(cfg.cols, 2)
        self.assertEqual(len(cfg.panels), 2)

    def test_panel_attributes(self):
        cfg = self._load_from_raw(self._make_raw())
        self.assertEqual(cfg.panels[0].input, "panel0.json")
        self.assertEqual(cfg.panels[0].row, 0)
        self.assertEqual(cfg.panels[0].col, 0)

    def test_default_theme_dark(self):
        cfg = self._load_from_raw(self._make_raw())
        self.assertEqual(cfg.theme, "dark")

    def test_missing_required_field_raises(self):
        raw = self._make_raw()
        del raw["title"]
        with self.assertRaises(ValueError):
            self._load_from_raw(raw)

    def test_out_of_bounds_row_raises(self):
        raw = self._make_raw()
        raw["charts"] = [{"input": "x.json", "row": 5, "col": 0}]
        with self.assertRaises(ValueError):
            self._load_from_raw(raw)

    def test_out_of_bounds_col_raises(self):
        raw = self._make_raw()
        raw["charts"] = [{"input": "x.json", "row": 0, "col": 5}]
        with self.assertRaises(ValueError):
            self._load_from_raw(raw)

    def test_unknown_theme_raises(self):
        raw = self._make_raw(theme="neon")
        with self.assertRaises(ValueError):
            self._load_from_raw(raw)

    def test_frozen(self):
        cfg = self._load_from_raw(self._make_raw())
        with self.assertRaises((AttributeError, TypeError)):
            cfg.title = "X"  # type: ignore[misc]


class TestRenderChartMocked(unittest.TestCase):
    """Test render_chart logic with matplotlib mocked out.

    matplotlib is lazily imported inside render_chart/render_grid, so we patch
    both _require_matplotlib (no-op the check) and the lazy imports within the
    function body. Since `import matplotlib.pyplot as plt` happens inside the
    function, we intercept sys.modules before the call.
    """

    def _make_spec(self):
        from charts.types.base import SeriesSpec
        from charts.types.line import LineChartSpec
        return LineChartSpec(
            title="Test",
            x_field="ts",
            series=[SeriesSpec(name="s", data=[{"ts": "2024-01-01", "value": 1}])],
        )

    def _mock_matplotlib(self):
        """Return a context manager that stubs matplotlib in sys.modules."""
        import sys
        mock_mpl = MagicMock()
        mock_plt = MagicMock()
        mock_plt.subplots.return_value = (MagicMock(), MagicMock())
        mock_mpl.pyplot = mock_plt
        return patch.dict(sys.modules, {
            "matplotlib": mock_mpl,
            "matplotlib.pyplot": mock_plt,
            "matplotlib.dates": MagicMock(),
        })

    def test_unsupported_format_raises(self):
        """render_chart should raise ValueError for .gif output."""
        spec = self._make_spec()

        with patch("charts.renderer._require_matplotlib"):
            with self._mock_matplotlib():
                from charts.renderer import render_chart
                with self.assertRaises(ValueError):
                    render_chart(spec, "/tmp/out.gif")

    def test_negative_dpi_raises(self):
        with patch("charts.renderer._require_matplotlib"):
            with self._mock_matplotlib():
                from charts.renderer import render_chart
                with self.assertRaises(ValueError):
                    render_chart(self._make_spec(), "/tmp/out.png", dpi=-1)


class TestRenderChartImportError(unittest.TestCase):
    """Verify that renderer raises ImportError if matplotlib is absent."""

    def test_import_error_without_matplotlib(self):
        import sys
        # Temporarily hide matplotlib
        orig = sys.modules.get("matplotlib")
        sys.modules["matplotlib"] = None  # type: ignore[assignment]
        try:
            # Need to reload to pick up the missing import
            import importlib
            import charts.renderer as renderer_mod
            importlib.reload(renderer_mod)
            with self.assertRaises(ImportError):
                renderer_mod._require_matplotlib()
        finally:
            if orig is None:
                del sys.modules["matplotlib"]
            else:
                sys.modules["matplotlib"] = orig
            # Reload back to clean state
            import importlib
            import charts.renderer as renderer_mod
            importlib.reload(renderer_mod)


if __name__ == "__main__":
    unittest.main()
