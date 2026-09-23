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
    run = run_binary(_STATUS_CMD, cwd=root)
    if run.returncode != 0:
        raise RuntimeError(f"git status failed (exit {run.returncode}): {run.stderr.strip()}")
    return {p: _content_hash(root / p) for p in sorted(parse_porcelain_z(run.stdout))}


def _normalise(path: str) -> str:
    return path[2:] if path.startswith("./") else path


def unlisted_changes(
    baseline: Mapping[str, str | None],
    current: Mapping[str, str | None],
    listed: Iterable[str],
) -> list[str]:
    """Paths changed since *baseline* that *listed* does not name.

    A path changed if it is dirty now and was clean at baseline, if its
    content differs from the baseline's, or if it was dirty at baseline and is
    clean now (something reverted it).
    """
    named = {_normalise(p) for p in listed}
    changed = {p for p, digest in current.items() if p not in baseline or baseline[p] != digest}
    changed |= set(baseline) - set(current)
    return sorted(changed - named)
