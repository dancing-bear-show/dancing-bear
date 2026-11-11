"""Local-only git backup of memory stores — explicit-path staging, no remote."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from shutil import copy2

from memory.models import MemoryStore

__all__ = ["BackupResult", "BackupStatus", "backup_status", "backup_stores"]


@dataclass(frozen=True)
class BackupResult:
    """Outcome of a backup operation.

    commit_sha is str | None because a backup with no changes produces no
    commit; callers must distinguish "nothing to do" from "committed".
    failed is True only for a genuine git subprocess failure (init/add/commit
    returning a non-zero exit for a reason other than "nothing to commit")
    — callers must surface this distinctly from commit_sha=None, which is
    also the no-op sentinel and is not itself a failure.
    """

    dest: str
    files_staged: tuple[str, ...]
    commit_sha: str | None
    message: str
    created_repo: bool
    failed: bool = False


@dataclass(frozen=True)
class BackupStatus:
    """Read-only snapshot of a backup repo's state, as reported by backup_status().

    initialized is False (with dirty=False) when no backup repo exists yet
    at the destination — this is a reportable state, not an error.
    """

    initialized: bool  # noqa - read via dataclasses.asdict in memory/commands/backup.py
    last_commit: str | None
    dirty: bool
    message: str


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 B607 - fixed git argv, list form, no shell
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False
    )


def _init_repo_if_absent(dest_path: Path) -> tuple[bool, BackupResult | None]:
    """Initialize a git repo at dest_path if one doesn't exist yet.

    Returns (created_repo, error_result). error_result is non-None only when
    `git init` itself failed — the caller must return it immediately.
    """
    if (dest_path / ".git").exists():
        return False, None
    dest_path.mkdir(parents=True, exist_ok=True)
    result = _run_git(["init"], cwd=dest_path)
    if result.returncode != 0:
        return False, BackupResult(
            dest=str(dest_path),
            files_staged=(),
            commit_sha=None,
            message=f"git init failed: {result.stderr}",
            created_repo=False,
            failed=True,
        )
    return True, None


def _copy_store_files(stores: tuple[MemoryStore, ...], dest_path: Path) -> list[str]:
    """Copy each memory file to dest, explicit path by explicit path."""
    files_staged: list[str] = []
    for store in stores:
        for memory in store.memories:
            src = Path(memory.path)
            if not src.exists():
                continue
            dest_file = dest_path / f"{store.project_slug}__{src.name}"
            copy2(src, dest_file)
            files_staged.append(str(dest_file))
    return files_staged


def _stage_files(
    files_staged: list[str], dest_path: Path, *, created_repo: bool
) -> BackupResult | None:
    """Stage each file explicitly. Returns an error BackupResult on the first
    failure, or None if every file staged successfully."""
    for file_path in files_staged:
        # git add is run with cwd=dest_path (the repo root); pass a path
        # relative to that root rather than the absolute path so `git add`
        # doesn't have to resolve an absolute path against its worktree root.
        relative_path = Path(file_path).name
        # "--" ends option parsing: staged names are "<project_slug>__<file>"
        # and Claude project slugs begin with "-" ("-Users-..."), which git
        # would otherwise parse as a cluster of short options.
        result = _run_git(["add", "--", relative_path], cwd=dest_path)
        if result.returncode != 0:
            return BackupResult(
                dest=str(dest_path),
                files_staged=tuple(files_staged),
                commit_sha=None,
                message=f"git add failed for {file_path}: {result.stderr}",
                created_repo=created_repo,
                failed=True,
            )
    return None


def _commit_and_resolve_sha(
    message: str, dest_path: Path, files_staged: list[str], *, created_repo: bool
) -> BackupResult:
    result = _run_git(["commit", "-m", message], cwd=dest_path)
    # git commit exits 0 on a genuine commit. A non-zero exit with "nothing
    # to commit" in stdout is the documented no-op case, not a failure. Any
    # other non-zero exit (e.g. a pre-commit hook rejecting the commit) is a
    # real failure and must be surfaced, never silently collapsed into the
    # same commit_sha=None sentinel as "nothing to do".
    if result.returncode != 0 and "nothing to commit" not in result.stdout:
        return BackupResult(
            dest=str(dest_path),
            files_staged=tuple(files_staged),
            commit_sha=None,
            message=f"git commit failed: {result.stderr or result.stdout}",
            created_repo=created_repo,
            failed=True,
        )

    commit_sha = None
    if result.returncode == 0:
        # Resolve the SHA directly rather than scraping the bracketed summary
        # line, which embeds the branch name (e.g. "[master abc1234]") and
        # silently fails to match on any non-master/main default branch.
        sha_result = _run_git(["rev-parse", "HEAD"], cwd=dest_path)
        if sha_result.returncode == 0:
            commit_sha = sha_result.stdout.strip()

    return BackupResult(
        dest=str(dest_path),
        files_staged=tuple(files_staged),
        commit_sha=commit_sha,
        message=message,
        created_repo=created_repo,
    )


def backup_stores(
    stores: tuple[MemoryStore, ...],
    dest: str | Path,
    message: str | None = None,
) -> BackupResult:
    """Stage and commit memory store files to a local-only git repository.

    Args:
        stores: Tuple of MemoryStore instances to back up.
        dest: Destination directory for the backup repo. Created if absent.
        message: Commit message. Defaults to ISO timestamp if None.

    Returns:
        BackupResult with destination, staged files, commit SHA, message, and repo-creation flag.
    """
    dest_path = Path(dest)

    created_repo, init_error = _init_repo_if_absent(dest_path)
    if init_error is not None:
        return init_error

    files_staged = _copy_store_files(stores, dest_path)

    stage_error = _stage_files(files_staged, dest_path, created_repo=created_repo)
    if stage_error is not None:
        return stage_error

    if message is None:
        message = datetime.now(UTC).isoformat()

    return _commit_and_resolve_sha(
        message, dest_path, files_staged, created_repo=created_repo
    )


def backup_status(dest: str | Path) -> BackupStatus:
    """Report backup status without modifying the repository.

    Checks if a backup repo exists at dest, reports last commit time, and
    compares store metadata to the backup state. This is strictly read-only:
    no git init, no add, no commit.

    Args:
        dest: Path to the backup repository.

    Returns:
        BackupStatus. If dest does not exist, returns initialized=False with
        a clear message.
    """
    dest_path = Path(dest)

    if not (dest_path / ".git").exists():
        return BackupStatus(
            initialized=False,
            last_commit=None,
            dirty=False,
            message=f"Backup repo not initialized at {dest}",
        )

    # Check for uncommitted changes
    result = _run_git(["status", "--porcelain"], cwd=dest_path)
    dirty = bool(result.stdout.strip())

    # Get last commit time
    result = _run_git(["log", "-1", "--format=%ai"], cwd=dest_path)
    last_commit = result.stdout.strip() if result.returncode == 0 else None

    return BackupStatus(
        initialized=True,
        last_commit=last_commit,
        dirty=dirty,
        message="Backup repo initialized and readable",
    )
