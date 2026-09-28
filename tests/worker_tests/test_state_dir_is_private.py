"""Guard test: the whole test process runs with a private worker state dir.

Per-test isolation via QueueRootIsolationMixin cannot protect against worker
threads that outlive their test and finish after the per-test restore.  The fix
is process-wide: tests/__init__.py sets DANCING_BEAR_WORKER_STATE_DIR to a
temporary directory before any worker module is imported, so "restoring to the
original" restores to that temp dir, never to the user's real queue.

This test asserts that the invariant holds for any invocation that imports
tests/__init__.py first (make test, make cov, and the documented
``python3 -m unittest discover -s tests -t .`` form).
"""

from __future__ import annotations

import os
import platform
import unittest
from pathlib import Path

from worker import _helpers as helpers
from worker import queue_ops


def _real_default_state_dir() -> Path:
    """Return the real default state dir ignoring any env override.

    Mirrors the logic in get_worker_state_dir with the env var stripped, so
    this test remains correct if the default path ever changes.
    """
    return Path.home() / "Library" / "Application Support" / "dancing-bear"


class TestStateDirectoryIsPrivate(unittest.TestCase):
    """The process-wide state dir must not be the user's real queue."""

    def test_worker_state_dir_is_not_real_default(self) -> None:
        """get_worker_state_dir() must not resolve to the real default location."""
        actual = helpers.get_worker_state_dir()
        real_default = _real_default_state_dir()
        self.assertFalse(
            actual == real_default or str(actual).startswith(str(real_default) + "/"),
            f"get_worker_state_dir() resolved to the REAL state dir: {actual}\n"
            "tests/__init__.py must set DANCING_BEAR_WORKER_STATE_DIR to a "
            "private temp dir before any worker module is imported.",
        )

    def test_queue_root_is_not_real_default(self) -> None:
        """queue_ops.QUEUE_ROOT must not be under the real default location."""
        actual = queue_ops.QUEUE_ROOT
        real_default = _real_default_state_dir()
        self.assertFalse(
            actual == real_default or str(actual).startswith(str(real_default) + "/"),
            f"queue_ops.QUEUE_ROOT is the REAL queue: {actual}\n"
            "tests/__init__.py must set DANCING_BEAR_WORKER_STATE_DIR before "
            "queue_ops is imported.",
        )

    def test_state_dir_env_var_set_to_temp_prefix(self) -> None:
        """DANCING_BEAR_WORKER_STATE_DIR must be set and under a temp prefix."""
        val = os.environ.get(helpers.WORKER_STATE_DIR_ENV, "")
        self.assertTrue(
            val,
            f"{helpers.WORKER_STATE_DIR_ENV} is not set; tests/__init__.py "
            "must set it to a private temp dir.",
        )
        # Must NOT be under the real default location.
        real_default = _real_default_state_dir()
        self.assertFalse(
            val == str(real_default)
            or val.startswith(str(real_default) + "/"),
            f"{helpers.WORKER_STATE_DIR_ENV}={val!r} is under the real state dir "
            f"{real_default}",
        )

    @unittest.skipUnless(platform.system() == "Darwin", "macOS-only path check")
    def test_private_dir_is_under_tmp(self) -> None:
        """On macOS the private dir should be under /var/folders or /tmp."""
        val = os.environ.get(helpers.WORKER_STATE_DIR_ENV, "")
        tmp_prefixes = ("/var/folders", "/tmp", "/private/tmp")  # nosec B108 - path prefix check only
        self.assertTrue(
            any(val.startswith(p) for p in tmp_prefixes),
            f"Expected a temp-style path, got {val!r}",
        )
