"""``./bin/workflow merge-fix-results``: executed per case against real-schema input.

Every input document is built by ``FixResults.to_json()`` -- the code that
writes fix-results.json -- so the tests exercise the schema the workflow
actually produces rather than a hand-typed approximation of it.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - runs the repo's own CLI with a fixed argv
import tempfile
import unittest
from pathlib import Path
from typing import Any

from workflow.review_ids import FixResults

_ROOT = Path(__file__).resolve().parents[2]
_TIMEOUT = 60


def _result(rid: str, action: str = "fixed", test_result: str = "pass",
            tests: tuple[str, ...] = (), **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": rid, "thread_id": f"PRRT_{rid}", "action": action,
        "files_changed": [f"src/{rid}.py"], "tests_added": list(tests),
        "test_result": test_result,
    }
    out.update(extra)
    return out


def _doc(*results: dict[str, Any], missing: tuple[str, ...] = (),
         mismatches: tuple[dict[str, Any], ...] = (),
         total: int | None = None) -> dict[str, Any]:
    """A fix-results document exactly as aggregate-fix-results writes it."""
    ids = [r["id"] for r in results] + list(missing)
    return FixResults(
        total_expected=len(ids) if total is None else total,
        results=tuple(results),
        missing_results=missing,
        key_mismatches=mismatches,
        scopes={rid: f"src/{rid}.py" for rid in ids},
    ).to_json()


def _mismatch(stem: str) -> dict[str, Any]:
    return {"file": f"{stem}.json", "id_in_file": None, "thread_id_in_file": None,
            "reason": "id field is missing"}


class MergeFixResultsCase(unittest.TestCase):
    def run_merge(self, fr: object, rr: object, *, raw: str | None = None,
                  drop_rr: bool = False) -> tuple[int, dict[str, Any] | None, str]:
        """Run the real CLI once; return (exit code, merged doc or None, stderr)."""
        with tempfile.TemporaryDirectory() as td:
            fr_path = Path(td) / "fix-results.json"
            rr_path = Path(td) / "refix-results.json"
            out_path = Path(td) / "merged.json"
            fr_path.write_text(json.dumps(fr), encoding="utf-8")
            if not drop_rr:
                rr_path.write_text(raw if raw is not None else json.dumps(rr), encoding="utf-8")
            proc = subprocess.run(  # nosec B603 - fixed argv invoking the repo's own CLI
                ["./bin/workflow", "merge-fix-results", str(fr_path), str(rr_path), str(out_path)],
                capture_output=True, text=True, cwd=str(_ROOT), timeout=_TIMEOUT, check=False,
            )
            merged = json.loads(out_path.read_text(encoding="utf-8")) if out_path.is_file() else None
            return proc.returncode, merged, proc.stderr

    def merged_ok(self, fr: object, rr: object) -> dict[str, Any]:
        rc, merged, stderr = self.run_merge(fr, rr)
        self.assertEqual(rc, 0, stderr)
        self.assertIsNotNone(merged)
        return merged or {}


class TestMergeSemantics(MergeFixResultsCase):
    def test_retry_supersedes_same_id_and_counts_once(self) -> None:
        fr = _doc(_result("x"), _result("y", note="first"))
        rr = _doc(_result("y", note="retry"), total=1)
        merged = self.merged_ok(fr, rr)
        ys = [r for r in merged["results"] if r["id"] == "y"]
        self.assertEqual([r["note"] for r in ys], ["retry"])
        self.assertEqual(merged["by_action"]["fixed"], 2)
        self.assertEqual(merged["total_results"], 2)
        self.assertEqual(merged["total_expected"], 2)

    def test_passing_retry_clears_the_original_failed_test(self) -> None:
        fr = _doc(_result("x", test_result="fail"), _result("z", test_result="fail"))
        self.assertEqual(len(fr["failed_tests"]), 2)
        merged = self.merged_ok(fr, _doc(_result("x", test_result="pass"), total=1))
        self.assertEqual([f["id"] for f in merged["failed_tests"]], ["z"])

    def test_failing_retry_keeps_a_failed_test(self) -> None:
        fr = _doc(_result("x", test_result="pass"))
        merged = self.merged_ok(fr, _doc(_result("x", test_result="fail"), total=1))
        self.assertEqual(merged["failed_tests"],
                         [{"id": "x", "thread_id": "PRRT_x", "test_result": "fail"}])

    def test_retry_tests_reach_tests_by_result_alongside_the_original(self) -> None:
        first = "tests/t/test_x.py::T::test_one"
        second = "tests/t/test_x.py::T::test_two"
        fr = _doc(_result("x", tests=(first,)))
        merged = self.merged_ok(fr, _doc(_result("x", tests=(second,)), total=1))
        self.assertEqual(merged["tests_by_result"], {"x": [first, second]})
        self.assertEqual(merged["tests_added"], [first, second])
        self.assertIn("tests/t/test_x.py", merged["files_changed"])

    def test_retry_resolves_a_missing_result(self) -> None:
        fr = _doc(_result("x"), missing=("gone",))
        merged = self.merged_ok(fr, _doc(_result("gone"), total=1))
        self.assertEqual(merged["missing_results"], [])
        self.assertEqual({r["id"] for r in merged["results"]}, {"x", "gone"})
        still = self.merged_ok(fr, _doc(_result("x"), total=1))
        self.assertEqual(still["missing_results"], ["gone"])

    def test_every_key_mismatch_is_kept(self) -> None:
        """Mismatches carry file/id_in_file, not id -- none may collapse."""
        fr = _doc(_result("x"), mismatches=(_mismatch("a"), _mismatch("b")))
        rr = _doc(mismatches=(_mismatch("c"),), total=0)
        merged = self.merged_ok(fr, rr)
        self.assertEqual([m["file"] for m in merged["key_mismatches"]],
                         ["a.json", "b.json", "c.json"])

    def test_out_of_scope_objects_merge_from_both_passes(self) -> None:
        fr = _doc(_result("x", out_of_scope_requests=["edit .envrc"],
                          files_changed=["src/x.py", "src/other.py"]))
        rr = _doc(_result("x", out_of_scope_requests=["push to main"]), total=1)
        self.assertEqual(fr["out_of_scope_paths"], [{"id": "x", "path": "src/other.py"}])
        merged = self.merged_ok(fr, rr)
        self.assertEqual(merged["out_of_scope_paths"], [{"id": "x", "path": "src/other.py"}])
        self.assertEqual(merged["out_of_scope_requests"],
                         [{"id": "x", "request": "edit .envrc"},
                          {"id": "x", "request": "push to main"}])
        self.assertNotIn("src/other.py", merged["files_changed"])

    def test_absent_optional_keys_take_their_defaults(self) -> None:
        merged = self.merged_ok(_doc(_result("x")), {"results": []})
        self.assertEqual([r["id"] for r in merged["results"]], ["x"])


class TestMergeRejectsMalformedInput(MergeFixResultsCase):
    """Exit 2, nothing written, for every wrong shape -- including falsy ones."""

    def assert_rejected(self, rr: object, field: str) -> None:
        rc, merged, stderr = self.run_merge(_doc(_result("x")), rr)
        self.assertEqual(rc, 2, stderr)
        self.assertIsNone(merged)
        self.assertIn(field, stderr)

    def test_present_but_falsy_wrong_types_are_not_coerced(self) -> None:
        cases: list[tuple[str, object]] = [
            ("results", None), ("results", ""), ("files_changed", 0),
            ("files_changed", False), ("missing_results", ""), ("failed_tests", None),
            ("key_mismatches", 0), ("tests_by_result", None), ("tests_by_result", ""),
            ("out_of_scope_paths", False), ("out_of_scope_requests", None),
            ("rejected_tests_added", ""), ("tests_added", None), ("by_action", []),
            ("total_expected", True), ("total_expected", -1), ("total_results", "1"),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                rr = _doc(_result("x"), total=1)
                rr[key] = value
                self.assert_rejected(rr, key)

    def test_bad_result_ids_are_rejected(self) -> None:
        for bad in ({"action": "fixed"}, {"id": 5}, {"id": ""}, {"id": None}):
            with self.subTest(result=bad):
                self.assert_rejected({"results": [bad]}, "results[0].id")
        self.assert_rejected({"results": [{"id": "x"}, {"id": "x"}]}, "results[1].id")

    def test_wrong_element_shapes_are_rejected(self) -> None:
        cases: list[tuple[str, object]] = [
            ("key_mismatches", [{"id_in_file": "x", "reason": "r"}]),
            ("out_of_scope_paths", ["src/x.py"]),
            ("out_of_scope_requests", ["text"]),
            ("failed_tests", [{"id": "x"}]),
            ("tests_by_result", {"x": "tests/t.py::T::t"}),
            ("missing_results", [3]),
        ]
        for key, value in cases:
            with self.subTest(key=key):
                rr = _doc(_result("x"), total=1)
                rr[key] = value
                self.assert_rejected(rr, key)

    def test_non_object_document_is_rejected(self) -> None:
        self.assert_rejected(["not", "an", "object"], "refix-results")

    def test_unsafe_files_changed_path_is_rejected(self) -> None:
        for path in ("src/$(touch pwned).py", "../outside.py", "src/a b.py", "/etc/passwd"):
            with self.subTest(path=path):
                rr = _doc(_result("x"), total=1)
                rr["files_changed"] = [path]
                rr["results"][0]["files_changed"] = [path]
                self.assert_rejected(rr, "files_changed[0]")

    def test_unclaimed_files_changed_path_is_rejected(self) -> None:
        rr = _doc(_result("x"), total=1)
        rr["files_changed"] = ["src/x.py", "src/unrelated.py"]
        self.assert_rejected(rr, "files_changed[1]")
        # A path a non-fixed result names is not claimed either.
        rr = _doc(_result("x", action="rejected"), total=1)
        rr["files_changed"] = ["src/x.py"]
        self.assert_rejected(rr, "files_changed[0]")

    def test_retry_for_an_unknown_finding_is_rejected(self) -> None:
        self.assert_rejected(_doc(_result("stranger"), total=1), "results[0].id")

    def test_missing_or_invalid_json_input_exits_1(self) -> None:
        rc, merged, _ = self.run_merge(_doc(_result("x")), None, drop_rr=True)
        self.assertEqual((rc, merged), (1, None))
        rc, merged, _ = self.run_merge(_doc(_result("x")), None, raw="{not json")
        self.assertEqual((rc, merged), (1, None))


if __name__ == "__main__":
    unittest.main()
