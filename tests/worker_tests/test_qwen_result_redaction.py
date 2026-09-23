"""contract.redaction for the success path: payload strings never reach disk or logs.

Failure strings and telemetry were already masked; the success result, the
explain-mode report and the model-pinning log lines echoed payload strings
verbatim. Each payload-derived field gets its own credential-shaped value, and
every assertion searches the whole serialized result and every captured log
line, so a newly added field that echoes the payload is caught too.
"""

from __future__ import annotations

import json
import logging
import unittest
from pathlib import Path
import unittest.mock as mock

from tests.worker_tests.qwen_fixtures import GREET_PATH, RUNNING_DIGEST, QwenHandlerCase

_MODEL_SECRET = "mdl0SECRET0aaaaaaaaaaaaaaaaaaaaaaaaaaaa"  # nosec B105 - fixture value, not a credential
_SYSTEM_SECRET = "sys0SECRET0bbbbbbbbbbbbbbbbbbbbbbbbbbbb"  # nosec B105 - fixture value, not a credential
_INSTRUCTION_SECRET = "ins0SECRET0cccccccccccccccccccccccccccc"  # nosec B105 - fixture value, not a credential
_PATH_SECRET = "pth0SECRET0dddddddddddddddddddddddddddd"  # nosec B105 - fixture value, not a credential
_SECRETS = (_MODEL_SECRET, _SYSTEM_SECRET, _INSTRUCTION_SECRET, _PATH_SECRET)

_SECRET_MODEL = f"qwen token={_MODEL_SECRET}"
_SECRET_FILE = f"src/example/password={_PATH_SECRET}.py"


class QwenSuccessPathRedactionTests(QwenHandlerCase):
    def setUp(self) -> None:
        super().setUp()
        secret_file = self.repo_root / _SECRET_FILE
        secret_file.write_text("x = 1\n", encoding="utf-8")

    def _payload(self, **extra: object) -> dict[str, object]:
        return {
            "files": [GREET_PATH, _SECRET_FILE],
            "instruction": f"return the greeting api_key={_INSTRUCTION_SECRET}",
            "model": _SECRET_MODEL,
            "system": f"be terse secret={_SYSTEM_SECRET}",
            **extra,
        }

    def _assert_no_secret(self, result: object, log_lines: list[str]) -> None:
        serialized = json.dumps(result, default=str)
        logs = "\n".join(log_lines)
        for secret in _SECRETS:
            self.assertNotIn(secret, serialized)
            self.assertNotIn(secret, logs)

    def _run_logged(self, **extra: object) -> tuple[bool, dict[str, object], list[str]]:
        with self.assertLogs("worker.qwen", level=logging.DEBUG) as logs:
            ok, out = self.run_handler(self._payload(**extra))
        return ok, self.as_dict(out), logs.output

    def _arrange_pin_state(self, state: str) -> None:
        """Set up one model-pin state; each logs the model on a different line."""
        self.tags_error = None
        self.digest_record.unlink(missing_ok=True)
        if state == "unverified":
            self.tags_error = OSError("tags down")
        elif state == "mismatch":
            self.record_digest("0" * 64, model=_SECRET_MODEL)
            self.tags_response = {"models": [{"name": _SECRET_MODEL, "digest": RUNNING_DIGEST}]}
        elif state == "unreadable record":
            self.digest_record.parent.mkdir(parents=True, exist_ok=True)
            self.digest_record.write_text("{not json", encoding="utf-8")

    def test_success_result_and_logs_mask_every_payload_string(self) -> None:
        for state in ("unpinned", "unverified", "mismatch", "unreadable record"):
            with self.subTest(state):
                self._arrange_pin_state(state)
                ok, result, log_lines = self._run_logged()

                self.assertTrue(ok, result)
                self.assertIn("REDACTED", str(result["model"]))
                self.assertTrue(any("REDACTED" in line for line in log_lines), log_lines)
                self._assert_no_secret(result, log_lines)

    def test_default_model_tag_is_not_altered(self) -> None:
        ok, out = self.run_handler()

        self.assertTrue(ok)
        self.assertEqual(self.as_dict(out)["model"], "qwen2.5-coder:14b")

    def test_patch_path_is_left_intact(self) -> None:
        ok, result, _ = self._run_logged()

        self.assertTrue(ok)
        self.assertTrue(Path(str(result["patch_path"])).is_file())

    def test_explain_report_and_logs_mask_every_payload_string(self) -> None:
        # An unreadable disk source makes the explain run log, so the log
        # side of the check is exercised rather than vacuous.
        self._start(mock.patch("worker.qwen._free_disk_bytes", return_value=None))

        ok, report, log_lines = self._run_logged(explain=True)

        self.assertTrue(ok)
        self._assert_no_secret(report, log_lines)
        self.assertIn("REDACTED", str(report["model"]))
        self.assertIn("REDACTED", json.dumps(report["options"]))
        resolved = report["resolved_files"]
        if not isinstance(resolved, list):
            self.fail(f"resolved_files is not a list: {resolved!r}")
        self.assertEqual(len(resolved), 2)
        self.assertTrue(any("REDACTED" in str(p) for p in resolved))
        per_file = self.as_dict(report["per_file_bytes"])
        self.assertEqual(len(per_file), 2)
        self.assertEqual(self.as_dict(report["guard_results"])["disk"], "pass")


if __name__ == "__main__":
    unittest.main()
