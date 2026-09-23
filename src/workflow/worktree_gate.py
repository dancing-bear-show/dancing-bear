"""Unlisted-edit gate for workflows that commit a list of fixer-edited files.

commit-and-push stages exactly the paths fix-results.json lists. Anything a
fixer edited that is NOT on that list was silently left behind: on the first
live run of review-fix-threads, a fixer's test file was missing from the list,
so the fix would have been pushed without its tests while verify-fixes -- which
tests the working tree -- still passed.

The checkout is shared with other sessions, so "the tree is dirty" is not by
itself a signal. The gate therefore compares against a snapshot taken before
any fixer ran: a path counts as changed by this run if it is newly dirty, or if
it was already dirty and its content has since changed. Every such path must
be on the list.

``git status`` alone only sees uncommitted changes. A fixer has Bash access and
the no-git rule is prose-only, so a fixer that stages and commits an unlisted
file before check-unlisted runs would show a clean status for that path even
though it changed after the baseline. ``head_commit``/``committed_since`` close
that gap: the baseline also records HEAD, and any path touched by a commit made
since is treated the same as a dirty, unlisted path.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path

from core.process import run_binary

#: ``git status`` flags: NUL-separated, never quoted, every untracked file
#: listed individually rather than collapsed to its directory.
_STATUS_CMD = ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all")

#: Porcelain v1 status letters whose entry is followed by a second NUL field,
#: the rename or copy origin.
_HAS_ORIGIN = frozenset("RC")

#: Bound on ``git status``/``git rev-parse``/``git diff``, in seconds. This
#: gate runs immediately before committing and pushing; a hung or blocked git
#: process must fail closed rather than leave snapshot-dirty/check-unlisted
#: waiting indefinitely.
_GIT_STATUS_TIMEOUT = 30.0

_HEAD_CMD = ("git", "rev-parse", "HEAD")


def parse_porcelain_z(output: str) -> set[str]:
    """Return every path named in ``git status --porcelain=v1 -z`` output.

    A rename or copy entry is followed by its origin as a separate field; both
    paths are returned, since a rename touches both.
    """
    paths: set[str] = set()
    fields = output.split("\0")
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        paths.add(entry[3:])
        if _HAS_ORIGIN & set(entry[:2]) and i < len(fields) and fields[i]:
            paths.add(fields[i])
            i += 1
    return paths


def _content_hash(path: Path) -> str | None:
    """sha256 of a file's bytes, of a symlink's target, or None if absent."""
    if path.is_symlink():
        return "link:" + hashlib.sha256(str(path.readlink()).encode()).hexdigest()
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    return None


def snapshot_dirty(repo: str | Path) -> dict[str, str | None]:
    """Map every dirty or untracked path in *repo* to its content hash.

    Raises:
        RuntimeError: if ``git status`` fails -- a gate that cannot see the
            tree must fail closed, never report it clean.
    """
    root = Path(repo)
    run = run_binary(_STATUS_CMD, cwd=root, timeout=_GIT_STATUS_TIMEOUT)
    if run.returncode != 0:
        raise RuntimeError(f"git status failed (exit {run.returncode}): {run.stderr.strip()}")
    return {p: _content_hash(root / p) for p in sorted(parse_porcelain_z(run.stdout))}


def head_commit(repo: str | Path) -> str:
    """Return the full sha of *repo*'s current HEAD.

    Raises:
        RuntimeError: if ``git rev-parse HEAD`` fails -- an unresolvable HEAD
            (no commits yet, detached and broken, not a repo) must fail closed
            rather than silently skip the commit check.
    """
    run = run_binary(_HEAD_CMD, cwd=Path(repo), timeout=_GIT_STATUS_TIMEOUT)
    if run.returncode != 0:
        raise RuntimeError(f"git rev-parse HEAD failed (exit {run.returncode}): {run.stderr.strip()}")
    return run.stdout.strip()


def committed_since(repo: str | Path, baseline_head: str) -> set[str]:
    """Paths touched by any commit made in *repo* since *baseline_head*.

    Closes the gap ``snapshot_dirty`` alone cannot: a fixer with Bash access
    can stage and commit an unlisted file before check-unlisted runs, and
    ``git status`` reports that path clean once it is committed even though it
    changed after the baseline.

    Uses ``git log --name-only`` over the commit range rather than a single
    ``git diff baseline..HEAD`` two-tree comparison: a two-tree diff nets out
    a path that one commit added and a later commit removed, so a
    commit-then-revert of an unlisted file would leave no trace. Walking each
    commit's own diff against its parent still reports that path, once per
    commit that touched it. ``--no-renames`` is passed for the same reason
    ``parse_porcelain_z`` keeps both sides of a rename: with rename detection
    on, a commit that renames a protected/unlisted source path would report
    only the destination filename, letting the original path -- and whatever
    it protected -- skip both this check and check-paths.

    Raises:
        RuntimeError: if the log over *baseline_head*..HEAD fails -- including
            when *baseline_head* no longer resolves (e.g. history was
            rewritten), since that is itself evidence the gate cannot trust
            what changed and must fail closed rather than report no commits.
    """
    run = run_binary(
        ("git", "log", "--name-only", "--no-renames", "-z", "--pretty=format:",
         f"{baseline_head}..HEAD"),
        cwd=Path(repo),
        timeout=_GIT_STATUS_TIMEOUT,
    )
    if run.returncode != 0:
        raise RuntimeError(
            f"git log {baseline_head}..HEAD failed (exit {run.returncode}): {run.stderr.strip()}"
        )
    return {p for p in run.stdout.split("\0") if p}


def _normalise(path: str) -> str:
    return path[2:] if path.startswith("./") else path


def unlisted_changes(
    baseline: Mapping[str, str | None],
    current: Mapping[str, str | None],
    listed: Iterable[str],
    committed: Iterable[str] = (),
) -> list[str]:
    """Paths changed since *baseline* that *listed* does not name.

    A path changed if it is dirty now and was clean at baseline, if its
    content differs from the baseline's, if it was dirty at baseline and is
    clean now (something reverted it), or if it appears in *committed* -- the
    paths touched by a commit made since the baseline HEAD (see
    ``committed_since``). A committed path is included even when it is also
    absent from *current*: staging and committing a file makes ``git status``
    report it clean, which would otherwise let it slip through the working-tree
    comparison alone.
    """
    named = {_normalise(p) for p in listed}
    changed = {p for p, digest in current.items() if p not in baseline or baseline[p] != digest}
    changed |= set(baseline) - set(current)
    changed |= set(committed)
    return sorted(changed - named)
