"""Repo-root resolution shared by the agent_helpers subcommands."""

from __future__ import annotations

from pathlib import Path

from core.process import run_binary

_GIT_TIMEOUT_SECONDS = 30.0


def resolve_repo_root(cwd: str | Path | None = None) -> tuple[str, str | None]:
    """Return ``(repo_root, error)``; ``error`` is None on success.

    Callers must check ``error`` before using ``repo_root`` (empty on failure).
    """
    run = run_binary(["git", "rev-parse", "--show-toplevel"], cwd=cwd, timeout=_GIT_TIMEOUT_SECONDS)
    if run.timed_out:
        return "", "git rev-parse timed out"
    if not run.ok:
        return "", "not inside a git repository"
    return run.stdout.strip(), None
