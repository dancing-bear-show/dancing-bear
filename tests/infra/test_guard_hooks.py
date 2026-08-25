"""Run the .claude/hooks shell suites under unittest discovery.

WHY THIS WRAPPER EXISTS
-----------------------
The guard-hook suites are shell scripts. They were documented as manual commands
only, so `make test` and CI -- both of which run Python unittest discovery and
nothing else -- never invoked them. A regression in a hook that blocks credential
reads would therefore ship green, which is the one class of regression these
hooks exist to prevent.

Shelling out from a discovered test is the smallest change that fixes that: no new
Makefile target to remember, no second CI step to keep in sync with the first, and
the suites stay runnable by hand exactly as the README documents. `make test`,
`make cov`, and `.github/workflows/ci.yml` all pick this up automatically because
all three go through discovery.

The suites are self-contained bash and require only `jq`. When `jq` or `bash` is
missing the test SKIPS rather than passes -- a missing tool is an unknown result,
not a passing one, and silently passing here would recreate the same blind spot in
a different place.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - runs trusted in-repo shell suites
import unittest
from pathlib import Path

from tests.fixtures import repo_root

HOOKS_DIR = repo_root() / ".claude" / "hooks"
TESTS_DIR = HOOKS_DIR / "tests"

# Each suite exits 0 on all-pass and 1 on any failure, and prints one line per case.
SUITES = (
    "block-destructive-bash.test.sh",
    "block-protected-paths.test.sh",
    "statusline.test.sh",
)


def _missing_tool() -> str | None:
    """Return the name of the first required tool that is not on PATH."""
    for tool in ("bash", "jq"):
        if shutil.which(tool) is None:
            return tool
    return None


class TestGuardHookSuites(unittest.TestCase):
    """Each .claude/hooks shell suite must exit 0."""

    def _run_suite(self, name: str) -> None:
        missing = _missing_tool()
        if missing is not None:
            self.skipTest(f"{missing} not on PATH; cannot run the hook shell suites")

        suite: Path = TESTS_DIR / name
        self.assertTrue(suite.is_file(), f"missing hook suite: {suite}")

        proc = subprocess.run(  # nosec B603 - trusted in-repo script, no user input
            ["bash", str(suite)],
            capture_output=True,
            text=True,
            cwd=str(repo_root()),
            timeout=180,
        )
        # The suite's own output is the useful failure message: it names every case
        # that failed and what it expected. Reproducing that in assert messages would
        # duplicate it and then drift.
        self.assertEqual(
            proc.returncode,
            0,
            msg=f"\n--- {name} ---\n{proc.stdout}\n{proc.stderr}",
        )
        # An empty run is not a passing run. A suite whose cases were all deleted, or
        # that exited before running anything, exits 0 and would otherwise read as
        # green -- the same fail-open shape the suites themselves guard against.
        self.assertIn("ALL PASS", proc.stdout, msg=proc.stdout)

    def test_block_destructive_bash_suite(self) -> None:
        """Bash guard: credential reads/writes, rm -rf targets, malformed payloads."""
        self._run_suite("block-destructive-bash.test.sh")

    def test_block_protected_paths_suite(self) -> None:
        """Write/Edit guard: credential paths, .git/, key material, templates."""
        self._run_suite("block-protected-paths.test.sh")

    def test_statusline_suite(self) -> None:
        """Statusline: unknown-vs-zero context, thresholds, prefix precedence."""
        self._run_suite("statusline.test.sh")

    def test_every_suite_in_the_directory_is_wired_in(self) -> None:
        """A new *.test.sh must be added to SUITES, not left unrun.

        The failure this prevents is the one that made this wrapper necessary in the
        first place: a suite that exists, passes when run by hand, and is never
        invoked by anything automated.
        """
        on_disk = {p.name for p in TESTS_DIR.glob("*.test.sh")}
        self.assertEqual(
            on_disk,
            set(SUITES),
            msg="hook suites on disk do not match the SUITES tuple in this file",
        )


if __name__ == "__main__":
    unittest.main()
