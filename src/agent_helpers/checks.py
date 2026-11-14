"""run-tests: run the repo's test, lint, or typecheck gate from the repo root.

``test`` demands evidence the suite ran: a zero exit with no ``Ran N tests``
line (or ``Ran 0 tests``) is reported as a failure, because a broken venv step
can exit 0 without executing anything.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from core.process import run_binary

TOOL_CHOICES = ("test", "lint", "typecheck")

_TIMEOUTS_SECONDS = {"test": 1800.0, "lint": 300.0, "typecheck": 900.0}
_MAX_OUTPUT_CHARS = 20000
_RAN_LINE = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)
_NO_EVIDENCE = "no 'Ran N tests' line with N > 0 in output; the suite may not have run"


@dataclass(frozen=True)
class CheckResult:
    tool: str
    paths: list[str]
    commands: list[list[str]]
    exit_code: int
    passed: bool
    tests_run: int | None = None
    timed_out: bool = False
    error: str | None = None
    output: str = ""
    truncated: bool = False


def parse_tests_run(output: str) -> int | None:
    """Sum every ``Ran N tests`` line in ``output``; None when there is none."""
    counts = [int(n) for n in _RAN_LINE.findall(output)]
    return sum(counts) if counts else None


def _resolve_test_path(root: Path, raw: str) -> tuple[Path | None, str | None]:
    """Resolve ``raw`` to an existing path inside ``root``, or explain why not."""
    path = (root / raw).resolve()
    if path != root and root not in path.parents:
        return None, f"path escapes the repo: {raw}"
    if not path.exists():
        return None, f"path not found: {raw}"
    return path, None


def _unittest_command(root: Path, path: Path) -> list[str]:
    """``unittest discover`` for a directory, or for one file via ``-p``.

    ``root`` and ``path`` must both be resolved: unittest rejects a start
    directory that is not textually inside the top-level directory.
    """
    base = [sys.executable, "-m", "unittest", "discover", "-t", str(root)]
    if path.is_dir():
        return [*base, "-s", str(path)]
    return [*base, "-s", str(path.parent), "-p", path.name]


def build_commands(tool: str, repo_root: str, paths: list[str]) -> tuple[list[list[str]], str | None]:
    """Return the commands for ``tool`` (one per path for scoped test runs)."""
    if tool == "lint":
        return [["make", "lint"]], None
    if tool == "typecheck":
        return [["make", "typecheck-changed"]], None
    if not paths:
        return [["make", "test"]], None
    root = Path(repo_root).resolve()
    commands: list[list[str]] = []
    for raw in paths:
        path, error = _resolve_test_path(root, raw)
        if path is None:
            return [], error
        commands.append(_unittest_command(root, path))
    return commands, None


def _child_env(repo_root: str) -> dict[str, str]:
    """Environment with ``PYTHONPATH`` replaced by this checkout's ``src``.

    Replaced, not prepended: an inherited entry naming another checkout would
    otherwise resolve imports to that tree and give a false green.
    """
    return {**os.environ, "PYTHONPATH": str(Path(repo_root) / "src")}


def _tail(text: str) -> tuple[str, bool]:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text, False
    return text[-_MAX_OUTPUT_CHARS:], True


def run_check(tool: str, repo_root: str, paths: list[str]) -> CheckResult:
    """Run ``tool`` and return a verdict; never raises."""
    commands, error = build_commands(tool, repo_root, paths)
    if error:
        return CheckResult(tool, paths, [], 1, False, error=error)

    env = _child_env(repo_root)
    exit_code = 0
    timed_out = False
    chunks: list[str] = []
    for cmd in commands:
        run = run_binary(cmd, cwd=repo_root, timeout=_TIMEOUTS_SECONDS[tool], env=env, errors="replace")
        chunks.append(run.stdout + run.stderr)
        timed_out = timed_out or run.timed_out
        if run.returncode != 0 and exit_code == 0:
            exit_code = run.returncode

    full_output = "".join(chunks)
    output, truncated = _tail(full_output)
    tests_run = parse_tests_run(full_output) if tool == "test" else None
    passed = exit_code == 0 and not timed_out
    problem: str | None = "timed out" if timed_out else None
    if tool == "test" and passed and not tests_run:
        passed, problem = False, _NO_EVIDENCE
    return CheckResult(
        tool=tool,
        paths=paths,
        commands=commands,
        exit_code=exit_code,
        passed=passed,
        tests_run=tests_run,
        timed_out=timed_out,
        error=problem,
        output=output,
        truncated=truncated,
    )
