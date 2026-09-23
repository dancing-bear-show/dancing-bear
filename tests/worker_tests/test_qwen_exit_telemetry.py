"""Telemetry is emitted once for EVERY handler outcome, off the job's thread.

Guard exits (admission, memory, prompt budget, post-generation disk, lock
busy, invalid input, internal errors) used to return before the span was
built, so the jobs an operator most needs to see were invisible. And the
export itself used to run inline, so a blackholed collector added its
timeouts to every job.
"""

from __future__ import annotations

import contextlib
import threading
import time
import unittest
import unittest.mock as mock
from collections.abc import Callable
from typing import Any

from worker import qwen, qwen_telemetry
from tests.worker_tests.qwen_fixtures import QwenHandlerCase

_Case = tuple[str, Callable[[], Any], dict[str, object], dict[str, object]]


class QwenEveryExitEmitsTelemetryTests(QwenHandlerCase):
    def _cases(self) -> tuple[_Case, ...]:
        """(expected outcome, patcher factory, payload, job overrides)."""
        return (
            (
                "terminal-lane-over-capacity",
                lambda: mock.patch("worker.qwen._lane_depth", return_value=qwen.THRESHOLDS.max_lane_depth),
                {},
                {},
            ),
            ("deferred-low-memory", lambda: mock.patch("worker.qwen._available_memory_bytes", return_value=1024), {}, {}),
            ("terminal-prompt-too-large", contextlib.nullcontext, {"max_tokens": qwen.THRESHOLDS.num_ctx - 1}, {}),
            ("deferred-low-disk", lambda: mock.patch("worker.qwen._free_disk_bytes", return_value=1024), {}, {}),
            ("deferred-qwen-busy", lambda: mock.patch("worker.qwen._acquire_model_lock", return_value=False), {}, {}),
            (qwen.INVALID_JOB_ID_OUTCOME, contextlib.nullcontext, {}, {"id": "../x"}),
            ("terminal-invalid-payload: files must be a non-empty list[str]", contextlib.nullcontext, {"files": []}, {}),
            ("terminal-path-not-allowed: src/missing.py", contextlib.nullcontext, {"files": ["src/missing.py"]}, {}),
            (
                "terminal-internal-error: ValueError",
                lambda: mock.patch("worker.qwen._build_prompt", side_effect=ValueError("boom")),
                {},
                {},
            ),
        )

    def test_each_guard_exit_emits_exactly_one_span_and_one_metrics_export(self) -> None:
        for outcome, patcher, payload, overrides in self._cases():
            with self.subTest(outcome=outcome):
                self.export.reset_mock()
                self.export_metrics.reset_mock()
                with patcher():
                    ok, out = self.run_handler(payload, **overrides)
                self.assertEqual((ok, out), (False, outcome))

                [attrs] = self.span_attrs()
                self.assertEqual(attrs["qwen.outcome"], outcome)
                self.assertIsNone(attrs["qwen.patch_valid"])
                self.assertIsInstance(attrs["qwen.generation_duration_ms"], int)
                self.assertGreaterEqual(int(str(attrs["qwen.generation_duration_ms"])), 0)
                self.assertNotIn("qwen.prompt_tokens", attrs)
                self.assertNotIn("qwen.completion_tokens", attrs)

                [(metric_attrs, duration_ms, prompt_tokens, completion_tokens)] = self.metrics_calls()
                self.assertEqual(metric_attrs["qwen.outcome"], outcome)
                self.assertGreaterEqual(duration_ms, 0)
                self.assertEqual((prompt_tokens, completion_tokens), (None, None))

    def test_deferral_limit_emits_its_terminal_outcome(self) -> None:
        self.seed_deferrals(qwen.THRESHOLDS.deferral_ceiling_count - 1, "low-memory")

        with mock.patch("worker.qwen._available_memory_bytes", return_value=1024):
            ok, out = self.run_handler()

        self.assertEqual((ok, out), (False, "terminal-deferral-limit: low-memory"))
        self.assertEqual([a["qwen.outcome"] for a in self.span_attrs()], ["terminal-deferral-limit: low-memory"])

    def test_success_still_emits_exactly_one_span_with_tokens(self) -> None:
        ok, _ = self.run_handler()

        self.assertTrue(ok)
        [attrs] = self.span_attrs()
        self.assertEqual(attrs["qwen.outcome"], "success")
        self.assertEqual((attrs["qwen.prompt_tokens"], attrs["qwen.completion_tokens"]), (84, 57))

    def test_successful_explain_run_emits_nothing(self) -> None:
        ok, _ = self.run_handler({"explain": True})

        self.assertTrue(ok)
        self.assertEqual(self.span_attrs(), [])
        self.assertEqual(self.metrics_calls(), [])


class QwenTelemetryIsOffTheJobPathTests(QwenHandlerCase):
    def test_handler_returns_while_the_collector_is_still_blocked(self) -> None:
        release = threading.Event()

        def blocked_post(url: str, body: dict[str, object], timeout: float) -> None:
            release.wait(3)

        self.post.side_effect = blocked_post
        started = time.monotonic()
        ok, _ = qwen.handle_qwen_patch(self.job())
        elapsed = time.monotonic() - started
        export_still_running = not qwen_telemetry.wait_for_exports(timeout=0.05)
        release.set()

        self.assertTrue(ok)
        self.assertLess(elapsed, 1.0, "the handler waited on the collector")
        self.assertTrue(export_still_running, "the export finished before the collector answered")
        self.assertTrue(qwen_telemetry.wait_for_exports(timeout=5))
        self.assertEqual(len(self.otlp_posts(path_suffix="/v1/traces")), 1)
        self.assertEqual(len(self.otlp_posts(path_suffix="/v1/metrics")), 1)


if __name__ == "__main__":
    unittest.main()
