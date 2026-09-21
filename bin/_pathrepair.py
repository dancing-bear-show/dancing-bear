#!/usr/bin/env python3
"""Import-path repair shared by every bin/ entry point.

This module exists because a ``PYTHONPATH`` entry naming ANOTHER checkout of
this repo silently wins the import race against the checkout you are editing.
The module names are identical (``core``, ``mail``, ``resume``, ...), so the
loser is invisible: the command runs, exits 0, and reports behaviour from
source nobody is editing.

How the wrong path gets there: ``.envrc`` exports ``PYTHONPATH="$PWD/src"``,
and direnv loads the ``.envrc`` of whichever checkout the shell *started* in.
Launch a shell in the main checkout, cd into ``.claude/worktrees/<wt>``, and
``PYTHONPATH`` still points at the main ``src/`` — the worktree's own ``.envrc``
is a different file and is not on direnv's allow list. A ``PYTHONPATH`` entry
also outranks the editable install's ``.pth``, so even the worktree's OWN
``.venv`` interpreter resolves those packages to the other tree.

Why this lives in ``bin/`` and not ``src/core/``
------------------------------------------------
Its entire job is to run BEFORE ``src/`` is importable. Putting it under
``src/core/`` would make the repair depend on the very import path it exists to
repair — and on a broken path it would either fail to import or, far worse,
import the FOREIGN checkout's copy of itself and "repair" nothing.

Callers therefore load it by explicit filesystem path relative to their own
``__file__`` (see ``bin/llm`` and ``bin/path-guard``), never via ``import``.
``bin/_router.py`` inlines the same logic because it is generated from a
template in ``bin/_gen_wrappers.py``; ``tests/infra/test_pathrepair_shared.py``
pins the two copies to identical behaviour.

Usage contract — ordering matters
---------------------------------
1. ``strip_foreign_src_paths(repo_root)`` BEFORE any ``.venv`` re-exec, so the
   corrected ``PYTHONPATH`` is inherited across ``os.execv``.
2. ``force_own_src_first(repo_root)`` AFTER the re-exec, immediately before the
   first ``from core.… import`` line.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "PROJECT_MARKER",
    "force_own_src_first",
    "is_foreign_repo_src",
    "strip_foreign_src_paths",
]

#: Sibling ``pyproject.toml`` content that identifies a checkout as THIS repo.
PROJECT_MARKER = 'name = "personal-assistants"'


def is_foreign_repo_src(entry: str, own_src: str) -> bool:
    """True when *entry* is the ``src/`` of a DIFFERENT checkout of THIS repo.

    The marker is a sibling ``pyproject.toml`` that names *this* project. A
    pyproject.toml alone is far too broad — most third-party checkouts have one,
    so matching on its mere presence would strip unrelated PYTHONPATH entries
    and break setups this repo knows nothing about.
    """
    try:
        resolved = Path(entry).resolve()
        if resolved.name != "src" or str(resolved) == own_src:
            return False
        proj = resolved.parent / "pyproject.toml"
        if not proj.is_file():
            return False
        return PROJECT_MARKER in proj.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False  # unreadable path: keep it rather than guess


def strip_foreign_src_paths(repo_root: Path) -> list[str]:
    """Drop PYTHONPATH entries that are another checkout's ``src/``.

    An entry is foreign when it is a ``src`` directory that is not
    ``repo_root/src`` and sits beside a ``pyproject.toml`` naming THIS project.
    That test is deliberately narrow: it removes other checkouts of this repo
    and leaves unrelated third-party ``PYTHONPATH`` entries alone, since
    stripping those would break setups this repo knows nothing about.

    Both ``os.environ["PYTHONPATH"]`` and the live ``sys.path`` are repaired —
    the environment so a re-exec and any child process inherit the correction,
    ``sys.path`` because PYTHONPATH was already expanded at interpreter startup
    and editing the environment alone does nothing for a process that does not
    re-exec.

    Returns the entries that were removed. Callers need not bind the result —
    ``DANCING_BEAR_PATH_DEBUG=1`` is how a human sees what was dropped — but the
    return value is what tests assert against.
    """
    raw = os.environ.get("PYTHONPATH", "")
    if not raw:
        return []

    own_src = str(repo_root / "src")
    kept: list[str] = []
    dropped: list[str] = []
    for entry in filter(None, raw.split(os.pathsep)):
        target = dropped if is_foreign_repo_src(entry, own_src) else kept
        target.append(entry)

    if not dropped:
        return []

    # Rewrite the variable so a re-exec and any subprocess this command spawns
    # inherit the corrected value. Setting it to our own src/ (rather than
    # deleting it) keeps `python3 -m <pkg>` working for child processes that
    # rely on it.
    kept.insert(0, own_src)
    os.environ["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(kept))

    # Repair the CURRENT interpreter too. Both spellings are removed because
    # sys.path may hold either the literal entry or its resolved form.
    stale = set()
    for entry in dropped:
        stale.add(entry)
        stale.add(str(Path(entry).resolve()))
    sys.path[:] = [p for p in sys.path if p not in stale]

    if os.environ.get("DANCING_BEAR_PATH_DEBUG"):
        print(
            f"[pathrepair] dropped foreign PYTHONPATH entries: {dropped}",
            file=sys.stderr,
        )
    return dropped


def force_own_src_first(repo_root: Path) -> str:
    """Put ``repo_root/src`` at the FRONT of ``sys.path`` and return it.

    Forcing the position, rather than only appending when absent, is the whole
    point. A membership test (``if src not in sys.path``) is not enough: when
    this checkout's ``src/`` is already on the path but sits behind another
    entry that also provides ``core``/``mail``/``resume``, the earlier entry
    wins and the guard silently does nothing.
    """
    src = str(repo_root / "src")
    while src in sys.path:
        sys.path.remove(src)
    sys.path.insert(0, src)
    return src
