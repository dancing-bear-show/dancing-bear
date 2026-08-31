"""Shared test helpers for worker_tests — queue root isolation utilities."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Protocol


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

    def addCleanup(self, function: Any, *args: Any, **kwargs: Any) -> None: ...
    def isolate_queue_root(self) -> None: ...
    def _restore_queue_root(self) -> None: ...


def _make_root() -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    return tmp, Path(tmp.name) / "queue"


class QueueRootIsolationMixin:
    """Save/restore QUEUE_ROOT around each test.

    Callers typically want a scratch queue directory plus isolation of the
    module-level ``queue_ops.QUEUE_ROOT``. Use ``self.setup_queue_root()`` in
    ``setUp`` to get both in one call; use ``isolate_queue_root()`` alone when
    the caller manages its own tempdir (see ``test_worker_purge_selective``
    and ``test_worker_retry_purge_status`` where ``self.root`` intentionally
    points at the tempdir root, not a ``queue`` subdirectory).
    """

    def isolate_queue_root(self: "_QueueHost"):
        from worker import queue_ops as q
        self._orig_queue_root = q.QUEUE_ROOT
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
        return self.root

    def _restore_queue_root(self):
        from worker import queue_ops as q
        q.QUEUE_ROOT = self._orig_queue_root
