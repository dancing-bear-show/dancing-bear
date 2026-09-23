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
import os
import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType
import unittest.mock as mock

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

    def test_job_type_is_registered_to_the_qwen_handler(self) -> None:
        from worker import handlers, qwen

        bq = _load_module()

        self.assertIs(handlers.REGISTRY[bq.JOB_TYPE], qwen.handle_qwen_patch)
        self.assertEqual(bq.JOB_TYPE, qwen.JOB_TYPE)


if __name__ == "__main__":
    unittest.main()
