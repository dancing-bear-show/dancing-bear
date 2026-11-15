"""git-ops: checkout and worktree operations run from the repo root.

Every function returns a GitOpResult; failures are reported via
``status: "error"`` with git's output, never raised.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.process import CompletedRun, run_binary

_GIT_TIMEOUT_SECONDS = 60.0
_FETCH_TIMEOUT_SECONDS = 180.0
_DIRTY_MESSAGE = "working tree has uncommitted changes; commit them before switching branches"

# Status constants
_STATUS_OK = "ok"
_STATUS_ERROR = "error"

# Op-name constants
_OP_CHECKOUT = "checkout"
_OP_WORKTREE_ADD = "worktree-add"
_OP_WORKTREE_REMOVE = "worktree-remove"
_OP_WORKTREE_LIST = "worktree-list"

OP_CHOICES = (_OP_CHECKOUT, _OP_WORKTREE_ADD, _OP_WORKTREE_REMOVE, _OP_WORKTREE_LIST)


@dataclass(frozen=True)
class GitOpResult:
    """Result of a git-ops operation; serialised to JSON at the CLI boundary."""

    op: str
    branch: str | None
    path: str | None
    status: str
    output: str


def _result(op: str, status: str, output: str, *, branch: str | None = None, path: str | None = None) -> GitOpResult:
    return GitOpResult(op=op, branch=branch, path=path, status=status, output=output)


def _git(args: list[str], cwd: str, timeout: float = _GIT_TIMEOUT_SECONDS) -> CompletedRun:
    return run_binary(["git", *args], cwd=cwd, timeout=timeout)


def _merged(run: CompletedRun) -> str:
    """Combined stdout+stderr; a timeout is stated explicitly."""
    text = run.stdout + run.stderr
    return f"timed out\n{text}" if run.timed_out else text


def _status(run: CompletedRun) -> str:
    return _STATUS_OK if run.ok else _STATUS_ERROR


def _is_dirty(cwd: str) -> bool:
    """True when tracked files have uncommitted changes (or status could not be read).

    Untracked files are ignored here.  If one would be overwritten by the target
    branch, git's own checkout aborts and that surfaces as an error result.
    """
    run = _git(["status", "--porcelain", "--untracked-files=no"], cwd)
    return not run.ok or bool(run.stdout.strip())


def _bad_ref(value: str | None) -> bool:
    """Reject values git would parse as an option."""
    return value is not None and value.startswith("-")


def op_checkout(repo_root: str, branch: str | None, fetch: bool) -> GitOpResult:
    if not branch:
        return _result(_OP_CHECKOUT, _STATUS_ERROR, "--branch is required for checkout", branch=branch)
    if _bad_ref(branch):
        return _result(_OP_CHECKOUT, _STATUS_ERROR, "--branch must not start with '-'", branch=branch)
    if _is_dirty(repo_root):
        return _result(_OP_CHECKOUT, _STATUS_ERROR, _DIRTY_MESSAGE, branch=branch)
    if fetch:
        fetched = _git(["fetch", "origin"], repo_root, _FETCH_TIMEOUT_SECONDS)
        if not fetched.ok:
            return _result(_OP_CHECKOUT, _STATUS_ERROR, _merged(fetched), branch=branch)
    run = _git(["checkout", branch], repo_root)
    return _result(_OP_CHECKOUT, _status(run), _merged(run), branch=branch)


def op_worktree_add(repo_root: str, path: str | None, branch: str | None) -> GitOpResult:
    if not path or not branch:
        return _result(_OP_WORKTREE_ADD, _STATUS_ERROR, "--path and --branch are required for worktree-add",
                       branch=branch, path=path)
    if _bad_ref(path) or _bad_ref(branch):
        return _result(_OP_WORKTREE_ADD, _STATUS_ERROR, "--path and --branch must not start with '-'",
                       branch=branch, path=path)
    run = _git(["worktree", "add", path, branch], repo_root)
    return _result(_OP_WORKTREE_ADD, _status(run), _merged(run), branch=branch, path=path)


def op_worktree_remove(repo_root: str, path: str | None, then_checkout: str | None) -> GitOpResult:
    if not path:
        return _result(_OP_WORKTREE_REMOVE, _STATUS_ERROR, "--path is required for worktree-remove")
    if _bad_ref(path) or _bad_ref(then_checkout):
        return _result(_OP_WORKTREE_REMOVE, _STATUS_ERROR, "--path and --then-checkout must not start with '-'", path=path)
    removed = _git(["worktree", "remove", path], repo_root)
    if not removed.ok:
        return _result(_OP_WORKTREE_REMOVE, _STATUS_ERROR, _merged(removed), path=path)
    if not then_checkout:
        return _result(_OP_WORKTREE_REMOVE, _STATUS_OK, _merged(removed), path=path)
    if _is_dirty(repo_root):
        return _result(_OP_WORKTREE_REMOVE, _STATUS_ERROR, _DIRTY_MESSAGE, branch=then_checkout, path=path)
    switched = _git(["checkout", then_checkout], repo_root)
    return _result(_OP_WORKTREE_REMOVE, _status(switched), _merged(removed) + _merged(switched),
                   branch=then_checkout, path=path)


def op_worktree_list(repo_root: str) -> GitOpResult:
    run = _git(["worktree", "list"], repo_root)
    return _result(_OP_WORKTREE_LIST, _status(run), _merged(run))
