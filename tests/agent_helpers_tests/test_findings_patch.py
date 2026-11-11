"""summarize-findings and analyze-patch."""

from __future__ import annotations

import json
import unittest
from textwrap import dedent

from tests.agent_helpers_tests.helpers import run_json, run_main, write
from tests.fixtures import TempDirMixin


class TestSummarizeFindings(TempDirMixin, unittest.TestCase):
    def _findings(self, data: object) -> str:
        return write(self.tmpdir, "findings.json", json.dumps(data))

    def test_groups_by_severity_with_unknown_bucket(self):
        path = self._findings(
            [{"severity": "major"}, {"severity": "major"}, {"severity": "minor"}, {"other": 1}, "not-an-object"]
        )
        result = run_json(["summarize-findings", "--input", path])
        self.assertEqual(result, {"total": 5, "by_severity": {"major": 2, "minor": 1, "unknown": 2}})

    def test_group_by_other_field_and_non_string_values(self):
        path = self._findings([{"n": 1}, {"n": 1}, {"n": None}])
        result = run_json(["summarize-findings", "--input", path, "--group-by", "n"])
        self.assertEqual(result["by_n"], {"1": 2, "unknown": 1})

    def test_csv_format(self):
        path = self._findings([{"severity": "a"}, {"severity": "b"}, {"severity": "a"}])
        rc, out, _err = run_main(["summarize-findings", "--input", path, "--format", "csv"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines()[0], "group,count")
        self.assertIn("a,2", out.splitlines())

    def test_empty_array_json(self):
        result = run_json(["summarize-findings", "--input", self._findings([])])
        self.assertEqual(result, {"total": 0, "by_severity": {}})

    def test_non_array_is_an_error(self):
        rc, out, err = run_main(["summarize-findings", "--input", self._findings({"a": 1})])
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("expected a JSON array", err)

    def test_invalid_json_and_missing_file_are_errors(self):
        bad = write(self.tmpdir, "bad.json", "{")
        for path, needle in ((bad, "JSON parse error"), (self.tmpdir + "/nope.json", "nope.json")):
            with self.subTest(path=path):
                rc, out, err = run_main(["summarize-findings", "--input", path])
                self.assertEqual((rc, out), (1, ""))
                self.assertIn(needle, err)


_PATCH = dedent(
    """\
    --- a/pkg/mod.py
    +++ b/pkg/mod.py
    @@ -1,6 +1,9 @@
    -import os
    +import sys
    +from pathlib import Path
     import json
    +__all__ = ["alpha", "beta"]
    +
    +def alpha(x):
    +    return x
    +
    +dispatch = {"a": "pkg.a:main", "b": "pkg.b:main"}
     def old():
         pass
    """
)


class TestAnalyzePatch(TempDirMixin, unittest.TestCase):
    def _extract(self, mode: str, text: str = _PATCH) -> dict:
        path = write(self.tmpdir, "p.diff", text)
        return run_json(["analyze-patch", "--patch", path, "--extract", mode])

    def test_imports_added_and_removed(self):
        result = self._extract("imports")["results"]
        self.assertIn({"op": "removed", "line": "import os"}, result)
        self.assertIn({"op": "added", "line": "import sys"}, result)
        self.assertIn({"op": "added", "line": "from pathlib import Path"}, result)
        self.assertEqual(len(result), 3)

    def test_added_functions_ignore_context_and_removed(self):
        self.assertEqual(self._extract("added-functions")["results"], ["alpha"])

    def test_all_list_from_post_image(self):
        self.assertEqual(self._extract("all-list")["results"], ["alpha", "beta"])

    def test_dispatch_map_from_post_image(self):
        self.assertEqual(self._extract("dispatch-map")["results"], {"a": "pkg.a:main", "b": "pkg.b:main"})

    def test_dispatch_map_keeps_non_literal_values_as_source(self):
        patch = "@@ -0,0 +1,1 @@\n+forward_map = {'x': some.func}\n"
        self.assertEqual(self._extract("dispatch-map", patch)["results"], {"x": "some.func"})

    def test_all_list_regex_fallback_on_unparseable_image(self):
        patch = "@@ -1,2 +1,3 @@\n+__all__ = ['one', 'two']\n+def broken(:\n"
        self.assertEqual(self._extract("all-list", patch)["results"], ["one", "two"])

    def test_nothing_found_yields_empty_results(self):
        patch = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
        self.assertEqual(self._extract("all-list", patch)["results"], [])
        self.assertEqual(self._extract("dispatch-map", patch)["results"], {})
        self.assertEqual(self._extract("added-functions", patch)["results"], [])

    def test_missing_patch_file_reports_error(self):
        result = run_json(["analyze-patch", "--patch", self.tmpdir + "/nope.diff", "--extract", "imports"])
        self.assertEqual(result["results"], [])
        self.assertTrue(result["error"])

    def test_unknown_extract_mode_is_rejected_by_argparse(self):
        path = write(self.tmpdir, "p.diff", _PATCH)
        with self.assertRaises(SystemExit) as ctx:
            run_main(["analyze-patch", "--patch", path, "--extract", "bogus"])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
