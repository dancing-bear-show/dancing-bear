"""Shared hermetic fixture for the qwen_patch handler tests.

Every handler test inherits QwenHandlerCase, which makes three promises the
per-test mock lists used to leave to chance:

* No network egress. urllib.request.urlopen is replaced by a router that
  serves /api/generate, /api/tags and /api/ps from per-test fixtures and records
  any other URL, and the test fails in cleanup if one was requested.
  Errors are raised from urlopen itself, so they travel the real
  _ollama_request -> _call_ollama_generate translation path.
* No telemetry egress. worker.qwen_telemetry._post is a recording stub,
  and worker.qwen.export_job_span wraps the real function so span
  attributes can be asserted and the real OTLP document still gets built.
  The handler exports on a background thread; run_handler waits for it
  (qwen_telemetry.wait_for_exports), so telemetry assertions made after
  run_handler are deterministic, and cleanup waits again before any patch
  is undone.
* No writes outside the test's temp dir. The lock, deferral, patch,
  model-response and digest-record paths all point into it.

The default model response is one SEARCH/REPLACE edit block for GREET_PATH
inside a ``` fence; the handler turns it into GREET_DIFF.
"""

from __future__ import annotations

import json
import logging
import os
import unittest
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any, TypeVar, cast
import unittest.mock as mock

from tests.fixtures import TempDirMixin
from worker import qwen, qwen_telemetry

MODEL = "qwen2.5-coder:14b"
RUNNING_DIGEST = "9ec8897f747e246e970bc5cfdda85d22f1123dc2e3d34978a010a75968716849"
GIB = 1024**3

GREET_PATH = "src/example/greet.py"
GREET_ORIGINAL = 'def greet(name):\n    print("hello " + name)\n    return None\n'

def edit_block(path: str, search: str, replace: str) -> str:
    """One SEARCH/REPLACE block; search and replace are newline-joined lines."""
    return f"FILE: {path}\n<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE\n"


GREET_EDIT = edit_block(GREET_PATH, '    print("hello " + name)', '    return f"hello {name}"')
# The diff the handler must build from GREET_EDIT.
GREET_DIFF = (
    "--- a/src/example/greet.py\n"
    "+++ b/src/example/greet.py\n"
    "@@ -1,3 +1,3 @@\n"
    " def greet(name):\n"
    '-    print("hello " + name)\n'
    '+    return f"hello {name}"\n'
    "     return None\n"
)
REAL_RESPONSE: dict[str, object] = {
    "model": MODEL,
    "response": f"```\n{GREET_EDIT}```",
    "done": True,
    "prompt_eval_count": 84,
    "eval_count": 57,
}

RESULT_SCHEMA_KEYS = frozenset(
    {
        "patch_path",
        "patch_valid",
        "files_touched",
        "lines_changed",
        "model",
        "model_digest",
        "digest_matches_recorded",
        "prompt_tokens",
        "completion_tokens",
        "duration_ms",
        "deferral_reasons",
    }
)

# The unpatched implementations, captured before any fixture replaces them,
# for tests that need the real seam wrapped in a spy.
REAL_GIT_APPLY_CHECK = qwen._git_apply_check
REAL_LANE_DEPTH = qwen._lane_depth
REAL_EXPORT_JOB_SPAN = qwen_telemetry.export_job_span
REAL_EXPORT_JOB_METRICS = qwen_telemetry.export_job_metrics


_T = TypeVar("_T")


def require(value: _T | None) -> _T:
    """Return value, failing the test if it is None."""
    if value is None:
        raise AssertionError("expected a value, got None")
    return value


def model_says(text: str) -> dict[str, object]:
    """A 200 /api/generate body whose response text is text."""
    return {**REAL_RESPONSE, "response": text}


class FakeResponse:
    """The slice of http.client.HTTPResponse that the qwen transports use."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://localhost:11434/api/generate", code, "error", Message(), None)


class QwenHandlerCase(TempDirMixin, unittest.TestCase):
    """Hermetic base for handler-level tests. See the module docstring."""

    def setUp(self) -> None:
        super().setUp()
        tmp = Path(self.tmpdir)
        self.repo_root = tmp / "repo"
        greet = self.repo_root / GREET_PATH
        greet.parent.mkdir(parents=True)
        greet.write_text(GREET_ORIGINAL, encoding="utf-8")
        self.patch_dir = tmp / "patches"
        self.response_dir = tmp / "responses"
        self.deferral_dir = tmp / "deferrals"
        self.lock_path = tmp / "state" / "model.lock"
        self.digest_record = tmp / "state" / "model_digest.json"

        self.generate_response: dict[str, object] = dict(REAL_RESPONSE)
        self.generate_raw: bytes | None = None
        self.generate_error: BaseException | None = None
        self.tags_response: dict[str, object] = {"models": [{"name": MODEL, "digest": RUNNING_DIGEST}]}
        self.tags_error: BaseException | None = None
        # /api/ps: no model loaded unless a test says otherwise.
        self.ps_response: dict[str, object] = {"models": []}
        self.ps_error: BaseException | None = None
        self.ps_raw: bytes | None = None
        self.requests: list[tuple[str, dict[str, Any] | None, float | None]] = []
        self.unexpected_urls: list[str] = []

        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        otel_vars = (
            qwen_telemetry.OTLP_ENDPOINT_ENV,
            qwen_telemetry.OTLP_PROTOCOL_ENV,
            qwen_telemetry.TRACES_ENDPOINT_ENV,
            qwen_telemetry.TRACES_PROTOCOL_ENV,
            qwen_telemetry.METRICS_ENDPOINT_ENV,
            qwen_telemetry.METRICS_PROTOCOL_ENV,
        )
        for var in ("QWEN_OLLAMA_HOST", *otel_vars):
            os.environ.pop(var, None)

        self.post = self._start(mock.patch("worker.qwen_telemetry._post"))
        self.export = self._start(mock.patch("worker.qwen.export_job_span", wraps=REAL_EXPORT_JOB_SPAN))
        self.export_metrics = self._start(
            mock.patch("worker.qwen.export_job_metrics", wraps=REAL_EXPORT_JOB_METRICS)
        )
        self.urlopen = self._start(mock.patch("urllib.request.urlopen", side_effect=self._route))
        for name, value in (
            ("_repo_root", self.repo_root),
            ("_git_apply_check", True),
            ("_available_memory_bytes", 64 * GIB),
            ("_free_disk_bytes", 64 * GIB),
            ("_lane_depth", 0),
            ("_lock_path", self.lock_path),
            ("_patch_dir", self.patch_dir),
            ("_response_dir", self.response_dir),
            ("_deferral_dir", self.deferral_dir),
            ("_recorded_digest_path", self.digest_record),
        ):
            self._start(mock.patch(f"worker.qwen.{name}", return_value=value))

        # The handler logs a warning per unpinned job; keep it off stderr.
        qwen_log = logging.getLogger("worker.qwen")
        null_handler = logging.NullHandler()
        qwen_log.addHandler(null_handler)
        self.addCleanup(qwen_log.removeHandler, null_handler)
        self.addCleanup(self._assert_no_unexpected_egress)
        # Registered last so it runs first: no export thread may outlive the
        # patches above, or it would post through the real _post.
        self.addCleanup(self._wait_for_exports)

    def _start(self, patcher: Any) -> Any:
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started

    def _wait_for_exports(self) -> None:
        self.assertTrue(qwen_telemetry.wait_for_exports(timeout=10), "a telemetry export thread did not finish")

    def _assert_no_unexpected_egress(self) -> None:
        self.assertEqual(self.unexpected_urls, [], "a test reached an unmocked network endpoint")

    def _route(self, req: urllib.request.Request, timeout: float | None = None) -> FakeResponse:
        url = req.full_url
        raw_body = req.data if isinstance(req.data, bytes) else None
        self.requests.append((url, json.loads(raw_body) if raw_body else None, timeout))
        if url.endswith("/api/generate"):
            if self.generate_error is not None:
                raise self.generate_error
            if self.generate_raw is not None:
                return FakeResponse(self.generate_raw)
            return FakeResponse(json.dumps(self.generate_response).encode("utf-8"))
        if url.endswith("/api/tags"):
            if self.tags_error is not None:
                raise self.tags_error
            return FakeResponse(json.dumps(self.tags_response).encode("utf-8"))
        if url.endswith("/api/ps"):
            if self.ps_error is not None:
                raise self.ps_error
            if self.ps_raw is not None:
                return FakeResponse(self.ps_raw)
            return FakeResponse(json.dumps(self.ps_response).encode("utf-8"))
        self.unexpected_urls.append(url)
        raise AssertionError(f"unexpected network egress to {url}")

    # -- helpers -----------------------------------------------------------

    def job(self, payload: dict[str, object] | None = None, **overrides: object) -> dict[str, object]:
        """A full job record as JobSafeProcessor hands it to the handler."""
        base_payload: dict[str, object] = {"files": [GREET_PATH], "instruction": "return the greeting"}
        base_payload.update(payload or {})
        record: dict[str, object] = {
            "id": "qwen-test-job",
            "type": "qwen_patch",
            "attempts": 0,
            "max_attempts": 3,
            "payload": base_payload,
        }
        record.update(overrides)
        return record

    def run_handler(self, payload: dict[str, object] | None = None, **overrides: object) -> tuple[bool, object]:
        result = qwen.handle_qwen_patch(self.job(payload, **overrides))
        self._wait_for_exports()
        return result

    def as_dict(self, value: object) -> dict[str, object]:
        """Assert value is a dict and return it typed as one."""
        self.assertIsInstance(value, dict)
        return cast(dict[str, object], value)

    def generate_requests(self) -> list[tuple[str, dict[str, Any] | None, float | None]]:
        return [r for r in self.requests if r[0].endswith("/api/generate")]

    def span_attrs(self) -> list[dict[str, object]]:
        return [dict(c.args[0]) for c in self.export.call_args_list]

    def metrics_calls(self) -> list[tuple[dict[str, object], float, int | None, int | None]]:
        """(attrs, duration_ms, prompt_tokens, completion_tokens) per export_job_metrics call."""
        return [
            (dict(c.args[0]), c.args[1], c.args[2], c.args[3]) for c in self.export_metrics.call_args_list
        ]

    def otlp_posts(self, *, path_suffix: str) -> list[Any]:
        """self.post.call_args_list entries whose URL ends with path_suffix

        (e.g. "/v1/traces" or "/v1/metrics"). Both span and metrics export
        share the same _post seam, so a test asserting on one signal's post
        must filter by URL rather than reading call_args/call_args_list
        directly.
        """
        return [c for c in self.post.call_args_list if c.args[0].endswith(path_suffix)]

    def record_digest(self, digest: str, model: str = MODEL) -> None:
        self.digest_record.parent.mkdir(parents=True, exist_ok=True)
        self.digest_record.write_text(json.dumps({model: digest}), encoding="utf-8")

    def deferral_file(self, job_id: str = "qwen-test-job") -> Path:
        return self.deferral_dir / f"{job_id}.json"

    def seed_deferrals(self, count: int, reason: str, job_id: str = "qwen-test-job") -> None:
        for _ in range(count):
            qwen._record_deferral(job_id, reason)

    def patch_files(self) -> list[Path]:
        return sorted(self.patch_dir.glob("*.patch")) if self.patch_dir.exists() else []

    def response_files(self) -> list[Path]:
        return sorted(self.response_dir.glob("*.txt")) if self.response_dir.exists() else []
