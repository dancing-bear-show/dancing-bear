"""Tests for worker.qwen.handle_qwen_patch: happy path, retry_map, guards.

Every class here inherits QwenHandlerCase (tests/worker_tests/qwen_fixtures.py),
which routes urllib.request.urlopen through a fixture and stubs the OTLP
post. Transport failures are raised from urlopen itself, so they take the
real _ollama_request -> _call_ollama_generate path rather than an exception
shape injected at a seam the transport never raises.

Route (a) is in effect (contract.json heartbeat.route_chosen == "a"): no
heartbeat field exists, so QwenBackwardCompatibilityTests covers the
pre-existing reaper behaviour instead of heartbeat freshness.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess  # nosec B404 - builds throwaway git repos inside the test temp dir
import time
import unittest
import urllib.error
from pathlib import Path
import unittest.mock as mock

from telemetry.otel.models import OTLPSpansRecord
from worker import queue_ops as q
from worker import qwen, qwen_telemetry
from tests.worker_tests.qwen_fixtures import (
    GREET_DIFF,
    GREET_EDIT,
    GREET_PATH,
    MODEL,
    REAL_GIT_APPLY_CHECK,
    REAL_LANE_DEPTH,
    RESULT_SCHEMA_KEYS,
    RUNNING_DIGEST,
    QwenHandlerCase,
    edit_block,
    http_error,
    model_says,
    require,
)

_PLAIN = qwen.TRANSIENT_OUTCOME_PREFIX
_FAKE_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"  # nosec B105 - fixture value asserted as masked, not a real credential


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # nosec B603 B607 - fixed git argv inside a test temp dir
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True
    )
    return result.stdout


def _many_files_diff(count: int) -> str:
    return "".join(f"--- a/src/f{i}.py\n+++ b/src/f{i}.py\n@@ -0,0 +1 @@\n+line{i}\n" for i in range(count))


def _single_file_diff(path: str) -> str:
    return f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n"


class QwenHandlerHappyPathTests(QwenHandlerCase):
    """A 200 response carrying an edit block succeeds."""

    def test_valid_diff_returns_success_matching_result_schema(self) -> None:
        ok, result = self.run_handler()

        self.assertTrue(ok)
        result = self.as_dict(result)
        self.assertEqual(set(result), RESULT_SCHEMA_KEYS)
        self.assertIs(result["patch_valid"], True)
        self.assertEqual(result["files_touched"], 1)
        self.assertEqual(result["lines_changed"], 2)
        self.assertEqual(result["model"], MODEL)
        self.assertEqual(result["model_digest"], RUNNING_DIGEST)
        self.assertIsNone(result["digest_matches_recorded"])
        self.assertEqual(result["prompt_tokens"], 84)
        self.assertEqual(result["completion_tokens"], 57)
        duration_ms = result["duration_ms"]
        self.assertIsInstance(duration_ms, int)
        self.assertGreaterEqual(int(str(duration_ms)), 0)
        self.assertIsNone(result["deferral_reasons"])
        self.assertEqual(len(self.generate_requests()), 1)

    def test_patch_artifact_holds_the_built_diff_under_patch_dir(self) -> None:
        ok, result = self.run_handler()

        self.assertTrue(ok)
        result = self.as_dict(result)
        patch_path = Path(str(result["patch_path"]))
        self.assertEqual(patch_path, self.patch_dir / "qwen-test-job.patch")
        self.assertEqual(patch_path.read_text(encoding="utf-8"), GREET_DIFF)
        self.assertEqual(self.patch_files(), [patch_path])

    def test_request_body_matches_the_transport_contract(self) -> None:
        self.run_handler({"system": "be terse"})

        [(url, raw_body, timeout)] = self.generate_requests()
        self.assertEqual(url, "http://localhost:11434/api/generate")
        body = require(raw_body)
        self.assertEqual(body["model"], MODEL)
        self.assertIs(body["stream"], False)
        self.assertEqual(body["system"], "be terse")
        self.assertEqual(body["options"], {"temperature": 0.2, "num_predict": 4096, "num_ctx": 8192})
        self.assertEqual(timeout, 600)
        self.assertIn("return the greeting", body["prompt"])

    def test_ollama_host_env_override_is_used(self) -> None:
        os.environ["QWEN_OLLAMA_HOST"] = "http://ollama.test:1234"

        ok, _ = self.run_handler()

        self.assertTrue(ok)
        self.assertEqual(self.generate_requests()[0][0], "http://ollama.test:1234/api/generate")

    def test_timeout_payload_defaults_to_600_and_honours_a_positive_number(self) -> None:
        """Invalid timeouts are covered by QwenOptionValidationTests."""
        cases = ((None, 600), (42, 42), (7.5, 7.5))
        for raw, expected in cases:
            with self.subTest(timeout=raw):
                self.requests.clear()
                self.run_handler({"timeout": raw})
                self.assertEqual(self.generate_requests()[0][2], expected)

    def test_built_diff_passes_the_real_git_apply_check(self) -> None:
        with mock.patch("worker.qwen._git_apply_check", wraps=REAL_GIT_APPLY_CHECK) as check:
            ok, result = self.run_handler()

        self.assertTrue(ok, result)
        check.assert_called_once()
        self.assertEqual(check.call_args.args[0], GREET_DIFF)
        self.assertTrue(REAL_GIT_APPLY_CHECK(GREET_DIFF, self.repo_root))
        self.assertFalse(REAL_GIT_APPLY_CHECK(GREET_DIFF.replace("print", "echo"), self.repo_root))


class QwenRetryMapTests(QwenHandlerCase):
    """Every row of contract.json's retry_map, by exact outcome string."""

    def _assert_plain(self, out: object, detail: str) -> None:
        self.assertEqual(out, f"{_PLAIN}: {detail}")

    def test_connection_refused_is_plain_failure(self) -> None:
        self.generate_error = urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

        ok, out = self.run_handler()

        self.assertFalse(ok)
        self._assert_plain(out, "[Errno 61] Connection refused")

    def test_connect_timeout_is_plain_failure(self) -> None:
        self.generate_error = urllib.error.URLError(TimeoutError("timed out"))

        ok, out = self.run_handler()

        self.assertFalse(ok)
        self._assert_plain(out, "timed out")

    def test_read_timeout_is_plain_failure(self) -> None:
        """A timeout during resp.read() escapes urlopen unwrapped."""
        self.generate_error = TimeoutError("timed out")

        ok, out = self.run_handler()

        self.assertFalse(ok)
        self._assert_plain(out, "timed out")

    def test_http_5xx_is_plain_failure(self) -> None:
        self.generate_error = http_error(503)

        ok, out = self.run_handler()

        self.assertFalse(ok)
        self._assert_plain(out, "http-error-503")

    def test_http_404_model_not_found_is_terminal(self) -> None:
        self.generate_error = http_error(404)

        ok, out = self.run_handler()

        self.assertFalse(ok)
        self.assertEqual(out, "terminal-model-not-found")

    def test_client_errors_are_terminal_not_retried(self) -> None:
        """Re-sending a refused request cannot fix it, so it must not burn attempts."""
        for status in (400, 401, 403, 405, 413, 422):
            with self.subTest(status=status):
                self.generate_error = http_error(status)

                ok, out = self.run_handler()

                self.assertFalse(ok)
                self.assertEqual(out, f"terminal-ollama-request-rejected: http-error-{status}")

    def test_retryable_statuses_stay_plain(self) -> None:
        """5xx, 408 and 429 are transient: plain failures the queue retries."""
        for status in (408, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                self.generate_error = http_error(status)

                ok, out = self.run_handler()

                self.assertFalse(ok)
                self._assert_plain(out, f"http-error-{status}")

    def test_seam_error_shapes_classify_by_status(self) -> None:
        """The exact shapes _ollama_request emits, injected at the seam."""
        cases = (
            (qwen.QwenGuardError("http-error-404"), "terminal-model-not-found"),
            (qwen.QwenGuardError("http-error-503"), f"{_PLAIN}: http-error-503"),
            (ConnectionError("refused"), f"{_PLAIN}: refused"),
        )
        for exc, expected in cases:
            with self.subTest(exc=repr(exc)), mock.patch("worker.qwen._ollama_request", side_effect=exc):
                self.assertEqual(self.run_handler(), (False, expected))

    def test_malformed_json_body_is_plain_failure(self) -> None:
        for raw, detail in (
            (b"<html>502 Bad Gateway</html>", "malformed response body"),
            (b"\xff\xfe", "malformed response body"),
            (b"[1, 2]", "response body is not a JSON object"),
        ):
            with self.subTest(raw=raw):
                self.generate_raw = raw
                ok, out = self.run_handler()
                self.assertFalse(ok)
                self._assert_plain(out, detail)

    def test_no_edit_blocks_is_terminal(self) -> None:
        responses: tuple[dict[str, object], ...] = (
            {"response": "sorry, I cannot help with that"},
            {"response": ""},
            {"error": "model runner crashed"},
            model_says(f"```diff\n{GREET_DIFF}```"),
        )
        for response in responses:
            with self.subTest(response=response):
                self.generate_response = response
                self.assertEqual(self.run_handler(), (False, "terminal-no-edits-found"))
        self.assertEqual(self.patch_files(), [])

    def test_each_edit_outcome_reaches_the_handler_result(self) -> None:
        cases = (
            (edit_block("src/other.py", "def greet(name):", "x"), "terminal-edit-outside-inputs"),
            (edit_block(GREET_PATH, "absent line", "x"), "terminal-edit-not-found"),
            (f"FILE: {GREET_PATH}\n<<<<<<< SEARCH\n=======\nx\n>>>>>>> REPLACE\n", "terminal-edit-ambiguous"),
            (edit_block(GREET_PATH, "def greet(name):", "def greet(name):"), "terminal-no-change"),
            (f"FILE: {GREET_PATH}\n<<<<<<< SEARCH\ndef greet(name):\n=======\n", "terminal-edit-malformed"),
        )
        for text, expected in cases:
            with self.subTest(expected=expected):
                self.generate_response = model_says(text)
                self.assertEqual(self.run_handler(), (False, expected))
        self.assertEqual(self.patch_files(), [])

    def test_patch_fails_git_apply_check_is_terminal(self) -> None:
        with mock.patch("worker.qwen._git_apply_check", return_value=False):
            ok, out = self.run_handler()

        self.assertFalse(ok)
        self.assertEqual(out, "terminal-patch-does-not-apply")
        self.assertEqual(self.patch_files(), [])

    def test_disallowed_files_path_is_terminal_path_not_allowed(self) -> None:
        outside = Path(self.tmpdir) / "outside.txt"
        outside.write_text("root:x:0:0::/root:/bin/bash\n", encoding="utf-8")

        with mock.patch("pathlib.Path.read_text", side_effect=AssertionError("file was read")):
            ok, out = self.run_handler({"files": ["../outside.txt"]})

        self.assertFalse(ok)
        self.assertEqual(out, "terminal-path-not-allowed: ../outside.txt")
        self.assertEqual(self.generate_requests(), [])

    def test_nonexistent_file_inside_allowlist_is_terminal_path_not_allowed(self) -> None:
        ok, out = self.run_handler({"files": ["src/missing.py"]})

        self.assertFalse(ok)
        self.assertEqual(out, "terminal-path-not-allowed: src/missing.py")

    def test_patch_too_broad_is_terminal(self) -> None:
        """Real check_patch_caps, fed through the handler: one edit to each of
        max_files + 1 input files."""
        paths = [f"src/example/f{i}.py" for i in range(qwen.THRESHOLDS.max_files + 1)]
        for i, path in enumerate(paths):
            (self.repo_root / path).write_text(f"line{i}\n", encoding="utf-8")
        self.generate_response = model_says(
            "".join(edit_block(path, f"line{i}", f"changed{i}") for i, path in enumerate(paths))
        )

        ok, out = self.run_handler({"files": paths})

        self.assertFalse(ok)
        self.assertEqual(out, "terminal-patch-too-broad")
        self.assertEqual(self.patch_files(), [])

    def test_prompt_too_large_is_terminal(self) -> None:
        with mock.patch("worker.qwen.THRESHOLDS", qwen.QwenThresholds(num_ctx=1)):
            ok, out = self.run_handler()

        self.assertFalse(ok)
        self.assertEqual(out, "terminal-prompt-too-large")
        self.assertEqual(self.generate_requests(), [])

    def test_max_tokens_leaving_no_room_for_the_prompt_is_prompt_too_large(self) -> None:
        """num_ctx - 1 is the largest valid max_tokens; it leaves one token of
        budget, which no real prompt fits. Larger values are invalid payloads."""
        self.assertEqual(
            self.run_handler({"max_tokens": qwen.THRESHOLDS.num_ctx - 1}), (False, "terminal-prompt-too-large")
        )
        self.assertEqual(self.generate_requests(), [])

    def test_invalid_payload_is_terminal(self) -> None:
        cases: tuple[dict[str, object], ...] = (
            {"files": None},
            {"files": []},
            {"files": "src/example/greet.py"},
            {"files": [1]},
            {"instruction": None},
            {"instruction": "   "},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                ok, out = self.run_handler(overrides)
                self.assertFalse(ok)
                self.assertTrue(str(out).startswith("terminal-invalid-payload: "), out)
        self.assertEqual(self.generate_requests(), [])


class QwenBackwardCompatibilityTests(QwenHandlerCase):
    """Route (a): no heartbeat field is written or read by this handler."""

    def test_job_with_no_heartbeat_field_processes_normally(self) -> None:
        job = self.job()
        self.assertNotIn("heartbeat", job)

        ok, _ = qwen.handle_qwen_patch(job)

        self.assertTrue(ok)
        self.assertNotIn("heartbeat", job)

    def test_existing_reaper_behaviour_unchanged_for_qwen_job_shape(self) -> None:
        """A qwen job enqueued with the default timeout_sec is never reaped
        under the shipped plist's job_timeout of 0, however old it is."""
        queue_root = Path(self.tmpdir) / "queue"
        job = q.Job(id="qwen-reaper-job", type="qwen_patch", payload={"files": [GREET_PATH], "instruction": "x"})
        self.assertEqual(job.timeout_sec, 0)
        proc_path = require(q.start_processing(q.enqueue(job, root=queue_root), root=queue_root))
        day_old = time.time() - 86_400
        os.utime(proc_path, (day_old, day_old))

        reaped = q.reap_stale_processing_jobs(0, root=queue_root)

        self.assertEqual(reaped, [])
        self.assertTrue(proc_path.exists())


class QwenTelemetryTests(QwenHandlerCase):
    """One qwen.job span per completed model call, with contract attributes."""

    def test_job_succeeds_when_telemetry_export_raises(self) -> None:
        with mock.patch("worker.qwen.export_job_span", side_effect=RuntimeError("collector unreachable")):
            ok, result = self.run_handler()

        self.assertTrue(ok)
        result = self.as_dict(result)
        self.assertTrue(Path(str(result["patch_path"])).exists())

    def test_job_succeeds_when_collector_post_fails(self) -> None:
        self.post.side_effect = OSError("connection refused")

        ok, _ = self.run_handler()

        self.assertTrue(ok)
        # Both span and metrics export attempt one POST each on this path.
        self.assertEqual(self.post.call_count, 2)

    def test_success_emits_one_span_with_contract_attributes(self) -> None:
        ok, _ = self.run_handler()

        self.assertTrue(ok)
        [attrs] = self.span_attrs()
        self.assertEqual(attrs["qwen.outcome"], "success")
        self.assertEqual(attrs["qwen.job_id"], "qwen-test-job")
        self.assertEqual(attrs["qwen.job_type"], "qwen_patch")
        self.assertEqual(attrs["qwen.model"], MODEL)
        self.assertEqual(attrs["qwen.attempt"], 0)
        self.assertIs(attrs["qwen.patch_valid"], True)
        self.assertEqual(attrs["qwen.prompt_tokens"], 84)
        self.assertEqual(attrs["qwen.completion_tokens"], 57)
        self.assertIsInstance(attrs["qwen.generation_duration_ms"], int)
        self.assertEqual(attrs["qwen.model_pin"], "unpinned")
        self.assertEqual(attrs["qwen.model_digest"], RUNNING_DIGEST)
        self.assertFalse(any("cost" in key for key in attrs))

    def test_posted_span_round_trips_to_the_default_collector(self) -> None:
        self.run_handler()

        [call] = self.otlp_posts(path_suffix="/v1/traces")
        url, doc = call.args[0], call.args[1]
        self.assertEqual(url, "http://localhost:4318/v1/traces")
        self.assertEqual(call.kwargs, {"timeout": qwen_telemetry.EXPORT_TIMEOUT_SEC})
        span = OTLPSpansRecord.from_dict(doc).spans[0]
        self.assertEqual(span.name, "qwen.job")
        self.assertEqual(span.get_attr("qwen.outcome"), "success")

    def test_otlp_endpoint_env_override(self) -> None:
        """The generic endpoint var only gets a path appended under an HTTP
        protocol (see test_otlp_endpoint_grpc_protocol_does_not_append_path
        for the complementary case)."""
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://collector.test:9999"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"

        self.run_handler()

        [call] = self.otlp_posts(path_suffix="/v1/traces")
        self.assertEqual(call.args[0], "http://collector.test:9999/v1/traces")
        [mcall] = self.otlp_posts(path_suffix="/v1/metrics")
        self.assertEqual(mcall.args[0], "http://collector.test:9999/v1/metrics")

    def test_otlp_endpoint_grpc_protocol_does_not_append_path(self) -> None:
        """src/telemetry/otel/health.py:53-56 tells users to pair the generic
        endpoint var with the collector's gRPC port and protocol=grpc. This
        handler speaks OTLP/HTTP JSON, so that combination must fall back to
        the HTTP default rather than appending /v1/traces to a gRPC
        endpoint, which would silently drop every export."""
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "grpc"

        self.run_handler()

        [call] = self.otlp_posts(path_suffix="/v1/traces")
        self.assertEqual(call.args[0], "http://localhost:4318/v1/traces")

    def test_per_signal_traces_endpoint_used_as_is(self) -> None:
        os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = "https://collector.test/traces-in"

        self.run_handler()

        [call] = self.otlp_posts(path_suffix="/traces-in")
        self.assertEqual(call.args[0], "https://collector.test/traces-in")

    def test_terminal_outcome_emits_span_with_exact_outcome(self) -> None:
        with mock.patch("worker.qwen._git_apply_check", return_value=False):
            self.run_handler()

        [attrs] = self.span_attrs()
        self.assertEqual(attrs["qwen.outcome"], "terminal-patch-does-not-apply")
        self.assertIsNone(attrs["qwen.patch_valid"])

    def test_success_emits_metrics_with_matching_token_counts_and_duration(self) -> None:
        ok, _ = self.run_handler()

        self.assertTrue(ok)
        [(attrs, duration_ms, prompt_tokens, completion_tokens)] = self.metrics_calls()
        self.assertEqual(attrs["qwen.outcome"], "success")
        self.assertEqual(attrs["qwen.job_id"], "qwen-test-job")
        self.assertEqual(prompt_tokens, 84)
        self.assertEqual(completion_tokens, 57)
        self.assertGreaterEqual(duration_ms, 0)

    def test_metrics_posted_to_the_default_metrics_endpoint(self) -> None:
        self.run_handler()

        metrics_posts = [c for c in self.post.call_args_list if c.args[0].endswith("/v1/metrics")]
        self.assertEqual(len(metrics_posts), 1)
        self.assertEqual(metrics_posts[0].args[0], "http://localhost:4318/v1/metrics")

    def test_job_succeeds_when_metrics_export_raises(self) -> None:
        with mock.patch("worker.qwen.export_job_metrics", side_effect=RuntimeError("collector unreachable")):
            ok, result = self.run_handler()

        self.assertTrue(ok)
        result = self.as_dict(result)
        self.assertTrue(Path(str(result["patch_path"])).exists())

    def test_metrics_export_failure_does_not_skip_span_export(self) -> None:
        with mock.patch("worker.qwen.export_job_metrics", side_effect=RuntimeError("collector unreachable")):
            ok, _ = self.run_handler()

        self.assertTrue(ok)
        self.export.assert_called_once()

    def test_span_export_failure_does_not_skip_metrics_export(self) -> None:
        with mock.patch("worker.qwen.export_job_span", side_effect=RuntimeError("collector unreachable")):
            ok, _ = self.run_handler()

        self.assertTrue(ok)
        self.export_metrics.assert_called_once()


class QwenMemoryPrecheckTests(QwenHandlerCase):
    def test_low_memory_defers_and_does_not_call_model(self) -> None:
        with mock.patch("worker.qwen._available_memory_bytes", return_value=1024**2):
            ok, out = self.run_handler()

        self.assertFalse(ok)
        self.assertEqual(out, "deferred-low-memory")
        self.assertEqual(self.generate_requests(), [])
        self.assertTrue(self.deferral_file().exists())

    def test_ample_memory_proceeds_to_call_model(self) -> None:
        ok, _ = self.run_handler()

        self.assertTrue(ok)
        self.assertEqual(len(self.generate_requests()), 1)

    def test_memory_source_unavailable_proceeds_with_warning(self) -> None:
        """A precheck that fails closed would silently stop every qwen job."""
        with (
            mock.patch("worker.qwen._available_memory_bytes", return_value=None),
            self.assertLogs("worker.qwen", level=logging.WARNING) as logs,
        ):
            ok, _ = self.run_handler()

        self.assertTrue(ok)
        self.assertEqual(len(self.generate_requests()), 1)
        self.assertTrue(any("memory reading unavailable" in line for line in logs.output))

    def test_parse_vm_stat_sums_free_inactive_speculative_pages(self) -> None:
        sample = (
            "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
            "Pages free:                               12345.\n"
            "Pages active:                            100000.\n"
            "Pages inactive:                           20000.\n"
            "Pages speculative:                         3000.\n"
            "Pages wired down:                         50000.\n"
        )

        self.assertEqual(qwen._parse_vm_stat(sample), (12345 + 20000 + 3000) * 16384)
        self.assertIsNone(qwen._parse_vm_stat("no page size line"))


class QwenDiskGuardTests(QwenHandlerCase):
    def test_low_disk_defers_and_writes_no_patch_file(self) -> None:
        with mock.patch("worker.qwen._free_disk_bytes", return_value=1024):
            ok, out = self.run_handler()

        self.assertFalse(ok)
        self.assertEqual(out, "deferred-low-disk")
        self.assertEqual(self.patch_files(), [])

    def test_ample_disk_proceeds(self) -> None:
        ok, _ = self.run_handler()

        self.assertTrue(ok)
        self.assertEqual(len(self.patch_files()), 1)

    def test_disk_source_unreadable_proceeds_with_warning(self) -> None:
        with (
            mock.patch("worker.qwen._free_disk_bytes", return_value=None),
            self.assertLogs("worker.qwen", level=logging.WARNING) as logs,
        ):
            ok, _ = self.run_handler()

        self.assertTrue(ok)
        self.assertTrue(any("disk reading unavailable" in line for line in logs.output))


class QwenModelPinningTests(QwenHandlerCase):
    """contract.model_pinning: compare against the install-time record."""

    def _pin_status(self) -> object:
        return self.span_attrs()[-1]["qwen.model_pin"]

    def test_digest_mismatch_recorded_but_job_still_succeeds(self) -> None:
        self.record_digest("0" * 64)

        with self.assertLogs("worker.qwen", level=logging.WARNING) as logs:
            ok, result = self.run_handler()

        self.assertTrue(ok, "a digest mismatch must not fail the job")
        result = self.as_dict(result)
        self.assertIs(result["digest_matches_recorded"], False)
        self.assertEqual(result["model_digest"], RUNNING_DIGEST)
        self.assertEqual(self._pin_status(), "mismatch")
        self.assertTrue(any("digest drift" in line for line in logs.output))

    def test_digest_match_is_true(self) -> None:
        self.record_digest(f"sha256:{RUNNING_DIGEST.upper()}")

        ok, result = self.run_handler()

        self.assertTrue(ok)
        result = self.as_dict(result)
        self.assertIs(result["digest_matches_recorded"], True)
        self.assertEqual(self._pin_status(), "match")

    def test_no_recorded_digest_is_reported_unpinned(self) -> None:
        with self.assertLogs("worker.qwen", level=logging.WARNING) as logs:
            ok, result = self.run_handler()

        self.assertTrue(ok)
        result = self.as_dict(result)
        self.assertIsNone(result["digest_matches_recorded"])
        self.assertEqual(self._pin_status(), "unpinned")
        self.assertTrue(any("unpinned" in line for line in logs.output))

    def test_record_for_a_different_model_is_unpinned(self) -> None:
        self.record_digest(RUNNING_DIGEST, model="llama3:8b")

        _, result = self.run_handler()

        result = self.as_dict(result)
        self.assertIsNone(result["digest_matches_recorded"])
        self.assertEqual(self._pin_status(), "unpinned")

    def test_corrupt_record_is_unpinned_not_an_error(self) -> None:
        self.digest_record.parent.mkdir(parents=True, exist_ok=True)
        self.digest_record.write_text("{not json", encoding="utf-8")

        ok, result = self.run_handler()

        self.assertTrue(ok)
        result = self.as_dict(result)
        self.assertIsNone(result["digest_matches_recorded"])

    def test_running_digest_unreadable_is_unverified(self) -> None:
        self.record_digest(RUNNING_DIGEST)
        for error in (http_error(500), urllib.error.URLError(ConnectionRefusedError())):
            with self.subTest(error=repr(error)):
                self.tags_error = error
                ok, result = self.run_handler()
                self.assertTrue(ok)
                result = self.as_dict(result)
                self.assertIsNone(result["model_digest"])
                self.assertIsNone(result["digest_matches_recorded"])
                self.assertEqual(self._pin_status(), "unverified")

    def test_model_digest_reads_the_api_tags_models_list(self) -> None:
        self.tags_response = {
            "models": [
                {"name": "llama3:8b", "digest": "1" * 64},
                {"name": MODEL, "digest": RUNNING_DIGEST},
            ]
        }

        self.assertEqual(qwen._model_digest("http://localhost:11434", MODEL), RUNNING_DIGEST)
        self.assertIsNone(qwen._model_digest("http://localhost:11434", "missing:1b"))
        self.assertEqual(self.requests[-1][0], "http://localhost:11434/api/tags")


class QwenDeferralBoundTests(QwenHandlerCase):
    """contract.deferral_bound: count and wall-clock ceilings, plus cleanup."""

    def _lock_unavailable(self) -> contextlib.AbstractContextManager[object]:
        return mock.patch("worker.qwen._acquire_model_lock", return_value=False)

    def test_deferral_counter_persists_across_a_real_retry_cycle(self) -> None:
        """retry() reloads the job from disk and writes only attempts,
        not_before, updated_at and last_error, so a payload-embedded counter
        is inert. The side-channel file must survive retry() plus
        _undo_retry_attempt()."""
        from worker.job_runtime import _undo_retry_attempt

        queue_root = Path(self.tmpdir) / "queue"
        job = q.Job(id="deferral-persist-job", type="qwen_patch", payload={"files": [GREET_PATH], "instruction": "x"})
        proc_path = require(q.start_processing(q.enqueue(job, root=queue_root), root=queue_root))

        with self._lock_unavailable():
            ok, out = qwen.handle_qwen_patch(self.job(id=job.id))
        q.retry(proc_path, delay_sec=60, reason=str(out), root=queue_root)
        _undo_retry_attempt(proc_path.stem, 0, q_root=queue_root)
        with self._lock_unavailable():
            qwen.handle_qwen_patch(self.job(id=job.id))

        self.assertFalse(ok)
        on_disk = json.loads((queue_root / "pending" / f"{job.id}.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["attempts"], 0)
        self.assertEqual(on_disk["last_error"], "deferred-qwen-busy")
        counter = json.loads(self.deferral_file(job.id).read_text(encoding="utf-8"))
        self.assertEqual(counter["count"], 2)
        self.assertEqual(counter["reasons"], {"qwen-busy": 2})

    def test_deferral_below_ceiling_stays_deferred(self) -> None:
        ceiling = qwen.THRESHOLDS.deferral_ceiling_count
        self.seed_deferrals(ceiling - 2, "qwen-busy")

        with self._lock_unavailable():
            ok, out = self.run_handler()

        self.assertEqual((ok, out), (False, "deferred-qwen-busy"))
        state = json.loads(self.deferral_file().read_text(encoding="utf-8"))
        self.assertEqual(state["count"], ceiling - 1)

    def test_deferral_limit_reached_at_exact_ceiling_is_terminal(self) -> None:
        self.seed_deferrals(qwen.THRESHOLDS.deferral_ceiling_count - 1, "qwen-busy")

        with self._lock_unavailable():
            ok, out = self.run_handler()

        self.assertEqual((ok, out), (False, "terminal-deferral-limit: qwen-busy"))
        self.assertFalse(self.deferral_file().exists(), "side-channel file must be deleted on a terminal exit")

    def test_low_memory_and_low_disk_deferrals_reach_the_limit(self) -> None:
        for reason, seam in (("low-memory", "_available_memory_bytes"), ("low-disk", "_free_disk_bytes")):
            with self.subTest(reason=reason):
                self.seed_deferrals(qwen.THRESHOLDS.deferral_ceiling_count - 1, reason)
                with mock.patch(f"worker.qwen.{seam}", return_value=1024):
                    ok, out = self.run_handler()
                self.assertEqual((ok, out), (False, f"terminal-deferral-limit: {reason}"))
                self.assertFalse(self.deferral_file().exists())

    def test_wallclock_backstop_triggers_limit(self) -> None:
        self.deferral_dir.mkdir(parents=True)
        forty_six_min_ago = time.time() - 46 * 60
        self.deferral_file().write_text(
            json.dumps({"count": 1, "reasons": {"qwen-busy": 1}, "first_deferred_at": forty_six_min_ago}),
            encoding="utf-8",
        )

        with self._lock_unavailable():
            ok, out = self.run_handler()

        self.assertEqual((ok, out), (False, "terminal-deferral-limit: qwen-busy"))
        self.assertFalse(self.deferral_file().exists())

    def test_wallclock_below_backstop_stays_deferred(self) -> None:
        self.deferral_dir.mkdir(parents=True)
        forty_four_min_ago = time.time() - 44 * 60
        self.deferral_file().write_text(
            json.dumps({"count": 1, "reasons": {"qwen-busy": 1}, "first_deferred_at": forty_four_min_ago}),
            encoding="utf-8",
        )

        with self._lock_unavailable():
            self.assertEqual(self.run_handler(), (False, "deferred-qwen-busy"))

    def _cleanup_case(self, expected_prefix: str, survives: bool, payload: dict[str, object] | None = None) -> None:
        self.seed_deferrals(3, "qwen-busy")
        ok, out = self.run_handler(payload)
        self.assertTrue(str(out if not ok else "success").startswith(expected_prefix), out)
        self.assertEqual(self.deferral_file().exists(), survives)
        self.deferral_file().unlink(missing_ok=True)

    def test_plain_failure_keeps_deferral_state(self) -> None:
        """A plain failure is retried under the same job id and may defer again."""
        self.generate_error = http_error(503)

        self._cleanup_case(_PLAIN, survives=True)

    def test_every_terminal_exit_clears_deferral_state(self) -> None:
        with self.subTest(outcome="terminal-no-edits-found"):
            self.generate_response = {"response": "no"}
            self._cleanup_case("terminal-no-edits-found", survives=False)
        with self.subTest(outcome="terminal-path-not-allowed"):
            self._cleanup_case("terminal-path-not-allowed", survives=False, payload={"files": ["src/missing.py"]})
        with self.subTest(outcome="terminal-model-not-found"):
            self.generate_error = http_error(404)
            self._cleanup_case("terminal-model-not-found", survives=False)

    def test_success_clears_deferral_state(self) -> None:
        self._cleanup_case("success", survives=False)


class QwenAdmissionCapTests(QwenHandlerCase):
    def test_excess_job_returns_terminal_lane_over_capacity(self) -> None:
        with mock.patch("worker.qwen._lane_depth", return_value=qwen.THRESHOLDS.max_lane_depth):
            ok, out = self.run_handler()

        self.assertEqual((ok, out), (False, "terminal-lane-over-capacity"))
        self.assertEqual(self.generate_requests(), [])

    def test_lane_depth_counts_only_qwen_patch_jobs(self) -> None:
        """Ten pending jobs of another type must not fill the qwen lane."""
        queue_root = Path(self.tmpdir) / "queue"
        for i in range(qwen.THRESHOLDS.max_lane_depth):
            q.enqueue(q.Job(id=f"cli-{i}", type="run_cli", payload={}), root=queue_root)
        q.enqueue(q.Job(id="qwen-a", type="qwen_patch", payload={}), root=queue_root)
        qwen_b = q.enqueue(q.Job(id="qwen-b", type="qwen_patch", payload={}), root=queue_root)
        q.start_processing(qwen_b, root=queue_root)

        with (
            mock.patch("worker.queue_ops.QUEUE_ROOT", queue_root),
            mock.patch("worker.qwen._lane_depth", wraps=REAL_LANE_DEPTH),
        ):
            self.assertEqual(qwen._lane_depth("qwen_patch"), 2)
            self.assertEqual(qwen._lane_depth("run_cli"), qwen.THRESHOLDS.max_lane_depth)
            ok, _ = self.run_handler()

        self.assertTrue(ok, "a full run_cli lane must not trip the qwen_patch admission cap")

    def test_deferred_job_with_future_not_before_counts_toward_the_cap(self) -> None:
        """Every deferral sets a future not_before; list_pending hides such jobs,
        so a count built on it would let a deferred backlog grow unbounded."""
        queue_root = Path(self.tmpdir) / "queue"
        q.enqueue(
            q.Job(id="qwen-deferred", type="qwen_patch", payload={}, not_before="2999-01-01T00:00:00Z"),
            root=queue_root,
        )
        for i in range(qwen.THRESHOLDS.max_lane_depth - 1):
            q.enqueue(q.Job(id=f"qwen-{i}", type="qwen_patch", payload={}), root=queue_root)

        with (
            mock.patch("worker.queue_ops.QUEUE_ROOT", queue_root),
            mock.patch("worker.qwen._lane_depth", wraps=REAL_LANE_DEPTH),
        ):
            self.assertEqual(qwen._lane_depth("qwen_patch"), qwen.THRESHOLDS.max_lane_depth)
            ok, out = self.run_handler()

        self.assertEqual((ok, out), (False, "terminal-lane-over-capacity"))
        self.assertEqual(self.generate_requests(), [])


class QwenRedactionTests(QwenHandlerCase):
    """contract.redaction: no secret reaches the outcome or the span."""

    def _assert_masked(self, out: object) -> None:
        self.assertNotIn(_FAKE_TOKEN, json.dumps(out))
        self.assertNotIn(_FAKE_TOKEN, json.dumps(self.span_attrs(), default=str))
        self.assertIn("REDACTED", str(out))

    def test_secret_in_transport_error_is_masked_in_outcome_and_span(self) -> None:
        errors = (
            urllib.error.URLError(ConnectionRefusedError(f"refused token={_FAKE_TOKEN}")),
            TimeoutError(f"timed out Authorization: Bearer {_FAKE_TOKEN}"),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                self.export.reset_mock()
                self.generate_error = error
                ok, out = self.run_handler()
                self.assertFalse(ok)
                self.assertTrue(str(out).startswith(f"{_PLAIN}: "), out)
                self.assertEqual(len(self.span_attrs()), 1)
                self._assert_masked(out)

    def test_secret_in_guard_error_is_masked(self) -> None:
        with mock.patch("worker.qwen._ollama_request", side_effect=qwen.QwenGuardError(f"http-error-502 token={_FAKE_TOKEN}")):
            ok, out = self.run_handler()

        self.assertFalse(ok)
        self._assert_masked(out)

    def test_secret_in_payload_path_is_masked(self) -> None:
        ok, out = self.run_handler({"files": [f"src/x?api_key={_FAKE_TOKEN}"]})

        self.assertFalse(ok)
        self.assertTrue(str(out).startswith("terminal-path-not-allowed: "))
        self._assert_masked(out)


class QwenExceptionBoundaryTests(QwenHandlerCase):
    def test_prompt_assembly_exception_returns_masked_content_free_string(self) -> None:
        secret_content = "MY-CONFIDENTIAL-FILE-CONTENTS-xyz"  # nosec B105 - fixture file content, not a real credential
        boom = ValueError(f"could not assemble prompt: saw {secret_content!r}")

        with mock.patch("worker.qwen._build_prompt", side_effect=boom):
            ok, out = self.run_handler()

        self.assertEqual((ok, out), (False, "terminal-internal-error: ValueError"))


class QwenPatchCapsTests(unittest.TestCase):
    def test_check_patch_caps_max_files_exceeded(self) -> None:
        self.assertEqual(qwen.check_patch_caps(_many_files_diff(9)), "terminal-patch-too-broad")
        self.assertIsNone(qwen.check_patch_caps(_many_files_diff(8)))

    def test_check_patch_caps_max_lines_exceeded(self) -> None:
        def big(n: int) -> str:
            return "--- a/src/big.py\n+++ b/src/big.py\n@@ -0,0 +1 @@\n" + "".join(f"+l{i}\n" for i in range(n))

        self.assertEqual(qwen.check_patch_caps(big(401)), "terminal-patch-too-broad")
        self.assertIsNone(qwen.check_patch_caps(big(400)))

    def test_check_patch_caps_ok_diff_returns_none(self) -> None:
        self.assertIsNone(qwen.check_patch_caps(GREET_DIFF))

    def test_denied_targets_including_case_and_path_variants(self) -> None:
        denied = (
            ".github/workflows/ci.yml",
            "bin/qwen",
            "configs/x.plist",
            ".claude/settings.json",
            "Bin/qwen",
            ".GitHub/workflows/ci.yml",
            "CONFIGS/x",
            ".Claude/settings.json",
            "./bin/x",
            "src/../bin/x",
            "src/.git/hooks/pre-commit",
            ".GIT/config",
            "../outside.py",
            "src/../../outside.py",
            "/etc/passwd",
        )
        for target in denied:
            with self.subTest(target=target):
                self.assertEqual(qwen.check_patch_caps(_single_file_diff(target)), "terminal-patch-too-broad")

    def test_similar_but_allowed_targets_pass(self) -> None:
        for target in ("src/binder.py", "src/bin/x.py", "docs/configs.md", "src/binary.txt", "src/./x.py"):
            with self.subTest(target=target):
                self.assertIsNone(qwen.check_patch_caps(_single_file_diff(target)))

    def test_sensitive_names_are_denied_as_patch_targets(self) -> None:
        """The input denylist applies to what the model writes, not just what it reads."""
        for target in (
            "src/credentials.ini",
            "src/.env",
            "tests/.env.local",
            "src/my_token.json",
            "docs/id_rsa",
            "src/cert.pem",
            "src/Credentials.INI",
        ):
            with self.subTest(target=target):
                self.assertEqual(qwen.check_patch_caps(_single_file_diff(target)), "terminal-patch-too-broad")

    def test_targets_outside_the_allowlisted_directories_are_denied(self) -> None:
        """A patch may only write where the job may read: src/, tests/, workflows/, concerns/, docs/."""
        for target in ("README.md", "binary.txt", "pyproject.toml", "out/generated.json", "_data/q.json", "srcevil/x.py"):
            with self.subTest(target=target):
                self.assertEqual(qwen.check_patch_caps(_single_file_diff(target)), "terminal-patch-too-broad")

    def test_quoted_header_path_is_unquoted_before_the_check(self) -> None:
        """git quotes a path holding special characters, a/ b/ prefix included."""
        diff = '--- "a/bin/quoted name"\n+++ "b/bin/quoted name"\n@@ -1 +1 @@\n-a\n+b\n'

        self.assertEqual(qwen.diff_stats(diff)[0], ["bin/quoted name"])
        self.assertEqual(qwen.check_patch_caps(diff), "terminal-patch-too-broad")

    def test_rename_only_diff_into_denied_prefix_is_caught(self) -> None:
        """A pure rename has no ---/+++ lines; the extended headers name the paths."""
        diff = (
            "diff --git a/src/tool.py b/bin/tool\n"
            "similarity index 100%\n"
            "rename from src/tool.py\n"
            "rename to bin/tool\n"
        )

        self.assertEqual(qwen.check_patch_caps(diff), "terminal-patch-too-broad")
        self.assertEqual(qwen.diff_stats(diff)[0], ["src/tool.py", "bin/tool"])

    def test_header_with_timestamp_is_parsed(self) -> None:
        diff = "--- a/bin/x\t2026-09-23 10:00:00\n+++ b/bin/x\t2026-09-23 10:00:01\n@@ -1 +1 @@\n-a\n+b\n"

        self.assertEqual(qwen.diff_stats(diff), (["bin/x"], 2))
        self.assertEqual(qwen.check_patch_caps(diff), "terminal-patch-too-broad")


class QwenPatchHeaderParsingTests(unittest.TestCase):
    """Headers the caps check must read the way git apply reads them.

    A patch with no ---/+++ lines (mode change, rename, binary) names its
    paths only in the diff --git and extended headers, so an unparsed header
    there is an unchecked write.
    """

    def test_quoted_diff_git_header_with_spaces_into_denied_prefix(self) -> None:
        diff = 'diff --git "a/bin/x y" "b/bin/x y"\nold mode 100644\nnew mode 100755\n'

        self.assertEqual(qwen.diff_stats(diff)[0], ["bin/x y"])
        self.assertEqual(qwen.check_patch_caps(diff), "terminal-patch-too-broad")

    def test_octal_escaped_quoted_names_are_decoded(self) -> None:
        """git writes non-ASCII bytes as C-style octal escapes: \\303\\251 is UTF-8 e-acute."""
        diff = 'diff --git "a/bin/caf\\303\\251" "b/bin/caf\\303\\251"\nold mode 100644\nnew mode 100755\n'

        self.assertEqual(qwen.diff_stats(diff)[0], ["bin/café"])
        self.assertEqual(qwen.check_patch_caps(diff), "terminal-patch-too-broad")

    def test_quoted_rename_headers_are_decoded(self) -> None:
        diff = (
            'diff --git a/src/tool.py "b/bin/t\\303\\251 x"\n'
            "similarity index 100%\n"
            "rename from src/tool.py\n"
            'rename to "bin/t\\303\\251 x"\n'
        )

        self.assertEqual(qwen.diff_stats(diff)[0], ["src/tool.py", "bin/té x"])
        self.assertEqual(qwen.check_patch_caps(diff), "terminal-patch-too-broad")

    def test_unparseable_path_header_fails_closed(self) -> None:
        for header in (
            'diff --git "a/bin/x',
            "diff --git a/src/x",
            'diff --git "a/src/x"b/src/x',
            'diff --git "a/src/\\q" "b/src/x"',
            'diff --git "a/src/x" "b/src/x" trailing',
            'rename to "src/unterminated',
        ):
            with self.subTest(header=header):
                diff = f"{header}\nold mode 100644\nnew mode 100755\n"
                self.assertEqual(qwen.check_patch_caps(diff), "terminal-patch-too-broad")

    def test_binary_patches_are_too_broad_even_on_allowed_paths(self) -> None:
        git_binary = (
            "diff --git a/src/blob.bin b/src/blob.bin\n"
            "new file mode 100644\n"
            "index 0000000..6b0c3d4\n"
            "GIT binary patch\n"
            "literal 3\n"
            "KcmZ?wdnf=\n"
            "\n"
            "literal 0\n"
            "HcmV?d00001\n"
        )
        summary = "diff --git a/src/blob.bin b/src/blob.bin\nindex 1..2 100644\nBinary files a/src/blob.bin and b/src/blob.bin differ\n"
        for name, diff in (("git-binary-patch", git_binary), ("binary-files-differ", summary)):
            with self.subTest(name=name):
                self.assertEqual(qwen.check_patch_caps(diff), "terminal-patch-too-broad")

    def test_any_first_component_is_stripped_like_git_apply_p1(self) -> None:
        """git apply strips the first component whatever it is: +++ y/bin/qwen writes bin/qwen."""
        diff = "--- x/bin/qwen\n+++ y/bin/qwen\n@@ -1 +1 @@\n-a\n+b\n"

        self.assertEqual(qwen.diff_stats(diff)[0], ["bin/qwen"])
        self.assertEqual(qwen.check_patch_caps(diff), "terminal-patch-too-broad")

    def test_removed_line_that_reads_like_a_header_is_a_change(self) -> None:
        """Removing the SQL comment "-- note" shows as "--- note" inside the hunk."""
        diff = "--- a/src/q.sql\n+++ b/src/q.sql\n@@ -1,2 +1 @@\n--- note\n keep\n"

        self.assertEqual(qwen.diff_stats(diff), (["src/q.sql"], 1))
        self.assertIsNone(qwen.check_patch_caps(diff))


class QwenPatchCapsThroughHandlerTests(QwenHandlerCase):
    """The caps check catches what git apply --check accepts."""

    def _init_repo_with(self, rel: str, content: str) -> Path:
        _git(self.repo_root, "init", "-q")
        target = self.repo_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        _git(self.repo_root, "add", rel)
        return target

    def test_edit_to_a_readable_but_denied_target_applies_but_is_too_broad(self) -> None:
        """bin/ is an allowed INPUT directory but a denied patch target: the
        built diff passes the real git apply --check, and the caps reject it."""
        self._init_repo_with("bin/tool", "echo old\n")
        self.generate_response = model_says(edit_block("bin/tool", "echo old", "echo new"))

        with mock.patch("worker.qwen._git_apply_check", wraps=REAL_GIT_APPLY_CHECK) as check:
            ok, out = self.run_handler({"files": ["bin/tool"]})

        check.assert_called_once()
        self.assertTrue(REAL_GIT_APPLY_CHECK(check.call_args.args[0], self.repo_root), "built diff must apply")
        self.assertEqual((ok, out), (False, "terminal-patch-too-broad"))
        self.assertEqual(self.patch_files(), [])

    def test_edit_naming_a_non_input_path_is_refused_before_any_diff(self) -> None:
        """A case variant, an escape, or another file: the model can only edit
        the files it was given, so none of these ever reaches git apply."""
        for target in ("Bin/qwen", "../outside.py", "./configs/x.plist", "SRC/example/greet.py", "/etc/passwd"):
            with self.subTest(target=target), mock.patch("worker.qwen._git_apply_check") as check:
                self.generate_response = model_says(edit_block(target, "def greet(name):", "x"))
                self.assertEqual(self.run_handler(), (False, "terminal-edit-outside-inputs"))
                check.assert_not_called()
        self.assertEqual(self.patch_files(), [])

    def test_edit_truncated_at_num_predict_is_malformed(self) -> None:
        """done_reason 'length': generation stopped inside the REPLACE body."""
        truncated = GREET_EDIT.split(">>>>>>> REPLACE")[0]
        self.generate_response = {**model_says(truncated), "done_reason": "length"}

        ok, out = self.run_handler()

        self.assertEqual((ok, out), (False, "terminal-edit-malformed"))


class QwenExplainModeTests(QwenHandlerCase):
    def test_explain_mode_does_not_call_model_or_take_the_lock(self) -> None:
        with mock.patch("worker.qwen._acquire_model_lock") as acquire:
            ok, _ = self.run_handler({"explain": True})

        self.assertTrue(ok)
        self.assertEqual(self.generate_requests(), [])
        acquire.assert_not_called()
        self.assertEqual(self.patch_files(), [])

    def test_explain_mode_reports_resolved_files_and_prompt_size(self) -> None:
        instruction = "return the greeting"

        ok, report = self.run_handler({"explain": True, "instruction": instruction})

        self.assertTrue(ok)
        report = self.as_dict(report)
        greet = str((self.repo_root / GREET_PATH).resolve())
        size = (self.repo_root / GREET_PATH).stat().st_size
        self.assertEqual(report["resolved_files"], [greet])
        self.assertEqual(report["per_file_bytes"], {greet: size})
        self.assertEqual(report["total_prompt_chars"], len(instruction) + size)
        self.assertEqual(report["estimated_prompt_tokens"], (len(instruction) + size) // 4)
        self.assertEqual(report["model"], MODEL)

    def test_explain_mode_reports_each_guards_real_verdict(self) -> None:
        all_pass = {
            "confinement": "pass",
            "memory": "pass",
            "disk": "pass",
            "admission": "pass",
            "prompt_budget": "pass",
        }
        cases = (
            (None, all_pass),
            (("_available_memory_bytes", 1024), {**all_pass, "memory": "deferred-low-memory"}),
            (("_free_disk_bytes", 1024 * 1024), {**all_pass, "disk": "deferred-low-disk"}),
            (("_lane_depth", qwen.THRESHOLDS.max_lane_depth), {**all_pass, "admission": "terminal-lane-over-capacity"}),
        )
        for override, expected in cases:
            with self.subTest(override=override):
                patcher = (
                    mock.patch(f"worker.qwen.{override[0]}", return_value=override[1])
                    if override
                    else contextlib.nullcontext()
                )
                with patcher:
                    ok, report = self.run_handler({"explain": True})
                self.assertTrue(ok)
                report = self.as_dict(report)
                self.assertEqual(report["guard_results"], expected)
        self.assertFalse(self.deferral_file().exists(), "explain mode must not record deferrals")

    def test_explain_mode_reports_the_real_prompt_budget_verdict(self) -> None:
        """The budget check runs on the assembled prompt, as a real run would."""
        big = self.repo_root / "src" / "example" / "big.py"
        big.write_text("x" * (qwen.THRESHOLDS.max_file_bytes - 1000), encoding="utf-8")
        cases: tuple[tuple[dict[str, object], str], ...] = (
            ({}, "pass"),
            ({"max_tokens": qwen.THRESHOLDS.num_ctx - 1}, "terminal-prompt-too-large"),
            ({"files": ["src/example/big.py"]}, "terminal-prompt-too-large"),
        )
        for extra, expected in cases:
            with self.subTest(extra=extra):
                ok, report = self.run_handler({"explain": True, **extra})
                self.assertTrue(ok)
                report = self.as_dict(report)
                guard_results = self.as_dict(report["guard_results"])
                self.assertEqual(guard_results["prompt_budget"], expected)
                self.assertIsInstance(report["assembled_prompt_tokens"], int)
        self.assertEqual(self.generate_requests(), [])

    def test_explain_mode_still_rejects_disallowed_path(self) -> None:
        """The assertion that stops explain mode from becoming a guard bypass."""
        ok, out = self.run_handler({"files": ["../../etc/passwd"], "explain": True})

        self.assertEqual((ok, out), (False, "terminal-path-not-allowed: ../../etc/passwd"))
        self.assertEqual(self.generate_requests(), [])


class QwenSeamTests(unittest.TestCase):
    """Direct tests of the side-effect seams every handler test mocks."""

    def test_pid_is_worker_matches_worker_command_lines(self) -> None:
        def ps(stdout: str, rc: int = 0) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(["ps"], rc, stdout=stdout, stderr="")

        cases = (
            (ps("/usr/bin/python3 -m worker daemon\n"), True),
            (ps("/bin/zsh\n"), False),
            (ps("", rc=1), None),
        )
        for completed, expected in cases:
            with self.subTest(stdout=completed.stdout), mock.patch("subprocess.run", return_value=completed) as run:
                self.assertIs(qwen._pid_is_worker(123), expected)
                self.assertEqual(run.call_args.args[0], ["ps", "-p", "123", "-o", "command="])

    def test_pid_is_worker_is_unknown_when_ps_cannot_run(self) -> None:
        """An unreadable process table is "unknown", never "confirmed not a worker"."""
        for error in (FileNotFoundError("ps"), subprocess.TimeoutExpired(["ps"], 5)):
            with self.subTest(error=type(error).__name__), mock.patch("subprocess.run", side_effect=error):
                self.assertIsNone(qwen._pid_is_worker(123))

    def test_free_disk_bytes_is_none_on_error_and_int_for_a_real_file(self) -> None:
        missing = Path(os.sep) / "definitely" / "not" / "here"
        with mock.patch("shutil.disk_usage", side_effect=OSError("gone")):
            self.assertIsNone(qwen._free_disk_bytes(missing))
        self.assertIsInstance(qwen._free_disk_bytes(Path(__file__)), int)


class QwenSystemPromptBudgetTests(QwenHandlerCase):
    """options.system is sent to Ollama as its own field but shares the
    context window, so the budget guard must count it."""

    def _oversized_system(self) -> str:
        budget = qwen.THRESHOLDS.num_ctx - qwen.DEFAULT_MAX_TOKENS
        return "s" * (4 * budget + 4)

    def test_small_prompt_with_oversized_system_is_prompt_too_large(self) -> None:
        ok, out = self.run_handler({"system": self._oversized_system()})

        self.assertEqual((ok, out), (False, "terminal-prompt-too-large"))
        self.assertEqual(self.generate_requests(), [])

    def test_explain_reports_the_system_text_in_the_budget(self) -> None:
        system = self._oversized_system()

        ok, report = self.run_handler({"explain": True, "system": system})

        self.assertTrue(ok)
        report = self.as_dict(report)
        self.assertEqual(self.as_dict(report["guard_results"])["prompt_budget"], "terminal-prompt-too-large")
        size = (self.repo_root / GREET_PATH).stat().st_size
        self.assertEqual(report["total_prompt_chars"], len("return the greeting") + size + len(system))
        tokens = report["assembled_prompt_tokens"]
        self.assertIsInstance(tokens, int)
        self.assertGreater(int(str(tokens)), len(system) // 4)

    def test_small_system_still_fits(self) -> None:
        ok, _ = self.run_handler({"system": "be terse"})

        self.assertTrue(ok)


class QwenOptionValidationTests(QwenHandlerCase):
    """Every optional payload key is type- and range-checked up front: an
    invalid one is terminal-invalid-payload before any file is touched and
    before the prompt-budget guard."""

    def _assert_invalid(self, key: str, raw: object, message: str) -> None:
        with (
            self.subTest(key=key, raw=raw),
            mock.patch("worker.qwen._resolve_real_path", side_effect=AssertionError("touched a file")),
        ):
            self.assertEqual(self.run_handler({key: raw}), (False, f"terminal-invalid-payload: {message}"))

    def test_invalid_max_tokens_is_rejected(self) -> None:
        upper = qwen.THRESHOLDS.num_ctx - 1
        for raw in (-1, 0, True, False, 4096.0, "4096", upper + 1, 10**9):
            self._assert_invalid("max_tokens", raw, f"max_tokens must be an int in [1, {upper}]")
        self.assertEqual(self.generate_requests(), [])

    def test_invalid_temperature_is_rejected(self) -> None:
        for raw in (float("nan"), float("inf"), float("-inf"), -0.1, 2.5, True, "0.2"):
            self._assert_invalid("temperature", raw, "temperature must be a finite number in [0, 2.0]")
        self.assertEqual(self.generate_requests(), [])

    def test_invalid_timeout_is_rejected(self) -> None:
        for raw in (0, -5, "30", True, float("nan"), float("inf")):
            self._assert_invalid("timeout", raw, "timeout must be a finite number > 0")
        self.assertEqual(self.generate_requests(), [])

    def test_non_string_and_non_bool_options_are_rejected(self) -> None:
        for key, raw, message in (
            ("system", 123, "system must be a str"),
            ("model", ["qwen"], "model must be a str"),
            ("explain", "false", "explain must be a bool"),
            ("explain", 1, "explain must be a bool"),
        ):
            self._assert_invalid(key, raw, message)
        self.assertEqual(self.generate_requests(), [])

    def test_explain_mode_rejects_an_invalid_option_too(self) -> None:
        self.assertEqual(
            self.run_handler({"explain": True, "max_tokens": -1}),
            (False, f"terminal-invalid-payload: max_tokens must be an int in [1, {qwen.THRESHOLDS.num_ctx - 1}]"),
        )

    def test_boundary_values_are_accepted_and_sent(self) -> None:
        for temperature in (0, 1, 2.0):
            with self.subTest(temperature=temperature):
                self.requests.clear()
                ok, _ = self.run_handler({"temperature": temperature, "max_tokens": 1})
                self.assertTrue(ok)
                [(_, body, _)] = self.generate_requests()
                options = require(body)["options"]
                self.assertEqual((options["temperature"], options["num_predict"]), (temperature, 1))


if __name__ == "__main__":
    unittest.main()
