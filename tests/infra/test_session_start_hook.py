"""Tests for the inline Python SessionStart hook in .claude/settings.json.

The hook is an inline ``python3 -I -S -c "..."`` command that detects whether
the session is running in an isolated worktree and, if so, writes a
``.claude/.session-owner`` marker with a UUID session id and timestamp. It
emits a JSON object with a ``systemMessage`` key on every run.

The hook must:
- Compile successfully (no SyntaxError).
- Run under ``-I -S`` flags (no site-packages, no inherited sys.path).
- Always exit 0 and emit a valid JSON object, even outside a git repo.
- Write ``.claude/.session-owner`` when in a worktree, not when in main.
- Produce a marker whose ``session_id`` is a UUID and ``claimed_at`` is a float.
- Warn about a stale marker when one exists from a prior session.
- Run idempotently (multiple invocations do not fail or corrupt state).
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404 - runs extracted hook snippet, reviewed below
import tempfile
import time
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_FILE = REPO_ROOT / ".claude" / "settings.json"


# ---------------------------------------------------------------------------
# Snippet extraction
# ---------------------------------------------------------------------------

def _extract_snippet() -> str:
    """Extract the inline Python snippet from .claude/settings.json.

    Parses the JSON rather than re-typing the code, so the tests always run
    against the actual file. A hand-transcribed copy would validate the
    transcription, not the hook — the very failure mode this approach avoids.
    """
    settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    for group in settings.get("hooks", {}).get("SessionStart", []):
        for hook in group.get("hooks", []):
            cmd: str = hook.get("command", "")
            prefix = 'python3 -I -S -c "'
            if cmd.startswith(prefix) and cmd.endswith('"'):
                return cmd[len(prefix):-1]
    raise AssertionError(
        "Could not find the python3 -I -S -c hook in .claude/settings.json"
    )


SNIPPET = _extract_snippet()


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------

def _run_snippet(
    *,
    cwd: str,
    extra_env: dict[str, str] | None = None,
    home: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the extracted snippet via ``python3 -I -S -c <snippet>``.

    The snippet is passed verbatim as the ``-c`` argument so the test proves
    the actual file works under the ``-I -S`` flags, not just that
    ``exec()``-ing it in-process succeeds.

    ``HOME`` is overridden to a temp dir so the hook never touches the real
    ``~/.claude``.
    """
    env = dict(os.environ)
    if home is not None:
        env["HOME"] = home
    if extra_env:
        env.update(extra_env)
    return subprocess.run(  # nosec B603 B607 - argv is fixed; snippet from tracked file
        ["python3", "-I", "-S", "-c", SNIPPET],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=30,
    )


def _init_git_repo(path: str) -> None:
    """Initialise a minimal git repo at *path* (quiet, no config required)."""
    subprocess.run(  # nosec B603 B607 - fixed argv, temp dir
        ["git", "init", "-q"],
        cwd=path,
        capture_output=True,
        check=True,
        timeout=30,
    )


def _add_worktree(main_repo: str, worktree_path: str, branch: str) -> None:
    """Add a git worktree rooted at *worktree_path* off *main_repo*."""
    subprocess.run(  # nosec B603 B607 - fixed argv, temp dir
        ["git", "worktree", "add", "--orphan", "-b", branch, worktree_path],
        cwd=main_repo,
        capture_output=True,
        check=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSessionStartHookCompiles(unittest.TestCase):
    """The snippet extracted from settings.json must parse without error."""

    def test_snippet_compiles(self) -> None:
        """compile() succeeds — no SyntaxError in the hook code."""
        try:
            compile(SNIPPET, "<string>", "exec")
        except SyntaxError as exc:
            self.fail(
                f"The SessionStart hook snippet in .claude/settings.json "
                f"does not compile: {exc}"
            )


class TestSessionStartHookNonGitDir(unittest.TestCase):
    """In a non-git directory the hook must exit 0 and emit valid JSON."""

    def test_exit_code_zero_outside_git_repo(self) -> None:
        """Hook always exits 0 even when git commands fail."""
        with tempfile.TemporaryDirectory() as td:
            proc = _run_snippet(cwd=td, home=td)
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_emits_valid_json_outside_git_repo(self) -> None:
        """Hook emits a single JSON object with systemMessage outside a repo."""
        with tempfile.TemporaryDirectory() as td:
            proc = _run_snippet(cwd=td, home=td)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertIsInstance(payload, dict)
            self.assertIn("systemMessage", payload)
            self.assertIsInstance(payload["systemMessage"], str)

    def test_emits_no_worktree_message_outside_git_repo(self) -> None:
        """Hook warns that no worktree is detected when git is absent."""
        with tempfile.TemporaryDirectory() as td:
            proc = _run_snippet(cwd=td, home=td)
            payload = json.loads(proc.stdout)
            msg = payload["systemMessage"]
            self.assertIn("No worktree detected", msg)
            self.assertIn("EnterWorktree", msg)

    def test_no_marker_file_written_outside_git_repo(self) -> None:
        """The marker file must NOT be written when no worktree is active."""
        with tempfile.TemporaryDirectory() as td:
            _run_snippet(cwd=td, home=td)
            marker = Path(td) / ".claude" / ".session-owner"
            self.assertFalse(
                marker.exists(),
                f"marker was unexpectedly written at {marker}",
            )


class TestSessionStartHookInMainCheckout(unittest.TestCase):
    """In a plain (non-worktree) git repo the hook must NOT claim ownership."""

    def test_no_marker_in_main_checkout(self) -> None:
        """Marker file is not written when cwd is the main checkout."""
        with tempfile.TemporaryDirectory() as td:
            _init_git_repo(td)
            _run_snippet(cwd=td, home=td)
            marker = Path(td) / ".claude" / ".session-owner"
            self.assertFalse(
                marker.exists(),
                "hook wrote a marker in the main checkout — it should only "
                "write in an actual worktree",
            )

    def test_no_worktree_message_in_main_checkout(self) -> None:
        """Hook emits the no-worktree action-required message in a plain repo."""
        with tempfile.TemporaryDirectory() as td:
            _init_git_repo(td)
            proc = _run_snippet(cwd=td, home=td)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertIn("systemMessage", payload)
            msg = payload["systemMessage"]
            self.assertIn("EnterWorktree", msg)


class TestSessionStartHookInWorktree(unittest.TestCase):
    """In a real worktree the hook must claim ownership and emit valid JSON."""

    def test_marker_file_created_in_worktree(self) -> None:
        """Hook creates .claude/.session-owner in the worktree directory."""
        with tempfile.TemporaryDirectory() as td:
            main = os.path.join(td, "main")
            wt = os.path.join(td, "worktree")
            os.makedirs(main)
            os.makedirs(wt)
            _init_git_repo(main)
            _add_worktree(main, wt, "test-branch")

            proc = _run_snippet(cwd=wt, home=td)

            self.assertEqual(proc.returncode, 0, proc.stderr)
            marker = Path(wt) / ".claude" / ".session-owner"
            self.assertTrue(marker.exists(), f"marker not found at {marker}")

    def test_marker_json_structure(self) -> None:
        """Marker file contains a JSON object with session_id and claimed_at keys."""
        with tempfile.TemporaryDirectory() as td:
            main = os.path.join(td, "main")
            wt = os.path.join(td, "worktree")
            os.makedirs(main)
            os.makedirs(wt)
            _init_git_repo(main)
            _add_worktree(main, wt, "test-branch")

            proc = _run_snippet(cwd=wt, home=td)
            self.assertEqual(proc.returncode, 0, proc.stderr)

            marker = Path(wt) / ".claude" / ".session-owner"
            data = json.loads(marker.read_text(encoding="utf-8"))
            self.assertIn("session_id", data)
            self.assertIn("claimed_at", data)

    def test_marker_session_id_is_uuid(self) -> None:
        """session_id in the marker is a valid UUID string."""
        with tempfile.TemporaryDirectory() as td:
            main = os.path.join(td, "main")
            wt = os.path.join(td, "worktree")
            os.makedirs(main)
            os.makedirs(wt)
            _init_git_repo(main)
            _add_worktree(main, wt, "test-branch")

            _run_snippet(cwd=wt, home=td)

            marker = Path(wt) / ".claude" / ".session-owner"
            data = json.loads(marker.read_text(encoding="utf-8"))
            # Verify shape only — never a fixed literal value
            session_id = data["session_id"]
            self.assertIsInstance(session_id, str)
            try:
                parsed = uuid.UUID(session_id)
            except ValueError:
                self.fail(f"session_id is not a valid UUID: {session_id!r}")
            self.assertRegex(
                session_id,
                r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
                "session_id must be a UUID v4 in canonical hyphenated form",
            )
            self.assertIsNotNone(parsed)

    def test_marker_claimed_at_is_float_timestamp(self) -> None:
        """claimed_at in the marker is a numeric Unix timestamp."""
        with tempfile.TemporaryDirectory() as td:
            main = os.path.join(td, "main")
            wt = os.path.join(td, "worktree")
            os.makedirs(main)
            os.makedirs(wt)
            _init_git_repo(main)
            _add_worktree(main, wt, "test-branch")

            before = time.time()
            proc = _run_snippet(cwd=wt, home=td)
            after = time.time()

            self.assertEqual(proc.returncode, 0, proc.stderr)
            marker = Path(wt) / ".claude" / ".session-owner"
            data = json.loads(marker.read_text(encoding="utf-8"))
            claimed_at = data["claimed_at"]
            self.assertIsInstance(claimed_at, float)
            self.assertGreaterEqual(claimed_at, before)
            self.assertLessEqual(claimed_at, after)

    def test_emits_claimed_ownership_json_in_worktree(self) -> None:
        """Hook emits a JSON systemMessage confirming ownership in a worktree."""
        with tempfile.TemporaryDirectory() as td:
            main = os.path.join(td, "main")
            wt = os.path.join(td, "worktree")
            os.makedirs(main)
            os.makedirs(wt)
            _init_git_repo(main)
            _add_worktree(main, wt, "test-branch")

            proc = _run_snippet(cwd=wt, home=td)

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertIn("systemMessage", payload)
            msg = payload["systemMessage"]
            # First run — no stale marker — "claimed ownership" message
            self.assertIn("claimed ownership marker", msg)


class TestSessionStartHookStaleMarker(unittest.TestCase):
    """When a prior session's marker already exists, the hook must warn."""

    def _make_worktree(self, td: str) -> tuple[str, str]:
        """Return (main_path, worktree_path) set up under *td*."""
        main = os.path.join(td, "main")
        wt = os.path.join(td, "worktree")
        os.makedirs(main)
        os.makedirs(wt)
        _init_git_repo(main)
        _add_worktree(main, wt, "test-branch")
        return main, wt

    def test_warns_when_stale_marker_exists(self) -> None:
        """Second run (different session_id) triggers the stale-marker warning."""
        with tempfile.TemporaryDirectory() as td:
            _main, wt = self._make_worktree(td)
            # First run plants the marker
            first = _run_snippet(cwd=wt, home=td)
            self.assertEqual(first.returncode, 0, first.stderr)

            # Second run finds an existing marker and should warn
            second = _run_snippet(cwd=wt, home=td)
            self.assertEqual(second.returncode, 0, second.stderr)
            payload = json.loads(second.stdout)
            msg = payload["systemMessage"]
            self.assertIn("WARNING", msg)
            self.assertIn("re-claimed the marker", msg)

    def test_stale_warning_includes_prior_claimed_at(self) -> None:
        """The stale warning message includes the prior claimed_at timestamp."""
        with tempfile.TemporaryDirectory() as td:
            _main, wt = self._make_worktree(td)
            # Plant the first marker
            first = _run_snippet(cwd=wt, home=td)
            self.assertEqual(first.returncode, 0, first.stderr)

            marker = Path(wt) / ".claude" / ".session-owner"
            first_data = json.loads(marker.read_text(encoding="utf-8"))
            prior_claimed_at = str(first_data["claimed_at"])

            # Second run — warning should include the prior timestamp
            second = _run_snippet(cwd=wt, home=td)
            payload = json.loads(second.stdout)
            msg = payload["systemMessage"]
            self.assertIn(prior_claimed_at, msg)

    def test_marker_overwritten_on_second_run(self) -> None:
        """Second run replaces the marker with a fresh session_id."""
        with tempfile.TemporaryDirectory() as td:
            _main, wt = self._make_worktree(td)
            _run_snippet(cwd=wt, home=td)

            marker = Path(wt) / ".claude" / ".session-owner"
            first_id = json.loads(marker.read_text(encoding="utf-8"))["session_id"]

            _run_snippet(cwd=wt, home=td)

            second_id = json.loads(marker.read_text(encoding="utf-8"))["session_id"]
            self.assertNotEqual(
                first_id,
                second_id,
                "second run must overwrite the marker with a fresh session_id",
            )

    def test_corrupted_marker_does_not_raise(self) -> None:
        """A corrupted marker file is silently ignored; hook still exits 0."""
        with tempfile.TemporaryDirectory() as td:
            _main, wt = self._make_worktree(td)
            marker_dir = Path(wt) / ".claude"
            marker_dir.mkdir(parents=True, exist_ok=True)
            marker = marker_dir / ".session-owner"
            marker.write_text("NOT VALID JSON", encoding="utf-8")

            proc = _run_snippet(cwd=wt, home=td)

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertIn("systemMessage", payload)
            # Corrupted marker treated as absent — no stale warning
            self.assertNotIn("WARNING", payload["systemMessage"])


class TestSessionStartHookIdempotency(unittest.TestCase):
    """Multiple runs must not fail or produce inconsistent state."""

    def test_three_consecutive_runs_all_exit_zero(self) -> None:
        """Three consecutive invocations all exit 0."""
        with tempfile.TemporaryDirectory() as td:
            main = os.path.join(td, "main")
            wt = os.path.join(td, "worktree")
            os.makedirs(main)
            os.makedirs(wt)
            _init_git_repo(main)
            _add_worktree(main, wt, "test-branch")

            for i in range(3):
                proc = _run_snippet(cwd=wt, home=td)
                self.assertEqual(
                    proc.returncode, 0, f"run {i + 1} failed: {proc.stderr}"
                )

    def test_three_consecutive_runs_all_emit_valid_json(self) -> None:
        """Three consecutive invocations each emit a valid JSON object."""
        with tempfile.TemporaryDirectory() as td:
            main = os.path.join(td, "main")
            wt = os.path.join(td, "worktree")
            os.makedirs(main)
            os.makedirs(wt)
            _init_git_repo(main)
            _add_worktree(main, wt, "test-branch")

            for i in range(3):
                proc = _run_snippet(cwd=wt, home=td)
                try:
                    payload = json.loads(proc.stdout)
                except json.JSONDecodeError as exc:
                    self.fail(f"run {i + 1} emitted invalid JSON: {exc}\n{proc.stdout!r}")
                self.assertIn(
                    "systemMessage",
                    payload,
                    f"run {i + 1} missing systemMessage key",
                )

    def test_marker_file_valid_json_after_three_runs(self) -> None:
        """Marker file remains valid JSON after three consecutive runs."""
        with tempfile.TemporaryDirectory() as td:
            main = os.path.join(td, "main")
            wt = os.path.join(td, "worktree")
            os.makedirs(main)
            os.makedirs(wt)
            _init_git_repo(main)
            _add_worktree(main, wt, "test-branch")

            for _ in range(3):
                _run_snippet(cwd=wt, home=td)

            marker = Path(wt) / ".claude" / ".session-owner"
            self.assertTrue(marker.exists())
            data = json.loads(marker.read_text(encoding="utf-8"))
            self.assertIn("session_id", data)
            self.assertIn("claimed_at", data)
            # Shape checks
            uuid.UUID(data["session_id"])  # raises ValueError if invalid
            self.assertIsInstance(data["claimed_at"], float)


class TestSessionStartHookOutputShape(unittest.TestCase):
    """The hook's stdout must always be a single JSON object, never prose."""

    def test_output_is_single_json_object_outside_repo(self) -> None:
        """Exactly one JSON object on stdout when run outside a git repo."""
        with tempfile.TemporaryDirectory() as td:
            proc = _run_snippet(cwd=td, home=td)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)  # raises if malformed or multi-line
            self.assertIsInstance(payload, dict)
            self.assertEqual(list(payload.keys()), ["systemMessage"])

    def test_output_is_single_json_object_in_worktree(self) -> None:
        """Exactly one JSON object on stdout when run in a worktree."""
        with tempfile.TemporaryDirectory() as td:
            main = os.path.join(td, "main")
            wt = os.path.join(td, "worktree")
            os.makedirs(main)
            os.makedirs(wt)
            _init_git_repo(main)
            _add_worktree(main, wt, "test-branch")

            proc = _run_snippet(cwd=wt, home=td)

            payload = json.loads(proc.stdout)
            self.assertIsInstance(payload, dict)
            self.assertEqual(list(payload.keys()), ["systemMessage"])


class TestSessionStartHookIsolatedFlags(unittest.TestCase):
    """The hook must run correctly under ``python3 -I -S`` (no site-packages).

    Proving this with subprocess confirms the hook does not rely on any
    installed package or an inherited sys.path — which would fail in a clean
    CI environment or with a foreign PYTHONPATH active.
    """

    def test_runs_under_isolated_flags_outside_repo(self) -> None:
        """python3 -I -S -c <snippet> exits 0 in a non-git temp directory."""
        with tempfile.TemporaryDirectory() as td:
            proc = _run_snippet(cwd=td, home=td)
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_runs_under_isolated_flags_in_worktree(self) -> None:
        """python3 -I -S -c <snippet> exits 0 in a real worktree."""
        with tempfile.TemporaryDirectory() as td:
            main = os.path.join(td, "main")
            wt = os.path.join(td, "worktree")
            os.makedirs(main)
            os.makedirs(wt)
            _init_git_repo(main)
            _add_worktree(main, wt, "test-branch")

            proc = _run_snippet(cwd=wt, home=td)

            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_site_packages_absent_does_not_break_hook(self) -> None:
        """-S strips site-packages; hook must not import anything from there."""
        with tempfile.TemporaryDirectory() as td:
            # Poison the PYTHONPATH with a fake package that shadows stdlib.
            fake_pkg_dir = os.path.join(td, "evil_site")
            os.makedirs(fake_pkg_dir)
            Path(fake_pkg_dir, "json.py").write_text(
                "raise ImportError('evil json from fake site-packages')\n"
            )
            # -I ignores PYTHONPATH, so this is a belt-and-suspenders check.
            proc = _run_snippet(
                cwd=td,
                home=td,
                extra_env={"PYTHONPATH": fake_pkg_dir},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertIn("systemMessage", payload)


class TestSessionStartHookStdlibOnly(unittest.TestCase):
    """The hook uses only stdlib modules available under -I -S."""

    def test_imports_are_stdlib_only(self) -> None:
        """All imports in the snippet are standard-library modules."""
        # Extract import names from the snippet
        imported = re.findall(r"^import\s+([\w,\s]+)", SNIPPET, re.MULTILINE)
        names: list[str] = []
        for line in imported:
            for name in line.split(","):
                names.append(name.strip().split()[0])

        stdlib_modules = {
            "subprocess", "json", "os", "time", "uuid",
            "sys", "re", "pathlib", "collections", "functools",
            "itertools", "math", "datetime", "io", "typing",
        }
        for name in names:
            self.assertIn(
                name,
                stdlib_modules,
                f"snippet imports {name!r} which is not stdlib — "
                "the hook runs under -I -S and cannot import third-party packages",
            )


if __name__ == "__main__":
    unittest.main()
