"""Output contract checks for workflow stages.

Evaluates inline schema checks declared via ``StageSpec.validates_output``
after a stage completes. Pure Python — no external dependencies.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
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


def _check_is_dict(parsed: object | None, _key: str) -> tuple[bool, str]:
    """Verdict for ``is_dict``."""
    if isinstance(parsed, dict):
        return True, "top-level is dict"
    return False, f"expected dict, got {type(parsed).__name__}"


def _check_is_list(parsed: object | None, _key: str) -> tuple[bool, str]:
    """Verdict for ``is_list``."""
    if isinstance(parsed, list):
        return True, "top-level is list"
    return False, f"expected list, got {type(parsed).__name__}"


def _check_non_empty(parsed: object | None, _key: str) -> tuple[bool, str]:
    """Verdict for ``non_empty``."""
    if not isinstance(parsed, (dict, list)):
        return False, f"non_empty requires list or dict, got {type(parsed).__name__}"
    if len(parsed) > 0:
        return True, "non-empty"
    return False, "value is empty"


def _check_has_key(parsed: object | None, key: str) -> tuple[bool, str]:
    """Verdict for ``has_key:<k>``."""
    if not isinstance(parsed, dict):
        return False, f"has_key requires dict, got {type(parsed).__name__}"
    if key in parsed:
        return True, f"key '{key}' present"
    return False, f"key '{key}' not found in top-level dict"


def _check_values_have_key(parsed: object | None, key: str) -> tuple[bool, str]:
    """Verdict for ``values_have_key:<k>``."""
    if not isinstance(parsed, dict):
        return False, f"values_have_key requires dict, got {type(parsed).__name__}"
    missing = [k for k, v in parsed.items() if not isinstance(v, dict) or key not in v]
    if not missing:
        return True, f"all values have key '{key}'"
    sample = missing[:3]
    return False, f"values missing key '{key}': {sample}{'...' if len(missing) > 3 else ''}"


def _check_list_items_have_key(parsed: object | None, key: str) -> tuple[bool, str]:
    """Verdict for ``list_items_have_key:<k>``."""
    if not isinstance(parsed, list):
        return False, f"list_items_have_key requires list, got {type(parsed).__name__}"
    bad = [i for i, item in enumerate(parsed) if not isinstance(item, dict) or key not in item]
    if not bad:
        return True, f"all list items have key '{key}'"
    sample = bad[:3]
    return False, f"list items at indices {sample}{'...' if len(bad) > 3 else ''} missing key '{key}'"


# Exact-match check names -> verdict function. The second argument is unused for
# these but keeps one uniform signature across both tables.
_EXACT_CHECKS: dict[str, Callable[[object | None, str], tuple[bool, str]]] = {
    "is_dict": _check_is_dict,
    "is_list": _check_is_list,
    "non_empty": _check_non_empty,
}

# Prefixed check names ("has_key:foo") -> verdict function, which receives the
# text after the prefix as its key argument. Order is irrelevant: the prefixes
# are mutually exclusive, so no two can match one check name.
_PREFIX_CHECKS: dict[str, Callable[[object | None, str], tuple[bool, str]]] = {
    "has_key:": _check_has_key,
    "values_have_key:": _check_values_have_key,
    "list_items_have_key:": _check_list_items_have_key,
}


def _resolve_check(
    check_name: str,
) -> tuple[Callable[[object | None, str], tuple[bool, str]] | None, str]:
    """Return the verdict function for *check_name* and the key it should use.

    Returns ``(None, "")`` for an unrecognised name, which the caller reports as
    a skipped check rather than a failure.
    """
    exact = _EXACT_CHECKS.get(check_name)
    if exact is not None:
        return exact, ""
    for prefix, fn in _PREFIX_CHECKS.items():
        if check_name.startswith(prefix):
            return fn, check_name[len(prefix):]
    return None, ""


def _evaluate_check(
    check_name: str,
    path: str,
    parsed: object | None,
    read_error: str | None,
) -> CheckResult:
    """Evaluate a single check name against the already-parsed file value."""
    # is_json is special twice over: it is the only check that is meaningful
    # when the read failed, and a successful read IS the check. It must stay
    # ahead of the read_error guard below.
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

    check_fn, key = _resolve_check(check_name)
    if check_fn is None:
        return CheckResult(
            passed=True,
            path=path,
            check=check_name,
            message=f"unknown check '{check_name}' — skipped",
        )

    passed, message = check_fn(parsed, key)
    return CheckResult(passed=passed, path=path, check=check_name, message=message)
