"""Shared bootstrap: ensure DANCING_BEAR_WORKER_STATE_DIR points at a private dir.

This module is loaded by path (importlib.util.spec_from_file_location) from
tests/__init__.py and from the __init__.py of worker_tests, workflow_tests and
infra, so it runs whenever unittest imports one of those packages:

  - ``python -m unittest`` / ``discover`` with no -s (tests/__init__.py)
  - ``discover -s tests -t .`` and ``discover -s tests/<pkg> -t .``
    (tests/__init__.py, plus <pkg>/__init__.py for the latter)
  - ``python -m unittest tests.<pkg>.<module>`` (tests/__init__.py)
  - ``discover -s tests`` with no -t: tests/__init__.py is NOT imported, but
    each subdirectory is imported as a top-level package, so
    worker_tests/__init__.py etc. are

It does NOT run under ``discover -s tests/<pkg>`` without ``-t .``: the start
directory becomes the top level and unittest never imports its __init__.py.
That form is unsupported; see CLAUDE.md "Testing".

Import order does not matter: worker.queue_ops.QUEUE_ROOT resolves the env var
on every read, so the bootstrap only has to run before the first test does.

The call is idempotent: the first package to call ``ensure_private()`` wins.
Later calls see that the env var is already set to a private value and return
immediately without creating a second temp dir or overwriting the first.

Stdlib-only.  No repo imports.  Safe to load before sys.path is repaired.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import tempfile
from pathlib import Path

_WORKER_STATE_ENV = "DANCING_BEAR_WORKER_STATE_DIR"
_REAL_DEFAULT = (Path.home() / "Library" / "Application Support" / "dancing-bear").resolve()

# Marks the directory ensure_private() itself created, so callers can tell a
# bootstrap-created dir apart from a user-supplied private override without
# guessing from the path text (a user override can legally contain the
# "dancing-bear-test-state-" substring, e.g. ".../dancing-bear-test-state-
# project/state", and a substring match would misclassify it).
#
# An env var survives this module being loaded more than once by path under
# different sys.modules keys -- every package __init__.py and the test file
# itself do this -- which a plain module-level variable would not: a fresh
# module instance starts with fresh globals. Set only after the privacy check
# passes, so a failed/rejected mkdtemp never marks anything. Child processes
# inherit this env var, which is harmless -- it only ever names a temp dir
# this process already created and will clean up at exit.
_CREATED_MARKER_ENV = "DANCING_BEAR_TEST_STATE_CREATED"


def _is_private(val: str) -> bool:
    """Return True if *val* is set and is not the real default location.

    Normalizes *val* with ``Path.expanduser().resolve()`` before comparing, so
    a literal tilde or a symlink that resolves to the real default is correctly
    identified as not private.

    Ancestry check: ``_REAL_DEFAULT`` is ``~/Library/.../dancing-bear``.
    ``get_worker_state_dir`` appends only one segment (e.g. "queue"), so an
    ancestor of the real default — like ``$HOME`` — resolves to ``~/queue``,
    not into the real queue tree.  Only paths that *are* the real default or
    lie inside it need rejecting.
    """
    if not val:
        return False
    try:
        resolved = Path(val).expanduser().resolve()
    except Exception:  # nosec B110 - path resolution failure means we cannot confirm it is private
        return False
    return resolved != _REAL_DEFAULT and not resolved.is_relative_to(_REAL_DEFAULT)


def ensure_private() -> None:
    """Set DANCING_BEAR_WORKER_STATE_DIR to a private temp dir if not already set.

    Idempotent: does nothing when the env var already points at a private
    location (either a bootstrap-created temp dir from an earlier call, or a
    user-supplied override that is not the real default).
    """
    current = os.environ.get(_WORKER_STATE_ENV, "").strip()
    if _is_private(current):
        return

    # Create a fresh temp dir for the entire test process.  mkdtemp honours
    # TMPDIR, so the result is checked like any other value: a TMPDIR inside
    # the real state dir would otherwise make the "private" queue the real one.
    tmp_dir = tempfile.mkdtemp(prefix="dancing-bear-test-state-")
    if not _is_private(tmp_dir):
        # Only the empty directory mkdtemp just made; nothing else is touched.
        with contextlib.suppress(OSError):
            os.rmdir(tmp_dir)
        raise RuntimeError(
            f"tempfile.mkdtemp() returned {tmp_dir!r}, which is inside the real "
            f"worker state dir {_REAL_DEFAULT}. Point TMPDIR somewhere else; "
            f"{_WORKER_STATE_ENV} was not set to it."
        )
    os.environ[_WORKER_STATE_ENV] = tmp_dir
    os.environ[_CREATED_MARKER_ENV] = tmp_dir

    def _cleanup(_d: str = tmp_dir) -> None:
        import shutil
        try:
            shutil.rmtree(_d, ignore_errors=True)
        except Exception:  # nosec B110 - best-effort cleanup at exit
            pass

    atexit.register(_cleanup)


def created_by_bootstrap() -> bool:
    """Return True if ensure_private() created the current state dir.

    Tracks ownership via _CREATED_MARKER_ENV rather than inferring it from the
    path text: a user-supplied private override is free to contain the
    "dancing-bear-test-state-" substring (e.g. a dir named
    "dancing-bear-test-state-project"), and a substring match would wrongly
    call that bootstrap-created.
    """
    marker = os.environ.get(_CREATED_MARKER_ENV, "")
    current = os.environ.get(_WORKER_STATE_ENV, "")
    return bool(marker) and marker == current
