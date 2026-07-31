"""Tests for charts/cli.py — error paths and happy paths.

matplotlib is never imported; render_chart and render_grid are patched.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_spec_dict():
    return {
        "title": "Test Chart",
        "x_field": "ts",
        "series": [{"name": "s", "data": [{"ts": "2024-01-01", "value": 42}]}],
    }


def _write_temp_json(content: str) -> str:
    """Write content to a temp file, return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    f.write(content)
    f.close()
    return f.name


# ---------------------------------------------------------------------------
# _read_text
# ---------------------------------------------------------------------------


class TestReadText(unittest.TestCase):
    def test_missing_file_exits_1(self):
        from charts.cli import _read_text
        from core.cli_errors import CLIError, ExitCode

        with self.assertRaises(CLIError) as cm:
            _read_text("/nonexistent/path/does_not_exist.json")
        self.assertEqual(cm.exception.code, ExitCode.ERROR)
        self.assertIn("error", str(cm.exception).lower())

    def test_existing_file_returns_content(self):
        from charts.cli import _read_text

        path = _write_temp_json('{"hello": "world"}')
        try:
            result = _read_text(path)
            self.assertEqual(result.strip(), '{"hello": "world"}')
        finally:
            Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# _parse_rows
# ---------------------------------------------------------------------------


class TestParseRows(unittest.TestCase):
    def test_valid_list_returns_rows(self):
        from charts.cli import _parse_rows

        result = _parse_rows('[{"x": 1}, {"x": 2}]')
        self.assertEqual(len(result), 2)

    def test_invalid_json_exits_1(self):
        from charts.cli import _parse_rows

        with self.assertRaises(SystemExit) as cm:
            err = StringIO()
            with patch("sys.stderr", err):
                _parse_rows("not json at all {{")
        self.assertEqual(cm.exception.code, 1)

    def test_non_list_json_exits_1(self):
        from charts.cli import _parse_rows

        with self.assertRaises(SystemExit) as cm:
            err = StringIO()
            with patch("sys.stderr", err):
                _parse_rows('{"key": "value"}')
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("array", err.getvalue())


# ---------------------------------------------------------------------------
# _validate_row
# ---------------------------------------------------------------------------


class TestValidateRow(unittest.TestCase):
    def test_row_missing_x_field_exits_1(self):
        from charts.cli import _validate_row

        with self.assertRaises(SystemExit) as cm:
            err = StringIO()
            with patch("sys.stderr", err):
                _validate_row({"y_val": 10}, x_field="ts", y_field="y_val")
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("ts", err.getvalue())

    def test_row_missing_y_field_exits_1(self):
        from charts.cli import _validate_row

        with self.assertRaises(SystemExit) as cm:
            err = StringIO()
            with patch("sys.stderr", err):
                _validate_row({"ts": "2024-01-01"}, x_field="ts", y_field="count")
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("count", err.getvalue())

    def test_valid_row_returns_dict(self):
        from charts.cli import _validate_row

        row = {"ts": "2024-01-01", "count": 5}
        result = _validate_row(row, x_field="ts", y_field="count")
        self.assertEqual(result["ts"], "2024-01-01")
        self.assertEqual(result["count"], 5)


# ---------------------------------------------------------------------------
# _build_series_map
# ---------------------------------------------------------------------------


class TestBuildSeriesMap(unittest.TestCase):
    def test_group_by_field_absent_on_row_warns_and_produces_output(self):
        from charts.cli import _build_series_map

        rows = [{"ts": "2024-01-01", "count": 5}]
        err = StringIO()
        with patch("sys.stderr", err):
            result = _build_series_map(rows, x_field="ts", y_field="count", group_by="category")
        self.assertIn("warning", err.getvalue().lower())
        self.assertIn("<missing>", result)
        self.assertEqual(len(result["<missing>"]), 1)

    def test_group_by_present_splits_series(self):
        from charts.cli import _build_series_map

        rows = [
            {"ts": "2024-01-01", "count": 5, "cat": "a"},
            {"ts": "2024-01-02", "count": 3, "cat": "b"},
        ]
        result = _build_series_map(rows, x_field="ts", y_field="count", group_by="cat")
        self.assertIn("a", result)
        self.assertIn("b", result)

    def test_no_group_by_uses_value_series(self):
        from charts.cli import _build_series_map

        rows = [{"ts": "2024-01-01", "count": 5}]
        result = _build_series_map(rows, x_field="ts", y_field="count", group_by=None)
        self.assertIn("value", result)


# ---------------------------------------------------------------------------
# _handle_render
# ---------------------------------------------------------------------------


class TestHandleRender(unittest.TestCase):
    def _make_args(self, input_path="-", output_path="out.png", svg=False, theme="dark", dpi=None):
        args = MagicMock()
        args.input_path = input_path
        args.output_path = output_path
        args.svg = svg
        args.theme = theme
        args.dpi = dpi
        return args

    def test_invalid_json_input_exits_1(self):
        from charts.cli import _handle_render

        path = _write_temp_json("not valid json {{{{")
        try:
            args = self._make_args(input_path=path)
            with self.assertRaises(SystemExit) as cm:
                err = StringIO()
                with patch("charts.cli._require_matplotlib"):
                    with patch("sys.stderr", err):
                        _handle_render(args)
            self.assertEqual(cm.exception.code, 1)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_missing_output_triggers_argparse_required(self):
        """render subcommand requires --output; test via argparse."""
        from charts.cli import main

        with self.assertRaises(SystemExit) as cm:
            err = StringIO()
            with patch("sys.stderr", err):
                main(["render", "--input", "/dev/null"])
        self.assertNotEqual(cm.exception.code, 0)

    def test_valid_json_calls_render_chart_and_exits_0(self):
        """Covered by TestHandleRenderViaMain.test_render_subcommand_happy_path_exits_0."""
        pass


# ---------------------------------------------------------------------------
# _handle_render — happy path via main()
# ---------------------------------------------------------------------------


class TestHandleRenderViaMain(unittest.TestCase):
    def test_render_subcommand_happy_path_exits_0(self):
        """main() render subcommand: patch render_chart (where used), expect exit 0."""
        spec_dict = _make_valid_spec_dict()
        path = _write_temp_json(json.dumps(spec_dict))
        fake_out = Path("out/chart.png")

        try:
            mock_render = MagicMock(return_value=fake_out)
            stdout = StringIO()
            with patch("charts.cli._require_matplotlib"):
                # render_chart is imported inside _handle_render via
                # `from charts.renderer import render_chart`, so patch
                # the name on the source module (where it is used at call time).
                with patch("charts.renderer.render_chart", mock_render):
                    with patch("sys.stdout", stdout):
                        from charts.cli import main
                        rc = main(["render", "--input", path, "--output", "out/chart.png"])
            self.assertEqual(rc, 0)
            mock_render.assert_called_once()
        finally:
            Path(path).unlink(missing_ok=True)

    def test_grid_subcommand_happy_path_exits_0(self):
        """main() grid subcommand: patch render_grid, expect exit 0."""
        import tempfile
        try:
            import yaml
            _have_yaml = True
        except ImportError:
            _have_yaml = False

        panel_spec = _make_valid_spec_dict()
        panel_path = _write_temp_json(json.dumps(panel_spec))

        grid_raw = {
            "title": "Grid",
            "output": "out/grid.png",
            "rows": 1,
            "cols": 1,
            "charts": [{"input": panel_path, "row": 0, "col": 0}],
        }
        if _have_yaml:
            import yaml
            cfg_content = yaml.dump(grid_raw)
            suffix = ".yaml"
        else:
            cfg_content = json.dumps(grid_raw)
            suffix = ".yaml"

        with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
            f.write(cfg_content)
            cfg_path = f.name

        fake_out = Path("out/grid.png")
        mock_render_grid = MagicMock(return_value=fake_out)

        try:
            stdout = StringIO()
            with patch("charts.cli._require_matplotlib"):
                # render_grid is imported inside _handle_grid via
                # `from charts.renderer import render_grid`, so patch
                # the name on the source module.
                with patch("charts.renderer.render_grid", mock_render_grid):
                    with patch("sys.stdout", stdout):
                        from charts.cli import main
                        rc = main(["grid", "--config", cfg_path])
            self.assertEqual(rc, 0)
            mock_render_grid.assert_called_once()
        finally:
            Path(panel_path).unlink(missing_ok=True)
            Path(cfg_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# _handle_grid — invalid spec (config file unreadable)
# ---------------------------------------------------------------------------


class TestHandleGrid(unittest.TestCase):
    def test_invalid_config_path_exits_1(self):
        from charts.cli import main

        with self.assertRaises(SystemExit) as cm:
            err = StringIO()
            with patch("charts.cli._require_matplotlib"):
                with patch("sys.stderr", err):
                    main(["grid", "--config", "/no/such/file.yaml"])
        self.assertEqual(cm.exception.code, 1)

    def test_missing_config_flag_exits_nonzero(self):
        with self.assertRaises(SystemExit) as cm:
            err = StringIO()
            with patch("sys.stderr", err):
                from charts.cli import main
                main(["grid"])
        self.assertNotEqual(cm.exception.code, 0)


# ---------------------------------------------------------------------------
# _handle_reshape — missing file
# ---------------------------------------------------------------------------


class TestHandleReshape(unittest.TestCase):
    def test_missing_file_exits_1(self):
        from charts.cli import main

        with self.assertRaises(SystemExit) as cm:
            err = StringIO()
            with patch("sys.stderr", err):
                main(["reshape", "--input", "/nonexistent/file.json", "--x", "ts", "--y", "count"])
        self.assertEqual(cm.exception.code, 1)

    def test_valid_reshape_outputs_json(self):
        from charts.cli import main

        rows = [{"ts": "2024-01-01", "count": 5}, {"ts": "2024-01-02", "count": 10}]
        path = _write_temp_json(json.dumps(rows))
        try:
            out = StringIO()
            with patch("sys.stdout", out):
                rc = main(["reshape", "--input", path, "--x", "ts", "--y", "count"])
            self.assertEqual(rc, 0)
            parsed = json.loads(out.getvalue())
            self.assertIn("series", parsed)
        finally:
            Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
