"""validate-imports, validate-ast, validate-json."""

from __future__ import annotations

import unittest
from textwrap import dedent

from tests.agent_helpers_tests.helpers import run_json, run_main, write
from tests.fixtures import TempDirMixin


class TestValidateImports(unittest.TestCase):
    def test_all_symbols_present(self):
        result = run_json(["validate-imports", "--module", "os.path", "--symbols", "join,exists"])
        self.assertEqual(result["overall"], "PASS")
        self.assertEqual([s["status"] for s in result["symbols"]], ["PASS", "PASS"])

    def test_missing_symbol_fails_only_that_symbol(self):
        result = run_json(["validate-imports", "--module", "os.path", "--symbols", "join,no_such_name"])
        self.assertEqual(result["overall"], "FAIL")
        by_name = {s["name"]: s for s in result["symbols"]}
        self.assertEqual(by_name["join"]["status"], "PASS")
        self.assertEqual(by_name["no_such_name"]["status"], "FAIL")
        self.assertIn("no_such_name", by_name["no_such_name"]["error"])

    def test_unimportable_module_fails_every_symbol(self):
        result = run_json(["validate-imports", "--module", "no_such_module_xyz", "--symbols", "a,b"])
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(len(result["symbols"]), 2)
        self.assertTrue(all("ModuleNotFoundError" in s["error"] for s in result["symbols"]))

    def test_import_order_reports_per_module(self):
        result = run_json(["validate-imports", "--import-order", "os,no_such_module_xyz,sys"])
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual([m["status"] for m in result["modules"]], ["PASS", "FAIL", "PASS"])

    def test_requires_module_or_import_order(self):
        rc, out, err = run_main(["validate-imports"])
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertIn("--module", err)

    def test_module_requires_symbols(self):
        rc, _out, err = run_main(["validate-imports", "--module", "os"])
        self.assertEqual(rc, 2)
        self.assertIn("--symbols", err)


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

    def test_unknown_function_fails(self):
        path = write(self.tmpdir, "f.py", "def f(): ...\n")
        result = run_json(["validate-ast", "--file", path, "--function", "g", "--complexity"])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("not found", result["error"])

    def test_missing_file_fails_without_raising(self):
        result = run_json(["validate-ast", "--file", self.tmpdir + "/nope.py", "--all-exported"])
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["error"])

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
        result = run_json(["validate-json", "--file", path, "--keys", "status,results", "--count", "results"])
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

    def test_keys_on_non_object_reports_missing(self):
        path = write(self.tmpdir, "f.json", "[1, 2]")
        result = run_json(["validate-json", "--file", path, "--keys", "a"])
        self.assertIn("key not found", result["error"])

    def test_invalid_json(self):
        path = write(self.tmpdir, "f.json", "{not json")
        result = run_json(["validate-json", "--file", path])
        self.assertFalse(result["valid"])
        self.assertIn("JSON parse error", result["error"])

    def test_missing_file(self):
        result = run_json(["validate-json", "--file", self.tmpdir + "/nope.json"])
        self.assertFalse(result["valid"])
        self.assertTrue(result["error"])


if __name__ == "__main__":
    unittest.main()
