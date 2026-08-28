"""Subprocess command execution infrastructure for wifi diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from core.process import RC_NOT_FOUND, run_binary


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

        ``run_binary`` already maps a timeout to 124 and an unrunnable binary to
        127, which is the contract the probes expect. The one thing kept local
        is the not-found message: probes surface ``"<binary>: not found"``, which
        is terser than the errno text ``run_binary`` returns.
        """
        res = run_binary(cmd, timeout=timeout)
        if res.not_found:
            binary = cmd[0] if cmd else "<empty>"
            return CommandResult(stdout="", stderr=f"{binary}: not found", returncode=RC_NOT_FOUND)
        return CommandResult(stdout=res.stdout, stderr=res.stderr, returncode=res.returncode)
