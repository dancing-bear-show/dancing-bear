"""Subprocess command execution infrastructure for wifi diagnostics."""
from __future__ import annotations

import subprocess  # nosec B404
from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


class CommandRunner:
    """Simple abstraction to allow faking subprocess calls in tests."""

    def run(self, cmd: Sequence[str], timeout: Optional[float] = None) -> CommandResult:  # pragma: no cover - interface
        raise NotImplementedError


class SubprocessRunner(CommandRunner):
    def run(self, cmd: Sequence[str], timeout: Optional[float] = None) -> CommandResult:
        try:
            proc = subprocess.run(  # nosec B603 - cmd is controlled by caller
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return CommandResult(stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode(errors="ignore") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode(errors="ignore") if isinstance(exc.stderr, bytes) else (exc.stderr or "timeout")
            return CommandResult(stdout=stdout, stderr=stderr or "timeout", returncode=124)
        except FileNotFoundError:
            return CommandResult(stdout="", stderr=f"{cmd[0]}: not found", returncode=127)
