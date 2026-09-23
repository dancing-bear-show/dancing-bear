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


class QwenSameDirSymlinkTests(QwenHandlerCase):
    """job-a's file name planted as a symlink to job-b's file in the SAME
    directory resolves inside the dir, so a resolved-parent check admits it.
    Every job-scoped write must refuse it and leave job-b's file untouched."""

    OLD_MTIME_NS = 1_000_000_000 * 1_000_000_000

    def _plant(self, directory: Path, suffix: str) -> tuple[Path, Path, bytes]:
        directory.mkdir(parents=True, exist_ok=True)
        victim = directory / f"job-b{suffix}"
        content = b'{"count": 1, "reasons": {"low-disk": 1}, "first_deferred_at": 1.0}'
        victim.write_bytes(content)
        os.utime(victim, ns=(self.OLD_MTIME_NS, self.OLD_MTIME_NS))
        link = directory / f"job-a{suffix}"
        os.symlink(victim.name, link)  # relative: resolves to a sibling in the same dir
        return link, victim, content

    def _assert_untouched(self, victim: Path, content: bytes) -> None:
        self.assertEqual(victim.read_bytes(), content, "job-b's file was written through job-a's link")
        self.assertEqual(victim.stat().st_mtime_ns, self.OLD_MTIME_NS)

    def test_deferral_write_through_a_same_dir_link_is_refused(self) -> None:
        link, victim, content = self._plant(self.deferral_dir, ".json")

        with self.assertRaises(qwen.QwenGuardError) as ctx:
            qwen._record_deferral("job-a", "low-memory")

        self.assertEqual(str(ctx.exception), qwen.INVALID_JOB_ID_OUTCOME)
        self._assert_untouched(victim, content)
        self.assertTrue(link.is_symlink())

    def test_patch_write_through_a_same_dir_link_is_refused(self) -> None:
        link, victim, content = self._plant(self.patch_dir, ".patch")

        with self.assertRaises(qwen.QwenGuardError) as ctx:
            qwen._write_patch_file("job-a", "diff\n")

        self.assertEqual(str(ctx.exception), qwen.INVALID_JOB_ID_OUTCOME)
        self._assert_untouched(victim, content)
        self.assertTrue(link.is_symlink())

    def test_handler_refuses_and_clearing_removes_only_the_link(self) -> None:
        """End to end: a deferral under a planted link is terminal, and the
        terminal-exit cleanup unlinks the link itself, never its target."""
        link, victim, content = self._plant(self.deferral_dir, ".json")

        with mock.patch("worker.qwen._available_memory_bytes", return_value=GIB):
            ok, out = self.run_handler(id="job-a")

        self.assertEqual((ok, out), (False, qwen.INVALID_JOB_ID_OUTCOME))
        self._assert_untouched(victim, content)
        self.assertFalse(os.path.lexists(link), "the planted link was left in place")

    def test_successful_job_refuses_a_patch_link(self) -> None:
        _, victim, content = self._plant(self.patch_dir, ".patch")

        ok, out = self.run_handler(id="job-a")

        self.assertEqual((ok, out), (False, qwen.INVALID_JOB_ID_OUTCOME))
        self._assert_untouched(victim, content)

    def test_link_planted_after_the_check_is_replaced_not_followed(self) -> None:
        """The check-to-write race: the atomic write renames over the name,
        so a link that appears after job_scoped_path ran is swapped out for a
        regular file and its target is never opened."""
        link, victim, content = self._plant(self.deferral_dir, ".json")

        qwen._write_job_file(link, '{"count": 1}')

        self._assert_untouched(victim, content)
        self.assertFalse(link.is_symlink())
        self.assertEqual(link.read_text(encoding="utf-8"), '{"count": 1}')
        self.assertEqual(sorted(p.name for p in self.deferral_dir.iterdir()), ["job-a.json", "job-b.json"])


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
