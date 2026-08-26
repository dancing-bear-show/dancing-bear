"""Repo-relative path safety guard.

Verifies that a candidate path is safe to write back into:
  (a) resolves to a location inside the repo root (after symlink resolution)
  (b) does NOT resolve inside <repo_root>/.git/
  (c) is an existing regular file (not a directory, not missing, not special)

A cheap syntactic pre-filter rejects absolute paths and any path containing
a ".." segment *before* the realpath check — a path-traversal defence.

This is the single implementation used by both the ``bin/path-guard`` wrapper
and any workflow that previously inlined a 300-char Python one-liner for the
same purpose.

Exit semantics (used by ``bin/path-guard``):
  0  — path is safe
  1  — path was rejected; reason written to stderr
  2  — usage error (wrong argument count); usage written to stderr

A caller that treats "nonzero" as "unsafe" is correct: 2 means the guard
never ran, which must not be read as a pass.

Usage::

    from core.path_guard import check_path_safe, PathGuardError

    check_path_safe("/repo/root", "src/mail/cli.py")  # returns None; raises on refusal
"""
from __future__ import annotations

import os
import stat
import sys


class PathGuardError(Exception):
    """Raised when a path fails the safety check."""


def check_path_safe(repo_root: str, candidate: str) -> None:
    """Verify *candidate* is a safe, existing regular file inside *repo_root*.

    Applies a cheap syntactic pre-filter first (absolute paths, ".." segments),
    then resolves symlinks and verifies the resolved path is:
      * inside repo_root (after realpath)
      * NOT inside repo_root/.git/
      * an existing regular file

    Args:
        repo_root: Absolute path to the repository root (need not be realpath'd
            beforehand — this function calls os.path.realpath on it).
        candidate: The path string to validate (relative or absolute).

    Raises:
        PathGuardError: If the path fails any check, with a short reason string.
    """
    # --- syntactic pre-filter (cheap, no I/O) ---
    if os.path.isabs(candidate):
        raise PathGuardError(f"absolute path rejected: {candidate}")
    segments = candidate.replace("\\", "/").split("/")
    if ".." in segments:
        raise PathGuardError(f"path with '..' segment rejected: {candidate}")

    # --- realpath resolution ---
    real_repo = os.path.realpath(repo_root)
    real_target = os.path.realpath(os.path.join(real_repo, candidate))
    git_dir = os.path.join(real_repo, ".git")

    in_repo = real_target == real_repo or real_target.startswith(real_repo + os.sep)
    if not in_repo:
        raise PathGuardError(
            f"path escapes repo root after symlink resolution: {candidate}"
        )

    in_git = real_target == git_dir or real_target.startswith(git_dir + os.sep)
    if in_git:
        raise PathGuardError(f"path resolves inside .git/: {candidate}")

    try:
        st = os.stat(real_target)
    except FileNotFoundError:
        raise PathGuardError(f"path does not exist: {candidate}")

    if not stat.S_ISREG(st.st_mode):
        raise PathGuardError(f"path is not a regular file: {candidate}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: ``path-guard <repo_root> <candidate_path>``.

    Exits 0 if safe, 1 if refused (reason on stderr).
    """
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print(
            "Usage: path-guard <repo_root> <candidate_path>",
            file=sys.stderr,
        )
        return 2
    repo_root, candidate = args
    try:
        check_path_safe(repo_root, candidate)
        return 0
    except PathGuardError as exc:
        print(f"path-guard: refused — {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
