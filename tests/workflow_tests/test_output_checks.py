"""Tests for workflow.output_checks.

Covers every check type passing and failing, run_output_checks with mixed
results, missing-file behaviour, and the values_have_key partial-miss edge case.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from workflow.models import OutputCheck
from workflow.output_checks import CheckResult, run_output_checks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(tmp_path: str, filename: str, content: str) -> str:
    """Write *content* to *tmp_path/filename* and return the full path."""
    full = os.path.join(tmp_path, filename)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(content)
    return full


def _check(workspace: str, path: str, *check_names: str) -> list[CheckResult]:
    """Run output checks against a single file and return results."""
    return run_output_checks(workspace, [OutputCheck(path=path, checks=list(check_names))])


# ---------------------------------------------------------------------------
# is_json
# ---------------------------------------------------------------------------


class TestIsJson(unittest.TestCase):
    def test_valid_json_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, "out.json", '{"key": "value"}')
            results = _check(tmp_dir, "out.json", "is_json")
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].passed)

    def test_invalid_json_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, "out.json", "not json {")
            results = _check(tmp_dir, "out.json", "is_json")
            self.assertFalse(results[0].passed)
            self.assertIn("invalid JSON", results[0].message)

    def test_missing_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            results = _check(tmp_dir, "missing.json", "is_json")
            self.assertFalse(results[0].passed)


# ---------------------------------------------------------------------------
# is_dict
# ---------------------------------------------------------------------------


class TestIsDict(unittest.TestCase):
    def test_dict_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, "out.json", '{"a": 1}')
            results = _check(tmp_dir, "out.json", "is_dict")
            self.assertTrue(results[0].passed)

    def test_list_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, "out.json", '[1, 2]')
            results = _check(tmp_dir, "out.json", "is_dict")
            self.assertFalse(results[0].passed)
            self.assertIn("list", results[0].message)


# ---------------------------------------------------------------------------
# is_list
# ---------------------------------------------------------------------------


class TestIsList(unittest.TestCase):
    def test_list_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, "out.json", '[1, 2, 3]')
            results = _check(tmp_dir, "out.json", "is_list")
            self.assertTrue(results[0].passed)

    def test_dict_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, "out.json", '{"a": 1}')
            results = _check(tmp_dir, "out.json", "is_list")
            self.assertFalse(results[0].passed)


# ---------------------------------------------------------------------------
# non_empty
# ---------------------------------------------------------------------------


class TestNonEmpty(unittest.TestCase):
    def test_non_empty_dict_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, "out.json", '{"a": 1}')
            results = _check(tmp_dir, "out.json", "non_empty")
            self.assertTrue(results[0].passed)

    def test_empty_dict_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, "out.json", '{}')
            results = _check(tmp_dir, "out.json", "non_empty")
            self.assertFalse(results[0].passed)

    def test_non_empty_list_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, "out.json", '[1]')
            results = _check(tmp_dir, "out.json", "non_empty")
            self.assertTrue(results[0].passed)

    def test_empty_list_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, "out.json", '[]')
            results = _check(tmp_dir, "out.json", "non_empty")
            self.assertFalse(results[0].passed)


# ---------------------------------------------------------------------------
# has_key
# ---------------------------------------------------------------------------


class TestHasKey(unittest.TestCase):
    def test_key_present_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, "out.json", '{"status": "ok", "count": 5}')
            results = _check(tmp_dir, "out.json", "has_key:status")
            self.assertTrue(results[0].passed)

    def test_key_absent_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, "out.json", '{"count": 5}')
            results = _check(tmp_dir, "out.json", "has_key:status")
            self.assertFalse(results[0].passed)
            self.assertIn("status", results[0].message)

    def test_requires_dict_not_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, "out.json", '[1, 2]')
            results = _check(tmp_dir, "out.json", "has_key:status")
            self.assertFalse(results[0].passed)


# ---------------------------------------------------------------------------
# values_have_key
# ---------------------------------------------------------------------------


class TestValuesHaveKey(unittest.TestCase):
    def test_all_values_have_key_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data = {"a": {"x": 1}, "b": {"x": 2}}
            _write(tmp_dir, "out.json", json.dumps(data))
            results = _check(tmp_dir, "out.json", "values_have_key:x")
            self.assertTrue(results[0].passed)

    def test_partial_miss_fails_with_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data = {"a": {"x": 1}, "b": {"y": 2}}
            _write(tmp_dir, "out.json", json.dumps(data))
            results = _check(tmp_dir, "out.json", "values_have_key:x")
            self.assertFalse(results[0].passed)
            self.assertIn("b", results[0].message)


# ---------------------------------------------------------------------------
# list_items_have_key
# ---------------------------------------------------------------------------


class TestListItemsHaveKey(unittest.TestCase):
    def test_all_items_have_key_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data = [{"id": 1}, {"id": 2}]
            _write(tmp_dir, "out.json", json.dumps(data))
            results = _check(tmp_dir, "out.json", "list_items_have_key:id")
            self.assertTrue(results[0].passed)

    def test_missing_item_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data = [{"id": 1}, {"name": "no-id"}]
            _write(tmp_dir, "out.json", json.dumps(data))
            results = _check(tmp_dir, "out.json", "list_items_have_key:id")
            self.assertFalse(results[0].passed)


# ---------------------------------------------------------------------------
# path escaping workspace root
# ---------------------------------------------------------------------------


class TestPathEscaping(unittest.TestCase):
    def test_path_escaping_workspace_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            results = _check(tmp_dir, "../outside.json", "is_json")
            self.assertFalse(results[0].passed)
            self.assertIn("escapes workspace", results[0].message)


# ---------------------------------------------------------------------------
# unknown check
# ---------------------------------------------------------------------------


class TestUnknownCheck(unittest.TestCase):
    def test_unknown_check_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, "out.json", '{"a": 1}')
            results = _check(tmp_dir, "out.json", "some_unknown_check")
            # Unknown checks are skipped (passed=True) so they don't block workflows
            self.assertTrue(results[0].passed)
            self.assertIn("unknown", results[0].message)


if __name__ == "__main__":
    unittest.main()
