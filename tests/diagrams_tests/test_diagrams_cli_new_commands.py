"""Tests for new diagrams/cli.py commands and helpers added in the extended CLI.

Covers: _read_input, _write_output, _load_yaml, _validate_non_empty,
_convert_yaml_spec, _build_flowchart_from_spec, _build_sequence_from_spec,
cmd_embed, cmd_health, cmd_from_yaml.
"""

from __future__ import annotations

import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# _read_input
# ---------------------------------------------------------------------------


class TestReadInput(unittest.TestCase):
    def test_missing_file_returns_none_and_prints_to_stderr(self):
        from diagrams.cli import _read_input

        err = StringIO()
        with patch("sys.stderr", err):
            result = _read_input("/no/such/file.mmd")
        self.assertIsNone(result)
        self.assertIn("not found", err.getvalue().lower())

    def test_valid_file_returns_content(self):
        from diagrams.cli import _read_input

        with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False) as f:
            f.write("flowchart LR\n    A-->B")
            path = f.name
        try:
            result = _read_input(path)
            self.assertIsNotNone(result)
            self.assertIn("flowchart", result)
        finally:
            Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# _write_output
# ---------------------------------------------------------------------------


class TestWriteOutput(unittest.TestCase):
    def test_none_output_path_prints_to_stdout(self):
        from diagrams.cli import _write_output

        out = StringIO()
        with patch("sys.stdout", out):
            rc = _write_output("mermaid text", output_path=None)
        self.assertEqual(rc, 0)
        self.assertIn("mermaid text", out.getvalue())

    def test_valid_output_path_writes_file(self):
        from diagrams.cli import _write_output

        with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False) as f:
            path = f.name
        try:
            rc = _write_output("flowchart LR", output_path=path)
            self.assertEqual(rc, 0)
            content = Path(path).read_text()
            self.assertIn("flowchart LR", content)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_unwritable_path_returns_1(self):
        from diagrams.cli import _write_output

        err = StringIO()
        with patch("sys.stderr", err):
            rc = _write_output("content", output_path="/root/cannot_write_here.mmd")
        self.assertEqual(rc, 1)
        self.assertIn("error", err.getvalue().lower())


# ---------------------------------------------------------------------------
# _load_yaml
# ---------------------------------------------------------------------------


class TestLoadYaml(unittest.TestCase):
    def test_valid_yaml_returns_dict(self):
        from diagrams.cli import _load_yaml

        result = _load_yaml("type: flowchart\nnodes:\n  - id: A\n")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("type"), "flowchart")

    def test_malformed_yaml_returns_none(self):
        from diagrams.cli import _load_yaml

        err = StringIO()
        with patch("sys.stderr", err):
            result = _load_yaml("type: flowchart\n  bad_indent: [\nunclosed")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# _validate_non_empty
# ---------------------------------------------------------------------------


class TestValidateNonEmpty(unittest.TestCase):
    def test_empty_string_returns_false(self):
        from diagrams.cli import _validate_non_empty

        err = StringIO()
        with patch("sys.stderr", err):
            result = _validate_non_empty("   ")
        self.assertFalse(result)

    def test_non_empty_string_returns_true(self):
        from diagrams.cli import _validate_non_empty

        result = _validate_non_empty("flowchart LR")
        self.assertTrue(result)


# ---------------------------------------------------------------------------
# _convert_yaml_spec
# ---------------------------------------------------------------------------


class TestConvertYamlSpec(unittest.TestCase):
    def test_unsupported_diagram_type_returns_none_and_1(self):
        from diagrams.cli import _convert_yaml_spec

        err = StringIO()
        with patch("sys.stderr", err):
            text, code = _convert_yaml_spec({"type": "gantt"})
        self.assertIsNone(text)
        self.assertEqual(code, 1)
        self.assertIn("Unsupported", err.getvalue())

    def test_flowchart_type_returns_mermaid_text_and_0(self):
        from diagrams.cli import _convert_yaml_spec

        spec = {
            "type": "flowchart",
            "nodes": [{"id": "A", "label": "Start"}, {"id": "B", "label": "End"}],
            "edges": [{"source": "A", "target": "B"}],
        }
        text, code = _convert_yaml_spec(spec)
        self.assertEqual(code, 0)
        self.assertIsNotNone(text)
        self.assertIn("flowchart", text)

    def test_sequence_type_returns_mermaid_text_and_0(self):
        from diagrams.cli import _convert_yaml_spec

        spec = {
            "type": "sequence",
            "participants": [{"id": "A"}, {"id": "B"}],
            "messages": [{"sender": "A", "receiver": "B", "text": "Hello"}],
        }
        text, code = _convert_yaml_spec(spec)
        self.assertEqual(code, 0)
        self.assertIsNotNone(text)
        self.assertIn("sequenceDiagram", text)


# ---------------------------------------------------------------------------
# _build_flowchart_from_spec
# ---------------------------------------------------------------------------


class TestBuildFlowchartFromSpec(unittest.TestCase):
    def test_direction_nodes_edges_produce_valid_mermaid(self):
        from diagrams.cli import _build_flowchart_from_spec

        spec = {
            "direction": "LR",
            "nodes": [
                {"id": "S", "label": "Start"},
                {"id": "E", "label": "End"},
            ],
            "edges": [
                {"source": "S", "target": "E", "label": "goes to"},
            ],
        }
        result = _build_flowchart_from_spec(spec)
        self.assertIn("flowchart", result)
        self.assertIn("S", result)
        self.assertIn("E", result)

    def test_empty_spec_still_returns_flowchart(self):
        from diagrams.cli import _build_flowchart_from_spec

        result = _build_flowchart_from_spec({})
        self.assertIn("flowchart", result)


# ---------------------------------------------------------------------------
# _build_sequence_from_spec
# ---------------------------------------------------------------------------


class TestBuildSequenceFromSpec(unittest.TestCase):
    def test_participants_and_messages_produce_valid_mermaid(self):
        from diagrams.cli import _build_sequence_from_spec

        spec = {
            "participants": [{"id": "A", "label": "Alice"}, {"id": "B", "label": "Bob"}],
            "messages": [{"sender": "A", "receiver": "B", "text": "Hi"}],
        }
        result = _build_sequence_from_spec(spec)
        self.assertIn("sequenceDiagram", result)
        self.assertIn("A", result)
        self.assertIn("B", result)

    def test_empty_spec_still_returns_sequence_diagram(self):
        from diagrams.cli import _build_sequence_from_spec

        result = _build_sequence_from_spec({})
        self.assertIn("sequenceDiagram", result)


# ---------------------------------------------------------------------------
# cmd_embed
# ---------------------------------------------------------------------------


class TestCmdEmbed(unittest.TestCase):
    def _make_args(self, input_path, output=None, from_yaml=False):
        args = MagicMock()
        args.input = input_path
        args.output = output
        args.from_yaml = from_yaml
        return args

    def test_valid_mmd_input_exits_0_with_fence(self):
        from diagrams.cli import cmd_embed

        with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False) as f:
            f.write("flowchart LR\n    A-->B")
            path = f.name
        try:
            out = StringIO()
            with patch("sys.stdout", out):
                rc = cmd_embed(self._make_args(input_path=path))
            self.assertEqual(rc, 0)
            self.assertIn("```mermaid", out.getvalue())
            self.assertIn("flowchart", out.getvalue())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_missing_input_file_returns_1(self):
        from diagrams.cli import cmd_embed

        err = StringIO()
        with patch("sys.stderr", err):
            rc = cmd_embed(self._make_args(input_path="/no/such/file.mmd"))
        self.assertEqual(rc, 1)


# ---------------------------------------------------------------------------
# cmd_health
# ---------------------------------------------------------------------------


class TestCmdHealth(unittest.TestCase):
    def _make_args(self, skip_render=True):
        args = MagicMock()
        args.skip_render = skip_render
        return args

    def test_builder_fails_returns_1(self):
        from diagrams.cli import cmd_health

        with patch("diagrams.mermaid.FlowchartBuilder.render", side_effect=RuntimeError("broken")):
            rc = cmd_health(self._make_args())
        self.assertEqual(rc, 1)

    def test_all_checks_pass_returns_0(self):
        from diagrams.cli import cmd_health

        # skip_render=True bypasses LocalRenderer; builder + TextRenderer are real
        rc = cmd_health(self._make_args(skip_render=True))
        self.assertEqual(rc, 0)

    def test_local_renderer_fail_returns_1(self):
        from diagrams.cli import cmd_health
        from diagrams.renderers import LocalRendererError

        with patch("diagrams.renderers.LocalRenderer", side_effect=LocalRendererError("mmdc not found")):
            rc = cmd_health(self._make_args(skip_render=False))
        self.assertEqual(rc, 1)


# ---------------------------------------------------------------------------
# cmd_from_yaml
# ---------------------------------------------------------------------------


class TestCmdFromYaml(unittest.TestCase):
    def _make_args(self, input_path, output=None, embedded=False):
        args = MagicMock()
        args.input = input_path
        args.output = output
        args.embedded = embedded
        return args

    def test_valid_flowchart_yaml_exits_0_with_mermaid_output(self):
        from diagrams.cli import cmd_from_yaml

        yaml_content = (
            "type: flowchart\n"
            "nodes:\n"
            "  - id: A\n"
            "    label: Start\n"
            "  - id: B\n"
            "    label: End\n"
            "edges:\n"
            "  - source: A\n"
            "    target: B\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name
        try:
            out = StringIO()
            with patch("sys.stdout", out):
                rc = cmd_from_yaml(self._make_args(input_path=path))
            self.assertEqual(rc, 0)
            self.assertIn("flowchart", out.getvalue())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_missing_input_file_returns_1(self):
        from diagrams.cli import cmd_from_yaml

        err = StringIO()
        with patch("sys.stderr", err):
            rc = cmd_from_yaml(self._make_args(input_path="/no/such/spec.yaml"))
        self.assertEqual(rc, 1)

    def test_unsupported_type_returns_nonzero(self):
        from diagrams.cli import cmd_from_yaml

        yaml_content = "type: gantt\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name
        try:
            err = StringIO()
            with patch("sys.stderr", err):
                rc = cmd_from_yaml(self._make_args(input_path=path))
            self.assertNotEqual(rc, 0)
        finally:
            Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
