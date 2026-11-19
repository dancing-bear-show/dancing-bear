"""Shared git invocation: one env scrub, one timeout default, one failure contract.

Callers used to run ``git rev-parse --show-toplevel`` (and friends) through
three separate ``subprocess`` call sites with different timeouts and failure
handling, and only one scrubbed the environment. An inherited ``GIT_DIR`` or
``GIT_WORK_TREE`` (set by git hooks, or by a wrapper running inside another
checkout) silently points git at a different repository than ``cwd``.

Failure contract: nothing here raises. :func:`run_git` returns a
:class:`~core.process.CompletedRun` (timeout -> ``timed_out``; missing git ->
``not_found``; non-zero exit -> ``ok`` is False). :func:`git_toplevel` returns
``None`` for any of those.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from core.process import CompletedRun, run_binary

__all__ = ["GIT_ENV_OVERRIDES", "GIT_TIMEOUT_SECONDS", "git_env", "git_toplevel", "run_git"]

GIT_TIMEOUT_SECONDS = 30.0

# Variables that would point git at a different repository than ``cwd``.
GIT_ENV_OVERRIDES = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
)


def git_env() -> dict[str, str]:
    """The current environment minus the variables that redirect git."""
    return {k: v for k, v in os.environ.items() if k not in GIT_ENV_OVERRIDES}


def run_git(
    args: Sequence[str],
    *,
    cwd: str | Path | None = None,
    timeout: float | None = GIT_TIMEOUT_SECONDS,
) -> CompletedRun:
    """Run ``git <args>`` in ``cwd`` with redirecting env vars scrubbed."""
    return run_binary(["git", *args], cwd=cwd, timeout=timeout, env=git_env())


def git_toplevel(
    cwd: str | Path | None = None, *, timeout: float | None = GIT_TIMEOUT_SECONDS
) -> Path | None:
    """Top level of the checkout containing ``cwd``; None on any failure."""
    run = run_git(["rev-parse", "--show-toplevel"], cwd=cwd, timeout=timeout)
    out = run.stdout.strip()
    if not run.ok or not out:
        return None
    return Path(out)
