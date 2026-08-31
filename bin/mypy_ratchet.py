#!/usr/bin/env python3
"""Incremental mypy enforcement: a changed-files gate and a repo-wide ratchet.

`make typecheck` is report-only (it ends in `|| true`) and CI never invoked it,
so the type gate was decorative — nothing stopped a PR adding new untyped or
mis-typed code. Gating on a clean run is not viable either: the repo carries a
large pre-existing error count, most of it structural (untyped dicts, and mixins
whose attributes live on the sibling class). See the mypy note in pyproject.toml
[dev] for that reasoning; this script extends it rather than replacing it.

Two modes, both exiting non-zero on regression:

  changed  — run mypy over only the .py files this branch changed, and fail if
             any of them has an error. Files that already carried errors at
             baseline are listed in the baseline's `legacy_files` and are
             reported but not blocking, so a contributor is never blocked by
             debt they did not write.

  ratchet  — run mypy repo-wide, compare per-package counts against the
             committed baseline, and fail if any package regressed.

Both modes fail loudly rather than silently passing. The two ways this lands
broken are a run that checked nothing and a summary line that could not be
parsed, and each is an explicit error here:

  - An empty file list in `changed` mode is NOT a pass. The scanned-file count
    is always printed, and a degenerate diff falls back to the working tree
    before reporting "0 files" as an explicit, visible outcome.
  - A missing `Found N errors` / `Success` summary line is a hard failure. mypy
    prints notes and context lines that are not errors, so the summary is
    parsed rather than the output counted; if mypy crashed, matched no files, or
    was invoked wrongly, treating that as zero errors would silently disarm the
    ratchet permanently.

Baseline file: see BASELINE_PATH. Regenerate with `--update-baseline` (wired up
as `make typecheck-baseline`) and commit the result; nothing rewrites it
automatically, because a silent rewrite defeats the ratchet.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B603 review
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = REPO_ROOT / "typecheck-baseline.json"

# Roots the gate is willing to check, and the same set the baseline measures.
# A path outside these is ignored rather than silently unchecked.
#
# bin/ is included despite holding mostly extensionless wrappers: those are
# symlinks to _router.py, so mypy sees only the handful of real .py files
# there — and they are real logic (this script among them). Excluding bin/
# would leave new CLI-adjacent code ungated, which is the hole this gate exists
# to close.
CHECKED_ROOTS = ("src", "tests", "bin")

# Matches mypy's own summary line, the only trustworthy error count in its
# output. `Found 1 error in 1 file` is singular, hence the optional plurals.
_SUMMARY_RE = re.compile(r"^Found (\d+) errors? in (\d+) files?", re.MULTILINE)
_SUCCESS_RE = re.compile(r"^Success: no issues found", re.MULTILINE)

# Matches a single mypy diagnostic. Notes (`: note:`) are deliberately excluded:
# mypy emits them as context for an adjacent error, not as findings of their own.
_ERROR_RE = re.compile(r"^(?P<path>[^:]+):(?P<line>\d+):(?:\d+:)? error:", re.MULTILINE)


class MypyInvocationError(RuntimeError):
    """mypy produced output we cannot trust — never treated as zero errors."""


def _mypy_cmd() -> list[str]:
    """Resolve the interpreter running mypy, preferring this checkout's venv.

    A bare `mypy` on PATH may be absent or belong to another checkout; the venv
    copy is the pinned one the Makefile installs.
    """
    venv_py = REPO_ROOT / ".venv" / "bin" / "python"
    python = str(venv_py) if venv_py.exists() else sys.executable
    return [python, "-m", "mypy", "--ignore-missing-imports"]


def _run_mypy(paths: list[str]) -> str:
    """Run mypy over `paths` and return its combined output."""
    proc = subprocess.run(  # nosec B603 - fixed argv, no shell; paths are repo-internal and validated by the caller
        [*_mypy_cmd(), *paths],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    output = proc.stdout + proc.stderr
    if not output.strip():
        raise MypyInvocationError(
            f"mypy produced no output at all (exit {proc.returncode}). "
            "Refusing to interpret that as a clean run."
        )
    return output


def _parse_total(output: str) -> int:
    """Extract the error count from mypy's summary line.

    Raises rather than defaulting to 0: an unparseable run means we do not know
    the count, and guessing zero would disarm the ratchet for good.
    """
    match = _SUMMARY_RE.search(output)
    if match:
        return int(match.group(1))
    if _SUCCESS_RE.search(output):
        return 0
    raise MypyInvocationError(
        "could not find mypy's summary line ('Found N errors' or 'Success') in "
        "its output. mypy likely crashed or matched no files. Output was:\n"
        + output.strip()[-2000:]
    )


def _errors_by_file(output: str) -> dict[str, int]:
    """Count real errors (not notes) per file path, as mypy reported them."""
    counts: dict[str, int] = {}
    for match in _ERROR_RE.finditer(output):
        path = match.group("path")
        counts[path] = counts.get(path, 0) + 1
    return counts


def _package_of(path: str) -> str:
    """Group key for a path: `src/<pkg>/...` -> `<pkg>`, else the top-level dir.

    Per-package rather than a single total because a regression in a small
    package (wifi has 2 errors) is invisible against a four-hundred-error total
    but obvious against its own number.
    """
    parts = Path(path).parts
    if len(parts) >= 2 and parts[0] == "src":
        return parts[1]
    return parts[0] if parts else path


def _packages(counts: dict[str, int]) -> dict[str, int]:
    """Aggregate per-file counts into per-package counts."""
    packages: dict[str, int] = {}
    for path, count in counts.items():
        key = _package_of(path)
        packages[key] = packages.get(key, 0) + count
    return dict(sorted(packages.items()))


def _rev_exists(ref: str) -> bool:
    """True when `ref` resolves to a commit in this clone."""
    return bool(_git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip())


def _git(*args: str) -> str:
    """Run a git command in the repo root, returning stdout ('' on failure)."""
    git_bin = shutil.which("git")
    if git_bin is None:
        print("WARNING: git not found in PATH", file=sys.stderr)
        return ""
    proc = subprocess.run(  # nosec B603 - git_bin resolved via shutil.which, fixed argv, no shell
        [git_bin, *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else ""


def _is_checkable(rel_path: str) -> bool:
    """True for existing .py files under a root the gate checks."""
    if not rel_path.endswith(".py"):
        return False
    if not rel_path.startswith(tuple(f"{r}/" for r in CHECKED_ROOTS)):
        return False
    # Skip deleted files: they are in the diff but no longer on disk, and
    # passing a nonexistent path makes mypy error out on the invocation itself.
    return (REPO_ROOT / rel_path).is_file()


def _changed_files(base: str) -> tuple[list[str], str]:
    """Python files changed versus `base`, plus the source used to find them.

    Three dots, not two: `main..HEAD` diffs against the current tip of main and
    drags in every commit merged since the branch started (on a day-old branch
    that turned 9 changed files into 46). Three dots diffs against the
    merge-base — this branch's changes only, the same set CI evaluates.

    The committed diff is unioned with the working tree (modified, staged, and
    untracked), never used alone. Taking the diff alone and only falling back
    when it is empty means that on a branch with any commit at all, staged and
    uncommitted work is silently skipped — a developer running this before
    committing would get a pass while their new code went unchecked. That is
    the same false-clean this gate exists to prevent, so both sources always
    contribute.
    """
    # An unresolvable base is a hard error, not a quiet downgrade to the working
    # tree. A typo in TYPECHECK_BASE, or a shallow CI clone with no merge-base,
    # would otherwise check almost nothing and report a pass — the exact
    # false-clean this gate is built to prevent. CI must use fetch-depth: 0.
    if not _rev_exists(base):
        raise MypyInvocationError(
            f"base ref {base!r} does not resolve to a commit in this clone. "
            "In CI this usually means a shallow checkout — set `fetch-depth: 0` "
            "on actions/checkout. Locally, fetch the branch or pass a valid "
            "--base. Refusing to fall back to the working tree, because that "
            "would silently check far less than intended."
        )

    sources: list[str] = []

    diff = _git("diff", "--name-only", "--diff-filter=d", f"{base}...HEAD")
    committed = [p for p in diff.splitlines() if _is_checkable(p)]
    if committed:
        sources.append(f"git diff {base}...HEAD")

    working: list[str] = []
    for line in _git("status", "--porcelain").splitlines():
        if not line.strip():
            continue
        path = line[3:].strip() if len(line) > 3 else ""
        # Renames read as `old -> new`; only the destination exists on disk.
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path and _is_checkable(path):
            working.append(path)
    if working:
        sources.append("working tree")

    files = sorted(set(committed) | set(working))
    if sources:
        label = " + ".join(sources)
    else:
        label = f"git diff {base}...HEAD + working tree"
    return files, label


def _display_path(path: Path) -> str:
    """Repo-relative path when possible, absolute otherwise.

    relative_to() raises for a path outside the repo, so it cannot be used bare
    inside an error message — that turns a clear diagnostic into a ValueError.
    """
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _load_baseline() -> dict:
    """Read the committed baseline, failing loudly when it is missing."""
    if not BASELINE_PATH.exists():
        raise MypyInvocationError(
            f"no baseline at {_display_path(BASELINE_PATH)}. "
            "Generate it with `make typecheck-baseline` and commit the result."
        )
    with BASELINE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_baseline(total: int, packages: dict[str, int], legacy: list[str]) -> None:
    """Write the baseline file, sorted for a stable diff."""
    payload = {
        "_comment": (
            "mypy ratchet baseline. Regenerate with `make typecheck-baseline` "
            "and commit. `total`/`packages` gate the repo-wide ratchet; "
            "`legacy_files` lists files that already had errors when the gate "
            "was introduced, which the changed-files gate reports but does not "
            "block on. Never let these numbers grow."
        ),
        "mypy_version": "2.3.1",
        "mypy_args": ["--ignore-missing-imports"],
        "roots": list(CHECKED_ROOTS),
        "total": total,
        "packages": packages,
        "legacy_files": sorted(legacy),
    }
    with BASELINE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")


def cmd_changed(args: argparse.Namespace) -> int:
    """Fail if any file this branch changed has a new mypy error."""
    files, source = _changed_files(args.base)

    # Always print the count. An empty list is the failure mode this whole
    # branch of the code exists to make visible: mypy given no paths exits 0
    # having checked nothing, which is indistinguishable from a real pass.
    print(f"typecheck-changed: {len(files)} file(s) to check (via {source})")

    if not files:
        print(
            "typecheck-changed: 0 files to check — nothing changed under "
            f"{'/, '.join(CHECKED_ROOTS)}/. This is NOT a type-check pass; "
            "no files were examined."
        )
        return 0

    for path in files:
        print(f"  {path}")

    baseline = _load_baseline()
    legacy = set(baseline.get("legacy_files", []))

    output = _run_mypy(files)
    total = _parse_total(output)  # Validates the run before we trust its errors.
    per_file = _errors_by_file(output)

    blocking = {p: n for p, n in per_file.items() if p not in legacy}
    grandfathered = {p: n for p, n in per_file.items() if p in legacy}

    if grandfathered:
        print(
            f"\ntypecheck-changed: {sum(grandfathered.values())} pre-existing "
            f"error(s) in {len(grandfathered)} changed file(s) — reported, not blocking:"
        )
        for path, count in sorted(grandfathered.items()):
            print(f"  {path}: {count}")
        print(
            "  These files already had errors when the gate was introduced. "
            "Fixing them is welcome but not required; if you do, regenerate the "
            "baseline with `make typecheck-baseline`."
        )

    if not blocking:
        if grandfathered:
            print(
                f"\ntypecheck-changed: OK — {len(files)} file(s) checked, no new "
                f"type errors ({total} reported, all pre-existing)."
            )
        else:
            print(f"\ntypecheck-changed: OK — {len(files)} file(s) checked, no type errors.")
        return 0

    sys.stdout.flush()  # Keep the stderr block below ordered after the listing.
    print(
        f"\ntypecheck-changed: FAIL — {sum(blocking.values())} type error(s) in "
        f"{len(blocking)} changed file(s):",
        file=sys.stderr,
    )
    for line in output.splitlines():
        match = _ERROR_RE.match(line)
        if match and match.group("path") in blocking:
            print(f"  {line}", file=sys.stderr)
    print(
        "\nThese files are not in the baseline's legacy list, so the errors are "
        "new. Fix them, or — if the file is genuinely pre-existing debt you only "
        "moved — say so in the PR rather than adding a type: ignore.",
        file=sys.stderr,
    )
    return 1


def cmd_ratchet(args: argparse.Namespace) -> int:
    """Fail if the repo-wide error count grew against the committed baseline."""
    baseline = _load_baseline()
    output = _run_mypy(list(CHECKED_ROOTS))
    total = _parse_total(output)
    packages = _packages(_errors_by_file(output))

    base_total = baseline["total"]
    base_packages = baseline.get("packages", {})

    print(f"typecheck-ratchet: {total} error(s) now, {base_total} at baseline")

    regressed = {
        pkg: (count, base_packages.get(pkg, 0))
        for pkg, count in packages.items()
        if count > base_packages.get(pkg, 0)
    }

    if regressed:
        sys.stdout.flush()  # Keep the stderr block below ordered after the summary.
        print("\ntypecheck-ratchet: FAIL — these packages regressed:", file=sys.stderr)
        for pkg, (now, was) in sorted(regressed.items()):
            print(f"  {pkg}: {was} -> {now}  (+{now - was})", file=sys.stderr)

        # Name the files, not just the package. A bare "+1" gives no way to tell
        # a real regression from an environment difference (a dependency whose
        # stubs resolve differently on another OS), and sends the reader hunting
        # through the whole package.
        per_file = _errors_by_file(output)
        legacy = baseline.get("legacy_files", [])
        legacy_counts = {path: 0 for path in legacy}
        suspects = {
            path: count
            for path, count in per_file.items()
            if _package_of(path) in regressed and path not in legacy_counts
        }
        if suspects:
            print("\n  Files with errors that were clean at baseline:", file=sys.stderr)
            for path, count in sorted(suspects.items()):
                print(f"    {path}: {count}", file=sys.stderr)
            for line in output.splitlines():
                match = _ERROR_RE.match(line)
                if match and match.group("path") in suspects:
                    print(f"      {line}", file=sys.stderr)
        else:
            print(
                "\n  No newly-failing file: every error is in a file that was "
                "already in the baseline, so a file's own count grew. Run "
                "`make typecheck-ratchet` locally to compare, and note that the "
                "baseline is platform-sensitive — some dependency stubs resolve "
                "differently across operating systems.",
                file=sys.stderr,
            )

        print(
            "\nNew type errors were introduced. Fix them; do not raise the "
            "baseline to accommodate them.",
            file=sys.stderr,
        )
        return 1

    improved = {
        pkg: (packages.get(pkg, 0), was)
        for pkg, was in base_packages.items()
        if packages.get(pkg, 0) < was
    }
    if improved:
        print("\ntypecheck-ratchet: improvements found:")
        for pkg, (now, was) in sorted(improved.items()):
            print(f"  {pkg}: {was} -> {now}  ({now - was})")
        print(
            f"\n  Total is down {base_total - total}. Lock it in:\n"
            "    make typecheck-baseline\n"
            "  then commit typecheck-baseline.json. (Not done automatically — a "
            "silent rewrite would defeat the ratchet.)"
        )
        return 0

    print("typecheck-ratchet: OK — no package regressed.")
    return 0


def _format_delta(delta: int) -> str:
    """Render a signed count change for the baseline-update summary."""
    if delta == 0:
        return "unchanged"
    return f"+{delta}" if delta > 0 else str(delta)


def cmd_update_baseline(args: argparse.Namespace) -> int:
    """Regenerate the baseline from the current tree."""
    output = _run_mypy(list(CHECKED_ROOTS))
    total = _parse_total(output)
    per_file = _errors_by_file(output)
    packages = _packages(per_file)

    previous = None
    if BASELINE_PATH.exists():
        with BASELINE_PATH.open(encoding="utf-8") as handle:
            previous = json.load(handle).get("total")

    _write_baseline(total, packages, list(per_file))

    rel = _display_path(BASELINE_PATH)
    if previous is None:
        print(f"Wrote {rel}: {total} error(s) in {len(per_file)} file(s).")
    else:
        delta = total - previous
        direction = _format_delta(delta)
        print(f"Updated {rel}: {previous} -> {total} ({direction}).")
        if delta > 0:
            print(
                "  WARNING: the count went UP. Only do this deliberately — the "
                "ratchet exists to stop exactly this.",
                file=sys.stderr,
            )
    print("  Commit the file to lock the new ceiling in.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mypy_ratchet",
        description="Incremental mypy enforcement: changed-files gate and repo-wide ratchet.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    changed = sub.add_parser("changed", help="fail on type errors in changed files")
    changed.add_argument(
        "--base",
        default="main",
        help="branch to diff against with three dots (default: main)",
    )
    changed.set_defaults(func=cmd_changed)

    ratchet = sub.add_parser("ratchet", help="fail if the repo-wide count grew")
    ratchet.set_defaults(func=cmd_ratchet)

    update = sub.add_parser("update-baseline", help="regenerate the baseline file")
    update.set_defaults(func=cmd_update_baseline)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except MypyInvocationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
