"""Which ``os.link`` failures select the no-hardlink publish fallback.

Only errno values meaning "this filesystem cannot hard-link" may take the
check-then-replace fallback in ``_copy_exclusive``. Any other failure (EIO,
EACCES, ...) must re-raise with ``dest`` untouched, ``staged`` kept for a
later recovery pass, and no hidden temp file left in pending/.

No threads are started.
"""

from __future__ import annotations

import errno
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.worker_tests.helpers import QueueRootIsolationMixin
from worker import queue_ops as q

_RECORD = b'{"id": "j1", "type": "noop", "status": "pending"}'
_RIVAL = b'{"id": "j1", "type": "noop", "status": "pending", "rival": true}'
_UNSUPPORTED = (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS, errno.EXDEV)
_OTHER = (errno.EIO, errno.EACCES, errno.ENOSPC, errno.EMLINK)


def _link_error(code: int):
    return patch("worker.queue_ops.os.link", side_effect=OSError(code, os.strerror(code)))


class _Base(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self) -> None:
        self.setup_queue_root()
        paths = q._ensure_dirs(self.root)
        self.pending = paths["pending"]
        self.staged = paths["processing"] / "j1.json.requeue"
        self.staged.write_bytes(_RECORD)
        self.dest = self.pending / "j1.json"

    def _pending_names(self) -> list[str]:
        return sorted(p.name for p in self.pending.iterdir())


class TestUnsupportedErrnoTakesFallback(_Base):
    def test_publish_succeeds_via_copy_for_each_unsupported_errno(self) -> None:
        for code in _UNSUPPORTED:
            with self.subTest(errno=errno.errorcode[code]):
                self.staged.write_bytes(_RECORD)
                self.dest.unlink(missing_ok=True)
                with _link_error(code):
                    self.assertTrue(q._publish_no_clobber(self.staged, self.dest))
                self.assertEqual(self.dest.read_bytes(), _RECORD)
                self.assertFalse(self.staged.exists())
                self.assertEqual(self._pending_names(), ["j1.json"])

    def test_copy_exclusive_falls_back_for_each_unsupported_errno(self) -> None:
        for code in _UNSUPPORTED:
            with self.subTest(errno=errno.errorcode[code]):
                self.dest.unlink(missing_ok=True)
                with _link_error(code):
                    q._copy_exclusive(self.staged, self.dest)
                self.assertEqual(self.dest.read_bytes(), _RECORD)
                self.assertEqual(self._pending_names(), ["j1.json"])


class TestOtherErrnoReraises(_Base):
    def test_publish_reraises_and_keeps_staged(self) -> None:
        for code in _OTHER:
            with self.subTest(errno=errno.errorcode[code]):
                with _link_error(code), self.assertRaises(OSError) as ctx:
                    q._publish_no_clobber(self.staged, self.dest)
                self.assertEqual(ctx.exception.errno, code)
                self.assertFalse(self.dest.exists())
                self.assertEqual(self.staged.read_bytes(), _RECORD)
                self.assertEqual(self._pending_names(), [])

    def test_copy_exclusive_reraises_without_leaving_temp(self) -> None:
        """The fallback's own os.link fails transiently: no temp, no dest."""
        for code in _OTHER:
            with self.subTest(errno=errno.errorcode[code]):
                with _link_error(code), self.assertRaises(OSError) as ctx:
                    q._copy_exclusive(self.staged, self.dest)
                self.assertEqual(ctx.exception.errno, code)
                self.assertEqual(self._pending_names(), [])

    def test_existing_dest_is_untouched(self) -> None:
        self.dest.write_bytes(_RIVAL)
        with _link_error(errno.EIO), self.assertRaises(OSError):
            q._copy_exclusive(self.staged, self.dest)
        self.assertEqual(self.dest.read_bytes(), _RIVAL)
        self.assertEqual(self._pending_names(), ["j1.json"])

    def test_failed_replace_leaves_no_temp(self) -> None:
        """A failure inside the fallback's replace also cleans up the temp."""
        with _link_error(errno.EPERM), patch.object(
            Path, "replace", side_effect=OSError(errno.EIO, "replace failed")
        ), self.assertRaises(OSError):
            q._copy_exclusive(self.staged, self.dest)
        self.assertEqual(self._pending_names(), [])


class TestFileExistsUnchanged(_Base):
    def test_rival_is_refused_and_staged_kept(self) -> None:
        self.dest.write_bytes(_RIVAL)
        self.assertFalse(q._publish_no_clobber(self.staged, self.dest))
        self.assertEqual(self.dest.read_bytes(), _RIVAL)
        self.assertTrue(self.staged.exists())
        self.assertEqual(self._pending_names(), ["j1.json"])

    def test_copy_exclusive_raises_file_exists_without_temp(self) -> None:
        self.dest.write_bytes(_RIVAL)
        with self.assertRaises(FileExistsError):
            q._copy_exclusive(self.staged, self.dest)
        self.assertEqual(self.dest.read_bytes(), _RIVAL)
        self.assertEqual(self._pending_names(), ["j1.json"])


if __name__ == "__main__":
    unittest.main()
