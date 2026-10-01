"""Tests for .claude/skills/rename-session/rename.sh.

The script validates the name, renames the tmux session, and pushes the OSC 0
tab-title escape to the outer client tty. We stub tmux with a tiny shell script
that logs each argument NUL-terminated to a file and echoes a fake tty path on
`display-message`, so argv is unambiguous (no space-splitting confusion).
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

# Log each argument NUL-terminated so the test can split unambiguously.
# Exit with the value of STUB_EXIT (default 0) so failure tests can override it.
_STUB_TMUX = """\
#!/usr/bin/env bash
# Stub tmux: logs each argv element NUL-terminated, echoes fake tty on display-message.
printf '%s\\0' "$@" >> "${TMUX_LOG}"
if [ "${1:-}" = "display-message" ]; then
    echo "${FAKE_TTY}"
fi
exit "${STUB_EXIT:-0}"
"""

# Sentinel written between invocations so we can split calls from each other.
_CALL_SEP = b"\xff"
_STUB_TMUX_WITH_SEP = """\
#!/usr/bin/env bash
# Stub tmux: logs each argv element NUL-terminated, separates calls with 0xff.
printf '%s\\0' "$@" >> "${TMUX_LOG}"
printf '\\xff' >> "${TMUX_LOG}"
if [ "${1:-}" = "display-message" ]; then
    echo "${FAKE_TTY}"
fi
exit "${STUB_EXIT:-0}"
"""


def _make_stub(tmp: Path, *, with_sep: bool = False) -> None:
    """Write a stub tmux script into *tmp*."""
    stub = tmp / "tmux"
    stub.write_text(_STUB_TMUX_WITH_SEP if with_sep else _STUB_TMUX, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _parse_log(tmp: Path) -> list[list[str]]:
    """Return a list of invocations; each is a list of string args.

    The log is NUL-terminated args separated by 0xff sentinels between calls.
    """
    raw = (tmp / "tmux.log").read_bytes()
    calls = []
    for chunk in raw.split(_CALL_SEP):
        chunk = chunk.strip(b"\x00")
        if not chunk:
            continue
        args = [a.decode() for a in chunk.split(b"\x00") if a]
        if args:
            calls.append(args)
    return calls


def _run(
    name: str,
    tmp: Path,
    *,
    tmux_env: bool = True,
    fake_tty: str = "",
    stub_exit: int = 0,
) -> subprocess.CompletedProcess[str]:
    """Run rename.sh with a stub tmux on PATH."""
    log = tmp / "tmux.log"
    log.write_bytes(b"")
    env = {
        **os.environ,
        "PATH": f"{tmp}:{os.environ['PATH']}",
        "TMUX_LOG": str(log),
        "FAKE_TTY": fake_tty,
        "STUB_EXIT": str(stub_exit),
    }
    if tmux_env:
        env["TMUX"] = "/tmp/tmux-1000/default,12345,0"  # nosec B108 - test fixture value, not a real temp path
    else:
        env.pop("TMUX", None)
    return subprocess.run(  # nosec B603 B607 - fixed argv, repo script under test
        ["bash", str(SCRIPT), name],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


class TestRenameSessionScript(unittest.TestCase):
    """Happy-path and sad-path coverage for rename.sh."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        _make_stub(self.tmp, with_sep=True)

    def tearDown(self) -> None:
        self._td.cleanup()

    # ------------------------------------------------------------------
    # Happy path — argv pinned element-by-element
    # ------------------------------------------------------------------

    def test_valid_name_calls_rename_session(self) -> None:
        name = "mail-label-sync"
        result = _run(name, self.tmp)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = _parse_log(self.tmp)
        # First invocation must be rename-session with the exact name.
        self.assertGreater(len(calls), 0, "expected at least one tmux call")
        self.assertEqual(
            calls[0],
            ["rename-session", "--", name],
            "first tmux invocation must be rename-session -- <name>",
        )

    def test_valid_name_with_pr_prefix(self) -> None:
        name = "pr-42-gmail-filters"
        result = _run(name, self.tmp)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = _parse_log(self.tmp)
        self.assertEqual(calls[0], ["rename-session", "--", name])

    def test_max_length_name_accepted(self) -> None:
        # exactly 30 characters
        name = "a" * 30
        result = _run(name, self.tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tty_write_skipped_for_regular_file(self) -> None:
        """A regular file must NOT receive the OSC escape."""
        fake = self.tmp / "fake.tty"
        fake.write_bytes(b"")
        # Pass a regular file as the fake tty; the -c check must refuse it.
        result = _run("some-task", self.tmp, fake_tty=str(fake))
        self.assertEqual(result.returncode, 0, result.stderr)
        # The file must remain empty — no OSC escape written.
        self.assertEqual(fake.read_bytes(), b"")

    @unittest.skipUnless(hasattr(os, "openpty"), "os.openpty not available")
    def test_tty_write_to_char_device(self) -> None:
        """The OSC 0 title escape must be written to a real character device."""
        master_fd, slave_fd = os.openpty()
        try:
            slave_name = os.ttyname(slave_fd)
            result = _run("some-task", self.tmp, fake_tty=slave_name)
            self.assertEqual(result.returncode, 0, result.stderr)
            # Read what was written to the master side of the pty.
            # Use os.read with a small buffer; the escape is ~14 bytes.
            import select
            ready, _, _ = select.select([master_fd], [], [], 1.0)
            if not ready:
                self.fail("no data written to pty master within 1 second")
            data = os.read(master_fd, 256)
            self.assertEqual(
                data,
                b"\x1b]0;some-task\x07",
                "expected OSC 0 title escape on the pty master",
            )
        finally:
            os.close(master_fd)
            os.close(slave_fd)

    def test_tmux_unset_exits_zero_without_invoking_stub(self) -> None:
        result = _run("some-task", self.tmp, tmux_env=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TMUX is unset", result.stdout)
        calls = _parse_log(self.tmp)
        self.assertEqual(calls, [], "tmux must not be called when TMUX is unset")

    # ------------------------------------------------------------------
    # Operational failure — rename-session exits non-zero
    # ------------------------------------------------------------------

    @unittest.skipUnless(hasattr(os, "openpty"), "os.openpty not available")
    def test_rename_session_failure_propagates_and_no_title_written(self) -> None:
        """When tmux rename-session fails the script exits non-zero and writes no title.

        Uses a real PTY so the absence of the OSC write is truly detectable:
        without set -e the script would continue to display-message, get the
        slave tty name, pass the -c/-w guards, and write the escape — which
        would be visible on the master fd within the select timeout.
        """
        import select
        master_fd, slave_fd = os.openpty()
        try:
            slave_name = os.ttyname(slave_fd)
            result = _run("some-task", self.tmp, stub_exit=1, fake_tty=slave_name)
            self.assertNotEqual(result.returncode, 0,
                                "script must exit non-zero when rename-session fails")
            # No title must have been written to the pty.
            ready, _, _ = select.select([master_fd], [], [], 0.3)
            if ready:
                data = os.read(master_fd, 256)
                self.fail(f"tab title must not be written when rename-session fails; got {data!r}")
        finally:
            os.close(master_fd)
            os.close(slave_fd)

    # ------------------------------------------------------------------
    # Invalid names → exit 2, tmux never invoked
    # ------------------------------------------------------------------

    def _assert_invalid(self, name: str) -> None:
        result = _run(name, self.tmp)
        self.assertEqual(result.returncode, 2, f"expected exit 2 for {name!r}, got {result.returncode}")
        calls = _parse_log(self.tmp)
        self.assertEqual(calls, [], f"tmux must not be called for invalid name {name!r}")
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
            timeout=30,
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
