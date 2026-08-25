"""Tests for sheets CLI commands."""

from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _gen_args(**overrides) -> argparse.Namespace:
    defaults = {"yaml_file": "workbook.yaml", "output": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _val_args(**overrides) -> argparse.Namespace:
    defaults = {"yaml_file": "workbook.yaml"}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestCmdGenerate(unittest.TestCase):
    def test_missing_yaml_returns_1(self):
        from sheets.cli import cmd_generate
        result = cmd_generate(_gen_args(yaml_file="/no/such/file.yaml"))
        self.assertEqual(result, 1)

    def test_generate_success_with_explicit_output(self):
        import yaml
        from sheets.cli import cmd_generate
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"title": "T", "sheets": []}, f)
            yaml_path = f.name

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                out = str(Path(tmpdir) / "out.xlsx")
                args = _gen_args(yaml_file=yaml_path, output=out)
                result = cmd_generate(args)
                self.assertEqual(result, 0)
                self.assertTrue(Path(out).exists())
        finally:
            Path(yaml_path).unlink()

    def test_invalid_yaml_returns_1(self):
        from sheets.cli import cmd_generate
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(": invalid: yaml: : :")
            yaml_path = f.name
        try:
            result = cmd_generate(_gen_args(yaml_file=yaml_path))
            self.assertEqual(result, 1)
        finally:
            Path(yaml_path).unlink()

    def test_generate_default_output_path(self):
        """Without -o, output goes to output_dir('sheets')."""
        import yaml
        from sheets.cli import cmd_generate
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"title": "T", "sheets": []}, f)
            yaml_path = f.name

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # cmd_generate imports output_dir inside the function, so the
                # patch must target the definition site, not sheets.cli.
                with patch("core.paths.output_dir", return_value=Path(tmpdir)):
                    args = _gen_args(yaml_file=yaml_path, output=None)
                    result = cmd_generate(args)
                    self.assertEqual(result, 0)
        finally:
            Path(yaml_path).unlink()


class TestCmdValidate(unittest.TestCase):
    def test_missing_yaml_returns_1(self):
        from sheets.cli import cmd_validate
        result = cmd_validate(_val_args(yaml_file="/no/file.yaml"))
        self.assertEqual(result, 1)

    def test_valid_yaml_returns_0(self):
        import yaml
        from sheets.cli import cmd_validate
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"title": "Report", "author": "Alice", "sheets": [
                {"name": "S1", "headers": ["A", "B"], "rows": []}
            ]}, f)
            yaml_path = f.name
        try:
            result = cmd_validate(_val_args(yaml_file=yaml_path))
            self.assertEqual(result, 0)
        finally:
            Path(yaml_path).unlink()

    def test_malformed_yaml_returns_1(self):
        from sheets.cli import cmd_validate
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(": invalid: yaml: : :")
            yaml_path = f.name
        try:
            result = cmd_validate(_val_args(yaml_file=yaml_path))
            self.assertEqual(result, 1)
        finally:
            Path(yaml_path).unlink()
