"""Tests for diagrams/cli_yaml.py — YAML-to-Mermaid conversion helpers."""

from __future__ import annotations

import unittest
from io import StringIO
from unittest.mock import patch

import builtins
_real_import = builtins.__import__


def _import_no_yaml(name: str, *args, **kwargs):
    if name == "yaml":
        raise ImportError("no module named yaml")
    return _real_import(name, *args, **kwargs)


class TestLoadYamlHappyPath(unittest.TestCase):
    def test_parses_valid_yaml_dict(self):
        from diagrams.cli_yaml import _load_yaml

        result = _load_yaml("type: flowchart\ntitle: Hello")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["type"], "flowchart")

    def test_parses_valid_yaml_list(self):
        from diagrams.cli_yaml import _load_yaml

        result = _load_yaml("- a\n- b")
        self.assertEqual(result, ["a", "b"])


class TestLoadYamlImportError(unittest.TestCase):
    """Simulate PyYAML absent — the fallback path uses json.loads."""

    def test_falls_back_to_json_on_import_error(self):
        from diagrams.cli_yaml import _load_yaml

        with patch("builtins.__import__", side_effect=_import_no_yaml):
            result = _load_yaml('{"type": "flowchart"}')
        self.assertIsInstance(result, dict)
        self.assertEqual(result["type"], "flowchart")

    def test_json_parse_error_returns_none_and_prints_error(self):
        from diagrams.cli_yaml import _load_yaml

        stderr = StringIO()
        with patch("builtins.__import__", side_effect=_import_no_yaml):
            with patch("sys.stderr", stderr):
                result = _load_yaml("not valid json {{{{")
        self.assertIsNone(result)
        self.assertIn("Error parsing input", stderr.getvalue())


class TestLoadYamlParseError(unittest.TestCase):
    def test_invalid_yaml_returns_none_and_prints_error(self):
        from diagrams.cli_yaml import _load_yaml

        # Tabs mixed with spaces trigger a YAML scanner error.
        bad_yaml = "key:\t value"
        stderr = StringIO()
        with patch("sys.stderr", stderr):
            result = _load_yaml(bad_yaml)
        self.assertIsNone(result)
        self.assertIn("Error parsing YAML", stderr.getvalue())


class TestBuildFlowchartFromSpec(unittest.TestCase):
    def _base_spec(self) -> dict:
        return {
            "type": "flowchart",
            "nodes": [{"id": "A", "label": "Start"}],
            "edges": [],
        }

    def test_happy_path_no_title(self):
        from diagrams.cli_yaml import _build_flowchart_from_spec

        result = _build_flowchart_from_spec(self._base_spec())
        self.assertIn("flowchart", result)
        self.assertIn("A", result)

    def test_with_title_branch_taken(self):
        from diagrams.cli_yaml import _build_flowchart_from_spec

        spec = self._base_spec()
        spec["title"] = "My Diagram"
        result = _build_flowchart_from_spec(spec)
        self.assertIn("My Diagram", result)

    def test_with_direction_branch_taken(self):
        from diagrams.cli_yaml import _build_flowchart_from_spec

        spec = self._base_spec()
        spec["direction"] = "LR"
        result = _build_flowchart_from_spec(spec)
        self.assertIn("LR", result)


class TestBuildSequenceFromSpec(unittest.TestCase):
    def _base_spec(self) -> dict:
        return {
            "type": "sequence",
            "participants": [{"id": "A"}, {"id": "B"}],
            "messages": [{"sender": "A", "receiver": "B", "text": "hello"}],
        }

    def test_happy_path_no_title_no_autonumber(self):
        from diagrams.cli_yaml import _build_sequence_from_spec

        result = _build_sequence_from_spec(self._base_spec())
        self.assertIn("sequenceDiagram", result)
        self.assertIn("A", result)

    def test_with_title_branch_taken(self):
        from diagrams.cli_yaml import _build_sequence_from_spec

        spec = self._base_spec()
        spec["title"] = "Auth Flow"
        result = _build_sequence_from_spec(spec)
        self.assertIn("Auth Flow", result)

    def test_autonumber_branch_taken(self):
        from diagrams.cli_yaml import _build_sequence_from_spec

        spec = self._base_spec()
        spec["autonumber"] = True
        result = _build_sequence_from_spec(spec)
        self.assertIn("autonumber", result)


class TestConvertYamlSpec(unittest.TestCase):
    def test_non_dict_returns_none_exit_1(self):
        from diagrams.cli_yaml import _convert_yaml_spec

        stderr = StringIO()
        with patch("sys.stderr", stderr):
            text, code = _convert_yaml_spec(["not", "a", "dict"])
        self.assertIsNone(text)
        self.assertEqual(code, 1)
        self.assertIn("must be a dictionary", stderr.getvalue())

    def test_unsupported_type_returns_none_exit_1(self):
        from diagrams.cli_yaml import _convert_yaml_spec

        stderr = StringIO()
        with patch("sys.stderr", stderr):
            text, code = _convert_yaml_spec({"type": "barchart"})
        self.assertIsNone(text)
        self.assertEqual(code, 1)
        self.assertIn("Unsupported diagram type", stderr.getvalue())

    def test_unsupported_type_lists_supported(self):
        from diagrams.cli_yaml import _convert_yaml_spec

        stderr = StringIO()
        with patch("sys.stderr", stderr):
            _convert_yaml_spec({"type": "unknown"})
        self.assertIn("Supported types", stderr.getvalue())

    def test_happy_flowchart_returns_text_exit_0(self):
        from diagrams.cli_yaml import _convert_yaml_spec

        spec = {
            "type": "flowchart",
            "nodes": [{"id": "X"}],
            "edges": [],
        }
        text, code = _convert_yaml_spec(spec)
        self.assertIsNotNone(text)
        self.assertEqual(code, 0)
        self.assertIn("flowchart", text)

    def test_missing_required_field_keyerror_returns_none_exit_1(self):
        from diagrams.cli_yaml import _convert_yaml_spec

        # edges entries require 'source' and 'target'; omitting them raises KeyError
        spec = {
            "type": "flowchart",
            "nodes": [{"id": "A"}],
            "edges": [{"label": "no source or target"}],
        }
        stderr = StringIO()
        with patch("sys.stderr", stderr):
            text, code = _convert_yaml_spec(spec)
        self.assertIsNone(text)
        self.assertEqual(code, 1)
        self.assertIn("Missing required field", stderr.getvalue())

    def test_builder_generic_exception_returns_none_exit_1(self):
        from diagrams.cli_yaml import _convert_yaml_spec

        def bad_builder(spec: dict) -> str:
            raise RuntimeError("boom")

        stderr = StringIO()
        with patch("diagrams.cli_yaml._SPEC_BUILDERS", {"boom": bad_builder}):
            with patch("sys.stderr", stderr):
                text, code = _convert_yaml_spec({"type": "boom"})
        self.assertIsNone(text)
        self.assertEqual(code, 1)
        self.assertIn("Error building diagram", stderr.getvalue())

    def test_happy_sequence_returns_text_exit_0(self):
        from diagrams.cli_yaml import _convert_yaml_spec

        spec = {
            "type": "sequence",
            "participants": [{"id": "A"}, {"id": "B"}],
            "messages": [{"sender": "A", "receiver": "B", "text": "ping"}],
        }
        text, code = _convert_yaml_spec(spec)
        self.assertIsNotNone(text)
        self.assertEqual(code, 0)
        self.assertIn("sequenceDiagram", text)

    def test_graph_alias_resolves_to_flowchart(self):
        from diagrams.cli_yaml import _convert_yaml_spec

        spec = {"type": "graph", "nodes": [{"id": "N"}], "edges": []}
        text, code = _convert_yaml_spec(spec)
        self.assertIsNotNone(text)
        self.assertEqual(code, 0)
        self.assertIn("flowchart", text)
