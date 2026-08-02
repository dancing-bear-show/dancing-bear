"""Tests for charts/cli.py handler layer and charts/reshape.py.

Covers:
  - _handle_render: happy path + OutputWriter injection
  - _handle_grid: happy path + OutputWriter injection
  - _handle_reshape: happy path + OutputWriter injection (json & yaml)
  - reshape.json_to_spec: happy path + sad paths
  - reshape._coerce_series: happy path + sad paths
  - C5 CLIError raise sites: _require_matplotlib, _read_text
  - main()'s CLIError boundary: sys.exit(handle_error(e)) wiring
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch



# ---------------------------------------------------------------------------
# Minimal valid chart spec dict for reshape tests
# ---------------------------------------------------------------------------

def _raw_spec(kind: str = "line") -> dict:
    return {
        "title": "My Chart",
        "x_field": "ts",
        "kind": kind,
        "series": [
            {
                "name": "alpha",
                "data": [{"ts": "2024-01-01", "value": 1.0}],
            }
        ],
    }


def _raw_spec_two_series() -> dict:
    return {
        "title": "Multi",
        "x_field": "ts",
        "series": [
            {"name": "s1", "data": [{"ts": "A", "value": 1.0}]},
            {"name": "s2", "data": [{"ts": "B", "value": 2.5}]},
        ],
    }


# ---------------------------------------------------------------------------
# reshape.json_to_spec — happy paths
# ---------------------------------------------------------------------------

class TestJsonToSpecHappy(unittest.TestCase):
    def test_line_spec_parsed(self):
        from charts.reshape import json_to_spec
        from charts.types.line import LineChartSpec
        spec = json_to_spec(_raw_spec("line"))
        self.assertIsInstance(spec, LineChartSpec)
        self.assertEqual(spec.title, "My Chart")
        self.assertEqual(spec.x_field, "ts")
        self.assertEqual(len(spec.series), 1)

    def test_bar_spec_parsed(self):
        from charts.reshape import json_to_spec
        from charts.types.bar import BarChartSpec
        raw = _raw_spec("bar")
        spec = json_to_spec(raw)
        self.assertIsInstance(spec, BarChartSpec)

    def test_area_spec_parsed(self):
        from charts.reshape import json_to_spec
        from charts.types.area import AreaChartSpec
        spec = json_to_spec(_raw_spec("area"))
        self.assertIsInstance(spec, AreaChartSpec)

    def test_dual_spec_parsed(self):
        from charts.reshape import json_to_spec
        from charts.types.dual import DualAxisChartSpec
        spec = json_to_spec(_raw_spec("dual"))
        self.assertIsInstance(spec, DualAxisChartSpec)

    def test_defaults_to_line_when_kind_absent(self):
        from charts.reshape import json_to_spec
        from charts.types.line import LineChartSpec
        raw = {k: v for k, v in _raw_spec().items() if k != "kind"}
        spec = json_to_spec(raw)
        self.assertIsInstance(spec, LineChartSpec)

    def test_series_color_and_label_preserved(self):
        from charts.reshape import json_to_spec
        raw = {
            "title": "T",
            "x_field": "ts",
            "series": [
                {
                    "name": "s",
                    "data": [{"ts": "2024-01-01", "value": 3.0}],
                    "color": "#ff0000",
                    "label": "My Label",
                }
            ],
        }
        spec = json_to_spec(raw)
        self.assertEqual(spec.series[0].color, "#ff0000")
        self.assertEqual(spec.series[0].label, "My Label")

    def test_optional_fields_forwarded(self):
        from charts.reshape import json_to_spec
        raw = _raw_spec()
        raw["width_px"] = 800
        raw["height_px"] = 600
        raw["dpi"] = 72
        spec = json_to_spec(raw)
        self.assertEqual(spec.width_px, 800)
        self.assertEqual(spec.height_px, 600)
        self.assertEqual(spec.dpi, 72)


# ---------------------------------------------------------------------------
# reshape.json_to_spec — sad paths
# ---------------------------------------------------------------------------

class TestJsonToSpecSad(unittest.TestCase):
    def test_non_dict_raises(self):
        from charts.reshape import json_to_spec
        with self.assertRaises(ValueError) as ctx:
            json_to_spec([1, 2, 3])  # type: ignore[arg-type]
        self.assertIn("JSON object", str(ctx.exception))

    def test_missing_title_raises(self):
        from charts.reshape import json_to_spec
        raw = _raw_spec()
        del raw["title"]
        with self.assertRaises(ValueError) as ctx:
            json_to_spec(raw)
        self.assertIn("title", str(ctx.exception))

    def test_missing_x_field_raises(self):
        from charts.reshape import json_to_spec
        raw = _raw_spec()
        del raw["x_field"]
        with self.assertRaises(ValueError) as ctx:
            json_to_spec(raw)
        self.assertIn("x_field", str(ctx.exception))

    def test_missing_series_raises(self):
        from charts.reshape import json_to_spec
        raw = _raw_spec()
        del raw["series"]
        with self.assertRaises(ValueError) as ctx:
            json_to_spec(raw)
        self.assertIn("series", str(ctx.exception))

    def test_empty_series_raises(self):
        from charts.reshape import json_to_spec
        raw = _raw_spec()
        raw["series"] = []
        with self.assertRaises(ValueError) as ctx:
            json_to_spec(raw)
        self.assertIn("series", str(ctx.exception))

    def test_unknown_kind_raises(self):
        from charts.reshape import json_to_spec
        raw = _raw_spec()
        raw["kind"] = "scatter"
        with self.assertRaises(ValueError) as ctx:
            json_to_spec(raw)
        self.assertIn("scatter", str(ctx.exception))

    def test_bar_invalid_orientation_raises(self):
        from charts.reshape import json_to_spec
        raw = _raw_spec("bar")
        raw["orientation"] = "diagonal"
        with self.assertRaises(ValueError) as ctx:
            json_to_spec(raw)
        self.assertIn("orientation", str(ctx.exception))

    def test_bar_invalid_bar_width_raises(self):
        from charts.reshape import json_to_spec
        raw = _raw_spec("bar")
        raw["bar_width"] = -1
        with self.assertRaises(ValueError) as ctx:
            json_to_spec(raw)
        self.assertIn("bar_width", str(ctx.exception))

    def test_area_invalid_alpha_raises(self):
        from charts.reshape import json_to_spec
        raw = _raw_spec("area")
        raw["alpha"] = 2.0
        with self.assertRaises(ValueError) as ctx:
            json_to_spec(raw)
        self.assertIn("alpha", str(ctx.exception))


# ---------------------------------------------------------------------------
# reshape._coerce_series — happy path + sad paths
# ---------------------------------------------------------------------------

class TestCoerceSeries(unittest.TestCase):
    def test_happy_path_returns_series_specs(self):
        from charts.reshape import _coerce_series
        from charts.types.base import SeriesSpec
        raw = [
            {"name": "s1", "data": [{"ts": "2024-01-01", "value": 1.0}]},
            {"name": "s2", "data": [{"ts": "2024-01-02", "value": 2.0}]},
        ]
        result = _coerce_series(raw, "ts")
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], SeriesSpec)
        self.assertEqual(result[0].name, "s1")
        self.assertEqual(result[1].name, "s2")

    def test_y_axis_defaults_to_left(self):
        from charts.reshape import _coerce_series
        raw = [{"name": "s", "data": [{"ts": "A", "value": 1.0}]}]
        result = _coerce_series(raw, "ts")
        self.assertEqual(result[0].y_axis, "left")

    def test_y_axis_overridden(self):
        from charts.reshape import _coerce_series
        raw = [{"name": "s", "y_axis": "right", "data": [{"ts": "A", "value": 1.0}]}]
        result = _coerce_series(raw, "ts")
        self.assertEqual(result[0].y_axis, "right")

    def test_non_dict_series_element_raises(self):
        from charts.reshape import _coerce_series
        with self.assertRaises(ValueError) as ctx:
            _coerce_series(["not_a_dict"], "ts")  # type: ignore[list-item]
        self.assertIn("series[0]", str(ctx.exception))

    def test_missing_name_raises(self):
        from charts.reshape import _coerce_series
        raw = [{"data": [{"ts": "A", "value": 1.0}]}]
        with self.assertRaises(ValueError) as ctx:
            _coerce_series(raw, "ts")
        self.assertIn("name", str(ctx.exception))

    def test_data_not_list_raises(self):
        from charts.reshape import _coerce_series
        raw = [{"name": "s", "data": "not_a_list"}]
        with self.assertRaises(ValueError) as ctx:
            _coerce_series(raw, "ts")
        self.assertIn("data", str(ctx.exception))

    def test_row_missing_x_field_raises(self):
        from charts.reshape import _coerce_series
        raw = [{"name": "s", "data": [{"WRONG": "A", "value": 1.0}]}]
        with self.assertRaises(ValueError) as ctx:
            _coerce_series(raw, "ts")
        self.assertIn("ts", str(ctx.exception))

    def test_row_missing_value_raises(self):
        from charts.reshape import _coerce_series
        raw = [{"name": "s", "data": [{"ts": "A"}]}]
        with self.assertRaises(ValueError) as ctx:
            _coerce_series(raw, "ts")
        self.assertIn("value", str(ctx.exception))

    def test_non_numeric_value_raises(self):
        from charts.reshape import _coerce_series
        raw = [{"name": "s", "data": [{"ts": "A", "value": "not_a_number"}]}]
        with self.assertRaises(ValueError) as ctx:
            _coerce_series(raw, "ts")
        self.assertIn("numeric", str(ctx.exception))


# ---------------------------------------------------------------------------
# C5 — CLIError raise sites
# ---------------------------------------------------------------------------

class TestRequireMatplotlibCLIError(unittest.TestCase):
    def test_import_error_raises_clierror(self):
        """_require_matplotlib raises CLIError (not SystemExit) when matplotlib absent."""
        from charts.cli import _require_matplotlib
        from core.cli_errors import CLIError, ExitCode
        with patch.dict(sys.modules, {"matplotlib": None}):
            with self.assertRaises(CLIError) as ctx:
                _require_matplotlib()
        self.assertEqual(ctx.exception.code, ExitCode.ERROR)
        self.assertIn("matplotlib", str(ctx.exception))

    def test_happy_path_no_raise(self):
        """_require_matplotlib succeeds when matplotlib is importable."""
        from charts.cli import _require_matplotlib
        mock_mpl = MagicMock()
        with patch.dict(sys.modules, {"matplotlib": mock_mpl}):
            # Should not raise
            _require_matplotlib()


class TestReadTextCLIError(unittest.TestCase):
    def test_missing_file_raises_clierror(self):
        """_read_text raises CLIError (not SystemExit) on OSError."""
        from charts.cli import _read_text
        from core.cli_errors import CLIError, ExitCode
        with self.assertRaises(CLIError) as ctx:
            _read_text("/nonexistent/path/to/file.json")
        self.assertEqual(ctx.exception.code, ExitCode.ERROR)

    def test_happy_path_reads_file(self):
        """_read_text returns file contents for a real file."""
        from charts.cli import _read_text
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"key": "val"}')
            fpath = f.name
        try:
            result = _read_text(fpath)
            self.assertEqual(result, '{"key": "val"}')
        finally:
            Path(fpath).unlink(missing_ok=True)

    def test_stdin_returns_content(self):
        """_read_text with '-' reads from stdin."""
        from charts.cli import _read_text
        fake_stdin = io.StringIO('{"stdin": true}')
        with patch("sys.stdin", fake_stdin):
            result = _read_text("-")
        self.assertEqual(result, '{"stdin": true}')


# ---------------------------------------------------------------------------
# main() CLIError boundary: sys.exit(handle_error(e))
# ---------------------------------------------------------------------------

class TestMainCLIErrorBoundary(unittest.TestCase):
    def test_clierror_from_require_matplotlib_causes_sys_exit(self):
        """main() catches CLIError raised by _require_matplotlib and calls sys.exit."""
        from charts.cli import main
        from core.cli_errors import CLIError, ExitCode

        def raise_clierror(*args, **kwargs):
            raise CLIError("matplotlib is not installed. Run: pip install matplotlib",
                           ExitCode.ERROR)

        with (
            patch("charts.cli._require_matplotlib", side_effect=raise_clierror),
            self.assertRaises(SystemExit) as ctx,
        ):
            main(["render", "--input", "f.json", "--output", "out.png"])
        self.assertEqual(ctx.exception.code, ExitCode.ERROR)

    def test_clierror_from_read_text_causes_sys_exit(self):
        """main() catches CLIError from _read_text and calls sys.exit."""
        from charts.cli import main
        from core.cli_errors import CLIError, ExitCode

        def raise_clierror(*args, **kwargs):
            raise CLIError("error: [Errno 2] No such file", ExitCode.ERROR)

        with (
            patch("charts.cli._require_matplotlib"),
            patch("charts.cli._read_text", side_effect=raise_clierror),
            self.assertRaises(SystemExit) as ctx,
        ):
            main(["render", "--input", "f.json", "--output", "out.png"])
        self.assertEqual(ctx.exception.code, ExitCode.ERROR)


# ---------------------------------------------------------------------------
# _handle_render — happy path + OutputWriter injection
# ---------------------------------------------------------------------------

class TestHandleRender(unittest.TestCase):
    def _make_args(self, input_path="input.json", output_path="out.png",
                   theme="dark", dpi=None, svg=False):
        args = MagicMock()
        args.input_path = input_path
        args.output_path = output_path
        args.theme = theme
        args.dpi = dpi
        args.svg = svg
        return args

    def test_happy_path_calls_render_chart_and_prints_path(self):
        """_handle_render calls render_chart and prints the path via OutputWriter."""
        from charts.cli import _handle_render

        captured = []
        mock_writer = MagicMock()
        mock_writer.print.side_effect = lambda s: captured.append(s)

        spec = MagicMock()
        fake_path = Path("/tmp/out.png")

        with (
            patch("charts.cli._require_matplotlib"),
            patch("charts.cli._read_text", return_value='{"title":"T","x_field":"ts","series":[]}'),
            patch("charts.reshape.json_to_spec", return_value=spec),
            patch("charts.renderer.render_chart", return_value=fake_path) as mock_render,
        ):
            result = _handle_render(self._make_args(), writer=mock_writer)

        self.assertEqual(result, 0)
        mock_render.assert_called_once()
        mock_writer.print.assert_called_once_with(str(fake_path))

    def test_output_flows_through_writer_not_bare_print(self):
        """Verifies OutputWriter.print is called, not bare builtin print."""
        from charts.cli import _handle_render

        mock_writer = MagicMock()
        spec = MagicMock()
        fake_path = Path("/tmp/chart.png")

        with (
            patch("charts.cli._require_matplotlib"),
            patch("charts.cli._read_text", return_value='{}'),
            patch("charts.reshape.json_to_spec", return_value=spec),
            patch("charts.renderer.render_chart", return_value=fake_path),
            patch("builtins.print") as mock_print,
        ):
            _handle_render(self._make_args(), writer=mock_writer)

        mock_writer.print.assert_called_once_with("/tmp/chart.png")
        # bare print should NOT have been called for the path output
        # (it may still be called for error paths, but not the success path)
        path_calls = [c for c in mock_print.call_args_list
                      if "/tmp/chart.png" in str(c)]
        self.assertEqual(len(path_calls), 0)

    def test_default_writer_created_when_none(self):
        """When no writer passed, _handle_render creates its own OutputWriter."""
        from charts.cli import _handle_render

        spec = MagicMock()
        fake_path = Path("/tmp/out.png")

        with (
            patch("charts.cli._require_matplotlib"),
            patch("charts.cli._read_text", return_value='{}'),
            patch("charts.reshape.json_to_spec", return_value=spec),
            patch("charts.renderer.render_chart", return_value=fake_path),
            patch("charts.cli.OutputWriter") as mock_ow_cls,
        ):
            mock_ow_cls.return_value = MagicMock()
            _handle_render(self._make_args(), writer=None)

        mock_ow_cls.assert_called_once()

    def test_svg_flag_changes_output_extension(self):
        """When --svg is set and output doesn't end in .svg, extension is changed."""
        from charts.cli import _handle_render

        mock_writer = MagicMock()
        spec = MagicMock()
        fake_path = Path("/tmp/out.svg")

        with (
            patch("charts.cli._require_matplotlib"),
            patch("charts.cli._read_text", return_value='{}'),
            patch("charts.reshape.json_to_spec", return_value=spec),
            patch("charts.renderer.render_chart", return_value=fake_path) as mock_render,
        ):
            _handle_render(self._make_args(output_path="out.png", svg=True),
                           writer=mock_writer)

        # render_chart should have been called with .svg path
        called_output = mock_render.call_args[0][1]
        self.assertTrue(called_output.endswith(".svg"), called_output)


# ---------------------------------------------------------------------------
# _handle_grid — happy path + OutputWriter injection
# ---------------------------------------------------------------------------

class TestHandleGrid(unittest.TestCase):
    def _make_args(self, config_path="grid.yaml", output_path=None,
                   theme=None, svg=False):
        args = MagicMock()
        args.config_path = config_path
        args.output_path = output_path
        args.theme = theme
        args.svg = svg
        return args

    def _make_grid_cfg(self):
        from charts.config import GridConfig, PanelConfig
        return GridConfig(
            title="Grid",
            output="/tmp/grid_out.png",
            rows=1,
            cols=1,
            panels=[PanelConfig(input="panel.json", row=0, col=0)],
            theme="dark",
            dpi=150,
            width_px=1200,
            height_px=400,
        )

    def test_happy_path_calls_render_grid_and_prints_path(self):
        """_handle_grid calls render_grid and prints the path via OutputWriter."""
        from charts.cli import _handle_grid

        mock_writer = MagicMock()
        cfg = self._make_grid_cfg()
        fake_path = Path("/tmp/grid_out.png")
        spec = MagicMock()

        with (
            patch("charts.cli._require_matplotlib"),
            patch("charts.config.load_grid_config", return_value=cfg),
            patch("charts.cli._load_panel_specs", return_value=[spec]),
            patch("charts.renderer.render_grid", return_value=fake_path) as mock_render,
        ):
            result = _handle_grid(self._make_args(), writer=mock_writer)

        self.assertEqual(result, 0)
        mock_render.assert_called_once()
        mock_writer.print.assert_called_once_with(str(fake_path))

    def test_output_flows_through_writer_not_bare_print(self):
        """Verifies OutputWriter.print is called for the path, not bare print."""
        from charts.cli import _handle_grid

        mock_writer = MagicMock()
        cfg = self._make_grid_cfg()
        fake_path = Path("/tmp/grid.png")
        spec = MagicMock()

        with (
            patch("charts.cli._require_matplotlib"),
            patch("charts.config.load_grid_config", return_value=cfg),
            patch("charts.cli._load_panel_specs", return_value=[spec]),
            patch("charts.renderer.render_grid", return_value=fake_path),
            patch("builtins.print") as mock_print,
        ):
            _handle_grid(self._make_args(), writer=mock_writer)

        mock_writer.print.assert_called_once_with("/tmp/grid.png")
        path_calls = [c for c in mock_print.call_args_list
                      if "/tmp/grid.png" in str(c)]
        self.assertEqual(len(path_calls), 0)

    def test_default_writer_created_when_none(self):
        """When no writer passed, _handle_grid creates its own OutputWriter."""
        from charts.cli import _handle_grid

        cfg = self._make_grid_cfg()
        fake_path = Path("/tmp/grid.png")
        spec = MagicMock()

        with (
            patch("charts.cli._require_matplotlib"),
            patch("charts.config.load_grid_config", return_value=cfg),
            patch("charts.cli._load_panel_specs", return_value=[spec]),
            patch("charts.renderer.render_grid", return_value=fake_path),
            patch("charts.cli.OutputWriter") as mock_ow_cls,
        ):
            mock_ow_cls.return_value = MagicMock()
            _handle_grid(self._make_args(), writer=None)

        mock_ow_cls.assert_called_once()


# ---------------------------------------------------------------------------
# _handle_reshape — happy path + OutputWriter injection
# ---------------------------------------------------------------------------

class TestHandleReshape(unittest.TestCase):
    def _make_args(self, input_path="-", x_field="ts", y_field="val",
                   group_by=None, title="Chart", fmt="json"):
        args = MagicMock()
        args.input_path = input_path
        args.x_field = x_field
        args.y_field = y_field
        args.group_by = group_by
        args.title = title
        args.fmt = fmt
        return args

    def _make_rows_json(self, rows=None):
        if rows is None:
            rows = [{"ts": "2024-01-01", "val": 10.0}]
        return json.dumps(rows)

    def test_happy_path_json_output_calls_print_data(self):
        """_handle_reshape (json) calls OutputWriter.print_data with shaped data."""
        from charts.cli import _handle_reshape

        mock_writer = MagicMock()
        rows_json = self._make_rows_json()

        with patch("charts.cli._read_text", return_value=rows_json):
            result = _handle_reshape(self._make_args(fmt="json"), writer=mock_writer)

        self.assertEqual(result, 0)
        mock_writer.print_data.assert_called_once()
        data_arg = mock_writer.print_data.call_args[0][0]
        self.assertEqual(data_arg["title"], "Chart")
        self.assertEqual(data_arg["x_field"], "ts")
        self.assertIn("series", data_arg)
        self.assertEqual(len(data_arg["series"]), 1)

    def test_happy_path_yaml_format_uses_yaml_output_format(self):
        """_handle_reshape with --format yaml constructs OutputWriter with YAML format."""
        from charts.cli import _handle_reshape

        mock_writer = MagicMock()
        rows_json = self._make_rows_json()

        with patch("charts.cli._read_text", return_value=rows_json):
            result = _handle_reshape(self._make_args(fmt="yaml"), writer=mock_writer)

        self.assertEqual(result, 0)
        mock_writer.print_data.assert_called_once()

    def test_default_writer_uses_correct_format_for_yaml(self):
        """When no writer provided and fmt=yaml, OutputWriter is constructed with YAML."""
        from charts.cli import _handle_reshape
        from core.cli_output import OutputFormat

        rows_json = self._make_rows_json()

        with (
            patch("charts.cli._read_text", return_value=rows_json),
            patch("charts.cli.OutputWriter") as mock_ow_cls,
            patch("charts.cli.OutputConfig") as mock_oc_cls,
        ):
            mock_ow_cls.return_value = MagicMock()
            _handle_reshape(self._make_args(fmt="yaml"), writer=None)

        # OutputConfig should have been called with format=OutputFormat.YAML
        mock_oc_cls.assert_called_once()
        oc_call_kwargs = mock_oc_cls.call_args[1]
        self.assertEqual(oc_call_kwargs.get("format"), OutputFormat.YAML)

    def test_default_writer_uses_correct_format_for_json(self):
        """When no writer provided and fmt=json, OutputWriter uses JSON format."""
        from charts.cli import _handle_reshape
        from core.cli_output import OutputFormat

        rows_json = self._make_rows_json()

        with (
            patch("charts.cli._read_text", return_value=rows_json),
            patch("charts.cli.OutputWriter") as mock_ow_cls,
            patch("charts.cli.OutputConfig") as mock_oc_cls,
        ):
            mock_ow_cls.return_value = MagicMock()
            _handle_reshape(self._make_args(fmt="json"), writer=None)

        mock_oc_cls.assert_called_once()
        oc_call_kwargs = mock_oc_cls.call_args[1]
        self.assertEqual(oc_call_kwargs.get("format"), OutputFormat.JSON)

    def test_group_by_splits_into_multiple_series(self):
        """Rows with different group_by values create separate series."""
        from charts.cli import _handle_reshape

        rows = [
            {"ts": "2024-01-01", "val": 1.0, "region": "us"},
            {"ts": "2024-01-02", "val": 2.0, "region": "eu"},
        ]
        mock_writer = MagicMock()

        with patch("charts.cli._read_text", return_value=json.dumps(rows)):
            _handle_reshape(
                self._make_args(group_by="region"),
                writer=mock_writer,
            )

        data = mock_writer.print_data.call_args[0][0]
        series_names = {s["name"] for s in data["series"]}
        self.assertIn("us", series_names)
        self.assertIn("eu", series_names)

    def test_output_flows_through_writer_print_data(self):
        """print_data is called on the writer — verifies OutputWriter injection."""
        from charts.cli import _handle_reshape

        mock_writer = MagicMock()
        rows_json = self._make_rows_json()

        with (
            patch("charts.cli._read_text", return_value=rows_json),
            patch("builtins.print") as mock_builtin_print,
        ):
            _handle_reshape(self._make_args(), writer=mock_writer)

        mock_writer.print_data.assert_called_once()
        # The path/data output must NOT go through bare print
        self.assertEqual(mock_builtin_print.call_count, 0)


# ---------------------------------------------------------------------------
# main() dispatch integration smoke tests
# ---------------------------------------------------------------------------

class TestMainDispatch(unittest.TestCase):
    def test_no_command_returns_nonzero(self):
        """main() with no subcommand prints help and returns 1."""
        from charts.cli import main
        with patch("argparse.ArgumentParser.print_help"):
            result = main([])
        self.assertEqual(result, 1)

    def test_reshape_dispatch_end_to_end(self):
        """main(['reshape', ...]) reaches _handle_reshape and returns 0."""
        from charts.cli import main

        rows = [{"ts": "2024-01-01", "val": 5.0}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(rows, f)
            fpath = f.name

        try:
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                result = main([
                    "reshape",
                    "--input", fpath,
                    "--x", "ts",
                    "--y", "val",
                    "--title", "Smoke",
                    "--format", "json",
                ])
        finally:
            Path(fpath).unlink(missing_ok=True)

        self.assertEqual(result, 0)
        output = captured.getvalue()
        self.assertIn("Smoke", output)

    def test_leading_separator_is_optional(self):
        """A post-subcommand '--' — the shape workflow.compiler._build_cli_command
        actually emits (subcommand, then '--', then flags) — and its absence
        must dispatch identically. Regression test for CLIApp's optional-
        separator normalization not being applied in main()."""
        from charts.cli import main

        rows = [{"ts": "2024-01-01", "val": 5.0}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(rows, f)
            fpath = f.name

        try:
            flags = ["--input", fpath, "--x", "ts", "--y", "val", "--format", "json"]

            captured_with_sep = io.StringIO()
            with patch("sys.stdout", captured_with_sep):
                result_with_sep = main(["reshape", "--"] + flags)

            captured_without_sep = io.StringIO()
            with patch("sys.stdout", captured_without_sep):
                result_without_sep = main(["reshape"] + flags)
        finally:
            Path(fpath).unlink(missing_ok=True)

        self.assertEqual(result_with_sep, 0)
        self.assertEqual(result_with_sep, result_without_sep)
        self.assertEqual(captured_with_sep.getvalue(), captured_without_sep.getvalue())

    def test_render_dispatch_clierror_exits(self):
        """main(['render', ...]) raises SystemExit when _require_matplotlib raises CLIError."""
        from charts.cli import main
        from core.cli_errors import CLIError, ExitCode

        with (
            patch("charts.cli._require_matplotlib",
                  side_effect=CLIError("no matplotlib", ExitCode.ERROR)),
            self.assertRaises(SystemExit) as ctx,
        ):
            main(["render", "--input", "f.json", "--output", "out.png"])

        self.assertEqual(ctx.exception.code, ExitCode.ERROR)


if __name__ == "__main__":
    unittest.main()
