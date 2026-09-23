"""Tests for the DANCING_BEAR_WORKER_STATE_DIR seam.

The variable exists so a process can run real jobs in a fully private queue
without redirecting HOME (which also redirects git's configuration, and which
worktree guard hooks refuse for that reason). The properties that matter:

- unset, nothing changes — the default location is exactly what it was;
- set, BOTH the queue and the perf logs move, so a private run leaves nothing
  in the user's shared state;
- an explicit log-dir variable still wins for logs, as before;
- end to end, a real `./bin/worker` enqueue + run-once with the variable set
  never touches the queue it would otherwise use.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404 - runs the repo's own bin/worker wrapper in a test
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worker._helpers import WORKER_STATE_DIR_ENV, _get_log_dir, get_worker_state_dir

REPO_ROOT = Path(__file__).resolve().parents[2]
_WRAPPER_TIMEOUT_S = 60

# Variables that would otherwise decide the log dir before the state dir does.
_LOG_ENVS = ("DANCING_BEAR_LOG_DIR", "SRE_LOG_DIR")


def _env_without(*names: str) -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in names}


class TestGetWorkerStateDir(unittest.TestCase):
    def test_default_is_unchanged_when_unset(self) -> None:
        with patch.dict(os.environ, _env_without(WORKER_STATE_DIR_ENV), clear=True):
            self.assertEqual(
                get_worker_state_dir("queue"),
                Path.home() / "Library" / "Application Support" / "dancing-bear" / "queue",
            )

    def test_blank_value_is_treated_as_unset(self) -> None:
        env = {**_env_without(WORKER_STATE_DIR_ENV), WORKER_STATE_DIR_ENV: "   "}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                get_worker_state_dir("queue"),
                Path.home() / "Library" / "Application Support" / "dancing-bear" / "queue",
            )

    def test_override_replaces_the_base_for_every_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            env = {**_env_without(WORKER_STATE_DIR_ENV), WORKER_STATE_DIR_ENV: td}
            with patch.dict(os.environ, env, clear=True):
                base = Path(td).resolve()
                self.assertEqual(get_worker_state_dir("queue"), base / "queue")
                self.assertEqual(get_worker_state_dir("logs"), base / "logs")

    def test_override_does_not_depend_on_home(self) -> None:
        """The point of the seam is not having to touch HOME."""
        with tempfile.TemporaryDirectory() as td:
            env = {**_env_without(WORKER_STATE_DIR_ENV), WORKER_STATE_DIR_ENV: td}
            with patch.dict(os.environ, env, clear=True), patch.object(
                Path, "home", return_value=Path("/nonexistent-home-should-not-be-used")
            ):
                self.assertEqual(get_worker_state_dir("queue"), Path(td).resolve() / "queue")


class TestLogDirFollowsStateDir(unittest.TestCase):
    def test_logs_move_with_the_state_dir(self) -> None:
        """Without this, a private-queue run still writes perf logs to the shared location."""
        with tempfile.TemporaryDirectory() as td:
            env = {**_env_without(WORKER_STATE_DIR_ENV, *_LOG_ENVS), WORKER_STATE_DIR_ENV: td}
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(_get_log_dir(), Path(td).resolve() / "logs")

    def test_explicit_log_dir_still_wins(self) -> None:
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as logs:
            env = {
                **_env_without(WORKER_STATE_DIR_ENV, *_LOG_ENVS),
                WORKER_STATE_DIR_ENV: td,
                "DANCING_BEAR_LOG_DIR": logs,
            }
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(_get_log_dir(), Path(logs))


class TestPrivateQueueEndToEnd(unittest.TestCase):
    """Real ./bin/worker processes; the variable is read at process start.

    queue_ops computes QUEUE_ROOT at import, so only a subprocess can prove the
    variable takes effect the way a workflow stage uses it. HOME is pointed at a
    SECOND temp dir so that, if the seam were ignored, the job would land in
    that decoy location — observable, and never the developer's real queue.
    """

    def _run(self, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603 - fixed argv, repo-internal wrapper
            [str(REPO_ROOT / "bin" / "worker"), *args],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=_WRAPPER_TIMEOUT_S,
            check=False,
        )

    def test_enqueue_and_run_once_stay_in_the_private_queue(self) -> None:
        with tempfile.TemporaryDirectory() as state, tempfile.TemporaryDirectory() as decoy_home:
            env = {
                **_env_without(*_LOG_ENVS),
                WORKER_STATE_DIR_ENV: state,
                "HOME": decoy_home,
            }
            enq = self._run(
                ["enqueue", "--type", "run_shell", "--payload-json", '{"argv": ["ls", "/"]}'],
                env,
            )
            self.assertEqual(enq.returncode, 0, enq.stderr)
            job_id = json.loads(enq.stdout)["id"]

            ran = self._run(["run-once", "--max", "1"], env)
            self.assertEqual(ran.returncode, 0, ran.stderr)

            private_q = Path(state).resolve() / "queue"
            self.assertTrue((private_q / "done" / f"{job_id}.json").is_file())
            self.assertTrue(any((Path(state).resolve() / "logs").glob("perf-worker-*.jsonl")))

            decoy_state = Path(decoy_home) / "Library" / "Application Support" / "dancing-bear"
            self.assertFalse(
                decoy_state.exists(),
                "the HOME-based location was written; the state-dir seam was ignored",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
