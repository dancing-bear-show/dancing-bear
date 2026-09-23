"""Validate caller-overridable trigger params as DATA, never as shell source.

Workflow trigger params are overridable with ``--params`` and the engine's
``resolve_params`` substitutes them into stage description TEXT by raw string
replacement. Any guard that embeds such a value into shell source is defeatable
by some encoding of that value -- two mechanisms were tried and disproven by
probe:

* double quotes do NOT stop command substitution: ``"http://h$(echo PWNED)"``
  runs the subshell;
* a single-quoted heredoc (``<<'RAW'``) is also broken, because the value is
  substituted into the script text BEFORE bash parses it, so a value carrying a
  newline plus the literal delimiter closes the heredoc early, executes the
  remainder, and then passes the regex on the truncated remnant -- an inert
  guard that reports success after arbitrary code has already run.

What works is reading the value as DATA from the JSON file the engine itself
wrote (``init-workspace`` serialises every trigger param into
``manifest.json`` under ``trigger_params`` via ``json.dump``) and validating it
in Python. Only the engine-controlled workspace path is ever interpolated into
a command line; the untrusted value never becomes shell source at all.

This module is therefore deliberately shaped so that the value being checked is
NEVER a function argument sourced from the command line: callers pass the path
to the manifest and the patterns to enforce, and the values are read from disk.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ParamCheck:
    """One ``name=pattern`` requirement to enforce against a params mapping."""

    name: str
    pattern: str


@dataclass(frozen=True)
class ParamGuardResult:
    """Outcome of validating a set of params. ``ok`` is the contract."""

    ok: bool
    failures: tuple[str, ...] = ()


#: Where the params live inside the JSON document, by document kind.
_PARAMS_KEY = "trigger_params"


def parse_check(spec: str) -> ParamCheck:
    """Parse a ``name=pattern`` spec.

    The pattern may itself contain ``=``; only the first one separates.

    Raises:
        ValueError: if the spec has no ``=`` or an empty name or pattern.
    """
    name, sep, pattern = spec.partition("=")
    if not sep or not name or not pattern:
        raise ValueError(f"expected name=pattern, got {spec!r}")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid regex for {name!r}: {exc}") from exc
    return ParamCheck(name=name, pattern=pattern)


def load_params(manifest_path: str | Path, *, key: str | None = _PARAMS_KEY) -> dict[str, object]:
    """Read the params mapping out of a JSON document.

    Args:
        manifest_path: Path to the JSON file the engine wrote.
        key: Top-level key holding the mapping, or ``None`` to treat the whole
            document as the mapping (used for stage output files, which carry
            agent-written fields at the top level).

    Raises:
        ValueError: if the file is missing, is not JSON, or does not hold a
            JSON object at the expected location.
    """
    path = Path(manifest_path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc

    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(doc, dict):
        raise ValueError(f"{path} does not contain a JSON object")

    if key is None:
        return doc

    section = doc.get(key)
    if section is None:
        raise ValueError(f"{path} has no {key!r} section")
    if not isinstance(section, dict):
        raise ValueError(f"{path}: {key!r} is not a JSON object")
    return section


def check_params(params: dict[str, object], checks: list[ParamCheck]) -> ParamGuardResult:
    """Apply each check with ``re.fullmatch``, collecting every failure.

    A param that is absent, is not a string, or does not fully match its
    pattern is a failure. Every check is evaluated so the caller sees all
    problems at once rather than only the first.

    Rejected values are NOT echoed back: a value that reaches here may be
    hostile, and reproducing it into a log is how it finds its way onto a
    command line later.
    """
    failures: list[str] = []
    for check in checks:
        value = params.get(check.name)
        if value is None:
            failures.append(f"{check.name}: missing from params")
        elif not isinstance(value, str):
            failures.append(f"{check.name}: not a string (got {type(value).__name__})")
        elif re.fullmatch(check.pattern, value) is None:
            failures.append(f"{check.name}: does not match {check.pattern}")
    return ParamGuardResult(ok=not failures, failures=tuple(failures))


def select_printable(
    name: str, params: dict[str, object], checks: list[ParamCheck]
) -> str:
    """Return the value of ``name``, but only if a check covers and accepts it.

    This exists so ``check-params --print`` can hand a value to a shell
    variable without ever putting it in shell source. Two conditions guard it,
    and both are necessary:

    * ``name`` must appear among ``checks``. Printing a param nobody validated
      would hand the caller exactly what this module exists to withhold --
      and silently, since the command would still exit 0 on the strength of
      the OTHER params' checks.
    * the value must still satisfy every pattern registered for that name.
      Callers are expected to have run :func:`check_params` first; re-checking
      here means a future caller that forgets cannot leak an unvalidated
      value, rather than relying on call order for its safety.

    Raises:
        ValueError: if no check covers ``name``, or the value fails one.
    """
    patterns = [c.pattern for c in checks if c.name == name]
    if not patterns:
        raise ValueError(f"--print {name}: no --check covers it; refusing to print")

    value = params.get(name)
    if not isinstance(value, str):
        raise ValueError(f"--print {name}: not a string; refusing to print")
    if any(re.fullmatch(pattern, value) is None for pattern in patterns):
        raise ValueError(f"--print {name}: failed validation; refusing to print")
    return value
