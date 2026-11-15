"""validate-imports, validate-ast, validate-json."""

from __future__ import annotations

import ast
import os
import tempfile
import unittest
from textwrap import dedent

from agent_helpers.validate import _overall, parse_all_names
from tests.agent_helpers_tests.helpers import run_json, run_main, write
from tests.fixtures import TempDirMixin


class TestValidateImports(unittest.TestCase):
    def test_all_symbols_present(self):
        result = run_json(["validate-imports", "--module", "os.path", "--symbols", "join,exists"])
        self.assertEqual(result["overall"], "PASS")
        self.assertEqual([s["status"] for s in result["symbols"]], ["PASS", "PASS"])

    def test_missing_symbol_fails_only_that_symbol(self):
        result = run_json(
            ["validate-imports", "--module", "os.path", "--symbols", "join,no_such_name"]
        )
        self.assertEqual(result["overall"], "FAIL")
        by_name = {s["name"]: s for s in result["symbols"]}
        self.assertEqual(by_name["join"]["status"], "PASS")
        self.assertEqual(by_name["no_such_name"]["status"], "FAIL")
        self.assertIn("no_such_name", by_name["no_such_name"]["error"])

    def test_unimportable_module_fails_every_symbol(self):
        result = run_json(
            ["validate-imports", "--module", "no_such_module_xyz", "--symbols", "a,b"]
        )
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(len(result["symbols"]), 2)
        self.assertTrue(all("ModuleNotFoundError" in s["error"] for s in result["symbols"]))

    def test_import_order_reports_per_module(self):
        result = run_json(["validate-imports", "--import-order", "os,no_such_module_xyz,sys"])
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual([m["status"] for m in result["modules"]], ["PASS", "FAIL", "PASS"])

    def test_import_order_empty_list_returns_fail(self):
        """_overall([]) must return FAIL, not PASS."""
        result = run_json(["validate-imports", "--import-order", "os,sys"])
        # sanity: non-empty succeeds
        self.assertEqual(result["overall"], "PASS")
        # Directly test _overall with empty list via the library
        self.assertEqual(_overall([]), "FAIL")

    def test_import_order_blank_value_is_usage_error(self):
        """--import-order with only commas (zero modules) exits 2."""
        rc, out, err = run_main(["validate-imports", "--import-order", ","])
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertIn("zero module names", err)

    def test_requires_module_or_import_order(self):
        rc, out, err = run_main(["validate-imports"])
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertIn("--module", err)

    def test_module_requires_symbols(self):
        rc, _out, err = run_main(["validate-imports", "--module", "os"])
        self.assertEqual(rc, 2)
        self.assertIn("--symbols", err)


class TestParseAllNames(unittest.TestCase):
    """parse_all_names: shared __all__ extractor used by validate-ast and analyze-patch."""

    def _tree(self, source: str) -> ast.Module:
        return ast.parse(dedent(source))

    def test_list_assignment(self):
        tree = self._tree('__all__ = ["a", "b"]')
        self.assertEqual(parse_all_names(tree), ["a", "b"])

    def test_tuple_assignment(self):
        tree = self._tree('__all__ = ("a", "b")')
        self.assertEqual(parse_all_names(tree), ["a", "b"])

    def test_annotated_assignment(self):
        tree = self._tree('__all__: list[str] = ["a", "b"]')
        self.assertEqual(parse_all_names(tree), ["a", "b"])

    def test_augmented_assignment_appends(self):
        tree = self._tree('__all__ = ["a"]\n__all__ += ["b"]')
        self.assertEqual(parse_all_names(tree), ["a", "b"])

    def test_no_all_returns_none(self):
        tree = self._tree("x = 1\n")
        self.assertIsNone(parse_all_names(tree))

    def test_validate_ast_and_analyze_patch_agree_on_list(self):
        """Both commands must yield the same names for a simple list assignment."""
        source = '__all__ = ["a", "b"]\ndef a(): ...\ndef b(): ...\n'
        # validate-ast --all-exported
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(source)
            py_path = f.name
        # analyze-patch --extract all-list
        diff_text = "--- a/m.py\n+++ b/m.py\n@@ -0,0 +1,3 @@\n"
        for line in source.splitlines():
            diff_text += f"+{line}\n"
        with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as f:
            f.write(diff_text)
            diff_path = f.name
        try:
            ast_result = run_json(["validate-ast", "--file", py_path, "--all-exported"])
            patch_result = run_json(
                ["analyze-patch", "--patch", diff_path, "--extract", "all-list"]
            )
            self.assertEqual(sorted(ast_result["all_list"]), sorted(patch_result["results"]))
        finally:
            os.unlink(py_path)
            os.unlink(diff_path)


class TestValidateAst(TempDirMixin, unittest.TestCase):
    def test_all_exported_pass_counts_imports_and_annotated_names(self):
        path = write(
            self.tmpdir,
            "good.py",
            dedent(
                """\
                from os import path
                __all__ = ["Foo", "bar", "path", "CONST"]
                CONST: int = 1
                class Foo: ...
                def bar(): ...
                """
            ),
        )
        result = run_json(["validate-ast", "--file", path, "--all-exported"])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["undefined"], [])

    def test_all_exported_names_the_undefined_entry(self):
        path = write(self.tmpdir, "bad.py", '__all__ = ["Foo", "ghost"]\nclass Foo: ...\n')
        result = run_json(["validate-ast", "--file", path, "--all-exported"])
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["undefined"], ["ghost"])

    def test_all_exported_counts_unpacking_augmented_and_nested_bindings(self):
        path = write(
            self.tmpdir,
            "nested.py",
            dedent(
                """\
                import sys
                __all__ = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]
                a, (b, *c) = 1, (2, 3)
                d = 0
                d += 1
                try:
                    import json as e
                except ImportError:
                    e = None
                else:
                    f = 1
                finally:
                    g = 2
                if sys.platform:
                    def h(): ...
                else:
                    class i: ...
                with open(__file__) as fh:
                    j = 1
                """
            ),
        )
        result = run_json(["validate-ast", "--file", path, "--all-exported"])
        self.assertEqual(result["undefined"], [])
        self.assertEqual(result["status"], "PASS")

    def _undefined(self, source: str, names: list[str]) -> list[str]:
        path = write(self.tmpdir, "forms.py", f"__all__ = {names!r}\n" + dedent(source))
        return run_json(["validate-ast", "--file", path, "--all-exported"])["undefined"]

    def test_all_exported_counts_loop_and_while_bindings(self):
        source = """\
            for a, b in []:
                c = 1
            else:
                d = 1
            while False:
                e = 1
            else:
                f = 1
            async def _run():
                async for g in []:
                    pass
            """
        self.assertEqual(self._undefined(source, ["a", "b", "c", "d", "e", "f"]), [])
        self.assertEqual(self._undefined(source, ["g"]), ["g"])  # inside a def: not module level

    def test_all_exported_counts_with_as_targets(self):
        source = """\
            with open(__file__) as a, open(__file__) as (b):
                pass
            """
        self.assertEqual(self._undefined(source, ["a", "b"]), [])

    def test_all_exported_counts_except_handler_names(self):
        source = """\
            try:
                pass
            except ValueError as err:
                pass
            """
        self.assertEqual(self._undefined(source, ["err"]), [])

    def test_all_exported_counts_match_bodies_and_capture_names(self):
        source = """\
            match 1:
                case [first, *rest]:
                    a = 1
                case {"k": v, **extra}:
                    b = 1
                case int() as num:
                    pass
                case _:
                    c = 1
            """
        names = ["first", "rest", "v", "extra", "num", "a", "b", "c"]
        self.assertEqual(self._undefined(source, names), [])

    def test_all_exported_counts_module_level_walrus(self):
        source = """\
            if (a := 1):
                pass
            print(b := 2)
            while (c := 0):
                pass
            """
        self.assertEqual(self._undefined(source, ["a", "b", "c"]), [])

    def test_all_exported_ignores_walrus_in_scopes_and_function_bound_names(self):
        source = """\
            def f():
                if (inner := 1):
                    pass
                for loop_var in []:
                    pass
            fn = lambda: (lam := 1)
            comp = [(item := x) for x in []]
            """
        names = ["inner", "loop_var", "lam", "item"]
        self.assertEqual(self._undefined(source, names), names)

    def test_all_exported_ignores_names_bound_inside_functions(self):
        path = write(self.tmpdir, "fn.py", '__all__ = ["inner"]\ndef f():\n    inner = 1\n')
        result = run_json(["validate-ast", "--file", path, "--all-exported"])
        self.assertEqual(result["undefined"], ["inner"])
        self.assertEqual(result["status"], "FAIL")

    def test_all_exported_without_all_fails(self):
        path = write(self.tmpdir, "none.py", "x = 1\n")
        result = run_json(["validate-ast", "--file", path, "--all-exported"])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("__all__", result["error"])

    def test_nesting_depth_flat_function_is_zero(self):
        path = write(self.tmpdir, "flat.py", "def f():\n    return 1\n")
        result = run_json(["validate-ast", "--file", path, "--function", "f", "--complexity"])
        self.assertEqual((result["status"], result["nesting_depth"]), ("PASS", 0))

    def test_nesting_depth_counts_nested_branches_not_siblings(self):
        path = write(
            self.tmpdir,
            "nested.py",
            dedent(
                """\
                def f(xs):
                    if xs:
                        for x in xs:
                            if x:
                                return x
                    if xs:
                        return 0
                """
            ),
        )
        result = run_json(["validate-ast", "--file", path, "--function", "f", "--complexity"])
        self.assertEqual(result["nesting_depth"], 3)

    def test_function_without_complexity_does_not_report_nesting_depth(self):
        """--function without --complexity must not include nesting_depth."""
        path = write(self.tmpdir, "f.py", "def f(): ...\n")
        result = run_json(["validate-ast", "--file", path, "--function", "f"])
        self.assertEqual(result["status"], "PASS")
        self.assertNotIn("nesting_depth", result)

    def test_all_exported_and_function_are_mutually_exclusive(self):
        path = write(self.tmpdir, "f.py", "x = 1\n")
        rc, out, _err = run_main(
            ["validate-ast", "--file", path, "--all-exported", "--function", "f"]
        )
        self.assertEqual((rc, out), (2, ""))

    def test_unknown_function_fails(self):
        path = write(self.tmpdir, "f.py", "def f(): ...\n")
        result = run_json(["validate-ast", "--file", path, "--function", "g", "--complexity"])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("not found", result["error"])

    def test_missing_file_fails_without_raising(self):
        result = run_json(["validate-ast", "--file", self.tmpdir + "/nope.py", "--all-exported"])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("nope.py", result["error"])

    def test_syntax_error_fails_without_raising(self):
        path = write(self.tmpdir, "broken.py", "def (:\n")
        result = run_json(["validate-ast", "--file", path, "--all-exported"])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("SyntaxError", result["error"])

    def test_usage_errors(self):
        path = write(self.tmpdir, "f.py", "x = 1\n")
        for argv in (["--file", path], ["--file", path, "--complexity"]):
            with self.subTest(argv=argv):
                rc, out, _err = run_main(["validate-ast", *argv])
                self.assertEqual((rc, out), (2, ""))


class TestValidateJson(TempDirMixin, unittest.TestCase):
    def test_keys_and_count(self):
        path = write(self.tmpdir, "f.json", '{"status": "ok", "results": [1, 2, 3]}')
        result = run_json(
            ["validate-json", "--file", path, "--keys", "status,results", "--count", "results"]
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["keys"], ["status", "results"])
        self.assertEqual(result["counts"], {"results": 3})
        self.assertIsNone(result["error"])

    def test_missing_key_reports_first_missing(self):
        path = write(self.tmpdir, "f.json", '{"status": "ok"}')
        result = run_json(["validate-json", "--file", path, "--keys", "status,results,other"])
        self.assertTrue(result["valid"])
        self.assertEqual(result["keys"], ["status"])
        self.assertIn("'results'", result["error"])

    def test_count_on_non_list(self):
        path = write(self.tmpdir, "f.json", '{"results": "x"}')
        result = run_json(["validate-json", "--file", path, "--count", "results"])
        self.assertEqual(result["counts"], {})
        self.assertIn("not a list", result["error"])

    def test_count_missing_key(self):
        """--count with a key absent from the object reports key-not-found."""
        path = write(self.tmpdir, "f.json", '{"other": 1}')
        result = run_json(["validate-json", "--file", path, "--count", "missing"])
        self.assertEqual(result["counts"], {})
        self.assertIn("key not found", result["error"])

    def test_keys_on_non_object_reports_missing(self):
        path = write(self.tmpdir, "f.json", "[1, 2]")
        result = run_json(["validate-json", "--file", path, "--keys", "a"])
        self.assertIn("key not found", result["error"])

    def test_keys_blank_value_is_zero_checks(self):
        """--keys with only commas checks zero keys; valid stays true."""
        path = write(self.tmpdir, "f.json", '{"a": 1}')
        result = run_json(["validate-json", "--file", path, "--keys", ","])
        self.assertTrue(result["valid"])
        self.assertEqual(result["keys"], [])
        self.assertIsNone(result["error"])

    def test_invalid_json(self):
        path = write(self.tmpdir, "f.json", "{not json")
        result = run_json(["validate-json", "--file", path])
        self.assertFalse(result["valid"])
        self.assertIn("JSON parse error", result["error"])

    def test_missing_file(self):
        result = run_json(["validate-json", "--file", self.tmpdir + "/nope.json"])
        self.assertFalse(result["valid"])
        self.assertIn("nope.json", result["error"])

    def test_unreadable_file_unicode_error(self):
        """A file with invalid UTF-8 is reported as invalid without raising."""
        path = os.path.join(self.tmpdir, "bad.json")
        with open(path, "wb") as f:
            f.write(b"\xff\xfe")  # invalid UTF-8 start bytes
        result = run_json(["validate-json", "--file", path])
        self.assertFalse(result["valid"])
        self.assertIsNotNone(result["error"])


if __name__ == "__main__":
    unittest.main()
