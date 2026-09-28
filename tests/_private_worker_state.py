"""Shared bootstrap: ensure DANCING_BEAR_WORKER_STATE_DIR points at a private dir.

This module is loaded by path (importlib.util.spec_from_file_location) from the
__init__.py of every test package that can import ``worker`` directly or
transitively, so the bootstrap runs regardless of which unittest discovery form
is used:

  - ``python -m unittest``  (bare; tests is a package)
  - ``python -m unittest discover``  (no -s/-t; cwd is top-level, tests is a package)
  - ``python -m unittest discover -s tests -t .``  (tests is a package)
  - ``python -m unittest discover -s tests``  (NO -t; each subdirectory is a
    top-level package so tests/__init__.py is NOT imported, but
    tests/worker_tests/__init__.py, tests/workflow_tests/__init__.py, etc. ARE)
  - ``python -m unittest discover -s tests/worker_tests``  (only worker_tests
    is discovered; again tests/__init__.py is not imported)

The call is idempotent: the first package to call ``ensure_private()`` wins.
Later calls see that the env var is already set to a private value and return
immediately without creating a second temp dir or overwriting the first.

Stdlib-only.  No repo imports.  Safe to load before sys.path is repaired.
"""

from __future__ import annotations

import atexit
import os
import tempfile
from pathlib import Path

_WORKER_STATE_ENV = "DANCING_BEAR_WORKER_STATE_DIR"
_REAL_DEFAULT = Path.home() / "Library" / "Application Support" / "dancing-bear"


def _is_private(val: str) -> bool:
    """Return True if *val* is set and is not the real default location."""
    return bool(
        val
        and val != str(_REAL_DEFAULT)
        and not val.startswith(str(_REAL_DEFAULT) + "/")
    )


def ensure_private() -> None:
    """Set DANCING_BEAR_WORKER_STATE_DIR to a private temp dir if not already set.

    Idempotent: does nothing when the env var already points at a private
    location (either a bootstrap-created temp dir from an earlier call, or a
    user-supplied override that is not the real default).
    """
    current = os.environ.get(_WORKER_STATE_ENV, "").strip()
    if _is_private(current):
        return

    # Create a fresh temp dir for the entire test process.
    tmp_dir = tempfile.mkdtemp(prefix="dancing-bear-test-state-")
    os.environ[_WORKER_STATE_ENV] = tmp_dir

    def _cleanup(_d: str = tmp_dir) -> None:
        import shutil
        try:
            shutil.rmtree(_d, ignore_errors=True)
        except Exception:  # nosec B110 - best-effort cleanup at exit
            pass

    atexit.register(_cleanup)
