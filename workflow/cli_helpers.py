"""Shared CLI helpers for ``./bin/workflow``.

Provides precise error messages when a workflow YAML path cannot be found,
including detection of stale worktree paths.
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = [
    "check_workflow_path",
    "format_workflow_not_found",
    "is_stale_worktree_path",
    "list_available_workflows",
]

_WORKTREE_MARKER = ".claude/worktrees/"

_EXCLUDED_SUBDIRS = {"shared", "hints"}


def is_stale_worktree_path(path: str | Path) -> bool:
    """Return True when *path* references a missing parent under ``.claude/worktrees/``."""
    path_str = str(path)
    if _WORKTREE_MARKER not in path_str:
        return False
    parent = Path(path_str).parent
    return not parent.exists()


def list_available_workflows(repo_root: Path | None = None) -> list[str]:
    """Return sorted relative paths of workflow ``*.yaml`` files in *repo_root*."""
    root = repo_root or Path.cwd()
    workflows_dir = root / "workflows"
    if not workflows_dir.is_dir():
        return []
    return sorted(
        str(p.relative_to(root))
        for p in workflows_dir.rglob("*.yaml")
        if not _EXCLUDED_SUBDIRS.intersection(p.relative_to(workflows_dir).parts[:-1])
    )


def format_workflow_not_found(
    path: str | Path,
    *,
    label: str = "workflow",
    repo_root: Path | None = None,
) -> str:
    """Build a multi-line error message for a missing workflow path."""
    lines: list[str] = []
    if is_stale_worktree_path(path):
        lines.append(f"Error: {label} path not found: {path}")
        lines.append(
            "This looks like a path from a deleted worktree (.claude/worktrees/...)."
        )
        lines.append(
            "Use a relative path instead, e.g.: "
            "./bin/workflow status workflows/<name>.yaml"
        )
    else:
        lines.append(f"Error: {label} file not found: {path}")

    available = list_available_workflows(repo_root=repo_root)
    if available:
        lines.append("Available workflows:")
        lines.extend(f"  - {entry}" for entry in available)
    else:
        lines.append("No workflows/ directory found in current directory.")

    return "\n".join(lines)


def check_workflow_path(path: str) -> bool:
    """Return True when *path* exists; print a friendly error to stderr otherwise."""
    if Path(path).is_file():
        return True
    print(format_workflow_not_found(path), file=sys.stderr)
    return False
