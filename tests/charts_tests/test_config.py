"""Tests for charts.config — load_grid_config validation branches.

Covers the error branches missed by the existing TestGridConfig in tests/test_charts.py:
  - non-mapping root (line 46)
  - 'charts' not a list (line 54)
  - panel not a mapping (line 59)
  - panel missing required field (line 62)
  - negative row/col in _validate_panel_placement (line 92)
  - rows/cols <= 0 in _validate_grid (line 107)
  - dpi <= 0 (line 111)
  - width_px <= 0 (line 113)
  - height_px <= 0 (line 115)

Happy-path round-trip is already in tests/test_charts.py::TestGridConfig; these
tests pair each error branch with a corresponding positive assertion where the
error condition is NOT triggered.
"""

from __future__ import annotations

import json
import tempfile
import os
import unittest


def _write_yaml(data: dict, suffix: str = ".yaml") -> str:
    """Write data to a temp YAML file, return path. Falls back to JSON."""
    try:
        import yaml
        content = yaml.safe_dump(data)
        with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
            f.write(content)
            return f.name
    except ImportError:
        content = json.dumps(data)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(content)
            return f.name


def _write_raw_text(content: str, suffix: str = ".yaml") -> str:
    """Write raw text to a temp file, return path."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        f.write(content)
        return f.name


def _minimal_raw(**overrides) -> dict:
    """Return a minimal valid raw config dict with optional overrides."""
    base = {
        "title": "Test Grid",
        "output": "out/grid.png",
        "rows": 2,
        "cols": 2,
        "charts": [
            {"input": "a.json", "row": 0, "col": 0},
        ],
    }
    base.update(overrides)
    return base


class TestLoadGridConfigNonMapping(unittest.TestCase):
    """Root YAML value is not a dict — line 46 branch."""

    def test_list_root_raises_value_error(self):
        # Write a YAML list (not a mapping) as the root
        path = _write_raw_text("- item1\n- item2\n")
        try:
            from charts.config import load_grid_config
            with self.assertRaises(ValueError) as ctx:
                load_grid_config(path)
            self.assertIn("mapping", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_mapping_root_does_not_raise(self):
        raw = _minimal_raw()
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            cfg = load_grid_config(path)
            self.assertEqual(cfg.title, "Test Grid")
        finally:
            os.unlink(path)


class TestLoadGridConfigChartsNotList(unittest.TestCase):
    """'charts' key exists but is not a list — line 54 branch."""

    def test_charts_as_string_raises_value_error(self):
        raw = _minimal_raw(charts="not-a-list")
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            with self.assertRaises(ValueError) as ctx:
                load_grid_config(path)
            self.assertIn("list", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_charts_as_dict_raises_value_error(self):
        raw = _minimal_raw(charts={"input": "x.json", "row": 0, "col": 0})
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            with self.assertRaises(ValueError) as ctx:
                load_grid_config(path)
            self.assertIn("list", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_charts_as_list_does_not_raise(self):
        raw = _minimal_raw()
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            cfg = load_grid_config(path)
            self.assertEqual(len(cfg.panels), 1)
        finally:
            os.unlink(path)


class TestLoadGridConfigPanelNotMapping(unittest.TestCase):
    """A chart entry is not a dict — line 59 branch."""

    def test_panel_as_string_raises_value_error(self):
        raw = _minimal_raw(charts=["not-a-dict"])
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            with self.assertRaises(ValueError) as ctx:
                load_grid_config(path)
            self.assertIn("mapping", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_panel_as_int_raises_value_error(self):
        raw = _minimal_raw(charts=[42])
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            with self.assertRaises(ValueError) as ctx:
                load_grid_config(path)
            self.assertIn("mapping", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_panel_as_dict_does_not_raise(self):
        raw = _minimal_raw()
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            cfg = load_grid_config(path)
            self.assertIsInstance(cfg.panels[0].input, str)
        finally:
            os.unlink(path)


class TestLoadGridConfigPanelMissingRequiredField(unittest.TestCase):
    """A chart entry is a dict but missing 'input', 'row', or 'col' — line 62 branch."""

    def test_panel_missing_input_raises_value_error(self):
        raw = _minimal_raw(charts=[{"row": 0, "col": 0}])
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            with self.assertRaises(ValueError) as ctx:
                load_grid_config(path)
            self.assertIn("input", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_panel_missing_row_raises_value_error(self):
        raw = _minimal_raw(charts=[{"input": "x.json", "col": 0}])
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            with self.assertRaises(ValueError) as ctx:
                load_grid_config(path)
            self.assertIn("row", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_panel_missing_col_raises_value_error(self):
        raw = _minimal_raw(charts=[{"input": "x.json", "row": 0}])
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            with self.assertRaises(ValueError) as ctx:
                load_grid_config(path)
            self.assertIn("col", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_panel_with_all_required_fields_does_not_raise(self):
        raw = _minimal_raw(charts=[{"input": "x.json", "row": 0, "col": 0}])
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            cfg = load_grid_config(path)
            self.assertEqual(cfg.panels[0].input, "x.json")
        finally:
            os.unlink(path)


class TestLoadGridConfigNegativeRowCol(unittest.TestCase):
    """Negative row or col in _validate_panel_placement — line 92 branch."""

    def test_negative_row_raises_value_error(self):
        raw = _minimal_raw(charts=[{"input": "x.json", "row": -1, "col": 0}])
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            with self.assertRaises(ValueError) as ctx:
                load_grid_config(path)
            self.assertIn("non-negative", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_negative_col_raises_value_error(self):
        raw = _minimal_raw(charts=[{"input": "x.json", "row": 0, "col": -1}])
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            with self.assertRaises(ValueError) as ctx:
                load_grid_config(path)
            self.assertIn("non-negative", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_zero_row_and_col_does_not_raise(self):
        raw = _minimal_raw(charts=[{"input": "x.json", "row": 0, "col": 0}])
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            cfg = load_grid_config(path)
            self.assertEqual(cfg.panels[0].row, 0)
            self.assertEqual(cfg.panels[0].col, 0)
        finally:
            os.unlink(path)


class TestValidateGridDimensions(unittest.TestCase):
    """_validate_grid checks rows/cols/dpi/width_px/height_px — lines 107-115."""

    def test_zero_rows_raises_value_error(self):
        raw = _minimal_raw(rows=0, charts=[])
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            with self.assertRaises(ValueError) as ctx:
                load_grid_config(path)
            self.assertIn("rows", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_zero_cols_raises_value_error(self):
        raw = _minimal_raw(cols=0, charts=[])
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            with self.assertRaises(ValueError) as ctx:
                load_grid_config(path)
            self.assertIn("cols", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_positive_rows_and_cols_does_not_raise(self):
        raw = _minimal_raw(rows=1, cols=1, charts=[{"input": "x.json", "row": 0, "col": 0}])
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            cfg = load_grid_config(path)
            self.assertEqual(cfg.rows, 1)
            self.assertEqual(cfg.cols, 1)
        finally:
            os.unlink(path)

    def test_zero_dpi_raises_value_error(self):
        raw = _minimal_raw(dpi=0)
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            with self.assertRaises(ValueError) as ctx:
                load_grid_config(path)
            self.assertIn("dpi", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_positive_dpi_does_not_raise(self):
        raw = _minimal_raw(dpi=72)
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            cfg = load_grid_config(path)
            self.assertEqual(cfg.dpi, 72)
        finally:
            os.unlink(path)

    def test_zero_width_px_raises_value_error(self):
        raw = _minimal_raw(width_px=0)
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            with self.assertRaises(ValueError) as ctx:
                load_grid_config(path)
            self.assertIn("width_px", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_positive_width_px_does_not_raise(self):
        raw = _minimal_raw(width_px=800)
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            cfg = load_grid_config(path)
            self.assertEqual(cfg.width_px, 800)
        finally:
            os.unlink(path)

    def test_zero_height_px_raises_value_error(self):
        raw = _minimal_raw(height_px=0)
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            with self.assertRaises(ValueError) as ctx:
                load_grid_config(path)
            self.assertIn("height_px", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_positive_height_px_does_not_raise(self):
        raw = _minimal_raw(height_px=600)
        path = _write_yaml(raw)
        try:
            from charts.config import load_grid_config
            cfg = load_grid_config(path)
            self.assertEqual(cfg.height_px, 600)
        finally:
            os.unlink(path)
