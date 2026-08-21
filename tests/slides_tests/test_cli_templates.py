"""Tests for slides.cli.cmd_templates and _list_pptx_layouts.

Rewritten against the dest CLIApp decorator pattern: source's
SlidesCLI._cmd_templates bound method and SlidesCLI._list_pptx_layouts
staticmethod have no equivalent class here. slides.cli exposes module-level
cmd_templates(args) -> int and _list_pptx_layouts(path) functions instead.

Per cli-surface.md's resolved gap: dest's core.cli_output.emit_rows has no
text_fn parameter, and "text" was never a declared --format choice in source
either (source's own add_format_argument call only declares
table/json/yaml). TestSlidesCLICmdTemplatesTextFn exercised an
argparse-unreachable path -- it is dropped, not ported, per the design doc's
explicit resolution.

test_yaml_format_outputs_layouts is ported UNMODIFIED (see class below) --
it is the oracle for the CLI's real-YAML --format yaml branch.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import capture_stdout

from slides.cli import cmd_templates, _list_pptx_layouts


def _make_templates_args(**overrides: object):
    """Create a Namespace for cmd_templates with all required attributes."""
    import argparse

    defaults = {
        "pptx": "template.pptx",
        "format": "table",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _create_minimal_pptx(path: str, layout_names: list[str] | None = None) -> None:
    """Create a minimal PPTX ZIP file with slide layout XML entries."""
    if layout_names is None:
        layout_names = ["Title Slide", "Title and Content"]

    with zipfile.ZipFile(path, "w") as zf:
        for idx, name in enumerate(layout_names, 1):
            xml_content = (
                f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<p:cSld name="{name}"><p:spTree/></p:cSld>'
            ).encode()
            zf.writestr(f"ppt/slideLayouts/slideLayout{idx}.xml", xml_content)


class TestCmdTemplates(unittest.TestCase):
    """Tests for cmd_templates with valid PPTX files."""

    def test_table_format_lists_layouts(self):
        """cmd_templates with table format prints layout names."""
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            pptx_path = f.name

        try:
            _create_minimal_pptx(pptx_path, ["Title Slide", "Blank"])
            args = _make_templates_args(pptx=pptx_path, format="table")

            with capture_stdout() as buf:
                result = cmd_templates(args)

            self.assertEqual(result, 0)
            output = buf.getvalue()
            self.assertIn("Title Slide", output)
            self.assertIn("Blank", output)
            self.assertIn("name", output)
            self.assertIn("rel", output)
        finally:
            os.unlink(pptx_path)

    def test_json_format_outputs_valid_json(self):
        """cmd_templates with json format outputs valid JSON with layouts."""
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            pptx_path = f.name

        try:
            _create_minimal_pptx(pptx_path, ["Title Slide", "Content"])
            args = _make_templates_args(pptx=pptx_path, format="json")

            with capture_stdout() as buf:
                result = cmd_templates(args)

            self.assertEqual(result, 0)
            output = buf.getvalue()
            data = json.loads(output)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 2)
            names = [layout["name"] for layout in data]
            self.assertIn("Title Slide", names)
            self.assertIn("Content", names)
        finally:
            os.unlink(pptx_path)

    def test_yaml_format_outputs_layouts(self):
        """cmd_templates with yaml format outputs layout data.

        PORTED UNMODIFIED per port-tests-cli stage spec: asserts "name:" (a
        colon-suffixed YAML mapping key) which no table-rendering fallback
        path can produce. If this fails, the CLI's --format yaml branch is
        not emitting real YAML -- that is a CLI bug to report, not a reason
        to weaken this assertion.
        """
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            pptx_path = f.name

        try:
            _create_minimal_pptx(pptx_path, ["Title Only"])
            args = _make_templates_args(pptx=pptx_path, format="yaml")

            with capture_stdout() as buf:
                result = cmd_templates(args)

            self.assertEqual(result, 0)
            output = buf.getvalue()
            self.assertIn("Title Only", output)
            self.assertIn("name:", output)
        finally:
            os.unlink(pptx_path)


class TestCmdTemplatesErrors(unittest.TestCase):
    """Tests for cmd_templates error cases."""

    def test_nonexistent_file_returns_1(self):
        """cmd_templates returns 1 when PPTX file does not exist."""
        args = _make_templates_args(pptx="/nonexistent/template.pptx")
        result = cmd_templates(args)
        self.assertEqual(result, 1)

    def test_nonexistent_file_prints_error(self):
        """cmd_templates prints error for non-existent file."""
        args = _make_templates_args(pptx="/nonexistent/template.pptx")
        with patch("builtins.print") as mock_print:
            cmd_templates(args)
            printed = [str(c) for c in mock_print.call_args_list]
            joined = "\n".join(printed)
            self.assertIn("File not found", joined)

    def test_invalid_zip_returns_1(self):
        """cmd_templates returns 1 when file is not a valid ZIP/PPTX."""
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            f.write(b"not a zip file")
            bad_path = f.name

        try:
            args = _make_templates_args(pptx=bad_path)
            result = cmd_templates(args)
            self.assertEqual(result, 1)
        finally:
            os.unlink(bad_path)


class TestListPptxLayouts(unittest.TestCase):
    """Tests for _list_pptx_layouts function."""

    def test_extracts_layout_names(self):
        """_list_pptx_layouts extracts layout names from PPTX ZIP."""
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            pptx_path = f.name

        try:
            _create_minimal_pptx(pptx_path, ["Title Slide", "Two Content"])
            layouts = _list_pptx_layouts(Path(pptx_path))

            self.assertEqual(len(layouts), 2)
            self.assertEqual(layouts[0]["name"], "Title Slide")
            self.assertIn("rel", layouts[0])
            self.assertEqual(layouts[1]["name"], "Two Content")
        finally:
            os.unlink(pptx_path)

    def test_empty_pptx_returns_empty_list(self):
        """_list_pptx_layouts returns empty list for PPTX with no layouts."""
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            pptx_path = f.name

        try:
            with zipfile.ZipFile(pptx_path, "w") as zf:
                zf.writestr("ppt/presentation.xml", "<presentation/>")

            layouts = _list_pptx_layouts(Path(pptx_path))
            self.assertEqual(layouts, [])
        finally:
            os.unlink(pptx_path)

    def test_layout_without_name_uses_fallback(self):
        """_list_pptx_layouts uses '(no name)' when layout has no name attribute."""
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            pptx_path = f.name

        try:
            with zipfile.ZipFile(pptx_path, "w") as zf:
                xml = b'<?xml version="1.0"?><p:cSld><p:spTree/></p:cSld>'
                zf.writestr("ppt/slideLayouts/slideLayout1.xml", xml)

            layouts = _list_pptx_layouts(Path(pptx_path))
            self.assertEqual(len(layouts), 1)
            self.assertEqual(layouts[0]["name"], "(no name)")
        finally:
            os.unlink(pptx_path)

    def test_ignores_rels_files(self):
        """_list_pptx_layouts ignores _rels/ entries in slideLayouts."""
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            pptx_path = f.name

        try:
            with zipfile.ZipFile(pptx_path, "w") as zf:
                xml = b'<p:cSld name="Real"><p:spTree/></p:cSld>'
                zf.writestr("ppt/slideLayouts/slideLayout1.xml", xml)
                zf.writestr(
                    "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
                    b"<Relationships/>",
                )

            layouts = _list_pptx_layouts(Path(pptx_path))
            self.assertEqual(len(layouts), 1)
            self.assertEqual(layouts[0]["name"], "Real")
        finally:
            os.unlink(pptx_path)


if __name__ == "__main__":
    unittest.main()
