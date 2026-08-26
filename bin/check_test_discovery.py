#!/usr/bin/env python3
"""Fail loudly when a test directory cannot be reached by `unittest discover`.

Three failure modes, all silent by default and all seen in this repo:

1. A directory holding `test_*.py` has no `__init__.py`. `unittest discover`
   skips it without a warning, so the tests never run in `make test`, `make cov`,
   or CI — and the module under test reports 0% coverage as if it were untested.

2. The `__init__.py` exists on disk but is gitignored, so it never reaches CI.
   A bare `build/` pattern in .gitignore once matched `tests/metals_tests/build/`
   this way, hiding 8 passing tests from every automated run while they kept
   passing locally.

3. A test directory's name shadows a stdlib or third-party module. Under
   `unittest discover -s tests/<domain>` (no `-t`), the discovery root goes on
   sys.path, so `tests/resume_tests/docx/` won the import over the real
   `python-docx` — 198 phantom errors, and mock.patch reported them as
   unrelated AttributeErrors. `make test` is immune (bare `python -m unittest`
   from the repo root keeps `tests` as the top-level package), which is exactly
   what let it sit undetected: the failure only appears in domain-scoped runs,
   which is what the agent workflows use.

Exit 0 when every test directory is discoverable, 1 otherwise.
"""
from __future__ import annotations

import shutil
import subprocess  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B602/B603 review
import sys
import sysconfig
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent / "tests"
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
INIT_PY = "__init__.py"

# Directory names allowed to shadow an importable module. Add only names that
# are provably safe (never imported by src/ under that name).
SHADOW_ALLOWLIST: set[str] = set()


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


def _importable_names() -> set[str]:
    """Top-level module names that a test dirname could shadow.

    Covers the stdlib plus whatever is installed in site-packages, since the
    collision that motivated this check was against the third-party
    `python-docx`, not the stdlib.
    """
    names = set(sys.stdlib_module_names)
    for key in ("purelib", "platlib"):
        site = sysconfig.get_paths().get(key)
        if not site or not Path(site).is_dir():
            continue
        for entry in Path(site).iterdir():
            if entry.name.startswith(("_", ".")):
                continue
            if entry.is_dir() and (entry / INIT_PY).exists():
                names.add(entry.name)
            elif entry.suffix == ".py":
                names.add(entry.stem)
    return names


def _shadowing(dirs: list[Path]) -> list[tuple[Path, str]]:
    """Test dirs whose name shadows an importable top-level module."""
    importable = _importable_names()
    hits = []
    for d in dirs:
        if d == TESTS_ROOT or d.name in SHADOW_ALLOWLIST:
            continue
        if d.name in importable:
            hits.append((d, d.name))
    return sorted(hits)


def main() -> int:
    if not TESTS_ROOT.is_dir():
        print(f"ERROR: no tests directory at {TESTS_ROOT}", file=sys.stderr)
        return 1

    dirs = _test_dirs(TESTS_ROOT)
    missing = [d for d in dirs if not (d / INIT_PY).exists()]
    present = [d / INIT_PY for d in dirs if (d / INIT_PY).exists()]
    ignored = sorted(_gitignored(present))
    shadowing = _shadowing(dirs)

    if not missing and not ignored and not shadowing:
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
    if shadowing:
        print(
            "ERROR: test directory names shadow importable modules — under "
            "`unittest discover -s <dir>` (no -t) these win the import and "
            "produce phantom failures:",
            file=sys.stderr,
        )
        for d, name in shadowing:
            print(f"  {rel(d)}  shadows module '{name}'", file=sys.stderr)
        print(
            "  Rename the directory (e.g. 'docx' -> 'docx_tests'), updating any "
            "dotted imports that name it.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
