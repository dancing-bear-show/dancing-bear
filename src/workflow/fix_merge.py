"""Merge fix-results.json with refix-results.json, as tested code.

review-fix-threads retries every finding the regression sweep blocked, once.
Both passes are aggregated by ``aggregate-fix-results`` against their own
index (fix-index.json and refix-index.json), so both inputs share the
:meth:`workflow.review_ids.FixResults.to_json` schema. This module combines
them into fix-results-merged.json, the file every later stage reads.

Neither input is trusted more than the other. Each is validated field by
field against the real schema before anything is merged: a key that is
absent takes its empty default, but a key that is present with the wrong
type is rejected -- a falsy wrong value (``""``, ``0``, ``false``, ``null``)
is never coerced to an empty list. Every ``files_changed`` entry must be a
shell-safe repo path (the same ``_is_safe_repo_path`` contract
aggregate-fix-results applies) and must be claimed by a fixed result in the
same document, because those paths are later interpolated into
``check-paths`` and ``git add`` command text.

Derived fields are recomputed from the merged ``results`` with the same
helpers ``FixResults.to_json`` uses, rather than combined from the inputs'
copies, so a retry that now passes clears its original failed-test record
and retry tests reach ``tests_by_result``.

Diagnostics name an offending entry by position and field, never by echoing
its value -- the values are fixer-authored text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from workflow.review_ids import (
    _claimed_paths,
    _count_actions,
    _failed_test,
    _is_safe_repo_path,
    _is_unproven_fix,
    _out_of_scope_requests,
    _validated_tests,
)

_LIST = "list"
_DICT = "object"


@dataclass(frozen=True)
class FixDoc:
    """The fields of one validated fix-results document the merge reads."""

    total_expected: int
    results: tuple[dict[str, Any], ...]
    files_changed: tuple[str, ...]
    out_of_scope_paths: tuple[dict[str, Any], ...]
    missing_results: tuple[str, ...]
    key_mismatches: tuple[dict[str, Any], ...]


def _field(doc: dict[str, Any], key: str, label: str, kind: str) -> Any:
    """``doc[key]``, or its empty default only when the key is absent."""
    if key not in doc:
        return [] if kind == _LIST else {}
    value = doc[key]
    expected = list if kind == _LIST else dict
    if not isinstance(value, expected):
        raise ValueError(f"{label}: '{key}' must be a JSON {kind}, got {type(value).__name__}")
    return value


def _nonempty_str(value: object) -> bool:
    return isinstance(value, str) and value != ""


def _str_list(doc: dict[str, Any], key: str, label: str) -> list[str]:
    values = _field(doc, key, label, _LIST)
    for i, item in enumerate(values):
        if not _nonempty_str(item):
            raise ValueError(f"{label}: '{key}[{i}]' must be a non-empty string")
    return list(values)


def _object_list(doc: dict[str, Any], key: str, label: str,
                 str_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """A list of objects, each carrying a non-empty string at every ``str_keys``."""
    values = _field(doc, key, label, _LIST)
    for i, item in enumerate(values):
        if not isinstance(item, dict):
            raise ValueError(f"{label}: '{key}[{i}]' must be a JSON object")
        for name in str_keys:
            if not _nonempty_str(item.get(name)):
                raise ValueError(f"{label}: '{key}[{i}].{name}' must be a non-empty string")
    return list(values)


def _count(doc: dict[str, Any], key: str, label: str) -> int:
    if key not in doc:
        return 0
    value = doc[key]
    # bool is an int subclass; a JSON true is not a count.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label}: '{key}' must be a non-negative integer")
    return value


def _results(doc: dict[str, Any], label: str) -> list[dict[str, Any]]:
    results = _object_list(doc, "results", label, ("id",))
    seen: set[str] = set()
    for i, result in enumerate(results):
        if result["id"] in seen:
            raise ValueError(f"{label}: 'results[{i}].id' repeats an earlier result's id")
        seen.add(result["id"])
    return results


def _files_changed(doc: dict[str, Any], label: str,
                   results: list[dict[str, Any]]) -> list[str]:
    files = _str_list(doc, "files_changed", label)
    claimed: set[str] = set()
    for result in results:
        if result.get("action") == "fixed":
            claimed |= _claimed_paths(result)
    for i, path in enumerate(files):
        if not _is_safe_repo_path(path):
            raise ValueError(f"{label}: 'files_changed[{i}]' is not a safe repo path")
        if path not in claimed:
            raise ValueError(f"{label}: 'files_changed[{i}]' is not claimed by any fixed result")
    return files


def _check_derived_fields(doc: dict[str, Any], label: str) -> None:
    """Type-check the fields the merge recomputes rather than reads.

    They are rebuilt from ``results``, but a document carrying a malformed
    copy is malformed, and accepting it would hide whatever wrote it.
    """
    _str_list(doc, "tests_added", label)
    _object_list(doc, "failed_tests", label, ("id", "test_result"))
    _object_list(doc, "out_of_scope_requests", label, ("id",))
    _object_list(doc, "rejected_tests_added", label, ("id", "test"))
    _count(doc, "total_results", label)
    for value in _field(doc, "by_action", label, _DICT).values():
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{label}: 'by_action' value for an action is not an integer")
    tests_by_result = _field(doc, "tests_by_result", label, _DICT)
    for position, tests in enumerate(tests_by_result.values()):
        if not isinstance(tests, list) or not all(_nonempty_str(t) for t in tests):
            raise ValueError(
                f"{label}: 'tests_by_result' entry {position} must be a list of non-empty strings"
            )


def parse_fix_doc(doc: object, label: str) -> FixDoc:
    """Validate one fix-results document against the ``FixResults`` schema.

    Raises:
        ValueError: on any field of the wrong shape, naming it by position.
    """
    if not isinstance(doc, dict):
        raise ValueError(f"{label}: must be a JSON object, got {type(doc).__name__}")
    results = _results(doc, label)
    _check_derived_fields(doc, label)
    return FixDoc(
        total_expected=_count(doc, "total_expected", label),
        results=tuple(results),
        files_changed=tuple(_files_changed(doc, label, results)),
        out_of_scope_paths=tuple(_object_list(doc, "out_of_scope_paths", label, ("id", "path"))),
        missing_results=tuple(_str_list(doc, "missing_results", label)),
        key_mismatches=tuple(_object_list(doc, "key_mismatches", label, ("file", "reason"))),
    )


def _dedup(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop exact duplicates, keeping first-seen order."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = json.dumps(item, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _merged_results(primary: FixDoc, retry: FixDoc) -> list[dict[str, Any]]:
    """Primary results in order, each replaced by its retry when one exists.

    A retry may only answer a finding the primary pass knew about -- one it
    credited or reported missing. Anything else did not come from
    refix-index.json's subset of fix-index.json.
    """
    known = {r["id"] for r in primary.results} | set(primary.missing_results)
    retry_by_id = {r["id"]: r for r in retry.results}
    for i, rid in enumerate(retry_by_id):
        if rid not in known:
            raise ValueError(
                f"refix-results: 'results[{i}].id' is not a finding fix-results knows"
            )
    merged = [retry_by_id.pop(r["id"], r) for r in primary.results]
    # What remains retried a finding the primary pass reported missing.
    return merged + list(retry_by_id.values())


def _merged_tests(primary: FixDoc, retry: FixDoc) -> dict[str, Any]:
    """Validated tests from both passes; a retry adds to the primary's tests.

    The primary fix's tests are still in the tree after a retry, so they stay
    under the id alongside the retry's own -- verify-fixes runs both.
    """
    first = _validated_tests(primary.results)
    second = _validated_tests(retry.results)
    by_result: dict[str, list[str]] = {}
    for source in (first["tests_by_result"], second["tests_by_result"]):
        for rid, tests in source.items():
            by_result[rid] = sorted(set(by_result.get(rid, [])) | set(tests))
    return {
        "tests_added": sorted({t for ids in by_result.values() for t in ids}),
        "tests_by_result": by_result,
        "rejected_tests_added": _dedup(
            first["rejected_tests_added"] + second["rejected_tests_added"]
        ),
    }


def merge_fix_docs(primary: FixDoc, retry: FixDoc) -> dict[str, Any]:
    """Combine a fix pass and its retry into one fix-results document.

    * ``results``: the retry supersedes the primary entry with the same id.
    * ``by_action``, ``failed_tests``: recomputed from the merged results, so a
      retry that passes clears the primary's failure and nothing is counted
      twice.
    * ``tests_added``, ``tests_by_result``, ``rejected_tests_added``:
      re-validated from both passes' results and unioned per id.
    * ``files_changed``: union of both validated lists; ``out_of_scope_paths``,
      ``out_of_scope_requests``, ``key_mismatches``: every entry from both
      passes is kept (exact duplicates dropped).
    * ``missing_results``: union, minus ids the retry produced a result for.

    Raises:
        ValueError: if the retry names a finding the primary pass did not.
    """
    results = _merged_results(primary, retry)
    retried = {r["id"] for r in retry.results}
    missing = [m for m in dict.fromkeys(primary.missing_results + retry.missing_results)
               if m not in retried]
    return {
        "total_expected": primary.total_expected,
        "total_results": len(results),
        "by_action": _count_actions(results),
        "files_changed": sorted(set(primary.files_changed) | set(retry.files_changed)),
        "out_of_scope_paths": _dedup(
            list(primary.out_of_scope_paths) + list(retry.out_of_scope_paths)
        ),
        **_merged_tests(primary, retry),
        "missing_results": missing,
        "failed_tests": [_failed_test(r) for r in results if _is_unproven_fix(r)],
        "key_mismatches": _dedup(list(primary.key_mismatches) + list(retry.key_mismatches)),
        "out_of_scope_requests": _dedup(
            _out_of_scope_requests(primary.results) + _out_of_scope_requests(retry.results)
        ),
        "results": results,
    }
