"""Worker test package.

Bootstraps the process-wide private worker state dir (see
tests/_private_worker_state.py) when unittest imports this package: under
``discover -s tests`` without ``-t .``, and under ``-s tests/worker_tests -t .``.
``discover -s tests/worker_tests`` without ``-t .`` never imports this file, so that
form is unsupported (CLAUDE.md "Testing").
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_BOOTSTRAP = Path(__file__).parent.parent / "_private_worker_state.py"
_BOOTSTRAP_KEY = "_dancing_bear_private_worker_state"
if _BOOTSTRAP_KEY not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_BOOTSTRAP_KEY, _BOOTSTRAP)
    if _spec is not None and _spec.loader is not None:
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[_BOOTSTRAP_KEY] = _mod
        _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
sys.modules[_BOOTSTRAP_KEY].ensure_private()  # type: ignore[attr-defined]
