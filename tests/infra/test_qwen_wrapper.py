"""Tests for bin/qwen, the standalone entry point (contract.json:entry_point).

bin/ is not a package, so the module is loaded by path, following the
pattern in tests/infra/test_mypy_ratchet.py. Loading it runs its top level,
which repairs sys.path and PYTHONPATH and may os.execv into the repo venv;
_load_module blocks the exec and restores both afterwards so the rest of the
test process is unaffected.

--apply must never run anything: it PRINTS the git apply command text. That
is checked at every process-spawning boundary Python offers, not just
subprocess.run/Popen.
"""

from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shlex
import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType
import unittest.mock as mock

from tests.worker_tests.qwen_fixtures import MODEL as PIN_MODEL
from tests.worker_tests.qwen_fixtures import RUNNING_DIGEST, PinRecordCase

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "bin" / "qwen"

# Every stdlib route to a new process or program image.
_SPAWN_ROUTES = (
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "os.system",
    "os.popen",
    "os.execv",
    "os.execve",
    "os.execvp",
    "os.execvpe",
    "os.execl",
    "os.execlp",
    "os.spawnv",
    "os.spawnve",
    "os.spawnvp",
    "os.posix_spawn",
    "os.posix_spawnp",
    "os.fork",
    "pty.spawn",
)


@contextlib.contextmanager
def _no_process_spawn() -> Iterator[None]:
    with contextlib.ExitStack() as stack:
        for target in _SPAWN_ROUTES:
            stack.enter_context(mock.patch(target, side_effect=AssertionError(f"--apply spawned via {target}")))
        yield


def _load_module() -> ModuleType:
    # bin/qwen is extensionless, so spec_from_file_location cannot infer a
    # loader from the suffix. Build the loader explicitly.
    loader = importlib.machinery.SourceFileLoader("bin_qwen", str(SCRIPT))
    spec = importlib.util.spec_from_loader("bin_qwen", loader)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    saved_path = list(sys.path)
    try:
        with (
            mock.patch.dict(os.environ),
            mock.patch("os.execv", side_effect=AssertionError("bin/qwen tried to re-exec the test runner")),
        ):
            spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved_path
    return module


class QwenWrapperBuildPayloadTests(unittest.TestCase):
    def test_build_payload_from_files_and_instruction(self) -> None:
        bq = _load_module()

        payload = bq.build_payload(files=["src/worker/qwen.py"], instruction="add logging", explain=False)

        self.assertEqual(payload, {"files": ["src/worker/qwen.py"], "instruction": "add logging"})

    def test_build_payload_explain_flag_set(self) -> None:
        bq = _load_module()

        payload = bq.build_payload(files=["src/worker/qwen.py"], instruction="add logging", explain=True)

        self.assertIs(payload["explain"], True)

    def test_instruction_file_is_read_correctly(self) -> None:
        bq = _load_module()

        with tempfile.TemporaryDirectory() as td, mock.patch.object(bq, "enqueue") as mock_enqueue:
            instr_path = Path(td) / "instruction.txt"
            instr_path.write_text("do the thing\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                bq.main(["patch", "--files", "src/worker/qwen.py", "--instruction-file", str(instr_path)])

        (called_job,) = mock_enqueue.call_args.args
        self.assertEqual(called_job.payload["instruction"], "do the thing")


class QwenWrapperApplyCommandTests(unittest.TestCase):
    def test_apply_prints_git_apply_command_without_executing(self) -> None:
        """--apply prints the command and spawns nothing, by any route."""
        bq = _load_module()
        patch_path = Path("patches") / "some-job-id.patch"

        buf = io.StringIO()
        with (
            mock.patch.object(bq, "_patch_path_for_job", return_value=patch_path),
            _no_process_spawn(),
            redirect_stdout(buf),
        ):
            exit_code = bq.main(["--apply", "some-job-id"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(buf.getvalue(), f"git apply {patch_path}\n")

    def test_spawn_sentinel_has_teeth(self) -> None:
        with _no_process_spawn(), self.assertRaises(AssertionError):
            os.system("true")  # nosec B605 B607 - patched to raise; nothing runs

    def test_apply_command_points_at_the_qwen_patch_dir(self) -> None:
        bq = _load_module()

        with mock.patch.dict(os.environ, {"DANCING_BEAR_DATA_HOME": "/data-home"}):
            command = bq.apply_command("some-job-id")

        self.assertEqual(command, "git apply /data-home/qwen/patches/some-job-id.patch")

    def test_apply_command_quotes_a_data_home_with_spaces_and_metacharacters(self) -> None:
        """The printed line is pasted into a shell, so it must split back into
        exactly three words whatever the data home contains."""
        bq = _load_module()
        data_home = "/Application Support/x; rm -rf ~ $(id)"

        with mock.patch.dict(os.environ, {"DANCING_BEAR_DATA_HOME": data_home}):
            command = bq.apply_command("some-job-id")

        self.assertEqual(
            shlex.split(command),
            ["git", "apply", f"{data_home}/qwen/patches/some-job-id.patch"],
        )


class QwenWrapperMainTests(unittest.TestCase):
    def test_main_patch_enqueues_a_qwen_patch_job(self) -> None:
        bq = _load_module()

        with mock.patch.object(bq, "enqueue") as mock_enqueue, redirect_stdout(io.StringIO()):
            exit_code = bq.main(["patch", "--files", "src/worker/qwen.py", "--instruction", "add a test"])

        self.assertEqual(exit_code, 0)
        (job,), kwargs = mock_enqueue.call_args
        self.assertEqual(job.type, "qwen_patch")
        self.assertEqual(job.payload, {"files": ["src/worker/qwen.py"], "instruction": "add a test"})
        self.assertEqual(job.timeout_sec, 0, "a positive timeout_sec would arm the reaper against qwen jobs")
        self.assertEqual(kwargs, {"root": bq.QUEUE_ROOT})

    def test_main_show_returns_nonzero_for_unknown_job(self) -> None:
        bq = _load_module()

        with mock.patch.object(bq, "find_job_path_by_id", return_value=None), contextlib.redirect_stderr(io.StringIO()):
            exit_code = bq.main(["--show", "does-not-exist"])

        self.assertEqual(exit_code, 1)

    def test_apply_and_show_refuse_an_unsafe_job_id_before_building_a_path(self) -> None:
        bq = _load_module()

        for flag in ("--apply", "--show"):
            for job_id in ("../../etc/passwd", "..", "a/b", ".hidden"):
                with self.subTest(flag=flag, job_id=job_id):
                    out, err = io.StringIO(), io.StringIO()
                    with (
                        mock.patch.object(bq, "find_job_path_by_id") as find,
                        redirect_stdout(out),
                        contextlib.redirect_stderr(err),
                    ):
                        exit_code = bq.main([flag, job_id])
                    self.assertEqual(exit_code, 2)
                    self.assertEqual(out.getvalue(), "")
                    self.assertIn("invalid job id", err.getvalue())
                    find.assert_not_called()

    def test_apply_refuses_a_patch_path_that_is_a_symlink(self) -> None:
        """job-a.patch -> job-b.patch would make --apply print a command that
        applies another job's patch. It must refuse with a clear error."""
        bq = _load_module()

        with tempfile.TemporaryDirectory() as data_home:
            patches = Path(data_home) / "qwen" / "patches"
            patches.mkdir(parents=True)
            (patches / "job-b.patch").write_text("diff\n", encoding="utf-8")
            os.symlink("job-b.patch", patches / "job-a.patch")
            out, err = io.StringIO(), io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DANCING_BEAR_DATA_HOME": data_home}),
                redirect_stdout(out),
                contextlib.redirect_stderr(err),
            ):
                exit_code = bq.main(["--apply", "job-a"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("symlink", err.getvalue())

    def test_patch_path_builder_refuses_an_unsafe_job_id(self) -> None:
        from worker import qwen

        bq = _load_module()

        with self.assertRaises(qwen.QwenGuardError):
            bq._patch_path_for_job("../escape")

    def test_job_type_is_registered_to_the_qwen_handler(self) -> None:
        from worker import handlers, qwen

        bq = _load_module()

        self.assertIs(handlers.REGISTRY[bq.JOB_TYPE], qwen.handle_qwen_patch)
        self.assertEqual(bq.JOB_TYPE, qwen.JOB_TYPE)


class QwenWrapperPinModelTests(PinRecordCase):
    """`qwen pin-model` end to end through main(), against a temp state dir."""

    def run_main(self, *argv: str) -> tuple[int, str, str]:
        bq = _load_module()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), contextlib.redirect_stderr(err):
            code = bq.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_pin_model_writes_the_default_tag_and_reports_json(self) -> None:
        code, out, _ = self.run_main("pin-model")

        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(out),
            {
                "model": PIN_MODEL,
                "digest": RUNNING_DIGEST,
                "path": str(self.record_path),
                "written": True,
                "reason": "written",
                "readback_ok": True,
            },
        )
        self.assertEqual(self.read_record(), {PIN_MODEL: RUNNING_DIGEST})

    def test_default_model_is_the_handler_default(self) -> None:
        from worker import qwen

        self.assertEqual(PIN_MODEL, qwen.DEFAULT_MODEL_TAG)

    def test_pin_model_second_run_is_already_current(self) -> None:
        self.run_main("pin-model")

        code, out, _ = self.run_main("pin-model")

        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual((report["written"], report["reason"]), (False, "already-current"))

    def test_pin_model_honours_model_flag(self) -> None:
        self.tags_response = {"models": [{"name": "llama3:8b", "digest": "c" * 64}]}

        code, out, _ = self.run_main("pin-model", "--model", "llama3:8b")

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["model"], "llama3:8b")
        self.assertEqual(self.read_record(), {"llama3:8b": "c" * 64})

    def test_pin_model_digest_unavailable_exits_1_and_writes_nothing(self) -> None:
        self.tags_error = ConnectionError("refused")

        code, out, err = self.run_main("pin-model")

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("running digest unavailable", err)
        self.assertFalse(self.record_path.parent.exists())

    def test_pin_model_refuses_invalid_record_and_leaves_it(self) -> None:
        self.write_record("{broken")

        code, out, err = self.run_main("pin-model")

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("nothing written", err)
        self.assertEqual(self.record_path.read_text(encoding="utf-8"), "{broken")

    def test_pin_model_refuses_a_symlinked_record(self) -> None:
        target = Path(self.tmpdir) / "target.json"
        target.write_text("{}", encoding="utf-8")
        self.record_path.parent.mkdir(parents=True)
        os.symlink(target, self.record_path)

        code, _, _ = self.run_main("pin-model")

        self.assertEqual(code, 1)
        self.assertEqual(target.read_text(encoding="utf-8"), "{}")

    def test_pin_model_failed_readback_exits_1(self) -> None:
        from worker import qwen

        def write_wrong(path: object, record: dict[str, object]) -> None:
            self.write_record(json.dumps({PIN_MODEL: "d" * 64}))

        with mock.patch.object(qwen, "_write_pin_record", side_effect=write_wrong):
            code, out, _ = self.run_main("pin-model")

        self.assertEqual(code, 1)
        self.assertIs(json.loads(out)["readback_ok"], False)

    def test_check_reports_each_status_with_its_exit_code(self) -> None:
        cases: list[tuple[str, str | None, dict[str, object], int]] = [
            ("match", RUNNING_DIGEST, self.tags_response, 0),
            ("mismatch", "e" * 64, self.tags_response, 1),
            ("unpinned", None, self.tags_response, 1),
            ("unverified", RUNNING_DIGEST, {"models": []}, 1),
        ]
        for status, recorded, tags, want_code in cases:
            with self.subTest(status):
                if recorded is None:
                    self.record_path.unlink(missing_ok=True)
                else:
                    self.write_record(json.dumps({PIN_MODEL: recorded}))
                self.tags_response = tags
                before = self.record_path.read_bytes() if recorded else None

                code, out, _ = self.run_main("pin-model", "--check")

                self.assertEqual(code, want_code)
                report = json.loads(out)
                self.assertEqual(set(report), {"model", "path", "recorded", "running", "status"})
                self.assertEqual(report["status"], status)
                self.assertEqual(report["recorded"], recorded)
                self.assertEqual(report["path"], str(self.record_path))
                if before is None:
                    self.assertFalse(self.record_path.exists(), "--check must write nothing")
                else:
                    self.assertEqual(self.record_path.read_bytes(), before)

    def test_help_lists_pin_model(self) -> None:
        bq = _load_module()

        self.assertIn("pin-model", bq._build_parser().format_help())


if __name__ == "__main__":
    unittest.main()
