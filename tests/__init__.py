"""Test package initialization.

Ensures the repository-local ``src/`` is imported ahead of any editable
install. The project's ``.venv`` lives in the main checkout and its editable
``.pth`` hardcodes that checkout's ``src/``; without this, running
``python3 -m unittest`` from a git worktree would silently import and test the
MAIN checkout's code instead of the worktree's. Prepending the local ``src``
(the same effect as the Makefile's ``PYTHONPATH=src``) makes tests always
exercise the tree they were launched from.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir():
    _src_str = str(_SRC)
    # Drop any *other* checkout's src that an editable .pth may have added
    # (a sibling path ending in "/src" that isn't ours), plus the local one if
    # already present, then prepend the local src so this tree wins regardless
    # of sys.path ordering.
    sys.path[:] = [
        p for p in sys.path
        if p != _src_str and not (p.endswith("/src") and "/dancing-bear/" in p)
    ]
    sys.path.insert(0, _src_str)
