"""Regression tests: an omitted ``root`` must resolve QUEUE_ROOT at call time.

When queue_ops bound QUEUE_ROOT as a default argument at import, a call that
omitted ``root`` reached the user's real queue even after a test reassigned
QUEUE_ROOT, and the live daemon then ran the test's jobs.

The structural test fails on that regression without touching the filesystem.
The behavioural test skips itself when a default is not None, so it can never
write to the real queue while demonstrating the failure.
"""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from worker import queue_metrics, queue_ops
from worker.queue_ops import Job


def _root_defaults() -> dict[str, object]:
    """Map each queue function that takes ``root`` to that parameter's default."""
    found: dict[str, object] = {}
    for module in (queue_ops, queue_metrics):
        for name, fn in inspect.getmembers(module, inspect.isfunction):
            if fn.__module__ != module.__name__:
                continue
            param = inspect.signature(fn).parameters.get("root")
            # A required root (e.g. _q itself) has no default to bind.
            if param is not None and param.default is not inspect.Parameter.empty:
                found[f"{module.__name__}.{name}"] = param.default
    return found


class TestRootDefaultsResolveAtCallTime(unittest.TestCase):
    def test_every_root_default_is_none(self):
        defaults = _root_defaults()
        self.assertIn("worker.queue_ops.start_processing", defaults)
        self.assertIn("worker.queue_metrics.status", defaults)
        bound = {name: d for name, d in defaults.items() if d is not None}
        self.assertEqual(bound, {}, "root defaults bound at import reach the real queue")


class TestOmittedRootUsesReassignedQueueRoot(unittest.TestCase):
    def setUp(self):
        if any(d is not None for d in _root_defaults().values()):
            self.skipTest("root defaults are import-bound; running would touch the real queue")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "queue"
        original = queue_ops.QUEUE_ROOT
        self.addCleanup(setattr, queue_ops, "QUEUE_ROOT", original)
        queue_ops.QUEUE_ROOT = self.root

    def test_enqueue_list_and_claim_use_reassigned_root(self):
        path = queue_ops.enqueue(Job(id="calltime1", type="noop", payload={}))
        self.assertEqual(path, self.root / "pending" / "calltime1.json")
        pending = queue_ops.list_pending()
        self.assertEqual([p for p, _ in pending], [path])
        claimed = queue_ops.start_processing(path)
        self.assertEqual(claimed, self.root / "processing" / "calltime1.json")

    def test_metrics_use_reassigned_root(self):
        queue_ops.enqueue(Job(id="calltime2", type="noop", payload={}))
        self.assertEqual(queue_metrics.counts()["pending"], 1)
        self.assertEqual(queue_metrics.status()["root"], str(self.root))


if __name__ == "__main__":
    unittest.main()
