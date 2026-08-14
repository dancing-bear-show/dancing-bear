#!/usr/bin/env python3
"""Fail loudly when a test directory cannot be reached by `unittest discover`.

Two failure modes, both silent by default and both seen in this repo:

1. A directory holding `test_*.py` has no `__init__.py`. `unittest discover`
   skips it without a warning, so the tests never run in `make test`, `make cov`,
   or CI — and the module under test reports 0% coverage as if it were untested.

2. The `__init__.py` exists on disk but is gitignored, so it never reaches CI.
   A bare `build/` pattern in .gitignore once matched `tests/metals_tests/build/`
   this way, hiding 8 passing tests from every automated run while they kept
   passing locally.

Exit 0 when every test directory is discoverable, 1 otherwise.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent / "tests"
SKIP_DIRS = {"__pycache__", ".pytest_cache"}


def _test_dirs(root: Path) -> list[Path]:
    """Directories under `root` that contain at least one test_*.py file."""
    found = []
    for path in sorted(root.rglob("test_*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        parent = path.parent
        if parent not in found:
            found.append(parent)
    return found


def _gitignored(paths: list[Path]) -> set[Path]:
    """Subset of `paths` that git would ignore (so CI would never see them)."""
    if not paths:
        return set()
    git_bin = shutil.which("git")
    if git_bin is None:
        print("WARNING: git not found in PATH — skipping gitignore check", file=sys.stderr)
        return set()
    proc = subprocess.run(  # nosec B603 B607 - git_bin resolved via shutil.which, fixed argv, no shell, input is repo-internal paths
        [git_bin, "check-ignore", "--stdin"],
        input="\n".join(str(p) for p in paths),
        capture_output=True,
        text=True,
        cwd=TESTS_ROOT.parent,
        check=False,
    )
    return {Path(line.strip()) for line in proc.stdout.splitlines() if line.strip()}


def main() -> int:
    if not TESTS_ROOT.is_dir():
        print(f"ERROR: no tests directory at {TESTS_ROOT}", file=sys.stderr)
        return 1

    dirs = _test_dirs(TESTS_ROOT)
    missing = [d for d in dirs if not (d / "__init__.py").exists()]
    present = [d / "__init__.py" for d in dirs if (d / "__init__.py").exists()]
    ignored = sorted(_gitignored(present))

    if not missing and not ignored:
        print(f"OK: all {len(dirs)} test directories are discoverable")
        return 0

    rel = lambda p: p.relative_to(TESTS_ROOT.parent)  # noqa: E731
    if missing:
        print(
            "ERROR: test directories missing __init__.py — `unittest discover` "
            "skips these silently:",
            file=sys.stderr,
        )
        for d in missing:
            print(f"  {rel(d)}/__init__.py", file=sys.stderr)
    if ignored:
        print(
            "ERROR: test __init__.py files exist but are gitignored — they will "
            "not reach CI:",
            file=sys.stderr,
        )
        for p in ignored:
            print(f"  {rel(p)}", file=sys.stderr)
        print(
            "  Fix the .gitignore pattern (anchor it with a leading slash) rather "
            "than force-adding the file.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
