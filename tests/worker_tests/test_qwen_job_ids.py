"""Job ids become file names; an unsafe one must never become a path.

`worker enqueue --id` accepts any string, so a job id such as ../x would
otherwise put the deferral side-channel file (and its later unlink) or the
patch artifact outside the qwen state and output dirs.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
import unittest.mock as mock

from worker import qwen
from tests.worker_tests.qwen_fixtures import GIB, QwenHandlerCase

UNSAFE_IDS = (
    "../escape",
    "..",
    ".",
    "",
    "a/b",
    "a\\b",
    "/abs",
    ".hidden",
    "-leading-dash",
    "x" * 129,
    "id\n",
    "nul\x00byte",
)
SAFE_IDS = ("qwen-test-job", "0b1c2d3e4f", "job_1.retry-2", "x" * 128)


class QwenJobIdValidatorTests(unittest.TestCase):
    def test_validator_accepts_only_single_safe_components(self) -> None:
        for job_id in UNSAFE_IDS:
            with self.subTest(job_id=job_id):
                self.assertFalse(qwen.is_safe_job_id(job_id))
        for job_id in SAFE_IDS:
            with self.subTest(job_id=job_id):
                self.assertTrue(qwen.is_safe_job_id(job_id))
        self.assertFalse(qwen.is_safe_job_id(None))


class QwenJobIdPathTests(QwenHandlerCase):
    def test_every_job_id_path_builder_refuses_an_unsafe_id(self) -> None:
        builders = (
            ("deferral", lambda job_id: qwen._record_deferral(job_id, "low-memory")),
            ("patch", qwen.patch_path_for_job),
            ("patch-write", lambda job_id: qwen._write_patch_file(job_id, "diff\n")),
        )
        for name, build in builders:
            for job_id in ("../escape", "..", "a/b"):
                with self.subTest(builder=name, job_id=job_id), self.assertRaises(qwen.QwenGuardError) as ctx:
                    build(job_id)
                self.assertEqual(str(ctx.exception), qwen.INVALID_JOB_ID_OUTCOME)
        self.assertEqual(sorted(p.name for p in Path(self.tmpdir).iterdir() if p.is_file()), [])

    def test_clearing_deferral_state_never_deletes_outside_the_state_dir(self) -> None:
        victim = Path(self.tmpdir) / "victim.json"
        victim.write_text("{}", encoding="utf-8")
        self.deferral_dir.mkdir(parents=True)

        qwen._clear_deferral_state("../victim")

        self.assertTrue(victim.exists(), "an unsafe id reached unlink outside the deferral dir")

    def test_symlink_at_the_job_file_name_is_refused(self) -> None:
        """Defence in depth: even a safe id may not write through a planted symlink."""
        outside = Path(self.tmpdir) / "outside.json"
        self.deferral_dir.mkdir(parents=True)
        os.symlink(outside, self.deferral_dir / "planted.json")

        with self.assertRaises(qwen.QwenGuardError):
            qwen._record_deferral("planted", "low-memory")

        self.assertFalse(outside.exists())


class QwenJobIdHandlerTests(QwenHandlerCase):
    def test_unsafe_job_id_is_terminal_before_any_path_is_built(self) -> None:
        """Low memory would otherwise record a deferral under ../escape.json."""
        escaped = Path(self.tmpdir) / "escape.json"
        for job_id in UNSAFE_IDS:
            with self.subTest(job_id=job_id):
                with mock.patch("worker.qwen._available_memory_bytes", return_value=GIB):
                    ok, out = self.run_handler(id=job_id)
                self.assertEqual((ok, out), (False, qwen.INVALID_JOB_ID_OUTCOME))
        self.assertFalse(escaped.exists())
        self.assertFalse(self.deferral_dir.exists())
        self.assertEqual(self.patch_files(), [])
        self.assertEqual(self.generate_requests(), [])

    def test_safe_job_id_still_succeeds(self) -> None:
        ok, result = self.run_handler(id="job_1.retry-2")

        self.assertTrue(ok)
        self.assertEqual(Path(str(self.as_dict(result)["patch_path"])).name, "job_1.retry-2.patch")


if __name__ == "__main__":
    unittest.main()
