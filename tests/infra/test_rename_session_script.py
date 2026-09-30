"""Tests for .claude/skills/rename-session/rename.sh.

The script validates the name, renames the tmux session, and pushes the OSC 0
tab-title escape to the outer client tty. We stub tmux with a tiny shell script
that logs its argv to a file and echoes a fake tty path on `display-message`.
"""

from __future__ import annotations

import os
import stat
import subprocess  # nosec B404 - runs this repo's own shell script, no user input
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / ".claude" / "skills" / "rename-session" / "rename.sh"

_STUB_TMUX = """\
#!/usr/bin/env bash
# Stub tmux: logs argv to $TMUX_LOG, echoes a fake tty on display-message.
echo "$@" >> "${TMUX_LOG}"
if [ "${1:-}" = "display-message" ]; then
    echo "${FAKE_TTY}"
fi
"""


def _make_stub(tmp: Path, fake_tty: str) -> Path:
    """Write a stub tmux script into *tmp* and return its directory."""
    stub = tmp / "tmux"
    stub.write_text(_STUB_TMUX, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return tmp


def _run(
    name: str,
    tmp: Path,
    *,
    tmux_env: bool = True,
    fake_tty: str = "",
) -> subprocess.CompletedProcess[str]:
    """Run rename.sh with a stub tmux on PATH."""
    log = tmp / "tmux.log"
    log.write_text("", encoding="utf-8")
    env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}",
           "TMUX_LOG": str(log), "FAKE_TTY": fake_tty}
    if tmux_env:
        env["TMUX"] = "/tmp/tmux-1000/default,12345,0"  # nosec B108 - test fixture value, not a real temp path
    else:
        env.pop("TMUX", None)
    return subprocess.run(  # nosec B603 B607 - fixed argv, repo script under test
        ["bash", str(SCRIPT), name],
        capture_output=True,
        text=True,
        env=env,
    )


class TestRenameSessionScript(unittest.TestCase):
    """Happy-path and sad-path coverage for rename.sh."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        _make_stub(self.tmp, "")  # default stub with no tty

    def tearDown(self) -> None:
        self._td.cleanup()

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_valid_name_calls_rename_session(self) -> None:
        result = _run("mail-label-sync", self.tmp)
        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.tmp / "tmux.log").read_text()
        self.assertIn("rename-session", log)
        self.assertIn("mail-label-sync", log)

    def test_valid_name_with_pr_prefix(self) -> None:
        result = _run("pr-42-gmail-filters", self.tmp)
        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.tmp / "tmux.log").read_text()
        self.assertIn("rename-session", log)
        self.assertIn("pr-42-gmail-filters", log)

    def test_max_length_name_accepted(self) -> None:
        # exactly 30 characters
        name = "a" * 30
        result = _run(name, self.tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tty_write_skipped_for_regular_file(self) -> None:
        """A regular file must NOT receive the OSC escape."""
        fake = self.tmp / "fake.tty"
        fake.write_text("", encoding="utf-8")
        # Pass a regular file as the fake tty; the -c check must refuse it.
        result = _run("some-task", self.tmp, fake_tty=str(fake))
        self.assertEqual(result.returncode, 0, result.stderr)
        # The file must remain empty — no OSC escape written.
        self.assertEqual(fake.read_text(), "")

    def test_tmux_unset_exits_zero_without_invoking_stub(self) -> None:
        result = _run("some-task", self.tmp, tmux_env=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TMUX is unset", result.stdout)
        log = (self.tmp / "tmux.log").read_text()
        self.assertEqual(log.strip(), "", "tmux must not be called when TMUX is unset")

    # ------------------------------------------------------------------
    # Invalid names → exit 2, tmux never invoked
    # ------------------------------------------------------------------

    def _assert_invalid(self, name: str) -> None:
        result = _run(name, self.tmp)
        self.assertEqual(result.returncode, 2, f"expected exit 2 for {name!r}, got {result.returncode}")
        log = (self.tmp / "tmux.log").read_text()
        self.assertEqual(log.strip(), "", f"tmux must not be called for invalid name {name!r}")
        # Rejected value must NOT appear in stderr (it may carry escape sequences).
        self.assertNotIn(name, result.stderr, "rejected name must not be echoed to stderr")

    def test_invalid_spaces(self) -> None:
        self._assert_invalid("Bad Name")

    def test_invalid_semicolon(self) -> None:
        self._assert_invalid("x;id")

    def test_invalid_command_substitution(self) -> None:
        self._assert_invalid("$(id)")

    def test_invalid_too_long(self) -> None:
        # 31 characters — one over the limit
        self._assert_invalid("a" * 31)

    def test_invalid_uppercase(self) -> None:
        self._assert_invalid("Mail-Sync")

    def test_invalid_trailing_hyphen(self) -> None:
        self._assert_invalid("mail-sync-")

    def test_invalid_double_hyphen(self) -> None:
        self._assert_invalid("mail--sync")

    def test_invalid_newline_embedded(self) -> None:
        """A newline-embedded name must be rejected (bypass via multi-line grep)."""
        self._assert_invalid("ok\nx")

    def test_invalid_esc_byte_embedded(self) -> None:
        """A name containing an ESC byte must be rejected and not echoed to stderr."""
        self._assert_invalid("ok\x1b]0;x")

    # ------------------------------------------------------------------
    # Teeth: prove the old grep form accepted the newline bypass
    # ------------------------------------------------------------------

    def test_grep_form_would_have_passed_newline(self) -> None:
        """The old echo|grep validation matched per LINE, so 'ok\\nx' passed.

        This test confirms the bypass exists in the grep form and would have
        let the injected value reach the tty. It runs the grep check directly
        via bash so it does not depend on having an old version of the script.
        """
        name = "ok\nx"
        # Replicate the old grep check exactly as it appeared in the script:
        #   NAME="..."; echo "$NAME" | grep -qE '^...$'
        # Pass the name via env to avoid any shell quoting of the newline.
        proc = subprocess.run(  # nosec B603 B607 - fixed argv, isolated bash snippet
            ["bash", "-c",
             "echo \"$NAME\" | grep -qE '^[a-z0-9]+(-[a-z0-9]+)*$'"],
            capture_output=True,
            env={**os.environ, "NAME": name},
        )
        self.assertEqual(
            proc.returncode, 0,
            "teeth: old grep form should have passed the newline-embedded name (bypass confirmed)",
        )
        # Confirm the current script rejects it.
        result = _run(name, self.tmp)
        self.assertEqual(result.returncode, 2, "current script must reject the newline-embedded name")


if __name__ == "__main__":
    unittest.main()
