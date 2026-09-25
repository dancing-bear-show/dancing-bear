"""Tests for graceful DaemonRunner shutdown (issue #420).

Covers: SIGTERM/SIGINT set a stop Event and the daemon loop exits on it,
handlers are installed only in the main thread and restored afterwards, the
drain waits for live job threads up to ``shutdown_grace``, a job still
running at the deadline goes back to pending/ without consuming an attempt,
another worker's processing/ job is never touched, a job that already left
processing/ is not recreated, and ``--shutdown-grace`` reaches WorkerConfig.
"""

from __future__ import annotations

import json
import signal
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.worker_tests.helpers import QueueRootIsolationMixin
from tests.worker_tests.test_daemon_nonblocking import (
    _make_runner,
    _patch_queue_root,
    _wait_for,
)
from worker.queue_ops import (
    Job,
    enqueue,
    requeue_processing,
    start_processing as _real_start,
)

_REASON = "requeued-on-shutdown"


class _GatedHandler:
    """Handler that signals ``started`` and then blocks until ``gate`` opens.

    ``on_start`` runs after ``started`` is set, before blocking, so a test
    can trigger a stop from inside a running job without any sleep.
    """

    def __init__(self, gate: threading.Event, on_start: Any = None) -> None:
        self._gate = gate
        self._on_start = on_start
        self.started = threading.Event()

    def __call__(self, job_data: dict[str, object]) -> tuple[bool, object]:
        self.started.set()
        if self._on_start is not None:
            self._on_start()
        self._gate.wait(timeout=10)
        return True, "ok"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class _ShutdownTestBase(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self) -> None:
        self.setup_queue_root()
        self.gate = threading.Event()
        self.handler = _GatedHandler(self.gate)
        base = _patch_queue_root(self.root)
        base.enter_context(patch.dict("worker.job_runtime.HANDLERS", {"slow": self.handler}))
        self.addCleanup(base.close)
        self._threads_before = set(threading.enumerate())
        # LIFO: open the gate, then join, then drop the patches.
        self.addCleanup(self._join_new_threads)
        self.addCleanup(self.gate.set)

    def _join_new_threads(self) -> None:
        for thread in threading.enumerate():
            if thread not in self._threads_before:
                thread.join(timeout=10)

    def _start_gated_job(self, runner: Any, job_id: str = "slow1", attempts: int = 1) -> Path:
        """Enqueue and start a gated job; return its processing/ path."""
        enqueue(Job(id=job_id, type="slow", payload={}, attempts=attempts), root=self.root)
        self.assertEqual(runner.tick(), 1)
        self.assertTrue(self.handler.started.wait(timeout=5), "gated job never started")
        proc = self.root / "processing" / f"{job_id}.json"
        self.assertTrue(proc.exists(), "gated job not in processing/")
        return proc


class TestDrainLiveThreads(_ShutdownTestBase):
    def test_job_finishing_within_grace_lands_in_done(self) -> None:
        runner = _make_runner(self.root, max_per_tick=1)
        self._start_gated_job(runner)
        runner.stop_event.set()

        opener = threading.Timer(0.05, self.gate.set)
        opener.start()
        self.addCleanup(opener.cancel)
        requeued = runner.drain_live_threads(grace=5.0)

        self.assertEqual(requeued, [])
        self.assertTrue((self.root / "done" / "slow1.json").exists())
        self.assertFalse((self.root / "pending" / "slow1.json").exists())
        self.assertFalse((self.root / "processing" / "slow1.json").exists())

    def test_job_never_finishing_is_requeued_without_consuming_attempt(self) -> None:
        runner = _make_runner(self.root, max_per_tick=1)
        self._start_gated_job(runner, attempts=1)

        started = time.monotonic()
        with self.assertLogs("worker.job_runtime", "WARNING") as logs:
            requeued = runner.drain_live_threads(grace=0.2)
        elapsed = time.monotonic() - started

        self.assertEqual(requeued, ["slow1"])
        self.assertIn("requeued running job slow1 on shutdown", logs.output[0])
        self.assertTrue(runner._live_threads["slow1"].is_alive())
        self.assertGreaterEqual(elapsed, 0.15)
        self.assertLess(elapsed, 2.0, "drain overran its grace ceiling")
        pending = self.root / "pending" / "slow1.json"
        self.assertTrue(pending.exists(), "running job was not requeued")
        data = _read(pending)
        self.assertEqual(data["attempts"], 1)
        self.assertEqual(data["last_error"], _REASON)
        self.assertEqual(data["status"], "pending")
        self.assertFalse((self.root / "processing" / "slow1.json").exists())
        self.assertEqual(list((self.root / "processing").iterdir()), [], "staging file left behind")

    def test_other_workers_processing_job_is_untouched(self) -> None:
        runner = _make_runner(self.root, max_per_tick=1)
        self._start_gated_job(runner)
        other_pending = enqueue(Job(id="other1", type="slow", payload={}), root=self.root)
        other_proc = _real_start(other_pending, self.root)
        if other_proc is None:
            self.fail("could not claim the other worker's job")
        before = other_proc.read_bytes()

        with self.assertLogs("worker.job_runtime", "WARNING"):
            requeued = runner.drain_live_threads(grace=0.05)

        self.assertEqual(requeued, ["slow1"])
        self.assertTrue(other_proc.exists(), "another worker's job was moved")
        self.assertEqual(other_proc.read_bytes(), before)
        self.assertFalse((self.root / "pending" / "other1.json").exists())

    def test_job_that_left_processing_is_not_recreated(self) -> None:
        runner = _make_runner(self.root, max_per_tick=1)
        proc = self._start_gated_job(runner)
        # The thread is still alive at the deadline, but its job finished
        # (left processing/) before the requeue step reaches it.
        proc.replace(self.root / "done" / "slow1.json")

        requeued = runner.drain_live_threads(grace=0.05)

        self.assertEqual(requeued, [])
        self.assertFalse((self.root / "pending" / "slow1.json").exists())
        self.assertFalse((self.root / "processing" / "slow1.json").exists())


class TestRequeueProcessing(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self) -> None:
        self.setup_queue_root()

    def test_missing_job_returns_none_and_writes_nothing(self) -> None:
        self.assertIsNone(requeue_processing("ghost", reason=_REASON, root=self.root))
        for folder in ("pending", "processing", "done", "error"):
            self.assertEqual(list((self.root / folder).iterdir()), [], folder)

    def test_requeued_job_is_immediately_eligible(self) -> None:
        from worker.queue_ops import list_pending

        pending = enqueue(Job(id="j1", type="slow", payload={}, attempts=2), root=self.root)
        self.assertIsNotNone(_real_start(pending, self.root))

        new_path = requeue_processing("j1", reason=_REASON, root=self.root)

        self.assertEqual(new_path, self.root / "pending" / "j1.json")
        self.assertEqual([p.stem for p, _ in list_pending(root=self.root)], ["j1"])
        self.assertEqual(_read(self.root / "pending" / "j1.json")["attempts"], 2)


class TestStopSignals(_ShutdownTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.sentinel_calls: list[int] = []

        def _sentinel(signum: int, _frame: object) -> None:
            self.sentinel_calls.append(signum)

        self.sentinel = _sentinel
        for sig in (signal.SIGTERM, signal.SIGINT):
            self.addCleanup(signal.signal, sig, signal.getsignal(sig))
            signal.signal(sig, _sentinel)
        chdir = patch("worker.job_runtime.os.chdir")
        chdir.start()
        self.addCleanup(chdir.stop)
        repo = patch("worker.job_runtime.get_repo_root", return_value=self.root)
        repo.start()
        self.addCleanup(repo.stop)

    def test_handler_sets_stop_event(self) -> None:
        from worker.job_runtime import _make_stop_handler

        stop = threading.Event()
        _make_stop_handler(stop)(signal.SIGTERM, None)
        self.assertTrue(stop.is_set())

    def test_run_daemon_exits_on_event_and_restores_handlers(self) -> None:
        runner = _make_runner(self.root, interval=30.0, shutdown_grace=0.1)
        during: list[object] = []

        def _tick() -> int:
            during.append(signal.getsignal(signal.SIGTERM))
            during.append(signal.getsignal(signal.SIGINT))
            return 0

        setter = threading.Timer(0.05, runner.stop_event.set)
        self.addCleanup(setter.cancel)
        with patch.object(runner, "tick", side_effect=_tick):
            setter.start()
            started = time.monotonic()
            self.assertEqual(runner.run_daemon(), 0)
        self.assertLess(time.monotonic() - started, 5.0, "sleep did not wake on stop")
        self.assertTrue(during)
        self.assertNotIn(self.sentinel, during, "stop handlers were not installed")
        self.assertIs(signal.getsignal(signal.SIGTERM), self.sentinel)
        self.assertIs(signal.getsignal(signal.SIGINT), self.sentinel)

    def _assert_signal_stops_loop(self, sig: signal.Signals) -> None:
        runner = _make_runner(self.root, interval=0.01, shutdown_grace=0.1)
        ticks = [0]

        def _tick() -> int:
            ticks[0] += 1
            if ticks[0] == 1:
                signal.raise_signal(sig)
            elif ticks[0] > 50:
                raise KeyboardInterrupt  # failsafe so a regression cannot hang
            return 0

        with patch.object(runner, "tick", side_effect=_tick):
            self.assertEqual(runner.run_daemon(), 0)
        self.assertEqual(self.sentinel_calls, [], f"{sig.name} reached the previous handler")
        self.assertEqual(ticks[0], 1, f"{sig.name} did not stop the loop")

    def test_sigterm_stops_loop(self) -> None:
        self._assert_signal_stops_loop(signal.SIGTERM)

    def test_sigint_stops_loop(self) -> None:
        self._assert_signal_stops_loop(signal.SIGINT)

    def test_off_main_thread_installs_nothing_and_stops_on_event(self) -> None:
        runner = _make_runner(self.root, interval=30.0, shutdown_grace=0.1)
        during: list[object] = []
        result: list[int] = []

        def _tick() -> int:
            during.append(signal.getsignal(signal.SIGTERM))
            runner.stop_event.set()
            return 0

        with patch.object(runner, "tick", side_effect=_tick):
            worker = threading.Thread(target=lambda: result.append(runner.run_daemon()))
            worker.start()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [0])
        self.assertEqual(during, [self.sentinel])

    def test_run_daemon_requeues_job_running_at_stop(self) -> None:
        runner = _make_runner(self.root, interval=0.01, max_per_tick=1, shutdown_grace=0.1)
        self.handler._on_start = runner.stop_event.set
        enqueue(Job(id="slow1", type="slow", payload={}, attempts=0), root=self.root)

        with self.assertLogs("worker.job_runtime", "WARNING"):
            self.assertEqual(runner.run_daemon(), 0)

        pending = self.root / "pending" / "slow1.json"
        self.assertTrue(_wait_for(pending.exists, timeout=1), "running job stranded")
        data = _read(pending)
        self.assertEqual(data["attempts"], 0)
        self.assertEqual(data["last_error"], _REASON)


class TestShutdownGraceFlag(unittest.TestCase):
    def _config_for(self, argv: list[str]) -> Any:
        from worker.cli import main

        with patch("worker.cli.DaemonRunner") as runner_cls, patch("worker.cli.JobProcessor"):
            runner_cls.return_value.run_daemon.return_value = 0
            self.assertEqual(main(argv), 0)
        return runner_cls.call_args[0][0]

    def test_flag_parses_into_config(self) -> None:
        self.assertEqual(self._config_for(["daemon", "--shutdown-grace", "2.5"]).shutdown_grace, 2.5)

    def test_default_applies_when_omitted(self) -> None:
        self.assertEqual(self._config_for(["daemon"]).shutdown_grace, 10.0)

    def test_negative_grace_is_rejected(self) -> None:
        from worker.cli import main

        with patch("worker.cli.DaemonRunner") as runner_cls, patch("worker.cli.JobProcessor"), \
             patch("sys.stderr"):
            self.assertNotEqual(main(["daemon", "--shutdown-grace", "-1"]), 0)
        runner_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
