"""Shared hermetic fixture for the qwen_patch handler tests.

Every handler test inherits QwenHandlerCase, which makes three promises the
per-test mock lists used to leave to chance:

* No network egress. urllib.request.urlopen is replaced by a router that
  serves /api/generate and /api/tags from per-test fixtures and records
  any other URL, and the test fails in cleanup if one was requested.
  Errors are raised from urlopen itself, so they travel the real
  _ollama_request -> _call_ollama_generate translation path.
* No telemetry egress. worker.qwen_telemetry._post is a recording stub,
  and worker.qwen.export_job_span wraps the real function so span
  attributes can be asserted and the real OTLP document still gets built.
* No writes outside the test's temp dir. The lock, deferral, patch and
  digest-record paths all point into it.

The default model response is the real Ollama output captured in the
workflow survey (survey.baseline_generation_post_install.raw_response_excerpt):
a ```diff fence, ---/+++ headers with a/ b/ prefixes, no ``diff --git`` line.
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
from unittest import mock

from tests.fixtures import TempDirMixin
from worker import qwen, qwen_telemetry

MODEL = "qwen2.5-coder:14b"
RUNNING_DIGEST = "9ec8897f747e246e970bc5cfdda85d22f1123dc2e3d34978a010a75968716849"
GIB = 1024**3

GREET_PATH = "src/example/greet.py"
GREET_ORIGINAL = 'def greet(name):\n    print("hello " + name)\n    return None\n'
REAL_DIFF = (
    "--- a/src/example/greet.py\n"
    "+++ b/src/example/greet.py\n"
    "@@ -1,3 +1,3 @@\n"
    " def greet(name):\n"
    '-    print("hello " + name)\n'
    '+    return f"hello {name}"\n'
    "     return None"
)
REAL_RESPONSE_TEXT = f"```diff\n{REAL_DIFF}\n```"
REAL_RESPONSE: dict[str, object] = {
    "model": MODEL,
    "response": REAL_RESPONSE_TEXT,
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


_T = TypeVar("_T")


def require(value: _T | None) -> _T:
    """Return value, failing the test if it is None."""
    if value is None:
        raise AssertionError("expected a value, got None")
    return value


def fenced(diff: str) -> dict[str, object]:
    """A 200 /api/generate body whose response is diff inside a ```diff fence."""
    return {**REAL_RESPONSE, "response": f"```diff\n{diff}\n```"}


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
        self.deferral_dir = tmp / "deferrals"
        self.lock_path = tmp / "state" / "model.lock"
        self.digest_record = tmp / "state" / "model_digest.json"

        self.generate_response: dict[str, object] = dict(REAL_RESPONSE)
        self.generate_raw: bytes | None = None
        self.generate_error: BaseException | None = None
        self.tags_response: dict[str, object] = {"models": [{"name": MODEL, "digest": RUNNING_DIGEST}]}
        self.tags_error: BaseException | None = None
        self.requests: list[tuple[str, dict[str, Any] | None, float | None]] = []
        self.unexpected_urls: list[str] = []

        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for var in ("QWEN_OLLAMA_HOST", qwen_telemetry.OTLP_ENDPOINT_ENV):
            os.environ.pop(var, None)

        self.post = self._start(mock.patch("worker.qwen_telemetry._post"))
        self.export = self._start(mock.patch("worker.qwen.export_job_span", wraps=REAL_EXPORT_JOB_SPAN))
        self.urlopen = self._start(mock.patch("urllib.request.urlopen", side_effect=self._route))
        for name, value in (
            ("_repo_root", self.repo_root),
            ("_git_apply_check", True),
            ("_available_memory_bytes", 64 * GIB),
            ("_free_disk_bytes", 64 * GIB),
            ("_lane_depth", 0),
            ("_lock_path", self.lock_path),
            ("_patch_dir", self.patch_dir),
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

    def _start(self, patcher: Any) -> Any:
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started

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
        return qwen.handle_qwen_patch(self.job(payload, **overrides))

    def as_dict(self, value: object) -> dict[str, object]:
        """Assert value is a dict and return it typed as one."""
        self.assertIsInstance(value, dict)
        return cast(dict[str, object], value)

    def generate_requests(self) -> list[tuple[str, dict[str, Any] | None, float | None]]:
        return [r for r in self.requests if r[0].endswith("/api/generate")]

    def span_attrs(self) -> list[dict[str, object]]:
        return [dict(c.args[0]) for c in self.export.call_args_list]

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
