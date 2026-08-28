"""Subprocess command execution infrastructure for wifi diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from core.process import run_binary


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


class CommandRunner:
    """Simple abstraction to allow faking subprocess calls in tests."""

    def run(self, cmd: Sequence[str], timeout: float | None = None) -> CommandResult:  # pragma: no cover - interface
        raise NotImplementedError


class SubprocessRunner(CommandRunner):
    def run(self, cmd: Sequence[str], timeout: float | None = None) -> CommandResult:
        """Run ``cmd`` via ``core.process.run_binary`` and adapt the result.

        ``run_binary`` maps a timeout to 124 and an unrunnable binary to 127,
        which is the contract the probes expect, and already emits
        ``"<binary>: not found"`` for ENOENT.

        stderr is passed through unchanged rather than rewritten. An earlier
        version replaced it with ``"<binary>: not found"`` whenever the return
        code was 127, but 127 also covers permission-denied and exec-format
        errors -- so a present-but-not-executable binary was reported as
        missing, sending a diagnostics user after the wrong problem.
        """
        res = run_binary(cmd, timeout=timeout)
        return CommandResult(stdout=res.stdout, stderr=res.stderr, returncode=res.returncode)
