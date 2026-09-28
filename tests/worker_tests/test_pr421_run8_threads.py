"""Regression tests for PR #421 review threads on shutdown-marker recovery.

- Marker cleanup failures (4122495257, 4122495300): a filesystem error on one
  marker -- unlinking a stale marker, unlinking a marker after its requeue, or
  probing its processing/ record -- is logged and that marker is left for the
  next recovery, instead of raising out of
  ``recover_shutdown_timeout_markers`` and abandoning every marker after it.
  ``run_daemon`` and ``run_once`` call recovery unguarded, so the escape
  aborted worker startup.
"""

from __future__ import annotations

import errno
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.worker_tests.helpers import QueueRootIsolationMixin
from worker import queue_ops as q
from worker.queue_ops import Job, enqueue

_REAL_UNLINK = Path.unlink
_REAL_EXISTS = Path.exists


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def _markers(root: Path) -> list[str]:
    return [n for n in _names(root / "processing") if ".shutdown-timeout" in n]


def _fail_for(name: str, real: Any) -> Any:
    """Wrap Path method ``real`` so it raises EIO for the path named ``name``."""

    def _wrapped(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.name == name:
            raise OSError(errno.EIO, "injected I/O error", str(self))
        return real(self, *args, **kwargs)

    return _wrapped


class _Base(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self) -> None:
        self.setup_queue_root()

    def _claimed_with_marker(self, job_id: str) -> tuple[Path, str]:
        pending = enqueue(Job(id=job_id, type="noop", payload={}), root=self.root)
        claim = q.start_processing(pending, self.root)
        if claim is None or not claim[1]:
            self.fail(f"could not claim {job_id}")
        q.write_shutdown_timeout_marker(job_id, claim[1], root=self.root)
        return claim

    @staticmethod
    def _marker_name(job_id: str, token: str) -> str:
        return f"{job_id}.json.shutdown-timeout.{token}"


class TestMarkerCleanupFailureDoesNotAbortRecovery(_Base):
    def test_stale_marker_unlink_failure_recovers_the_other_markers(self) -> None:
        """4122495257: an undeletable stale marker must not stop the others."""
        stale_token = "b" * 32
        q.write_shutdown_timeout_marker("stale1", stale_token, root=self.root)
        stale_name = self._marker_name("stale1", stale_token)
        _proc, token = self._claimed_with_marker("live1")

        with patch.object(Path, "unlink", _fail_for(stale_name, _REAL_UNLINK)), \
                self.assertLogs(q.__name__, "WARNING") as logs:
            requeued = q.recover_shutdown_timeout_markers(root=self.root)

        self.assertIn(stale_name, "\n".join(logs.output))

        self.assertEqual(requeued, ["live1"])
        self.assertEqual(_names(self.root / "pending"), ["live1.json"])
        # The undeletable marker stays for the next recovery; the other is gone.
        self.assertEqual(_markers(self.root), [stale_name])
        self.assertNotIn(self._marker_name("live1", token), _markers(self.root))

    def test_unlink_failure_after_requeue_recovers_the_other_markers(self) -> None:
        """4122495300: the requeue happened; only the cleanup failed."""
        _p1, tok1 = self._claimed_with_marker("job1")
        _p2, _tok2 = self._claimed_with_marker("job2")
        name1 = self._marker_name("job1", tok1)

        with patch.object(Path, "unlink", _fail_for(name1, _REAL_UNLINK)), \
                self.assertLogs(q.__name__, "WARNING") as logs:
            requeued = q.recover_shutdown_timeout_markers(root=self.root)

        self.assertIn(name1, "\n".join(logs.output))

        self.assertEqual(sorted(requeued), ["job1", "job2"])
        self.assertEqual(_names(self.root / "pending"), ["job1.json", "job2.json"])
        self.assertEqual(_markers(self.root), [name1])

        # The leftover is harmless: the next recovery finds its record gone,
        # removes it as stale, and requeues nothing a second time.
        self.assertEqual(q.recover_shutdown_timeout_markers(root=self.root), [])
        self.assertEqual(_markers(self.root), [])
        self.assertEqual(_names(self.root / "pending"), ["job1.json", "job2.json"])

    def test_record_probe_failure_recovers_the_other_markers(self) -> None:
        """Same class: the existence probe of one marker's record fails."""
        p1, tok1 = self._claimed_with_marker("probe1")
        _p2, _tok2 = self._claimed_with_marker("probe2")

        with patch.object(Path, "exists", _fail_for(p1.name, _REAL_EXISTS)), \
                self.assertLogs(q.__name__, "WARNING") as logs:
            requeued = q.recover_shutdown_timeout_markers(root=self.root)

        self.assertIn("probe1", "\n".join(logs.output))

        self.assertEqual(requeued, ["probe2"])
        self.assertTrue(p1.exists(), "a record whose probe failed was moved anyway")
        self.assertEqual(_markers(self.root), [self._marker_name("probe1", tok1)])


if __name__ == "__main__":
    unittest.main()
