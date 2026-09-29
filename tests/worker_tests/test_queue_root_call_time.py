"""Regression tests: an omitted ``root`` must resolve QUEUE_ROOT at call time.

When queue_ops bound QUEUE_ROOT as a default argument at import, a call that
omitted ``root`` reached the user's real queue even after a test reassigned
QUEUE_ROOT, and the live daemon then ran the test's jobs.

The structural test fails on that regression without touching the filesystem.
The behavioural test skips itself when a default is not None, so it can never
write to the real queue while demonstrating the failure.
"""

from __future__ import annotations

import contextlib
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from worker import queue_metrics, queue_ops
from worker._helpers import WORKER_STATE_DIR_ENV
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
        # Resolve the tempdir path so it matches get_worker_state_dir()'s output,
        # which calls .resolve() internally (e.g. /var/folders -> /private/var/folders
        # on macOS).
        tmp_resolved = Path(tmp.name).resolve()
        self.root = tmp_resolved / "queue"
        # _q(None) now calls get_worker_state_dir("queue") at call time, which
        # reads DANCING_BEAR_WORKER_STATE_DIR from the environment.  Set the env
        # var so the call resolves to self.root (= <tmp>/queue).
        original_env = os.environ.get(WORKER_STATE_DIR_ENV)
        os.environ[WORKER_STATE_DIR_ENV] = str(tmp_resolved)
        self.addCleanup(
            lambda: (
                os.environ.pop(WORKER_STATE_DIR_ENV, None)
                if original_env is None
                else os.environ.__setitem__(WORKER_STATE_DIR_ENV, original_env)
            )
        )
        # Keep QUEUE_ROOT consistent for callers that use root=q.QUEUE_ROOT,
        # and for the test assertions that compare against self.root.
        # patch.object deletes the attribute on exit when it was not assigned
        # before, leaving QUEUE_ROOT resolved from the env var again.
        root_patch = patch.object(queue_ops, "QUEUE_ROOT", self.root)  # == tmp_resolved / "queue"
        root_patch.start()
        self.addCleanup(root_patch.stop)

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


class TestQueueRootResolvesAtReadTime(unittest.TestCase):
    """QUEUE_ROOT follows DANCING_BEAR_WORKER_STATE_DIR on every read.

    Simulates importing queue_ops before the test bootstrap sets the variable:
    the first read happens under one value, the second under another. An
    import-time snapshot would keep returning the first, and every caller that
    passes ``root=q.QUEUE_ROOT`` would keep writing there.
    """

    def setUp(self) -> None:
        # Run each test with no explicit QUEUE_ROOT assignment in effect, and
        # put back whatever was there afterwards.
        saved = vars(queue_ops).pop("QUEUE_ROOT", None)
        if saved is not None:
            self.addCleanup(setattr, queue_ops, "QUEUE_ROOT", saved)
        self.addCleanup(vars(queue_ops).pop, "QUEUE_ROOT", None)
        dirs = [tempfile.TemporaryDirectory() for _ in range(2)]
        for d in dirs:
            self.addCleanup(d.cleanup)
        self.dir_x, self.dir_y = (Path(d.name).resolve() for d in dirs)

    def _env(self, base: Path) -> contextlib.AbstractContextManager[object]:
        return patch.dict(os.environ, {WORKER_STATE_DIR_ENV: str(base)})

    def test_queue_root_follows_env_changes_after_first_read(self) -> None:
        with self._env(self.dir_x):
            first = queue_ops.QUEUE_ROOT
        with self._env(self.dir_y):
            second = queue_ops.QUEUE_ROOT
            q_none = queue_ops._q(None)
        self.assertEqual(first, self.dir_x / "queue")
        self.assertEqual(second, self.dir_y / "queue", "QUEUE_ROOT kept an earlier env value")
        self.assertEqual(q_none, second, "_q(None) and QUEUE_ROOT disagree")

    def test_explicit_assignment_wins_until_deleted(self) -> None:
        pinned = self.dir_x / "pinned"
        with self._env(self.dir_y):
            queue_ops.QUEUE_ROOT = pinned
            self.assertEqual(queue_ops.QUEUE_ROOT, pinned)
            self.assertEqual(queue_ops._q(None), pinned)
            del queue_ops.QUEUE_ROOT
            self.assertEqual(queue_ops.QUEUE_ROOT, self.dir_y / "queue")
            self.assertEqual(queue_ops._q(None), self.dir_y / "queue")

    def test_patch_object_leaves_queue_root_dynamic_on_exit(self) -> None:
        with patch.object(queue_ops, "QUEUE_ROOT", self.dir_x / "patched"):
            self.assertEqual(queue_ops._q(None), self.dir_x / "patched")
        self.assertNotIn("QUEUE_ROOT", vars(queue_ops).keys(), "patch.object re-pinned QUEUE_ROOT")
        with self._env(self.dir_y):
            self.assertEqual(queue_ops.QUEUE_ROOT, self.dir_y / "queue")

    def test_isolation_mixin_restore_leaves_queue_root_dynamic(self) -> None:
        from tests.worker_tests.helpers import QueueRootIsolationMixin

        class _Probe(unittest.TestCase, QueueRootIsolationMixin):
            # The attributes the mixin's self-type (_QueueHost) requires.
            tmp: tempfile.TemporaryDirectory
            root: Path
            _orig_queue_root: Any
            _orig_queue_root_assigned: bool
            _orig_worker_state_dir_env: Any

        # Never run; only its setup and cleanups are driven by hand below.
        probe = _Probe(methodName="setUp")
        with self._env(self.dir_x):
            probe.setup_queue_root()
            self.assertIn("QUEUE_ROOT", vars(queue_ops).keys(), "setup_queue_root did not pin QUEUE_ROOT")
            probe.doCleanups()
            self.assertNotIn("QUEUE_ROOT", vars(queue_ops).keys(), "mixin restore pinned QUEUE_ROOT")
        with self._env(self.dir_y):
            self.assertEqual(queue_ops.QUEUE_ROOT, self.dir_y / "queue")

    def test_unknown_attribute_still_raises(self) -> None:
        with self.assertRaises(AttributeError):
            getattr(queue_ops, "NO_SUCH_ATTRIBUTE")


if __name__ == "__main__":
    unittest.main()
