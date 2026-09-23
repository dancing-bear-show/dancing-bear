"""Shared test helpers for worker_tests — queue root isolation utilities."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Protocol

from worker._helpers import WORKER_STATE_DIR_ENV


class _QueueHost(Protocol):
    """Combined self-type for QueueRootIsolationMixin methods.

    setup_queue_root needs both addCleanup (from unittest.TestCase) and
    isolate_queue_root (from the mixin itself), so neither annotation alone
    is sufficient. This Protocol declares the full required surface.
    """
    # Dynamic instance attributes set during setup
    tmp: tempfile.TemporaryDirectory
    root: Path
    _orig_queue_root: Any
    _orig_worker_state_dir_env: Any

    def addCleanup(self, function: Any, *args: Any, **kwargs: Any) -> None: ...
    def isolate_queue_root(self) -> None: ...
    def _restore_queue_root(self) -> None: ...


def _make_root() -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    return tmp, Path(tmp.name) / "queue"


class QueueRootIsolationMixin:
    """Save/restore QUEUE_ROOT and DANCING_BEAR_WORKER_STATE_DIR around each test.

    Callers typically want a scratch queue directory plus isolation of the
    module-level ``queue_ops.QUEUE_ROOT``. Use ``self.setup_queue_root()`` in
    ``setUp`` to get both in one call; use ``isolate_queue_root()`` alone when
    the caller manages its own tempdir (see ``test_worker_purge_selective``
    and ``test_worker_retry_purge_status`` where ``self.root`` intentionally
    points at the tempdir root, not a ``queue`` subdirectory).

    ``DANCING_BEAR_WORKER_STATE_DIR`` is also redirected to the temp tree so
    that any call that resolves the queue root via ``get_worker_state_dir``
    (rather than the already-imported ``QUEUE_ROOT`` constant) also lands in
    the temp directory.  This closes the window where a function that does a
    fresh ``get_worker_state_dir`` call or a new-process invocation could still
    reach the user's real queue.
    """

    def isolate_queue_root(self: "_QueueHost"):
        from worker import queue_ops as q
        self._orig_queue_root = q.QUEUE_ROOT
        self._orig_worker_state_dir_env = os.environ.get(WORKER_STATE_DIR_ENV)
        self.addCleanup(self._restore_queue_root)

    def setup_queue_root(self: "_QueueHost") -> Path:
        """Create a scratch ``<tmp>/queue`` root and isolate ``QUEUE_ROOT``.

        Sets ``self.tmp`` (the ``TemporaryDirectory``) and ``self.root`` (the
        ``queue`` subpath). Returns ``self.root`` for callers that prefer
        expression style.
        """
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()
        # Point DANCING_BEAR_WORKER_STATE_DIR at the temp tree root so that
        # any call resolving the state dir via the env var (including new
        # process spawns) lands in the temp tree instead of the real queue.
        os.environ[WORKER_STATE_DIR_ENV] = str(self.tmp.name)
        # Also update the already-imported module-level QUEUE_ROOT.
        from worker import queue_ops as q
        q.QUEUE_ROOT = self.root
        return self.root

    def _restore_queue_root(self):
        from worker import queue_ops as q
        q.QUEUE_ROOT = self._orig_queue_root
        if self._orig_worker_state_dir_env is None:
            os.environ.pop(WORKER_STATE_DIR_ENV, None)
        else:
            os.environ[WORKER_STATE_DIR_ENV] = self._orig_worker_state_dir_env
