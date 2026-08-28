"""Shared subprocess invocation primitive.

Wraps the one thing every domain runner repeats -- ``subprocess.run`` with a
fixed argument vector, captured text output, and a timeout -- and normalizes
the two failure modes that are awkward to handle at each call site
(``TimeoutExpired`` and a missing binary) into ordinary return values.

Deliberately narrow. The domains that shell out do NOT share a failure
contract, and flattening them into one would be wrong:

- ``wifi.diagnostics_runners`` never raises; it maps timeout to rc 124 and a
  missing binary to rc 127 so probes can report a degraded result.
- ``qlty.runner`` raises ``QltyInvocationError`` with a remediation hint, and
  treats rc 1 as "issues found" rather than failure.
- ``phone.cli.cmd_profile`` uses ``check=True`` so an openssl failure aborts.
- ``core.gh_cli`` raises ``CLIError``, or ``SystemExit`` with an install URL.

So this returns a result and never raises on a non-zero exit; each caller keeps
its own translation. ``check=True``-style behaviour stays at the call site,
where the error message can say what the failure meant.
"""
from __future__ import annotations

import subprocess  # nosec B404 - deliberate; the single call site below is B603-reviewed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

__all__ = ["CompletedRun", "RC_NOT_FOUND", "RC_TIMEOUT", "run_binary"]

# Shell conventions: 124 is timeout(1)'s exit status, 127 is "command not found".
RC_TIMEOUT = 124
RC_NOT_FOUND = 127


@dataclass(frozen=True)
class CompletedRun:
    """Raw result of a subprocess call, before any domain interpretation."""

    stdout: str
    stderr: str
    returncode: int
    command: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        """True when the process exited 0.

        Note that a non-zero exit is not automatically an error -- qlty uses
        rc 1 for "issues found" -- so callers decide what it means.
        """
        return self.returncode == 0

    @property
    def timed_out(self) -> bool:
        """True when the call exceeded its timeout."""
        return self.returncode == RC_TIMEOUT

    @property
    def not_found(self) -> bool:
        """True when the binary could not be executed."""
        return self.returncode == RC_NOT_FOUND


def _as_text(value: object, fallback: str = "") -> str:
    """Coerce TimeoutExpired's stdout/stderr, which may be bytes or None."""
    if isinstance(value, bytes):
        return value.decode(errors="ignore")
    if isinstance(value, str):
        return value
    return fallback


def run_binary(
    cmd: Sequence[str],
    *,
    cwd: str | Path | None = None,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
) -> CompletedRun:
    """Run ``cmd`` as a fixed argument vector and capture its text output.

    Never uses ``shell=True``, so no metacharacter in an argument or resolved
    path can be interpreted. Never raises on a non-zero exit; a timeout yields
    ``RC_TIMEOUT`` and a missing or non-executable binary yields
    ``RC_NOT_FOUND``, both with whatever output was captured.
    """
    command = tuple(str(part) for part in cmd)
    if not command:
        # subprocess indexes args[0] before any OSError can be raised, so an
        # empty vector escapes the handler below as IndexError.
        return CompletedRun(
            stdout="", stderr="<empty>: no command given", returncode=RC_NOT_FOUND
        )
    try:
        proc = subprocess.run(  # nosec B603 - fixed arg vector from the caller, never shell=True
            command,
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd is not None else None,
            timeout=timeout,
            env=dict(env) if env is not None else None,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CompletedRun(
            stdout=_as_text(exc.stdout),
            stderr=_as_text(exc.stderr, "timeout") or "timeout",
            returncode=RC_TIMEOUT,
            command=command,
        )
    except FileNotFoundError:
        # ENOENT specifically: the binary is absent. Callers key terser
        # messaging off this, so it must not absorb other OSErrors.
        return CompletedRun(
            stdout="",
            stderr=f"{command[0]}: not found",
            returncode=RC_NOT_FOUND,
            command=command,
        )
    except OSError as exc:
        # Everything else that prevents exec -- permission denied, exec format
        # error, ETXTBSY. Still unrunnable, so the return code is the same, but
        # the errno text is preserved: reporting a non-executable binary as
        # "not found" sends a diagnostics user looking for the wrong problem.
        return CompletedRun(
            stdout="",
            stderr=f"{command[0]}: {exc}",
            returncode=RC_NOT_FOUND,
            command=command,
        )
    return CompletedRun(
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        returncode=proc.returncode,
        command=command,
    )
