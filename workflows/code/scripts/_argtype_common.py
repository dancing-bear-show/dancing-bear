"""Shared state and low-level walk helpers for detect_arg_type_mismatch.

This module is an implementation detail of detect_arg_type_mismatch.py.  It
must not be imported directly from outside that script family.

Shared-state design note
------------------------
``_STATS`` and ``_AMBIGUOUS`` are module-level mutable objects intentionally.
Both the signature-collection pass and the call-site scan pass mutate them,
and ``main`` reads the final values after both passes complete.  They must be
ONE shared mutable dict/set -- a per-module copy would split the counters and
cause main to report zeros for whichever half it did not see.

``collect_signatures`` calls ``_reset_stats()`` at the start of each run so
repeated in-process runs (e.g., in tests) do not accumulate across calls.
"""

from __future__ import annotations

import ast
import os

SKIP_WALK_DIRS = {
    ".git", ".venv", ".claude", "__pycache__", "node_modules",
    ".cache", "out", "_out", "backups", "personal_assistants.egg-info",
}

#: ``(module_stem, funcname) -> (src_path, lineno, [(param_name, annotation)])``
Sigs = dict[tuple[str, str], tuple[str, int, list[tuple[str, str | None]]]]

#: Keys claimed by more than one definition. The table is keyed by
#: (module_stem, funcname), which cannot distinguish sibling classes in one
#: file -- `consumers.consume` is defined 37 times in a single module. Whichever
#: definition wins is arbitrary, so an ambiguous key is DROPPED rather than
#: guessed: a wrong signature yields confidently wrong findings, whereas a
#: missing one yields silence that `stats` reports.
_AMBIGUOUS: set[tuple[str, str]] = set()

#: Files walked and files that failed to parse, per root. A detector that
#: reports zero because it scanned nothing is indistinguishable from one that
#: reports zero because the code is clean -- the exact false-clean this repo
#: has been bitten by before (see CLAUDE.md on qlty scanning zero files in a
#: worktree, and src/qlty/README.md F1). Counted so the caller can tell.
_STATS: dict[str, int] = {
    "src_files_scanned": 0,
    "src_files_unparsed": 0,
    "test_files_scanned": 0,
    "test_files_unparsed": 0,
    "signatures_collected": 0,
    "signatures_ambiguous_dropped": 0,
}


def _reset_stats() -> None:
    """Zero the scan counters so repeated in-process runs do not accumulate."""
    for key in _STATS:
        _STATS[key] = 0
    _AMBIGUOUS.clear()


def _iter_py(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_WALK_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def _parse_py(path: str) -> ast.Module | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return ast.parse(fh.read(), filename=path)
    except (OSError, SyntaxError, ValueError):
        return None  # nosec B112 - skip unreadable/bad-encoding files silently
