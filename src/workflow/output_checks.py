"""Output contract checks for workflow stages.

Evaluates inline schema checks declared via ``StageSpec.validates_output``
after a stage completes. Pure Python — no external dependencies.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .models import OutputCheck

__all__ = ["CheckResult", "run_output_checks"]


@dataclass
class CheckResult:
    """Result of evaluating one check against one output file."""

    passed: bool
    path: str  # workspace-relative path from OutputCheck
    check: str  # check name, e.g. "is_json" or "has_key:teams_list"
    message: str  # human-readable description


def run_output_checks(
    workspace_dir: str,
    checks: list[OutputCheck],
) -> list[CheckResult]:
    """Run all checks for all OutputCheck entries.

    Returns one ``CheckResult`` per check. Results for a file that cannot be
    read (missing or unreadable) are all failed with a clear message.

    Args:
        workspace_dir: Absolute path to the workflow workspace directory.
        checks: List of ``OutputCheck`` entries from ``StageSpec.validates_output``.

    Returns:
        Flat list of ``CheckResult`` — one per (path, check) pair.
    """
    workspace_real = os.path.realpath(workspace_dir)
    results: list[CheckResult] = []
    for output_check in checks:
        full_path = os.path.join(workspace_dir, output_check.path)
        real_full = os.path.realpath(full_path)
        if not real_full.startswith(workspace_real + os.sep) and real_full != workspace_real:
            for check_name in output_check.checks:
                results.append(CheckResult(
                    passed=False,
                    path=output_check.path,
                    check=check_name,
                    message="path escapes workspace root — rejected",
                ))
            continue
        parsed, read_error = _read_json(full_path)

        for check_name in output_check.checks:
            result = _evaluate_check(
                check_name=check_name,
                path=output_check.path,
                parsed=parsed,
                read_error=read_error,
            )
            results.append(result)
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_json(full_path: str) -> tuple[object | None, str | None]:
    """Attempt to read and JSON-parse a file."""
    try:
        with open(full_path, encoding="utf-8") as fh:
            content = fh.read()
    except FileNotFoundError:
        return None, f"file not found: {full_path}"
    except OSError as exc:
        return None, f"cannot read file: {exc}"

    try:
        return json.loads(content), None
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"


def _evaluate_check(  # NOSONAR - branching mirrors the check-name dispatch table
    check_name: str,
    path: str,
    parsed: object | None,
    read_error: str | None,
) -> CheckResult:
    """Evaluate a single check name against the already-parsed file value."""
    if check_name == "is_json":
        if read_error is not None:
            return CheckResult(passed=False, path=path, check=check_name, message=read_error)
        return CheckResult(passed=True, path=path, check=check_name, message="valid JSON")

    if read_error is not None:
        return CheckResult(
            passed=False,
            path=path,
            check=check_name,
            message=f"cannot check '{check_name}': {read_error}",
        )

    if check_name == "is_dict":
        if isinstance(parsed, dict):
            return CheckResult(passed=True, path=path, check=check_name, message="top-level is dict")
        return CheckResult(
            passed=False,
            path=path,
            check=check_name,
            message=f"expected dict, got {type(parsed).__name__}",
        )

    if check_name == "is_list":
        if isinstance(parsed, list):
            return CheckResult(passed=True, path=path, check=check_name, message="top-level is list")
        return CheckResult(
            passed=False,
            path=path,
            check=check_name,
            message=f"expected list, got {type(parsed).__name__}",
        )

    if check_name == "non_empty":
        if isinstance(parsed, (dict, list)) and len(parsed) > 0:
            return CheckResult(passed=True, path=path, check=check_name, message="non-empty")
        if isinstance(parsed, (dict, list)):
            return CheckResult(passed=False, path=path, check=check_name, message="value is empty")
        return CheckResult(
            passed=False,
            path=path,
            check=check_name,
            message=f"non_empty requires list or dict, got {type(parsed).__name__}",
        )

    if check_name.startswith("has_key:"):
        key = check_name[len("has_key:"):]
        if not isinstance(parsed, dict):
            return CheckResult(
                passed=False,
                path=path,
                check=check_name,
                message=f"has_key requires dict, got {type(parsed).__name__}",
            )
        if key in parsed:
            return CheckResult(passed=True, path=path, check=check_name, message=f"key '{key}' present")
        return CheckResult(
            passed=False,
            path=path,
            check=check_name,
            message=f"key '{key}' not found in top-level dict",
        )

    if check_name.startswith("values_have_key:"):
        key = check_name[len("values_have_key:"):]
        if not isinstance(parsed, dict):
            return CheckResult(
                passed=False,
                path=path,
                check=check_name,
                message=f"values_have_key requires dict, got {type(parsed).__name__}",
            )
        missing = [k for k, v in parsed.items() if not isinstance(v, dict) or key not in v]
        if not missing:
            return CheckResult(
                passed=True,
                path=path,
                check=check_name,
                message=f"all values have key '{key}'",
            )
        sample = missing[:3]
        return CheckResult(
            passed=False,
            path=path,
            check=check_name,
            message=f"values missing key '{key}': {sample}{'...' if len(missing) > 3 else ''}",
        )

    if check_name.startswith("list_items_have_key:"):
        key = check_name[len("list_items_have_key:"):]
        if not isinstance(parsed, list):
            return CheckResult(
                passed=False,
                path=path,
                check=check_name,
                message=f"list_items_have_key requires list, got {type(parsed).__name__}",
            )
        bad_indices = [
            i for i, item in enumerate(parsed) if not isinstance(item, dict) or key not in item
        ]
        if not bad_indices:
            return CheckResult(
                passed=True,
                path=path,
                check=check_name,
                message=f"all list items have key '{key}'",
            )
        sample = bad_indices[:3]
        return CheckResult(
            passed=False,
            path=path,
            check=check_name,
            message=f"list items at indices {sample}{'...' if len(bad_indices) > 3 else ''} missing key '{key}'",
        )

    return CheckResult(
        passed=True,
        path=path,
        check=check_name,
        message=f"unknown check '{check_name}' — skipped",
    )
