"""Tests for workflow.output_checks.

Covers every check type passing and failing, run_output_checks with mixed
results, missing-file behaviour, and the values_have_key partial-miss edge case.
"""

from __future__ import annotations

import json
import os

import pytest

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


class TestIsJson:
    def test_valid_json_passes(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        _write(ws, "out.json", '{"key": "value"}')
        results = _check(ws, "out.json", "is_json")
        assert len(results) == 1
        assert results[0].passed is True

    def test_invalid_json_fails(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        _write(ws, "out.json", "not json {")
        results = _check(ws, "out.json", "is_json")
        assert results[0].passed is False
        assert "invalid JSON" in results[0].message

    def test_missing_file_fails(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        results = _check(ws, "missing.json", "is_json")
        assert results[0].passed is False


# ---------------------------------------------------------------------------
# is_dict
# ---------------------------------------------------------------------------


class TestIsDict:
    def test_dict_passes(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        _write(ws, "out.json", '{"a": 1}')
        results = _check(ws, "out.json", "is_dict")
        assert results[0].passed is True

    def test_list_fails(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        _write(ws, "out.json", '[1, 2]')
        results = _check(ws, "out.json", "is_dict")
        assert results[0].passed is False
        assert "list" in results[0].message


# ---------------------------------------------------------------------------
# is_list
# ---------------------------------------------------------------------------


class TestIsList:
    def test_list_passes(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        _write(ws, "out.json", '[1, 2, 3]')
        results = _check(ws, "out.json", "is_list")
        assert results[0].passed is True

    def test_dict_fails(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        _write(ws, "out.json", '{"a": 1}')
        results = _check(ws, "out.json", "is_list")
        assert results[0].passed is False


# ---------------------------------------------------------------------------
# non_empty
# ---------------------------------------------------------------------------


class TestNonEmpty:
    def test_non_empty_dict_passes(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        _write(ws, "out.json", '{"a": 1}')
        results = _check(ws, "out.json", "non_empty")
        assert results[0].passed is True

    def test_empty_dict_fails(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        _write(ws, "out.json", '{}')
        results = _check(ws, "out.json", "non_empty")
        assert results[0].passed is False

    def test_non_empty_list_passes(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        _write(ws, "out.json", '[1]')
        results = _check(ws, "out.json", "non_empty")
        assert results[0].passed is True

    def test_empty_list_fails(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        _write(ws, "out.json", '[]')
        results = _check(ws, "out.json", "non_empty")
        assert results[0].passed is False


# ---------------------------------------------------------------------------
# has_key
# ---------------------------------------------------------------------------


class TestHasKey:
    def test_key_present_passes(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        _write(ws, "out.json", '{"status": "ok", "count": 5}')
        results = _check(ws, "out.json", "has_key:status")
        assert results[0].passed is True

    def test_key_absent_fails(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        _write(ws, "out.json", '{"count": 5}')
        results = _check(ws, "out.json", "has_key:status")
        assert results[0].passed is False
        assert "status" in results[0].message

    def test_requires_dict_not_list(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        _write(ws, "out.json", '[1, 2]')
        results = _check(ws, "out.json", "has_key:status")
        assert results[0].passed is False


# ---------------------------------------------------------------------------
# values_have_key
# ---------------------------------------------------------------------------


class TestValuesHaveKey:
    def test_all_values_have_key_passes(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        data = {"a": {"x": 1}, "b": {"x": 2}}
        _write(ws, "out.json", json.dumps(data))
        results = _check(ws, "out.json", "values_have_key:x")
        assert results[0].passed is True

    def test_partial_miss_fails_with_sample(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        data = {"a": {"x": 1}, "b": {"y": 2}}
        _write(ws, "out.json", json.dumps(data))
        results = _check(ws, "out.json", "values_have_key:x")
        assert results[0].passed is False
        assert "b" in results[0].message


# ---------------------------------------------------------------------------
# list_items_have_key
# ---------------------------------------------------------------------------


class TestListItemsHaveKey:
    def test_all_items_have_key_passes(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        data = [{"id": 1}, {"id": 2}]
        _write(ws, "out.json", json.dumps(data))
        results = _check(ws, "out.json", "list_items_have_key:id")
        assert results[0].passed is True

    def test_missing_item_fails(self, tmp_path: object) -> None:
        ws = str(tmp_path)
        data = [{"id": 1}, {"name": "no-id"}]
        _write(ws, "out.json", json.dumps(data))
        results = _check(ws, "out.json", "list_items_have_key:id")
        assert results[0].passed is False


# ---------------------------------------------------------------------------
# path escaping workspace root
# ---------------------------------------------------------------------------


def test_path_escaping_workspace_root_is_rejected(tmp_path: object) -> None:
    ws = str(tmp_path)
    results = _check(ws, "../outside.json", "is_json")
    assert results[0].passed is False
    assert "escapes workspace" in results[0].message


# ---------------------------------------------------------------------------
# unknown check
# ---------------------------------------------------------------------------


def test_unknown_check_is_skipped(tmp_path: object) -> None:
    ws = str(tmp_path)
    _write(ws, "out.json", '{"a": 1}')
    results = _check(ws, "out.json", "some_unknown_check")
    # Unknown checks are skipped (passed=True) so they don't block workflows
    assert results[0].passed is True
    assert "unknown" in results[0].message
