"""Tests for DaemonRunner's non-blocking DAEMON-mode tick.

Covers the daemon's liveness guarantees: a long-running job must not stall
later ticks from claiming and
completing other work, capacity accounting must account for started-but-not-
yet-processing threads, an already-claimed job must not be dispatched twice,
unbounded max_inflight must still cap live threads at max_per_tick, run_once
must keep blocking until its batch finishes, and finished threads must be
pruned so capacity recovers.
"""

from __future__ import annotations

import threading
import time
import unittest
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.worker_tests.helpers import QueueRootIsolationMixin
from worker.queue_ops import (
    Job,
    enqueue,
    finish as _real_finish,
    list_pending as _real_list_pending,
    reap_stale_processing_jobs as _real_reap,
    retry as _real_retry,
    start_processing as _real_start,
)


def _make_runner(root: Path, **config_kwargs: Any):
    from worker.job_runtime import DaemonRunner, JobProcessor, WorkerConfig
    from worker import queue_ops as q

    q.QUEUE_ROOT = root
    cfg = WorkerConfig(**config_kwargs)
    proc = JobProcessor(cfg, "daemon")
    return DaemonRunner(cfg, proc)


def _patch_queue_root(job_root: Path) -> ExitStack:
    """Patch every worker.job_runtime.q.* call site to forward root=job_root.

    ``worker.queue_ops`` functions bind their ``root`` default at import
    time, so reassigning ``q.QUEUE_ROOT`` after import does not affect a
    no-args call — the same reason ``TestJobProcessor`` in
    test_commands_gaps.py wraps each call site individually instead of
    relying on the module-level reassignment alone.
    """
    stack = ExitStack()
    # process_one logs every outcome to the real worker perf log
    # (<state dir>/logs/perf-worker-*.jsonl); keep that off disk.
    stack.enter_context(patch("worker.job_runtime.log_perf_jsonl"))
    stack.enter_context(
        patch(
            "worker.job_runtime.q.reap_stale_processing_jobs",
            side_effect=lambda job_timeout, root=None: _real_reap(job_timeout, root=job_root),
        )
    )
    stack.enter_context(
        patch(
            "worker.job_runtime.q.list_pending",
            side_effect=lambda: _real_list_pending(root=job_root),
        )
    )
    stack.enter_context(
        patch(
            "worker.job_runtime.q.start_processing",
            side_effect=lambda job_path, root=None: _real_start(job_path, job_root),
        )
    )
    stack.enter_context(
        patch(
            "worker.job_runtime.q.finish",
            side_effect=lambda job_path, success, **kw: _real_finish(
                job_path, success, root=job_root, **kw
            ),
        )
    )
    stack.enter_context(
        patch(
            "worker.job_runtime.q.retry",
            side_effect=lambda job_path, **kw: _real_retry(job_path, root=job_root, **kw),
        )
    )
    return stack


class _BlockingHandler:
    """Fake handler that blocks on an Event until released, then finishes.

    ``started`` is set as soon as the handler is invoked (before blocking),
    so a test can deterministically observe "job has begun" without any
    sleep. ``call_count`` records how many times the handler actually ran.
    """

    def __init__(self, gate: threading.Event) -> None:
        self._gate = gate
        self.started = threading.Event()
        self.call_count = 0
        self._lock = threading.Lock()

    def __call__(self, job_data: dict[str, object]) -> tuple[bool, object]:
        with self._lock:
            self.call_count += 1
        self.started.set()
        self._gate.wait(timeout=5)
        return True, "ok"


def _cheap_handler(job_data: dict[str, object]) -> tuple[bool, object]:
    return True, "ok"


class _CountingHandler:
    """Cheap handler that records how many times it ran."""

    def __init__(self) -> None:
        self.call_count = 0
        self._lock = threading.Lock()

    def __call__(self, job_data: dict[str, object]) -> tuple[bool, object]:
        with self._lock:
            self.call_count += 1
        return True, "ok"


class _HeldStart:
    """start_processing stand-in that blocks before the pending/ -> processing/
    rename until gate is set. ``waiting`` counts threads parked at the gate."""

    def __init__(self, job_root: Path, gate: threading.Event) -> None:
        self._job_root = job_root
        self._gate = gate
        self._lock = threading.Lock()
        self.waiting = 0

    def __call__(self, job_path: Path, root: Path | None = None) -> Path | None:
        with self._lock:
            self.waiting += 1
        self._gate.wait(timeout=5)
        return _real_start(job_path, self._job_root)


@contextmanager
def _hold_start_processing(job_root: Path, gate: threading.Event) -> Iterator[_HeldStart]:
    held = _HeldStart(job_root, gate)
    try:
        with patch("worker.job_runtime.q.start_processing", side_effect=held):
            yield held
    finally:
        gate.set()  # never leave a worker thread parked past the test


class TestDaemonNonblockingTick(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.setup_queue_root()
        # A base layer of the queue-root and handler patches stays active
        # until after _drain_threads has joined every worker thread. A test
        # that fails inside its own `with` block would otherwise leave a
        # thread running against the unpatched module: the real queue root,
        # the real perf log and an unknown-handler error for its job.
        base = _patch_queue_root(self.root)
        base.enter_context(
            patch.dict("worker.job_runtime.HANDLERS", {"slow": _cheap_handler, "cheap": _cheap_handler})
        )
        self.addCleanup(base.close)
        self._threads_before = set(threading.enumerate())
        self.addCleanup(self._drain_threads)  # LIFO: runs before base.close

    def _drain_threads(self) -> None:
        # Join every thread this test started, not just the registry's
        # current entries: a regression that registers two threads under one
        # stem overwrites the first, which would then outlive the patches.
        for thread in threading.enumerate():
            if thread not in self._threads_before:
                thread.join(timeout=10)

    def test_long_running_job_does_not_stall_later_tick(self):
        """required_tests[0]: a long-running job started in tick 1 does not
        stop tick 2 from starting and completing a cheap job."""
        gate = threading.Event()
        slow = _BlockingHandler(gate)
        enqueue(Job(id="slow1", type="slow", payload={}), root=self.root)
        runner = _make_runner(self.root, max_per_tick=5, max_inflight=0)

        with _patch_queue_root(self.root), \
             patch.dict("worker.job_runtime.HANDLERS", {"slow": slow, "cheap": _cheap_handler}, clear=False):
            started1 = runner.tick()
            self.assertEqual(started1, 1)
            self.assertTrue(slow.started.wait(timeout=5), "slow job never started")

            # Tick 1's thread is still blocked on the gate. A second, cheap
            # job enqueued now must be claimed and completed by tick 2
            # without waiting for the slow job.
            enqueue(Job(id="cheap1", type="cheap", payload={}), root=self.root)
            started2 = runner.tick()

            self.assertEqual(started2, 1)
            # The cheap job's processing/ file should show up (and move to
            # done/) promptly since its handler never blocks.
            done_path = self.root / "done" / "cheap1.json"
            self.assertTrue(
                _wait_for(lambda: done_path.exists(), timeout=5),
                "cheap job never finished while slow job was still running",
            )
            # Slow job must still be unfinished (proves tick 2 didn't wait on it).
            self.assertFalse((self.root / "done" / "slow1.json").exists())

            gate.set()  # release the slow job so the thread can exit cleanly
            self.assertTrue(
                _wait_for(lambda: (self.root / "done" / "slow1.json").exists(), timeout=5)
            )

    def test_max_inflight_respects_unfinished_started_threads(self):
        """required_tests[1]: max_inflight is respected when started threads
        have not yet moved their job into processing/.

        start_processing is held before its rename, so processing/ stays
        empty and only the live-thread registry knows two jobs are in
        flight. A capacity check that counted processing/ alone would start
        the third job here."""
        rename_gate = threading.Event()
        for i in range(3):
            enqueue(Job(id=f"held{i}", type="cheap", payload={}), root=self.root)
        runner = _make_runner(self.root, max_per_tick=5, max_inflight=2)
        handler = _CountingHandler()

        with _patch_queue_root(self.root), \
             _hold_start_processing(self.root, rename_gate) as held, \
             patch.dict("worker.job_runtime.HANDLERS", {"cheap": handler}, clear=False):
            started1 = runner.tick()
            self.assertEqual(started1, 2, "max_inflight=2 must cap the first tick at 2")
            self.assertTrue(_wait_for(lambda: held.waiting == 2, timeout=5))
            self.assertEqual(list((self.root / "processing").glob("*.json")), [])

            started2 = runner.tick()

            self.assertEqual(started2, 0, "live registry threads must count against max_inflight")
            rename_gate.set()
            self.assertTrue(
                _wait_for(lambda: len(list((self.root / "done").glob("*.json"))) >= 2, timeout=5)
            )
            self.assertEqual(handler.call_count, 2)

    def test_live_thread_job_not_dispatched_twice(self):
        """required_tests[2]: a job owned by a live thread is not dispatched
        again by a later tick.

        start_processing is held before its rename, so the job is still in
        pending/ when the second tick lists it; only the registry filter
        stops a second thread being started for it."""
        rename_gate = threading.Event()
        enqueue(Job(id="held-once", type="cheap", payload={}), root=self.root)
        runner = _make_runner(self.root, max_per_tick=5, max_inflight=0)
        handler = _CountingHandler()

        with _patch_queue_root(self.root), \
             _hold_start_processing(self.root, rename_gate) as held, \
             patch.dict("worker.job_runtime.HANDLERS", {"cheap": handler}, clear=False):
            self.assertEqual(runner.tick(), 1)
            self.assertTrue(_wait_for(lambda: held.waiting == 1, timeout=5))
            self.assertTrue((self.root / "pending" / "held-once.json").exists())

            started2 = runner.tick()

            self.assertEqual(started2, 0)
            self.assertEqual(list(runner._live_threads), ["held-once"])
            rename_gate.set()
            self.assertTrue(_wait_for(lambda: (self.root / "done" / "held-once.json").exists(), timeout=5))
            self.assertEqual(handler.call_count, 1)

    def test_unbounded_max_inflight_caps_live_threads_at_max_per_tick(self):
        """required_tests[3]: with max_inflight <= 0, live threads never
        exceed max_per_tick."""
        gate = threading.Event()
        slow = _BlockingHandler(gate)
        for i in range(5):
            enqueue(Job(id=f"u{i}", type="slow", payload={}), root=self.root)
        runner = _make_runner(self.root, max_per_tick=2, max_inflight=0)

        with _patch_queue_root(self.root), \
             patch.dict("worker.job_runtime.HANDLERS", {"slow": slow}, clear=False):
            started1 = runner.tick()
            self.assertEqual(started1, 2, "max_per_tick=2 must cap an unbounded tick at 2")

            self.assertTrue(_wait_for(lambda: slow.call_count >= 2, timeout=5))

            # 2 threads are live and max_per_tick is 2, so a further tick
            # must start 0 more even though 3 jobs remain pending.
            started2 = runner.tick()
            self.assertEqual(started2, 0)
            self.assertEqual(slow.call_count, 2)

            gate.set()
            # Wait for the two live threads to finish before the queue-root
            # patches (and the tempdir) are torn down.
            self.assertTrue(
                _wait_for(lambda: len(list((self.root / "done").glob("*.json"))) >= 2, timeout=5)
            )

    def test_run_once_still_blocks_until_batch_finishes(self):
        """required_tests[4]: run_once still blocks until every job in its
        batch has finished."""
        enqueue(Job(id="ro1", type="cheap", payload={}), root=self.root)
        enqueue(Job(id="ro2", type="cheap", payload={}), root=self.root)
        runner = _make_runner(self.root, max_per_tick=5, max_inflight=0)

        with _patch_queue_root(self.root), \
             patch.dict("worker.job_runtime.HANDLERS", {"cheap": _cheap_handler}, clear=False):
            result = runner.run_once()

        self.assertEqual(result, 0)
        # run_once returned only after both jobs finished — no polling/wait
        # needed, since a non-blocking implementation would leave these
        # still in processing/ at the moment run_once returns.
        self.assertTrue((self.root / "done" / "ro1.json").exists())
        self.assertTrue((self.root / "done" / "ro2.json").exists())

    def test_finished_threads_are_pruned_and_capacity_recovers(self):
        """required_tests[5]: finished threads are pruned, so capacity is
        recovered."""
        enqueue(Job(id="p1", type="cheap", payload={}), root=self.root)
        runner = _make_runner(self.root, max_per_tick=1, max_inflight=1)

        with _patch_queue_root(self.root), \
             patch.dict("worker.job_runtime.HANDLERS", {"cheap": _cheap_handler}, clear=False):
            started1 = runner.tick()
            self.assertEqual(started1, 1)

            # cheap handler returns immediately; wait for it to land in done/
            # (and therefore for its thread to have exited) before the next
            # tick, which is when pruning happens.
            self.assertTrue(_wait_for(lambda: (self.root / "done" / "p1.json").exists(), timeout=5))

            enqueue(Job(id="p2", type="cheap", payload={}), root=self.root)
            started2 = runner.tick()
            # Wait for p2's thread to finish before the queue-root patches
            # (and the tempdir) are torn down, so its file rename never
            # races test cleanup.
            self.assertTrue(_wait_for(lambda: (self.root / "done" / "p2.json").exists(), timeout=5))

        self.assertEqual(
            started2, 1, "capacity must recover once the first thread's job finished"
        )


def _wait_for(predicate: Callable[[], bool], timeout: float) -> bool:
    """Poll predicate() until it is True or timeout elapses; no fixed sleeps."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


if __name__ == "__main__":
    unittest.main()
