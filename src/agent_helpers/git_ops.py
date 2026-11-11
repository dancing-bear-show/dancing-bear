"""git-ops: checkout and worktree operations run from the repo root.

Every function returns a result dict; failures are reported via
``status: "error"`` with git's output, never raised.
"""

from __future__ import annotations

from core.process import CompletedRun, run_binary

OP_CHOICES = ("checkout", "worktree-add", "worktree-remove", "worktree-list")

_GIT_TIMEOUT_SECONDS = 60.0
_FETCH_TIMEOUT_SECONDS = 180.0
_DIRTY_MESSAGE = "working tree has uncommitted changes; commit them before switching branches"


def _result(op: str, status: str, output: str, *, branch: str | None = None, path: str | None = None) -> dict:
    return {"op": op, "branch": branch, "path": path, "status": status, "output": output}


def _git(args: list[str], cwd: str, timeout: float = _GIT_TIMEOUT_SECONDS) -> CompletedRun:
    return run_binary(["git", *args], cwd=cwd, timeout=timeout)


def _merged(run: CompletedRun) -> str:
    """Combined stdout+stderr; a timeout is stated explicitly."""
    text = run.stdout + run.stderr
    return f"timed out\n{text}" if run.timed_out else text


def _status(run: CompletedRun) -> str:
    return "ok" if run.ok else "error"


def _is_dirty(cwd: str) -> bool:
    """True when the working tree has uncommitted changes (or status could not be read)."""
    run = _git(["status", "--porcelain"], cwd)
    return not run.ok or bool(run.stdout.strip())


def _bad_ref(value: str | None) -> bool:
    """Reject values git would parse as an option."""
    return value is not None and value.startswith("-")


def op_checkout(repo_root: str, branch: str | None, fetch: bool) -> dict:
    if not branch:
        return _result("checkout", "error", "--branch is required for checkout", branch=branch)
    if _bad_ref(branch):
        return _result("checkout", "error", "--branch must not start with '-'", branch=branch)
    if _is_dirty(repo_root):
        return _result("checkout", "error", _DIRTY_MESSAGE, branch=branch)
    if fetch:
        fetched = _git(["fetch", "origin"], repo_root, _FETCH_TIMEOUT_SECONDS)
        if not fetched.ok:
            return _result("checkout", "error", _merged(fetched), branch=branch)
    run = _git(["checkout", branch], repo_root)
    return _result("checkout", _status(run), _merged(run), branch=branch)


def op_worktree_add(repo_root: str, path: str | None, branch: str | None) -> dict:
    if not path or not branch:
        return _result("worktree-add", "error", "--path and --branch are required for worktree-add",
                       branch=branch, path=path)
    if _bad_ref(path) or _bad_ref(branch):
        return _result("worktree-add", "error", "--path and --branch must not start with '-'",
                       branch=branch, path=path)
    run = _git(["worktree", "add", path, branch], repo_root)
    return _result("worktree-add", _status(run), _merged(run), branch=branch, path=path)


def op_worktree_remove(repo_root: str, path: str | None, then_checkout: str | None) -> dict:
    if not path:
        return _result("worktree-remove", "error", "--path is required for worktree-remove")
    if _bad_ref(path) or _bad_ref(then_checkout):
        return _result("worktree-remove", "error", "--path and --then-checkout must not start with '-'", path=path)
    removed = _git(["worktree", "remove", path], repo_root)
    if not removed.ok:
        return _result("worktree-remove", "error", _merged(removed), path=path)
    if not then_checkout:
        return _result("worktree-remove", "ok", _merged(removed), path=path)
    if _is_dirty(repo_root):
        return _result("worktree-remove", "error", _DIRTY_MESSAGE, branch=then_checkout, path=path)
    switched = _git(["checkout", then_checkout], repo_root)
    return _result("worktree-remove", _status(switched), _merged(removed) + _merged(switched),
                   branch=then_checkout, path=path)


def op_worktree_list(repo_root: str) -> dict:
    run = _git(["worktree", "list"], repo_root)
    return _result("worktree-list", _status(run), _merged(run))
