"""Infrastructure and integration tests.

Bootstraps the process-wide private worker state dir so that no test in this
package can accidentally write to the user's real queue when worker modules are
imported (e.g. test_qwen_wrapper.py lazily imports worker.qwen/handlers),
regardless of how unittest discover was invoked (with or without ``-t .``).
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
