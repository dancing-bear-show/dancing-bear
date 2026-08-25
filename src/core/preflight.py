"""Invariant-check framework for validating proposed changes before applying them.

The plan → dry-run → apply pattern this repo follows requires validating that a
proposed change set looks sane before any mutation occurs.  Each domain
(mail filter sync, calendar schedule apply, phone layout push) previously
hand-rolled its own sanity checks — or skipped them entirely.  This module
provides one vocabulary so callers get consistent, composable pre-apply
validation without rebuilding the plumbing.

This is deliberately small and orthogonal to the job queue in
``src/worker/queue_ops.py``, which owns job state, atomic persistence, retry,
and crash recovery.  ``preflight`` is stateless: given a change list, a
baseline, and a set of check functions, it returns a report.  No disk I/O,
no job IDs.

Usage pattern::

    from core.preflight import evaluate_invariants

    def no_mass_deletes(changes, baseline):
        total = baseline.get("total", len(changes))
        bad = [c for c in changes if c.get("op") == "delete"]
        if total and len(bad) > total / 2:
            return "deletes_more_than_half", bad
        return "deletes_more_than_half", []

    report = evaluate_invariants(changes, baseline, [no_mass_deletes])
    if not report.passed:
        print(report.summary())
        sys.exit(1)
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.secrets import SENSITIVE_PARAM_KEYS, mask_text

# Reuses the shared key set rather than a second list that would drift from
# it. Normalized to underscores once here so lookups stay cheap; the extra
# entries are header spellings that never appear as query params.
_SENSITIVE_KEYS = {k.replace("-", "_") for k in SENSITIVE_PARAM_KEYS} | {
    # Header spellings mask_headers already treats as sensitive but which
    # never appear as query params, so SENSITIVE_PARAM_KEYS omits them.
    "x_auth_token",
    "proxy_authorization",
    "api_secret",
    "private_key",
    "session_token",
}

_REDACTED_VALUE = "***REDACTED***"

__all__ = [
    "InvariantViolation",
    "PreflightReport",
    "CheckFn",
    "evaluate_invariants",
]

# A check function receives the proposed change list and a baseline dict and
# returns a (code, offending_samples) tuple.  A non-empty sample list signals
# a violation.  Define checks as plain functions — no subclassing required.
CheckFn = Callable[
    [list[dict[str, Any]], dict[str, Any]],
    tuple[str, list[dict[str, Any]]],
]


@dataclass(frozen=True)
class InvariantViolation:
    """A single invariant that failed, with evidence."""

    code: str
    """Stable machine-readable identifier, e.g. ``"deletes_more_than_half"``."""

    message: str
    """Human-readable description of what the invariant checks."""

    samples: list[dict[str, Any]]
    """Representative offending items (capped by ``max_samples``)."""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "code": self.code,
            "message": self.message,
            "samples": self.samples,
        }


@dataclass(frozen=True)
class PreflightReport:
    """Aggregate result of running all invariant checks."""

    passed: bool
    violations: list[InvariantViolation]
    tallies: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "tallies": self.tallies,
        }

    def summary(self) -> str:
        """Return a short human-readable summary suitable for CLI output."""
        total = self.tallies.get("total_changes", "?")
        n_violations = len(self.violations)
        status = "PASSED" if self.passed else "FAILED"
        lines = [
            f"{status}: {total} {_plural(total, 'change')}, "
            f"{n_violations} {_plural(n_violations, 'violation')}"
        ]
        for v in self.violations:
            n_samples = len(v.samples)
            lines.append(
                f"  [{v.code}] {v.message} "
                f"({n_samples} {_plural(n_samples, 'sample')})"
            )
        return "\n".join(lines)


def _mask_sample(sample: dict[str, Any]) -> dict[str, Any]:
    """Return ``sample`` with credential-bearing string values masked.

    Offending items are the caller's own change records, and a change that
    describes an API call carries the URL or headers that would make it --
    so an unmasked sample lands a live key in ``to_dict()`` output. Masking
    happens here rather than at the boundary because ``samples`` is public
    on the dataclass, so a caller reading ``violation.samples`` directly
    gets the same guarantee ``to_dict()`` does.

    Structure is preserved so the sample stays useful as evidence: only
    string leaves change, and nesting, keys, and non-string values are
    untouched.
    """
    return {key: _mask_value(value, key) for key, value in sample.items()}


def _is_sensitive_key(key: object) -> bool:
    """Return True when a mapping key marks its value as a credential.

    Normalizes ``-``/``_`` and case so ``X-Api-Key``, ``api_key`` and
    ``APIKEY`` all match the shared key set.
    """
    if not isinstance(key, str):
        return False
    normalized = key.strip().lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS


def _mask_value(value: Any, key: object = None) -> Any:
    """Recursively mask string leaves inside a sample value.

    ``key`` carries the mapping key a value was found under. It matters
    because ``mask_text`` recognizes credentials by their surrounding text
    -- ``?api_key=x`` or ``Authorization: Bearer x`` -- and a bare value
    stored under a sensitive key has no such marker. ``{"api_key": "x"}``
    would otherwise pass through untouched, which is the ordinary shape of
    a structured change record.
    """
    if isinstance(value, str):
        if _is_sensitive_key(key):
            return _REDACTED_VALUE
        return mask_text(value)
    if isinstance(value, dict):
        return {k: _mask_value(v, k) for k, v in value.items()}
    # A sensitive key holding a collection redacts every leaf inside it:
    # {"headers": {...}} is not sensitive, but {"token": [...]} is.
    if isinstance(value, list):
        return [_mask_value(v, key) for v in value]
    if isinstance(value, tuple):
        return tuple(_mask_value(v, key) for v in value)
    return value


def _check_label(check: object) -> str:
    """Return a safe identifying label for a check function.

    Never falls back to ``repr(check)``. A ``functools.partial`` has no
    ``__name__``, so a repr fallback would serialize its bound arguments --
    an API key passed as a partial argument would land verbatim in the
    report. A custom ``__repr__`` is also arbitrary user code that can raise,
    and raising here would escape the very handler that exists to stop a
    buggy check from aborting the run.

    Falls back to the wrapped function's name for a partial, then to the
    type name, both of which are structural rather than value-bearing.
    """
    name = getattr(check, "__name__", None)
    if isinstance(name, str) and name:
        return mask_text(name)

    inner = getattr(check, "func", None)  # functools.partial
    inner_name = getattr(inner, "__name__", None)
    if isinstance(inner_name, str) and inner_name:
        return f"partial({mask_text(inner_name)})"

    return type(check).__name__


def _plural(count: object, noun: str) -> str:
    """Return ``noun`` pluralized for ``count`` (regular -s nouns only)."""
    return noun if count == 1 else f"{noun}s"


def _code_to_message(code: str) -> str:
    """Derive a human-readable message from a snake_case code."""
    return code.replace("_", " ")


def evaluate_invariants(
    changes: list[dict[str, Any]],
    baseline: dict[str, Any],
    checks: list[CheckFn],
    *,
    max_samples: int = 10,
    messages: dict[str, str] | None = None,
) -> PreflightReport:
    """Run every check over the proposed changes and return a consolidated report.

    All checks run regardless of earlier failures — the caller needs the full
    picture, not just the first violation.

    Args:
        changes: The proposed change list, each item a ``dict[str, Any]``.
        baseline: Contextual data for checks (e.g. total item count in the
            mailbox so a check can compute deletion percentages).
        checks: Callables conforming to :data:`CheckFn`.
        max_samples: Maximum number of offending items kept per violation.
        messages: Optional mapping from violation code to human-readable message.
            When absent for a code, the message is derived from the code itself.

    Returns:
        A :class:`PreflightReport` with ``passed=True`` iff no violations were
        found.  A check that raises is recorded as a violation with a distinct
        ``check_error`` code so buggy checks surface loudly rather than silently
        passing.
    """
    violations: list[InvariantViolation] = []

    for check in checks:
        try:
            code, offending = check(changes, baseline)
        except Exception as exc:  # nosec B112 - handler continues; the error is recorded as a violation, never swallowed
            error_code = "check_error"
            error_message = (messages or {}).get(
                error_code, _code_to_message(error_code)
            )
            # This single sample is deliberately exempt from max_samples: it is
            # not one offending item among many but the sole diagnostic for a
            # check that crashed. Truncating it under max_samples=0 would report
            # "a check failed" with no way to tell which one or why.
            #
            # Both the message and the traceback are masked. A check commonly
            # wraps an HTTP or API call, so its exception text and the source
            # lines quoted in the traceback can carry a URL query token or auth
            # header -- and this report is built to be serialized via to_dict().
            violations.append(
                InvariantViolation(
                    code=error_code,
                    message=error_message,
                    samples=[
                        {
                            "check": _check_label(check),
                            "error": mask_text(str(exc)),
                            "traceback": mask_text(traceback.format_exc()),
                        }
                    ],
                )
            )
            continue

        if not offending:
            continue

        message = (messages or {}).get(code) or _code_to_message(code)
        violations.append(
            InvariantViolation(
                code=code,
                message=message,
                samples=[_mask_sample(s) for s in offending[:max_samples]],
            )
        )

    tallies: dict[str, Any] = {
        "total_changes": len(changes),
        "violation_count": len(violations),
    }

    return PreflightReport(
        passed=len(violations) == 0,
        violations=violations,
        tallies=tallies,
    )
