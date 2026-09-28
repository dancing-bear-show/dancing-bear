"""Guard test: the whole test process runs with a private worker state dir.

Per-test isolation via QueueRootIsolationMixin cannot protect against worker
threads that outlive their test and finish after the per-test restore.  The fix
is process-wide: DANCING_BEAR_WORKER_STATE_DIR is set to a temporary directory
before any worker module is imported, so "restoring to the original" restores to
that temp dir, never to the user's real queue.

The bootstrap logic lives in tests/_private_worker_state.py and is called from
tests/__init__.py AND from the __init__.py of every test package that reaches
worker (worker_tests, workflow_tests, infra), so the guard fires under every
supported discover form:

  - make test / make cov (bare -m unittest)
  - coverage run -m unittest discover  (CI; no -s/-t)
  - python3 -m unittest discover -s tests -t .
  - python3 -m unittest discover -s tests  (no -t; worker_tests/__init__.py fires)
  - python3 -m unittest discover -s tests/worker_tests  (this file's bootstrap)
  - python3 -m unittest discover -s tests/worker_tests -p test_commands_gaps.py

The last two forms are the hardest: with start_dir=tests/worker_tests and no -t,
Python never imports worker_tests/__init__.py; discover alphabetically imports
test_commands_gaps.py first, which triggers worker.queue_ops import and previously
froze QUEUE_ROOT at the real queue before the bootstrap could run.

The fix is two-layered:
1. This file has a module-level bootstrap so DANCING_BEAR_WORKER_STATE_DIR is
   set before the module-level ``from worker import queue_ops`` below.
2. queue_ops._q(None) calls get_worker_state_dir("queue") at call time (not
   QUEUE_ROOT at import time), so even if QUEUE_ROOT was frozen at the real path,
   every omitted-root call resolves via the env var.  Layer 2 alone closes the
   leak; layer 1 ensures QUEUE_ROOT itself is also private.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Bootstrap the private worker state dir before any worker import, so
# queue_ops.QUEUE_ROOT is computed from a private path regardless of how this
# module was loaded (with or without worker_tests/__init__.py running first).
_BOOTSTRAP = Path(__file__).parent.parent / "_private_worker_state.py"
_BOOTSTRAP_KEY = "_dancing_bear_private_worker_state"
if _BOOTSTRAP_KEY not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_BOOTSTRAP_KEY, _BOOTSTRAP)
    if _spec is not None and _spec.loader is not None:
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[_BOOTSTRAP_KEY] = _mod
        _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
sys.modules[_BOOTSTRAP_KEY].ensure_private()  # type: ignore[attr-defined]

from worker import _helpers as helpers  # noqa: E402
from worker import queue_ops  # noqa: E402


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
        """A user-supplied private dir (not under the real default) satisfies the invariant.

        Calls ensure_private() directly instead of reimplementing the predicate,
        so the test exercises the real bootstrap logic.
        """
        # Load _private_worker_state by path, the same way the package __init__ files do.
        bootstrap_path = Path(__file__).parent.parent / "_private_worker_state.py"
        key = "_dancing_bear_private_worker_state_test_reload"
        spec = importlib.util.spec_from_file_location(key, bootstrap_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Failed to load spec from {bootstrap_path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        import shutil

        with tempfile.TemporaryDirectory() as user_dir:
            with patch.dict(os.environ, {helpers.WORKER_STATE_DIR_ENV: user_dir}):
                mod.ensure_private()
                # ensure_private() must leave the env var unchanged — it is already private.
                self.assertEqual(
                    os.environ.get(helpers.WORKER_STATE_DIR_ENV),
                    user_dir,
                    "ensure_private() must not overwrite a user-supplied private dir",
                )

        # Sad path: env set to the real default string → ensure_private() must replace it.
        real_default_str = str(_real_default_state_dir())
        created_dir: str | None = None
        try:
            with patch.dict(os.environ, {helpers.WORKER_STATE_DIR_ENV: real_default_str}):
                mod.ensure_private()
                after = os.environ.get(helpers.WORKER_STATE_DIR_ENV, "")
                created_dir = after
                self.assertNotEqual(
                    after,
                    real_default_str,
                    "ensure_private() must replace the real default with a private dir",
                )
                self.assertTrue(
                    mod._is_private(after),
                    f"ensure_private() set the env var to a non-private value: {after!r}",
                )
        finally:
            if created_dir and created_dir != real_default_str:
                shutil.rmtree(created_dir, ignore_errors=True)

    def test_q_none_resolves_via_env_at_call_time(self) -> None:
        """queue_ops._q(None) must read the env var at call time, not QUEUE_ROOT.

        This test catches the import-order leak: even if queue_ops.QUEUE_ROOT was
        frozen at the real queue (because worker.queue_ops was imported before the
        bootstrap set DANCING_BEAR_WORKER_STATE_DIR), a call that omits root must
        still resolve to the private temp dir via get_worker_state_dir().

        Simulate the worst-case by temporarily resetting QUEUE_ROOT to the real
        queue root, then asserting that _q(None) still returns the private path
        set by the bootstrap (the env var is already private at this point).
        """
        real_queue = _real_default_state_dir() / "queue"
        original_queue_root = queue_ops.QUEUE_ROOT
        try:
            queue_ops.QUEUE_ROOT = real_queue  # simulate a frozen-at-import QUEUE_ROOT
            actual = queue_ops._q(None)
        finally:
            queue_ops.QUEUE_ROOT = original_queue_root

        self.assertFalse(
            actual == real_queue or str(actual).startswith(str(real_queue)),
            f"_q(None) returned the REAL queue {actual!r} even though "
            f"DANCING_BEAR_WORKER_STATE_DIR is set to a private dir.\n"
            "queue_ops._q(None) must call get_worker_state_dir() at call time.",
        )

    def test_q_raises_when_get_worker_state_dir_raises(self) -> None:
        """_q(None) must propagate exceptions from get_worker_state_dir, not fall back.

        Thread 1 fix: the try/except fallback to QUEUE_ROOT was removed.  A
        resolution failure must raise so callers know the queue root is unknown,
        rather than silently touching the real queue via QUEUE_ROOT.
        """
        with patch("worker.queue_ops.get_worker_state_dir", side_effect=OSError("path error")):
            with self.assertRaises(OSError):
                queue_ops._q(None)

    def test_q_explicit_path_bypasses_get_worker_state_dir(self) -> None:
        """_q(explicit_path) returns the explicit path without calling get_worker_state_dir."""
        explicit = Path(tempfile.mkdtemp())
        try:
            with patch("worker.queue_ops.get_worker_state_dir", side_effect=OSError("should not be called")):
                result = queue_ops._q(explicit)
            self.assertEqual(result, explicit)
        finally:
            import shutil
            shutil.rmtree(explicit, ignore_errors=True)


class TestIsPrivate(unittest.TestCase):
    """Unit tests for _private_worker_state._is_private after Thread 2 fix."""

    def setUp(self) -> None:
        # Load the module by path each time so we test the live version.
        bootstrap_path = Path(__file__).parent.parent / "_private_worker_state.py"
        key = "_dancing_bear_private_worker_state_is_private_suite"
        spec = importlib.util.spec_from_file_location(key, bootstrap_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Failed to load spec from {bootstrap_path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        self._mod = mod
        self._real_default = Path.home() / "Library" / "Application Support" / "dancing-bear"

    def _is_private(self, val: str) -> bool:
        return self._mod._is_private(val)  # type: ignore[attr-defined]

    def test_empty_string_is_not_private(self) -> None:
        self.assertFalse(self._is_private(""))

    def test_real_default_resolved_is_not_private(self) -> None:
        """The resolved real default path must not be private."""
        self.assertFalse(self._is_private(str(self._real_default.resolve())))

    def test_real_default_with_tilde_is_not_private(self) -> None:
        """A literal tilde form of the real default must also be rejected."""
        # Build the tilde form: ~/Library/Application Support/dancing-bear
        home = Path.home()
        relative = self._real_default.relative_to(home)
        tilde_form = "~/" + str(relative)
        self.assertFalse(self._is_private(tilde_form))

    def test_subdir_of_real_default_is_not_private(self) -> None:
        """A subdirectory of the real default (e.g. .../queue) is not private."""
        subdir = str(self._real_default / "queue")
        self.assertFalse(self._is_private(subdir))

    def test_symlink_to_real_default_is_not_private(self) -> None:
        """A symlink that resolves to the real default must not be private.

        Creating a symlink that POINTS at the real default is allowed (nothing is
        written through it); it just must not pass the privacy check.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            link = Path(tmpdir) / "link-to-real"
            link.symlink_to(self._real_default)
            self.assertFalse(self._is_private(str(link)))

    def test_plain_temp_dir_is_private(self) -> None:
        """A real temporary directory is private."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertTrue(self._is_private(tmpdir))
