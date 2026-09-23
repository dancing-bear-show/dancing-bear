"""Tests for bin/qwen — the standalone entry point (contract.json:entry_point).

bin/ is not a package, so the module is loaded by path, following the
pattern in tests/infra/test_mypy_ratchet.py.

bin/qwen does not exist in this worktree yet (impl-handler owns it, running
in a parallel stage). ModuleNotFoundError/FileNotFoundError here is
expected; see tests-impl.json.

--apply must never run a subprocess: it PRINTS the git apply command text.
A wrapper that helpfully applies the patch breaks this workflow's central
contract, so that assertion is checked at the subprocess boundary, not just
against the printed output text.
"""

from __future__ import annotations

import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "bin" / "qwen"


def _load_module():
    spec = importlib.util.spec_from_file_location("bin_qwen", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QwenWrapperBuildPayloadTests(unittest.TestCase):
    def test_build_payload_from_files_and_instruction(self) -> None:
        bq = _load_module()

        payload = bq.build_payload(
            files=["src/worker/qwen.py"], instruction="add logging", explain=False
        )

        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["files"], ["src/worker/qwen.py"])
        self.assertEqual(payload["instruction"], "add logging")
        self.assertFalse(payload.get("explain", False))

    def test_build_payload_explain_flag_set(self) -> None:
        bq = _load_module()

        payload = bq.build_payload(
            files=["src/worker/qwen.py"], instruction="add logging", explain=True
        )

        self.assertTrue(payload["explain"])

    def test_instruction_file_is_read_correctly(self) -> None:
        bq = _load_module()

        with mock.patch("sys.argv", ["qwen"]):
            with (
                mock.patch.object(bq, "enqueue") as mock_enqueue,
            ):
                import tempfile

                with tempfile.TemporaryDirectory() as td:
                    instr_path = Path(td) / "instruction.txt"
                    instr_path.write_text("do the thing\n", encoding="utf-8")

                    argv = [
                        "patch",
                        "--files",
                        "src/worker/qwen.py",
                        "--instruction-file",
                        str(instr_path),
                    ]
                    bq.main(argv)

        self.assertTrue(mock_enqueue.called)
        (called_job,), _kwargs = mock_enqueue.call_args
        self.assertEqual(called_job.payload["instruction"], "do the thing")


class QwenWrapperApplyCommandTests(unittest.TestCase):
    def test_apply_prints_git_apply_command_without_executing(self) -> None:
        """The one that matters: --apply prints the command and never runs
        a subprocess. Assert no subprocess ran, not merely that the printed
        text looks right."""
        bq = _load_module()

        with (
            mock.patch("subprocess.run") as mock_run,
            mock.patch("subprocess.Popen") as mock_popen,
            # Sentinel-only path: never accessed as a real file, only asserted
            # against the printed text below.
            mock.patch.object(bq, "apply_command", return_value="git apply patches/x.patch"),
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                bq.main(["--apply", "some-job-id"])

        self.assertIn("git apply", buf.getvalue())
        mock_run.assert_not_called()
        mock_popen.assert_not_called()

    def test_apply_command_builds_expected_text(self) -> None:
        bq = _load_module()

        with mock.patch.object(
            bq, "_patch_path_for_job", return_value=Path("patches/some-job-id.patch")
        ):
            command = bq.apply_command("some-job-id")

        self.assertIn("git apply", command)
        self.assertIn("some-job-id.patch", command)


class QwenWrapperMainTests(unittest.TestCase):
    def test_main_patch_enqueues_via_queue_ops(self) -> None:
        bq = _load_module()

        with mock.patch.object(bq, "enqueue") as mock_enqueue:
            exit_code = bq.main(
                ["patch", "--files", "src/worker/qwen.py", "--instruction", "add a test"]
            )

        mock_enqueue.assert_called_once()
        self.assertEqual(exit_code, 0)

    def test_main_show_returns_nonzero_for_unknown_job(self) -> None:
        bq = _load_module()

        with mock.patch.object(bq, "find_job_path_by_id", return_value=None):
            exit_code = bq.main(["--show", "does-not-exist"])

        self.assertNotEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
