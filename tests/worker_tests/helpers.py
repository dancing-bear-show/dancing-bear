"""Shared test helpers for worker_tests — queue root isolation utilities."""

from __future__ import annotations

import tempfile
from pathlib import Path


def _make_root() -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    return tmp, Path(tmp.name) / "queue"


class QueueRootIsolationMixin:
    """Save/restore QUEUE_ROOT around each test."""

    def isolate_queue_root(self):
        from worker import queue_ops as q
        self._orig_queue_root = q.QUEUE_ROOT
        self.addCleanup(self._restore_queue_root)

    def _restore_queue_root(self):
        from worker import queue_ops as q
        q.QUEUE_ROOT = self._orig_queue_root
