"""Guard test: the whole test process runs with a private worker state dir.

Per-test isolation via QueueRootIsolationMixin cannot protect against worker
threads that outlive their test and finish after the per-test restore.  The fix
is process-wide: DANCING_BEAR_WORKER_STATE_DIR is set to a temporary directory
before the first test runs, so "restoring to the original" restores to that temp
dir, never to the user's real queue.

The bootstrap logic lives in tests/_private_worker_state.py and is called from
tests/__init__.py and from the __init__.py of worker_tests, workflow_tests and
infra.  It runs under every supported invocation:

  - make test / make cov (bare -m unittest)
  - coverage run -m unittest discover  (CI; no -s/-t)
  - python3 -m unittest discover -s tests -t .
  - python3 -m unittest discover -s tests/<pkg> -t .
  - python3 -m unittest tests.<pkg>.<module>
  - python3 -m unittest discover -s tests  (no -t; <pkg>/__init__.py fires)

``discover -s tests/<pkg>`` without ``-t .`` imports no package __init__.py and
is unsupported (CLAUDE.md "Testing").  This module also bootstraps at module
level, so it is private when run alone even in that form.

Import order is irrelevant: queue_ops.QUEUE_ROOT has no import-time value.
Unless explicitly assigned, every read of it, and every _q(None), resolves the
env var at that moment (see test_queue_root_call_time.py).
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

# Bootstrap the private worker state dir even when no package __init__.py ran
# (e.g. ``discover -s tests/worker_tests -p test_state_dir_is_private.py``).
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


def _load_bootstrap(key: str):
    """Load a fresh copy of tests/_private_worker_state.py under *key*, by path."""
    spec = importlib.util.spec_from_file_location(key, _BOOTSTRAP)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load spec from {_BOOTSTRAP}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _bootstrap_created_dir() -> bool:
    """Return True if tests/__init__.py created the current state dir.

    Delegates to the bootstrap module's own marker
    (``created_by_bootstrap()``) instead of inferring ownership from the path
    text: a user-supplied private override can legally contain the
    "dancing-bear-test-state-" substring, and a substring match would
    misclassify it as bootstrap-created.
    """
    return sys.modules[_BOOTSTRAP_KEY].created_by_bootstrap()  # type: ignore[attr-defined]


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
        mod = _load_bootstrap("_dancing_bear_private_worker_state_test_reload")

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

    def test_q_none_and_queue_root_resolve_privately(self) -> None:
        """Neither _q(None) nor QUEUE_ROOT may resolve to the real queue.

        Both are read from the env var at access time, so they agree with each
        other and with get_worker_state_dir("queue") however the test modules
        were imported.
        """
        real_default = _real_default_state_dir()
        for label, actual in (("_q(None)", queue_ops._q(None)), ("QUEUE_ROOT", queue_ops.QUEUE_ROOT)):
            with self.subTest(label=label):
                self.assertFalse(
                    actual == real_default or actual.is_relative_to(real_default),
                    f"{label} resolved to the REAL queue {actual!r}",
                )

    def test_q_raises_when_get_worker_state_dir_raises(self) -> None:
        """_q(None) must propagate exceptions from get_worker_state_dir, not fall back.

        A resolution failure must raise so callers know the queue root is
        unknown, rather than silently using some other path.
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
    """Unit tests for _private_worker_state._is_private."""

    def setUp(self) -> None:
        self._mod = _load_bootstrap("_dancing_bear_private_worker_state_is_private_suite")
        self._real_default = Path.home() / "Library" / "Application Support" / "dancing-bear"

    def _is_private(self, val: str) -> bool:
        return self._mod._is_private(val)

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


class TestEnsurePrivateChecksMkdtemp(unittest.TestCase):
    """ensure_private() must not trust tempfile.mkdtemp() blindly.

    mkdtemp honours TMPDIR, so a TMPDIR inside the real state dir would make the
    "private" test queue the real one. The crafted mkdtemp result below goes
    through a symlink to the real default; it is never created, and os.rmdir is
    mocked, so nothing under the real state dir is touched.
    """

    def test_mkdtemp_inside_real_default_raises_and_leaves_env_alone(self) -> None:
        mod = _load_bootstrap("_dancing_bear_private_worker_state_mkdtemp_suite")
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "tmpdir-link"
            link.symlink_to(_real_default_state_dir())
            crafted = str(link / "dancing-bear-test-state-crafted")
            with (
                patch.dict(os.environ),
                patch.object(mod.tempfile, "mkdtemp", return_value=crafted),
                patch.object(mod.os, "rmdir") as rmdir,
                patch.object(mod.atexit, "register") as register,
            ):
                os.environ.pop(helpers.WORKER_STATE_DIR_ENV, None)
                with self.assertRaises(RuntimeError) as ctx:
                    mod.ensure_private()
                self.assertNotIn(helpers.WORKER_STATE_DIR_ENV, os.environ)
            self.assertIn("TMPDIR", str(ctx.exception))
            rmdir.assert_called_once_with(crafted)
            register.assert_not_called()

    def test_private_mkdtemp_result_is_used(self) -> None:
        mod = _load_bootstrap("_dancing_bear_private_worker_state_mkdtemp_ok_suite")
        with tempfile.TemporaryDirectory() as tmp:
            made = str(Path(tmp) / "state")
            with (
                patch.dict(os.environ),
                patch.object(mod.tempfile, "mkdtemp", return_value=made),
                patch.object(mod.atexit, "register"),
            ):
                os.environ.pop(helpers.WORKER_STATE_DIR_ENV, None)
                mod.ensure_private()
                self.assertEqual(os.environ.get(helpers.WORKER_STATE_DIR_ENV), made)


class TestCreatedByBootstrap(unittest.TestCase):
    """created_by_bootstrap() must track ownership via a marker, not path text.

    A user-supplied private override can legally contain the
    "dancing-bear-test-state-" substring in its path; only a directory
    ensure_private() itself created should read as bootstrap-created.
    """

    def test_user_dir_containing_bootstrap_substring_is_not_bootstrap_created(self) -> None:
        """Sad path: env points at a user dir whose path contains the bootstrap
        prefix, but the created-marker is unset (or names something else).

        Before this fix, _bootstrap_created_dir() inferred ownership from a
        substring match on the path and would misclassify this dir as
        bootstrap-created.
        """
        mod = _load_bootstrap("_dancing_bear_private_worker_state_created_marker_sad")
        with tempfile.TemporaryDirectory() as parent:
            user_dir = Path(parent) / "dancing-bear-test-state-project" / "state"
            user_dir.mkdir(parents=True)
            with patch.dict(os.environ):
                os.environ.pop(mod._CREATED_MARKER_ENV, None)
                os.environ[helpers.WORKER_STATE_DIR_ENV] = str(user_dir)
                self.assertFalse(
                    mod.created_by_bootstrap(),
                    "a user-supplied dir must not read as bootstrap-created just "
                    "because its path contains the bootstrap prefix",
                )

    def test_bootstrap_created_dir_is_recognized(self) -> None:
        """Happy path: after ensure_private() creates a dir, the marker matches it."""
        mod = _load_bootstrap("_dancing_bear_private_worker_state_created_marker_happy")
        import shutil

        created_dir: str | None = None
        try:
            with patch.dict(os.environ):
                os.environ.pop(helpers.WORKER_STATE_DIR_ENV, None)
                os.environ.pop(mod._CREATED_MARKER_ENV, None)
                mod.ensure_private()
                created_dir = os.environ.get(helpers.WORKER_STATE_DIR_ENV)
                self.assertTrue(mod.created_by_bootstrap())
        finally:
            if created_dir:
                shutil.rmtree(created_dir, ignore_errors=True)
