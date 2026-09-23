"""contract.disk_guard: the free-space floor holds on a first run.

The patch directory is created by the first successful write, so on a first
run neither it nor its parent exists. The guard must measure the nearest
existing ancestor instead of failing open, and must not create anything
while measuring.
"""

from __future__ import annotations

import logging
import os
import unittest
from pathlib import Path
import unittest.mock as mock

from tests.fixtures import TempDirMixin
from tests.worker_tests.qwen_fixtures import QwenHandlerCase
from worker import qwen

# Captured before QwenHandlerCase replaces the seam with a fixed value.
_REAL_FREE_DISK_BYTES = qwen._free_disk_bytes
_LOW_FREE = 1024


class _DiskUsageSpy:
    """Stands in for shutil.disk_usage: records each measured path.

    A path that does not exist raises FileNotFoundError, as the real call
    does, so a guard that measures a missing directory fails exactly the way
    it does in production.
    """

    def __init__(self, free: int = _LOW_FREE) -> None:
        self.free = free
        self.calls: list[str] = []

    def __call__(self, path: str) -> mock.Mock:
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        self.calls.append(path)
        return mock.Mock(free=self.free)


class QwenFreeDiskBytesTests(TempDirMixin, unittest.TestCase):
    def test_missing_multi_level_path_measures_nearest_existing_ancestor(self) -> None:
        root = Path(self.tmpdir)
        target = root / "a" / "b" / "patches"
        spy = _DiskUsageSpy()

        with mock.patch("shutil.disk_usage", side_effect=spy):
            free = qwen._free_disk_bytes(target)

        self.assertEqual(free, _LOW_FREE)
        self.assertEqual(spy.calls, [str(root)])
        self.assertFalse((root / "a").exists(), "measuring must not create the directory")

    def test_existing_directory_is_measured_directly(self) -> None:
        target = Path(self.tmpdir) / "patches"
        target.mkdir()
        spy = _DiskUsageSpy()

        with mock.patch("shutil.disk_usage", side_effect=spy):
            self.assertEqual(qwen._free_disk_bytes(target), _LOW_FREE)

        self.assertEqual(spy.calls, [str(target)])

    def test_real_disk_usage_reads_a_missing_path(self) -> None:
        target = Path(self.tmpdir) / "x" / "y" / "z"

        self.assertIsInstance(qwen._free_disk_bytes(target), int)
        self.assertFalse((Path(self.tmpdir) / "x").exists())

    def test_unmeasurable_path_still_returns_none(self) -> None:
        target = Path(self.tmpdir) / "a" / "patches"
        for label, patcher in (
            ("disk_usage fails", mock.patch("shutil.disk_usage", side_effect=OSError("unreadable"))),
            ("ancestor stat denied", mock.patch.object(Path, "exists", side_effect=PermissionError("denied"))),
        ):
            with self.subTest(label), patcher:
                self.assertIsNone(qwen._free_disk_bytes(target))


class QwenFirstRunDiskGuardTests(QwenHandlerCase):
    """Handler-level: the real _free_disk_bytes against a missing patch dir."""

    def setUp(self) -> None:
        super().setUp()
        self._start(mock.patch("worker.qwen._free_disk_bytes", side_effect=_REAL_FREE_DISK_BYTES))
        self.first_run_dir = Path(self.tmpdir) / "data-home" / "qwen" / "patches"
        self._start(mock.patch("worker.qwen._patch_dir", return_value=self.first_run_dir))

    def test_first_run_low_disk_defers(self) -> None:
        spy = _DiskUsageSpy()

        with mock.patch("shutil.disk_usage", side_effect=spy):
            ok, out = self.run_handler()

        self.assertEqual((ok, out), (False, "deferred-low-disk"))
        self.assertEqual(spy.calls, [self.tmpdir])
        self.assertFalse((Path(self.tmpdir) / "data-home").exists())

    def test_first_run_ample_disk_proceeds_and_writes_the_patch(self) -> None:
        spy = _DiskUsageSpy(free=64 * 1024**3)

        with mock.patch("shutil.disk_usage", side_effect=spy):
            ok, _ = self.run_handler()

        self.assertTrue(ok)
        self.assertEqual(len(list(self.first_run_dir.glob("*.patch"))), 1)

    def test_unmeasurable_disk_still_fails_open_with_warning(self) -> None:
        with (
            mock.patch("shutil.disk_usage", side_effect=OSError("unreadable")),
            self.assertLogs("worker.qwen", level=logging.WARNING) as logs,
        ):
            ok, _ = self.run_handler()

        self.assertTrue(ok)
        self.assertTrue(any("disk reading unavailable" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
