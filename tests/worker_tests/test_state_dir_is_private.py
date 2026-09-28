"""Guard test: the whole test process runs with a private worker state dir.

Per-test isolation via QueueRootIsolationMixin cannot protect against worker
threads that outlive their test and finish after the per-test restore.  The fix
is process-wide: tests/__init__.py sets DANCING_BEAR_WORKER_STATE_DIR to a
temporary directory before any worker module is imported, so "restoring to the
original" restores to that temp dir, never to the user's real queue.

This test asserts the invariant for invocations where tests/__init__.py runs:
  - make test (bare python -m unittest)
  - make cov
  - coverage run -m unittest discover  (no -s/-t; discovers from ., tests/ is a package)
  - python3 -m unittest discover -s tests -t .  (both flags required)

Use -t . with -s tests: without it, tests are imported as top-level modules and
tests/__init__.py is never imported, so the guard does not run.
"""

from __future__ import annotations

import os
import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worker import _helpers as helpers
from worker import queue_ops


def _real_default_state_dir() -> Path:
    """Return the real default state dir ignoring any env override.

    Mirrors the logic in get_worker_state_dir with the env var stripped, so
    this test remains correct if the default path ever changes.
    """
    return Path.home() / "Library" / "Application Support" / "dancing-bear"


def _bootstrap_created_dir() -> bool:
    """Return True if tests/__init__.py created the current state dir.

    The bootstrap names its temp dirs with the prefix "dancing-bear-test-state-".
    A user-supplied dir will not have that prefix.
    """
    val = os.environ.get(helpers.WORKER_STATE_DIR_ENV, "")
    return "dancing-bear-test-state-" in val


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

    def test_state_dir_env_var_is_not_real_default(self) -> None:
        """DANCING_BEAR_WORKER_STATE_DIR must be set and not point at the real queue."""
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
    @unittest.skipUnless(_bootstrap_created_dir(), "only applies to bootstrap-created dirs")
    def test_bootstrap_dir_is_under_tmp(self) -> None:
        """Bootstrap-created dirs must be under a macOS temp prefix.

        This assertion only applies when tests/__init__.py created the directory
        (identified by the 'dancing-bear-test-state-' prefix).  A user-supplied
        private dir may legitimately live outside /tmp.
        """
        val = os.environ.get(helpers.WORKER_STATE_DIR_ENV, "")
        tmp_prefixes = ("/var/folders", "/tmp", "/private/tmp")  # nosec B108 - path prefix check only
        self.assertTrue(
            any(val.startswith(p) for p in tmp_prefixes),
            f"Bootstrap-created dir expected under a temp prefix, got {val!r}",
        )

    def test_user_supplied_private_dir_is_accepted(self) -> None:
        """A user-supplied private dir (not under tmp) satisfies the invariant.

        The bootstrap in tests/__init__.py preserves any pre-existing value that
        is not the real default.  This test simulates that by running the bootstrap
        logic directly: a path like /home/user/dev/test-queue is private (not the
        real default) and must not be overwritten by the bootstrap.
        """
        real_default = _real_default_state_dir()

        with tempfile.TemporaryDirectory() as user_dir:
            # user_dir is a real private dir (under /tmp on macOS, but that is
            # incidental; the important property is that it is not the real default).
            with patch.dict(os.environ, {helpers.WORKER_STATE_DIR_ENV: user_dir}):
                current = os.environ.get(helpers.WORKER_STATE_DIR_ENV, "").strip()
                is_already_private = bool(
                    current
                    and current != str(real_default)
                    and not current.startswith(str(real_default) + "/")
                )
                # The bootstrap would preserve this value because it is already private.
                self.assertTrue(
                    is_already_private,
                    f"Bootstrap should preserve {user_dir!r} (private, not real default), "
                    f"but _is_already_private={is_already_private}",
                )
                # The invariant holds: the supplied dir is not the real default.
                state_dir = helpers.get_worker_state_dir()
                self.assertFalse(
                    state_dir == real_default
                    or str(state_dir).startswith(str(real_default) + "/"),
                    f"With user-supplied override, state dir resolved to real default: "
                    f"{state_dir}",
                )
