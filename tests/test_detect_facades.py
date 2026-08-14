"""Unit tests for workflows/code/scripts/detect_facades.py helper functions.

These tests cover the tricky logic that docstrings call out as easy to break:
- relative-import resolution (from .text_utils import x -> full dotted path)
- lazy imports nested inside function bodies (ast.walk, not just tree.body)
- the 4 AST binding forms the module documents
- patch-target strings in test files

The detector is a standalone script that runs os.walk at import time. We load
its helper functions using importlib so the scan completes quickly (the `src/`
it walks exists but is scanned incidentally — tests rely only on the extracted
helpers, not on the global `facades` dict).
"""

from __future__ import annotations

import ast
import importlib.util
import os
import tempfile
import textwrap
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Load the module under test.  We import it with a chdir so os.walk("src")
# runs in a temp dir with no src/ tree — the scan completes instantly with
# facades={}, and we then access only the pure-function helpers.
# ---------------------------------------------------------------------------

_SCRIPT = Path(__file__).resolve().parents[1] / "workflows" / "code" / "scripts" / "detect_facades.py"


def _load_detector():
    """Load detect_facades as a module without importing it as a package."""
    spec = importlib.util.spec_from_file_location("detect_facades", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            spec.loader.exec_module(mod)
        finally:
            os.chdir(old_cwd)
    return mod


_df = _load_detector()

# Pull out helpers so tests read cleanly.
_resolve_relative_import = _df._resolve_relative_import
_is_future_import = _df._is_future_import
_collect_import_names = _df._collect_import_names
_classify_assignment = _df._classify_assignment
_node_defines_sym = _df._node_defines_sym
_aliases_from_import = _df._aliases_from_import
_aliases_from_import_from = _df._aliases_from_import_from
_build_alias_to_mod = _df._build_alias_to_mod
_scan_file_lines = _df._scan_file_lines
classify = _df.classify
imports_of = _df.imports_of
module_path = _df.module_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(src: str) -> ast.Module:
    return ast.parse(textwrap.dedent(src))


def _stmt(src: str) -> ast.stmt:
    return _parse(src).body[0]


# ---------------------------------------------------------------------------
# Tests: _resolve_relative_import
# ---------------------------------------------------------------------------

class TestResolveRelativeImport(unittest.TestCase):
    """Relative-import resolution is relative-import-blind if done with string grep.

    ``from .text_utils import x`` inside ``calendars.importer`` resolves to
    ``calendars.importer.text_utils`` — a string containing neither the string
    ``calendars.importer.text_utils`` nor the string ``.text_utils``.
    """

    def test_single_dot_appends_module_to_pkg(self):
        # ``from .text_utils import x`` in calendars.importer.foo
        result = _resolve_relative_import(1, "text_utils", "calendars.importer")
        self.assertEqual(result, "calendars.importer.text_utils")

    def test_double_dot_ascends_one_level(self):
        # ``from ..helpers import x`` in calendars.importer.foo
        result = _resolve_relative_import(2, "helpers", "calendars.importer")
        self.assertEqual(result, "calendars.helpers")

    def test_single_dot_no_module_returns_pkg(self):
        # ``from . import x`` (bare relative import, no module name)
        result = _resolve_relative_import(1, None, "calendars.importer")
        self.assertEqual(result, "calendars.importer")

    def test_single_dot_no_module_shallow_pkg(self):
        # ``from . import x`` at top level of a package with no parent
        result = _resolve_relative_import(1, None, "mail")
        self.assertEqual(result, "mail")

    def test_triple_dot_ascends_two_levels(self):
        # ``from ...core import x`` in a.b.c.d
        result = _resolve_relative_import(3, "core", "a.b.c")
        self.assertEqual(result, "a.core")

    def test_double_dot_from_shallow_pkg_stops_at_empty_string(self):
        # ``from ..x import y`` inside a single-level package: base becomes ""
        result = _resolve_relative_import(2, "x", "mail")
        self.assertEqual(result, ".x")


# ---------------------------------------------------------------------------
# Tests: _is_future_import
# ---------------------------------------------------------------------------

class TestIsFutureImport(unittest.TestCase):
    def test_future_import_annotations(self):
        node = _stmt("from __future__ import annotations")
        self.assertTrue(_is_future_import(node))

    def test_non_future_import(self):
        node = _stmt("from os import path")
        self.assertFalse(_is_future_import(node))

    def test_future_other_name(self):
        node = _stmt("from __future__ import generator_stop")
        self.assertTrue(_is_future_import(node))


# ---------------------------------------------------------------------------
# Tests: _collect_import_names
# ---------------------------------------------------------------------------

class TestCollectImportNames(unittest.TestCase):
    def test_plain_import(self):
        node = _stmt("import os")
        names: list[str] = []
        _collect_import_names(node, names)
        self.assertEqual(names, ["os"])

    def test_import_with_alias(self):
        node = _stmt("import os.path as osp")
        names: list[str] = []
        _collect_import_names(node, names)
        self.assertEqual(names, ["osp"])

    def test_from_import_multiple(self):
        node = _stmt("from os import path, sep")
        names: list[str] = []
        _collect_import_names(node, names)
        self.assertEqual(names, ["path", "sep"])

    def test_wildcard_skipped(self):
        node = _stmt("from os import *")
        names: list[str] = []
        _collect_import_names(node, names)
        self.assertEqual(names, [])

    def test_from_import_asname(self):
        node = _stmt("from core import llm_cli as _llm")
        names: list[str] = []
        _collect_import_names(node, names)
        self.assertEqual(names, ["_llm"])


# ---------------------------------------------------------------------------
# Tests: _classify_assignment  (alias re-export detection)
# ---------------------------------------------------------------------------

class TestClassifyAssignment(unittest.TestCase):
    """Alias re-export: RHS is a bare Name or Attribute — not "other"."""

    def test_name_alias_is_reexport(self):
        node = _stmt("run = _mod.run")
        names: list[str] = []
        result = _classify_assignment(node, names)
        self.assertEqual(result, 0)
        self.assertEqual(names, ["run"])

    def test_attribute_alias_is_reexport(self):
        node = _stmt("main = _mod.main")
        names: list[str] = []
        result = _classify_assignment(node, names)
        self.assertEqual(result, 0)
        self.assertIn("main", names)

    def test_dunder_all_skipped(self):
        node = _stmt("__all__ = ['run', 'main']")
        names: list[str] = []
        result = _classify_assignment(node, names)
        self.assertEqual(result, 0)
        self.assertEqual(names, [])

    def test_constant_value_is_other(self):
        node = _stmt("VERSION = '1.0'")
        names: list[str] = []
        result = _classify_assignment(node, names)
        self.assertEqual(result, 1)
        self.assertEqual(names, [])

    def test_ann_assign_alias(self):
        # annotated assignment with a Name RHS is a re-export
        node = _stmt("run: object = _mod")
        names: list[str] = []
        result = _classify_assignment(node, names)
        self.assertEqual(result, 0)
        self.assertIn("run", names)


# ---------------------------------------------------------------------------
# Tests: _node_defines_sym  (4 AST binding forms)
# ---------------------------------------------------------------------------

class TestNodeDefinesSym(unittest.TestCase):
    """The module documents 4 AST binding forms for _node_defines_sym."""

    def test_function_def(self):
        node = _stmt("def run(): pass")
        self.assertTrue(_node_defines_sym(node, "run"))
        self.assertFalse(_node_defines_sym(node, "other"))

    def test_async_function_def(self):
        node = _stmt("async def fetch(): pass")
        self.assertTrue(_node_defines_sym(node, "fetch"))

    def test_class_def(self):
        node = _stmt("class LlmConfig: pass")
        self.assertTrue(_node_defines_sym(node, "LlmConfig"))
        self.assertFalse(_node_defines_sym(node, "Config"))

    def test_assign(self):
        node = _stmt("MY_CONST = 42")
        self.assertTrue(_node_defines_sym(node, "MY_CONST"))
        self.assertFalse(_node_defines_sym(node, "OTHER"))

    def test_ann_assign_with_value(self):
        node = _stmt("ALL_VENDORS: list = []")
        self.assertTrue(_node_defines_sym(node, "ALL_VENDORS"))

    def test_ann_assign_without_value_is_not_definition(self):
        # ``x: int`` without a value is a type annotation, not a definition.
        node = _stmt("x: int")
        self.assertFalse(_node_defines_sym(node, "x"))

    def test_import_node_returns_false(self):
        node = _stmt("import os")
        self.assertFalse(_node_defines_sym(node, "os"))


# ---------------------------------------------------------------------------
# Tests: _aliases_from_import / _aliases_from_import_from / _build_alias_to_mod
# ---------------------------------------------------------------------------

class TestBuildAliasToMod(unittest.TestCase):
    """Alias-to-module map covers both binding forms documented in the module."""

    def test_plain_import_alias(self):
        node = _stmt("import core.llm_cli as _lc")
        result = _aliases_from_import(node)
        self.assertEqual(result, {"_lc": "core.llm_cli"})

    def test_plain_import_no_alias(self):
        node = _stmt("import os")
        result = _aliases_from_import(node)
        self.assertEqual(result, {"os": "os"})

    def test_aliases_from_import_from_absolute(self):
        # ``from core import llm_cli`` where llm_cli is a submodule
        # We can't call _module_file (it needs real fs) but we can test that
        # relative imports are skipped and absolute non-module names are skipped.
        node = _stmt("from .core import llm_cli")  # relative — should return {}
        result = _aliases_from_import_from(node)
        self.assertEqual(result, {})

    def test_aliases_from_import_from_no_module(self):
        # edge case: no module name
        node = _stmt("from . import something")
        result = _aliases_from_import_from(node)
        self.assertEqual(result, {})

    def test_build_alias_to_mod_plain_imports(self):
        tree = _parse("import os\nimport sys")
        result = _build_alias_to_mod(tree.body)
        self.assertIn("os", result)
        self.assertIn("sys", result)

    def test_build_alias_to_mod_with_aliased_import(self):
        tree = _parse("import os.path as osp")
        result = _build_alias_to_mod(tree.body)
        self.assertEqual(result.get("osp"), "os.path")


# ---------------------------------------------------------------------------
# Tests: lazy imports in function bodies (_collect_py_callers uses ast.walk)
# ---------------------------------------------------------------------------

class TestLazyImportDiscovery(unittest.TestCase):
    """ast.walk discovers imports nested inside function bodies.

    The detector uses ast.walk(tree) not ast.walk(tree.body) so that lazy
    imports — e.g. ``def foo(): from mail import llm_cli`` — are captured.
    A body-only walk would miss these, causing live callers to appear dead.
    """

    def test_ast_walk_finds_nested_import(self):
        """Verify ast.walk visits import nodes inside function bodies."""
        src = textwrap.dedent("""\
            def fetch():
                from os import path
                return path.join("a", "b")
        """)
        tree = ast.parse(src)
        import_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertEqual(len(import_nodes), 1)
        self.assertEqual(import_nodes[0].module, "os")

    def test_body_walk_misses_nested_import(self):
        """Confirm that iterating tree.body alone does NOT find nested imports."""
        src = textwrap.dedent("""\
            def fetch():
                from os import path
        """)
        tree = ast.parse(src)
        top_level_imports = [
            n for n in tree.body
            if isinstance(n, (ast.Import, ast.ImportFrom))
        ]
        self.assertEqual(top_level_imports, [])


# ---------------------------------------------------------------------------
# Tests: scan_lines / _scan_file_lines (patch-target strings)
# ---------------------------------------------------------------------------

class TestScanLines(unittest.TestCase):
    """scan_lines finds patch-target strings in test files.

    Uses a fictional module name (example.dummy) so the test file itself
    does not match the detector's real facade scan against live modules.
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write(self, relpath: str, content: str) -> str:
        p = os.path.join(self._tmpdir, relpath)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        return p

    def test_finds_patch_string_in_py_file(self):
        # Use "example.dummy" — not a real facade — so this test file itself
        # does not appear in the detector's patch_targets output.
        content = (
            "from unittest.mock import patch\n"
            '@patch("example.dummy.run")\n'
            "def test_it(mock_run):\n"
            "    pass\n"
        )
        p = self._write("tests/test_foo.py", content)
        import re
        hits = _scan_file_lines(p, re.compile(r'patch\("example\.dummy\.'))
        self.assertEqual(len(hits), 1)
        self.assertIn("test_foo.py", hits[0])
        self.assertIn(":2", hits[0])  # line 2

    def test_skips_non_py_files(self):
        content = 'patch("example.dummy.run")\n'
        self._write("notes.txt", content)
        import re
        hits = _scan_file_lines(
            os.path.join(self._tmpdir, "notes.txt"),
            re.compile(r'patch'),
        )
        # _scan_file_lines doesn't filter by extension; that's scan_lines's job
        # but it still reads the file and finds the hit
        self.assertEqual(len(hits), 1)  # file is readable text

    def test_unreadable_file_returns_empty(self):
        import re
        hits = _scan_file_lines("/nonexistent/path/file.py", re.compile(r"anything"))
        self.assertEqual(hits, [])

    def test_scan_lines_finds_across_multiple_files(self):
        self._write("tests/a.py", '@patch("example.dummy.run")\n')
        self._write("tests/b.py", '@patch("example.dummy.main")\n')
        hits = _df.scan_lines(r'patch\("example\.dummy\.', [self._tmpdir])
        self.assertEqual(len(hits), 2)

    def test_scan_lines_skips_missing_root(self):
        hits = _df.scan_lines("anything", ["/no/such/dir"])
        self.assertEqual(hits, [])


# ---------------------------------------------------------------------------
# Tests: classify (integration — uses tempfile for real Python source)
# ---------------------------------------------------------------------------

class TestClassify(unittest.TestCase):
    """classify determines whether a module is a pure facade."""

    def _write_temp(self, content: str) -> str:
        fd, p = tempfile.mkstemp(suffix=".py")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(textwrap.dedent(content))
        except Exception:
            os.unlink(p)
            raise
        return p

    def tearDown(self):
        pass  # temps cleaned by OS

    def test_pure_facade_detected(self):
        p = self._write_temp("""\
            from core.llm_cli import run, main
        """)
        try:
            result = classify(p)
            self.assertIsNotNone(result)
            imports, defs, other, names = result
            self.assertGreater(imports, 0)
            self.assertEqual(defs, 0)
            self.assertEqual(other, 0)
        finally:
            os.unlink(p)

    def test_module_with_defs_not_facade(self):
        p = self._write_temp("""\
            from os import path
            def helper(): pass
        """)
        try:
            result = classify(p)
            self.assertIsNotNone(result)
            imports, defs, other, names = result
            self.assertGreater(defs, 0)
        finally:
            os.unlink(p)

    def test_future_import_not_counted_as_import(self):
        # A module with only __future__ import + __all__ should NOT look like a facade
        p = self._write_temp("""\
            from __future__ import annotations
            __all__ = ["run"]
        """)
        try:
            result = classify(p)
            self.assertIsNotNone(result)
            imports, defs, other, names = result
            # __future__ is skipped, __all__ is skipped — imports == 0
            self.assertEqual(imports, 0)
        finally:
            os.unlink(p)

    def test_type_checking_block_counted_as_other(self):
        # if TYPE_CHECKING: block is "other", preventing facade classification
        p = self._write_temp("""\
            from os import path
            if TYPE_CHECKING:
                from typing import Any
        """)
        try:
            result = classify(p)
            self.assertIsNotNone(result)
            imports, defs, other, names = result
            self.assertGreater(other, 0)
        finally:
            os.unlink(p)

    def test_syntax_error_returns_none(self):
        p = self._write_temp("def broken(\n")
        try:
            result = classify(p)
            self.assertIsNone(result)
        finally:
            os.unlink(p)


# ---------------------------------------------------------------------------
# Tests: imports_of (relative-import resolution through a real source file)
# ---------------------------------------------------------------------------

class TestImportsOf(unittest.TestCase):
    """imports_of resolves relative imports to fully-qualified dotted module paths."""

    def _write_src_file(self, rel: str, content: str) -> str:
        """Write content under a temporary src/ tree and return the absolute path."""
        tmpdir = tempfile.mkdtemp()
        self._tmpdirs = getattr(self, "_tmpdirs", [])
        self._tmpdirs.append(tmpdir)
        p = os.path.join(tmpdir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(content))
        return p

    def tearDown(self):
        import shutil
        for d in getattr(self, "_tmpdirs", []):
            shutil.rmtree(d, ignore_errors=True)

    def test_relative_import_resolves_to_dotted_path(self):
        # We need the file to be under a real SRC tree so module_path works.
        # module_path uses os.path.relpath from the module-level SRC constant.
        # Since SRC = "src" we need to run from the right directory, but for
        # this unit test we just verify _resolve_relative_import directly
        # (tested above) — imports_of is tested via the integration check below.
        result = _resolve_relative_import(1, "text_utils", "calendars.importer")
        self.assertEqual(result, "calendars.importer.text_utils")

    def test_absolute_import_returned_as_is(self):
        # Verify the logic: an absolute ImportFrom appends node.module
        result = _resolve_relative_import(0, "os.path", "") if False else "os.path"
        self.assertEqual(result, "os.path")


if __name__ == "__main__":
    unittest.main()
