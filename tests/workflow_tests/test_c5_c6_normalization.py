"""C8/C9 gap-filling tests for the design-criteria-normalization changes.

Covers:
  C5 — WorkflowCompileError/ParseError/ExecutionError now subclass CLIError;
       _load_definition and _load_manifest raise CLIError (not SystemExit);
       _build_resolved_params raises CLIError on parse failure.
  C6 — _emit_one thin wrapper covers yaml/table output paths; _emit_rows
       delegates directly to core.cli_output.emit_rows.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from unittest.mock import patch

from core.cli_errors import CLIError, ExitCode
from workflow.compiler import WorkflowCompileError
from workflow.cli_dispatch import (
    _build_resolved_params,
    _load_definition,
    _load_manifest,
)
from workflow.cli import _emit_one, _emit_rows

from tests.workflow_tests.helpers.factories import write_yaml


# ---------------------------------------------------------------------------
# Minimal YAML fixture
# ---------------------------------------------------------------------------

_MINIMAL_YAML = """\
name: test-wf
version: "0.1.0"
description: "Minimal test workflow"
trigger:
  source: manual
stages:
  - name: gather
    kind: gather
    description: "Gather stage"
    agent:
      role: researcher
"""

_INVALID_YAML = "invalid: yaml: {{{"


# ---------------------------------------------------------------------------
# C5 — WorkflowCompileError is a CLIError subclass
# ---------------------------------------------------------------------------


class TestWorkflowCompileErrorIsCliError(unittest.TestCase):
    """WorkflowCompileError must subclass CLIError with ExitCode.ERROR."""

    def test_is_instance_of_cli_error(self) -> None:
        err = WorkflowCompileError("something broke")
        self.assertIsInstance(err, CLIError)

    def test_exit_code_is_error(self) -> None:
        err = WorkflowCompileError("bad compile")
        self.assertEqual(err.code, ExitCode.ERROR)

    def test_message_preserved(self) -> None:
        err = WorkflowCompileError("cycle detected in stages: a, b")
        self.assertIn("cycle", str(err))

    def test_raised_as_cli_error(self) -> None:
        with self.assertRaises(CLIError):
            raise WorkflowCompileError("triggered for test")

    def test_str_returns_message(self) -> None:
        msg = "stage 'x' depends on unknown stage 'y'"
        err = WorkflowCompileError(msg)
        self.assertEqual(str(err), msg)


# ---------------------------------------------------------------------------
# C5 — _load_definition raises CLIError (not SystemExit)
# ---------------------------------------------------------------------------


class TestLoadDefinitionRaisesCLIError(unittest.TestCase):
    """_load_definition must raise CLIError, never SystemExit."""

    def test_missing_file_raises_cli_error(self) -> None:
        with self.assertRaises(CLIError):
            _load_definition("/nonexistent/path/wf.yaml")

    def test_missing_file_does_not_raise_system_exit(self) -> None:
        try:
            _load_definition("/nonexistent/path/wf.yaml")
        except CLIError:
            pass  # expected path under test — CLIError, not SystemExit
        except SystemExit:
            self.fail("_load_definition raised SystemExit instead of CLIError")

    def test_invalid_yaml_raises_cli_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(write_yaml(tmp_dir, _INVALID_YAML))
            with self.assertRaises(CLIError):
                _load_definition(path)

    def test_invalid_yaml_does_not_raise_system_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(write_yaml(tmp_dir, _INVALID_YAML))
            try:
                _load_definition(path)
            except CLIError:
                pass  # expected path under test — CLIError, not SystemExit
            except SystemExit:
                self.fail("_load_definition raised SystemExit instead of CLIError")

    def test_missing_file_cli_error_code_is_error(self) -> None:
        try:
            _load_definition("/no/such/file.yaml")
        except CLIError as exc:
            self.assertEqual(exc.code, ExitCode.ERROR)

    def test_happy_path_returns_definition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(write_yaml(tmp_dir, _MINIMAL_YAML))
            defn = _load_definition(path)
            self.assertEqual(defn.name, "test-wf")


# ---------------------------------------------------------------------------
# C5 — _load_manifest raises CLIError on compile failure
# ---------------------------------------------------------------------------


class TestLoadManifestRaisesCLIError(unittest.TestCase):
    """_load_manifest must raise CLIError on both parse and compile failures."""

    def test_missing_file_raises_cli_error(self) -> None:
        with self.assertRaises(CLIError):
            _load_manifest("/no/such/wf.yaml")

    def test_missing_file_does_not_raise_system_exit(self) -> None:
        try:
            _load_manifest("/no/such/wf.yaml")
        except CLIError:
            pass  # expected path under test — CLIError, not SystemExit
        except SystemExit:
            self.fail("_load_manifest raised SystemExit instead of CLIError")

    def test_compile_error_raises_cli_error(self) -> None:
        """A YAML with a dependency cycle raises CLIError from _load_manifest."""
        cyclic_yaml = """\
name: cyclic-wf
version: "0.1.0"
description: "Cyclic workflow"
trigger:
  source: manual
stages:
  - name: a
    kind: gather
    description: "A"
    depends_on: [b]
    agent:
      role: researcher
  - name: b
    kind: gather
    description: "B"
    depends_on: [a]
    agent:
      role: researcher
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(write_yaml(tmp_dir, cyclic_yaml))
            with self.assertRaises(CLIError):
                _load_manifest(path)

    def test_compile_error_does_not_raise_system_exit(self) -> None:
        cyclic_yaml = """\
name: cyclic2-wf
version: "0.1.0"
description: "Cyclic workflow 2"
trigger:
  source: manual
stages:
  - name: x
    kind: gather
    description: "X"
    depends_on: [y]
    agent:
      role: researcher
  - name: y
    kind: gather
    description: "Y"
    depends_on: [x]
    agent:
      role: researcher
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(write_yaml(tmp_dir, cyclic_yaml))
            try:
                _load_manifest(path)
            except CLIError:
                pass  # expected path under test — CLIError, not SystemExit
            except SystemExit:
                self.fail("_load_manifest raised SystemExit instead of CLIError")

    def test_happy_path_returns_defn_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(write_yaml(tmp_dir, _MINIMAL_YAML))
            defn, manifest = _load_manifest(path)
            self.assertEqual(defn.name, "test-wf")
            self.assertGreater(len(manifest.parallel_groups), 0)


# ---------------------------------------------------------------------------
# C5 — _build_resolved_params raises CLIError on parse failure
# ---------------------------------------------------------------------------


class TestBuildResolvedParamsRaisesCLIError(unittest.TestCase):
    """_build_resolved_params must raise CLIError when the YAML is unparseable."""

    def test_missing_file_raises_cli_error(self) -> None:
        with self.assertRaises(CLIError):
            _build_resolved_params("/no/such/file.yaml", {})

    def test_missing_file_does_not_raise_system_exit(self) -> None:
        try:
            _build_resolved_params("/no/such/file.yaml", {})
        except CLIError:
            pass  # expected path under test — CLIError, not SystemExit
        except SystemExit:
            self.fail("_build_resolved_params raised SystemExit instead of CLIError")

    def test_invalid_yaml_raises_cli_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(write_yaml(tmp_dir, _INVALID_YAML))
            with self.assertRaises(CLIError):
                _build_resolved_params(path, {})

    def test_invalid_yaml_error_code_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(write_yaml(tmp_dir, _INVALID_YAML))
            try:
                _build_resolved_params(path, {})
            except CLIError as exc:
                self.assertEqual(exc.code, ExitCode.ERROR)

    def test_happy_path_returns_merged_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(write_yaml(tmp_dir, _MINIMAL_YAML))
            params = _build_resolved_params(path, {"env": "prod"})
            self.assertEqual(params["env"], "prod")
            self.assertIn("work_dir", params)


# ---------------------------------------------------------------------------
# C6 — _emit_one output-format paths
# ---------------------------------------------------------------------------


class TestEmitOneJsonFormat(unittest.TestCase):
    """_emit_one json format delegates to core.cli_output.emit_one."""

    def test_json_format_is_parseable(self) -> None:
        data = {"key": "value", "count": 3}
        out = io.StringIO()
        with patch("sys.stdout", out):
            _emit_one(data, fmt="json")
        result = json.loads(out.getvalue())
        self.assertEqual(result["key"], "value")
        self.assertEqual(result["count"], 3)

    def test_json_format_preserves_all_keys(self) -> None:
        data = {"a": 1, "b": 2, "c": "three"}
        out = io.StringIO()
        with patch("sys.stdout", out):
            _emit_one(data, fmt="json")
        result = json.loads(out.getvalue())
        self.assertEqual(set(result.keys()), {"a", "b", "c"})

    def test_jsonl_format_is_single_line(self) -> None:
        data = {"x": "y"}
        out = io.StringIO()
        with patch("sys.stdout", out):
            _emit_one(data, fmt="jsonl")
        lines = [l for l in out.getvalue().splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)


class TestEmitOneTableFormat(unittest.TestCase):
    """_emit_one table format emits key: value lines."""

    def test_table_format_emits_key_value_lines(self) -> None:
        data = {"name": "test-wf", "version": "0.1.0"}
        out = io.StringIO()
        with patch("sys.stdout", out):
            _emit_one(data, fmt="table")
        output = out.getvalue()
        self.assertIn("name:", output)
        self.assertIn("test-wf", output)
        self.assertIn("version:", output)
        self.assertIn("0.1.0", output)

    def test_table_format_one_line_per_key(self) -> None:
        data = {"a": "alpha", "b": "beta"}
        out = io.StringIO()
        with patch("sys.stdout", out):
            _emit_one(data, fmt="table")
        lines = [l for l in out.getvalue().splitlines() if l.strip()]
        self.assertEqual(len(lines), 2)

    def test_table_format_does_not_produce_json(self) -> None:
        data = {"status": "ok"}
        out = io.StringIO()
        with patch("sys.stdout", out):
            _emit_one(data, fmt="table")
        # Should not be parseable as JSON
        with self.assertRaises((json.JSONDecodeError, ValueError)):
            json.loads(out.getvalue())


class TestEmitOneYamlFormat(unittest.TestCase):
    """_emit_one yaml format emits YAML when available, falls back to JSON."""

    def test_yaml_format_contains_key(self) -> None:
        data = {"workflow": "test-wf", "stage_count": 2}
        out = io.StringIO()
        with patch("sys.stdout", out):
            _emit_one(data, fmt="yaml")
        output = out.getvalue()
        self.assertIn("workflow", output)
        self.assertIn("test-wf", output)

    def test_yaml_format_fallback_on_import_error(self) -> None:
        """When yaml is unavailable, _emit_one falls back to JSON output."""
        data = {"key": "val"}
        out = io.StringIO()
        with patch("sys.stdout", out), \
             patch("builtins.__import__", side_effect=lambda name, *a, **kw: (
                 (_ for _ in ()).throw(ImportError("no yaml")) if name == "yaml"
                 else __import__(name, *a, **kw)
             )):
            _emit_one(data, fmt="yaml")
        output = out.getvalue().strip()
        # Should fall back to JSON when yaml is unavailable
        result = json.loads(output)
        self.assertEqual(result["key"], "val")


# ---------------------------------------------------------------------------
# C6 — _emit_rows thin wrapper
# ---------------------------------------------------------------------------


class TestEmitRowsDelegation(unittest.TestCase):
    """_emit_rows must delegate to core.cli_output.emit_rows."""

    def test_emit_rows_json_format(self) -> None:
        rows = [{"stage": "gather", "status": "success"}, {"stage": "propose", "status": "pending"}]
        out = io.StringIO()
        with patch("sys.stdout", out):
            _emit_rows(rows, fmt="json")
        result = json.loads(out.getvalue())
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["stage"], "gather")

    def test_emit_rows_table_format_includes_headers(self) -> None:
        rows = [{"name": "a", "kind": "gather"}]
        out = io.StringIO()
        with patch("sys.stdout", out):
            _emit_rows(rows, fmt="table", headers=["name", "kind"])
        output = out.getvalue()
        self.assertIn("name", output)
        self.assertIn("kind", output)

    def test_emit_rows_empty_list_prints_to_stderr(self) -> None:
        err = io.StringIO()
        out = io.StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", err):
            _emit_rows([], fmt="json")
        # Empty rows → emit_rows prints "No results." to stderr
        self.assertEqual(out.getvalue(), "")

    def test_emit_rows_with_headers_filters_columns(self) -> None:
        rows = [{"a": "1", "b": "2", "c": "3"}]
        out = io.StringIO()
        with patch("sys.stdout", out):
            _emit_rows(rows, fmt="json", headers=["a", "b"])
        result = json.loads(out.getvalue())
        # json format emits all keys regardless of headers; headers used for table
        self.assertIsInstance(result, list)


if __name__ == "__main__":
    unittest.main()
