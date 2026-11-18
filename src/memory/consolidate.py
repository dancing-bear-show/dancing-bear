"""Zero-loss multi-store consolidation — grouping, canonical election, conflict classification, TOCTOU-safe archive-never-delete application."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from core.fileutil import atomic_copy, file_sha256
from core.paths import output_dir
from memory.discovery import elect_canonical
from memory.index import append_entry, parse_index
from memory.models import MemoryStore
from memory.parser import parse_memory_file

_log = logging.getLogger(__name__)

__all__ = [
    "ConsolidationAborted",
    "ConsolidationPlan",
    "ConsolidationResult",
    "apply_plan",
    "plan_consolidation",
]

_VALID_DIVERGENCE_STRATEGIES = ("keep-newest", "keep-both", "prompt")

# Consolidation assumes no concurrent Claude Code session is actively writing
# to the target store. A file touched more recently than this window
# triggers a warning (not an abort) in the apply result.
RECENT_WRITE_WARNING_WINDOW_SECONDS = 60


def default_archive_root() -> Path:
    """``<data-home>/memory/archive`` — resolved per call so env overrides apply."""
    return output_dir("memory") / "archive"


@dataclass(frozen=True)
class ConsolidationPlan:
    """A pure, side-effect-free consolidation decision set.

    scanned_at records the discovery-scan timestamp; apply_plan re-validates
    every canonical-store file's mtime against it before touching anything.
    """

    canonical: MemoryStore
    identical: tuple[str, ...]
    to_copy: tuple[str, ...]
    conflicts: tuple[tuple[str, str], ...]
    to_archive: tuple[str, ...]
    on_divergence: str
    scanned_at: datetime


@dataclass(frozen=True)
class ConsolidationResult:
    """Outcome of applying a ConsolidationPlan."""

    applied: bool
    archived: tuple[str, ...]
    copied: tuple[str, ...]
    superseded: tuple[str, ...]
    warnings: tuple[str, ...]
    dry_run: bool


class ConsolidationAborted(Exception):
    """The user chose to quit at a conflict prompt; no changes were written."""


def _group_by_repo(
    stores: tuple[MemoryStore, ...],
) -> dict[str | None, tuple[MemoryStore, ...]]:
    groups: dict[str | None, list[MemoryStore]] = {}
    for store in stores:
        groups.setdefault(store.inferred_repo, []).append(store)
    # Exclude stores with no inferred_repo — they cannot be meaningfully
    # consolidated since they may belong to unrelated projects.
    groups.pop(None, None)
    return {repo: tuple(group) for repo, group in groups.items()}


def _warn_skipped_repos(
    groups: dict[str | None, tuple[MemoryStore, ...]], target_repo: str | None
) -> None:
    skipped_repos = [repo for repo in groups if repo != target_repo]
    if not skipped_repos:
        return
    _log.warning(
        "Warning: plan_consolidation only consolidates one repo group per "
        "call; skipping %d other repo group(s) (%s) — call again "
        "with --store to target those stores.",
        len(skipped_repos),
        ", ".join(sorted(r for r in skipped_repos if r)),
    )


def _classify_store_files(
    target_group: tuple[MemoryStore, ...], canonical: MemoryStore
) -> tuple[list[str], list[str], list[tuple[str, str]], list[str]]:
    """Classify every non-canonical store's files as identical/to_copy/conflict."""
    canonical_files = {Path(m.path).name: Path(m.path) for m in canonical.memories}

    identical: list[str] = []
    to_copy: list[str] = []
    conflicts: list[tuple[str, str]] = []
    to_archive: list[str] = []

    for store in target_group:
        if store is canonical:
            continue
        for memory in store.memories:
            filename = Path(memory.path).name
            source_path = Path(memory.path)
            canonical_path = canonical_files.get(filename)

            if canonical_path is None:
                to_copy.append(str(source_path))
            elif file_sha256(source_path) == file_sha256(canonical_path):
                identical.append(str(source_path))
            else:
                conflicts.append((str(source_path), str(canonical_path)))
        to_archive.append(store.root)

    return identical, to_copy, conflicts, to_archive


def plan_consolidation(
    stores: tuple[MemoryStore, ...],
    *,
    on_divergence: str = "keep-newest",
) -> ConsolidationPlan:
    """Plan zero-loss consolidation across a repo-group of stores.

    Deterministic, no merge engine: groups stores by inferred_repo, elects
    the canonical store (the store whose decoded repo path exists on disk,
    tie-broken on newest mtime), then classifies every file in every
    non-canonical store as identical (same sha256 as canonical) -> archive
    candidate, absent from canonical -> to_copy, or diverged (same filename,
    different content) -> conflict. on_divergence is validated against the
    exact choice set; an unrecognized value raises. Planning is pure — it
    computes and returns a plan and writes nothing to disk. An empty
    `stores` input returns a plan with no actions rather than indexing an
    empty sequence.
    """
    if on_divergence not in _VALID_DIVERGENCE_STRATEGIES:
        raise ValueError(
            f"unrecognized on_divergence strategy: {on_divergence!r} "
            f"(expected one of {_VALID_DIVERGENCE_STRATEGIES})"
        )

    scanned_at = datetime.now(UTC)

    if not stores:
        empty_store = MemoryStore(
            project_slug="",
            root="",
            memories=(),
            non_memory_files=(),
            index_path=None,
            index_entries=(),
            inferred_repo=None,
            is_worktree_slug=False,
        )
        return ConsolidationPlan(
            canonical=empty_store,
            identical=(),
            to_copy=(),
            conflicts=(),
            to_archive=(),
            on_divergence=on_divergence,
            scanned_at=scanned_at,
        )

    groups = _group_by_repo(stores)
    if not groups:
        # All stores had inferred_repo=None (e.g. non-macOS slug encoding) —
        # cannot consolidate without a decodable repo path; return empty plan.
        empty_store = MemoryStore(
            project_slug="",
            root="",
            memories=(),
            non_memory_files=(),
            index_path=None,
            index_entries=(),
            inferred_repo=None,
            is_worktree_slug=False,
        )
        return ConsolidationPlan(
            canonical=empty_store,
            identical=(),
            to_copy=(),
            conflicts=(),
            to_archive=(),
            on_divergence=on_divergence,
            scanned_at=scanned_at,
        )
    # Operate on the largest repo group (the common case is a single repo's
    # stores); callers wanting per-repo control call this once per group.
    target_repo = max(groups, key=lambda repo: len(groups[repo]))
    target_group = groups[target_repo]
    _warn_skipped_repos(groups, target_repo)

    canonical = elect_canonical(target_group)
    if canonical is None:  # unreachable: target_group is non-empty
        raise RuntimeError("no canonical store elected for a non-empty group")

    identical, to_copy, conflicts, to_archive = _classify_store_files(target_group, canonical)

    return ConsolidationPlan(
        canonical=canonical,
        identical=tuple(identical),
        to_copy=tuple(to_copy),
        conflicts=tuple(conflicts),
        to_archive=tuple(to_archive),
        on_divergence=on_divergence,
        scanned_at=scanned_at,
    )


def _check_no_concurrent_mutation(canonical: MemoryStore, scanned_at: datetime) -> list[str]:
    """Re-stat every canonical file; raise if any mtime moved since scanned_at.

    Returns a list of warnings for files written within the recent-write
    window (informational, not an abort condition).
    """
    warnings: list[str] = []
    now = datetime.now(UTC)
    for memory in canonical.memories:
        path = Path(memory.path)
        if not path.exists():
            raise RuntimeError(f"canonical file vanished since scan: {path}")
        current_mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if current_mtime > scanned_at:
            raise RuntimeError(
                f"aborting: {path} was modified since the discovery scan "
                f"(concurrent write detected) — no changes were applied"
            )
        if (now - current_mtime).total_seconds() < RECENT_WRITE_WARNING_WINDOW_SECONDS:
            warnings.append(
                f"{path} was written within the last {RECENT_WRITE_WARNING_WINDOW_SECONDS}s; "
                "a concurrent Claude Code session may be active"
            )
    return warnings


def _superseded_name(loser: Path, winner: Path) -> str:
    """Compute the archived filename for a keep-both conflict loser.

    Named after the winner (the file that remains canonical) with a suffix
    identifying which store the loser came from, so multiple losers with the
    same filename from different stores don't collide in the archive dir.
    """
    origin_slug = loser.parent.parent.name if loser.parent.name == "memory" else loser.parent.name
    return f"{winner.stem}.superseded-{origin_slug}.md"


def _preview_plan(plan: ConsolidationPlan) -> ConsolidationResult:
    """Build the dry-run preview result without touching the filesystem."""
    superseded = (
        tuple(_superseded_name(Path(loser), Path(winner)) for loser, winner in plan.conflicts)
        if plan.on_divergence == "keep-both"
        else ()
    )
    return ConsolidationResult(
        applied=False,
        archived=tuple(plan.identical) + tuple(plan.to_archive),
        copied=tuple(plan.to_copy),
        superseded=superseded,
        warnings=(),
        dry_run=True,
    )


def _read_choice(stdin: IO[str]) -> str:
    """Read one non-whitespace character from stdin."""
    while True:
        ch = stdin.read(1)
        if ch == "":
            return ""
        stripped = ch.strip().lower()
        if stripped:
            return stripped


def _prompt_conflict_choice(
    loser: Path,
    winner: Path,
    stdin: IO[str],
) -> str:
    """Print conflict info and read one character from stdin. Returns 'k', 'b', or 'q'."""
    loser_stat = loser.stat()
    winner_stat = winner.stat()
    loser_mtime = datetime.fromtimestamp(loser_stat.st_mtime, tz=UTC).isoformat()
    winner_mtime = datetime.fromtimestamp(winner_stat.st_mtime, tz=UTC).isoformat()
    slug = loser.stem
    print(
        f"\nConflict: {slug}\n"
        f"  canonical  {winner.name}  size={winner_stat.st_size}  mtime={winner_mtime}\n"
        f"  loser      {loser.name}   size={loser_stat.st_size}  mtime={loser_mtime}\n"
        "[k]eep-canonical / [b]oth / [q]uit? ",
        end="",
        flush=True,
        file=sys.stderr,
    )
    ch = _read_choice(stdin)
    if ch == "":
        # EOF (piped input exhausted or Ctrl+D) — treat as quit to avoid silently
        # defaulting to keep-canonical for all remaining conflicts.
        return "q"
    if ch not in ("k", "b", "q"):
        print(
            f"\nUnrecognized input {ch!r}. [k]eep-canonical / [b]oth / [q]uit? ",
            end="",
            flush=True,
            file=sys.stderr,
        )
        ch = _read_choice(stdin)
        if ch == "" or ch not in ("k", "b", "q"):
            return "q"
    return ch


_REPLACE = "replace"  # keep-newest: the non-canonical copy is newer and wins
_KEEP = "keep"  # canonical wins; the other copy is archived
_BOTH = "both"  # canonical wins; the other copy is archived as superseded


def _decide_conflict(
    plan: ConsolidationPlan, loser: Path, winner: Path, stdin: IO[str] | None
) -> str:
    """One conflict's decision per on_divergence. Raises ConsolidationAborted on 'q'."""
    if plan.on_divergence == "keep-both":
        return _BOTH
    if plan.on_divergence == "prompt":
        ch = _prompt_conflict_choice(loser, winner, stdin if stdin is not None else sys.stdin)
        if ch == "q":
            raise ConsolidationAborted("aborted at conflict prompt — no changes were applied")
        return _BOTH if ch == "b" else _KEEP
    # keep-newest: strictly newer mtime wins; a tie keeps canonical
    return _REPLACE if loser.stat().st_mtime > winner.stat().st_mtime else _KEEP


def _resolve_conflicts(
    plan: ConsolidationPlan, *, stdin: IO[str] | None
) -> list[tuple[Path, Path, str]]:
    """Decide every conflict before any write."""
    return [
        (Path(loser), Path(winner), _decide_conflict(plan, Path(loser), Path(winner), stdin))
        for loser, winner in plan.conflicts
    ]


def _apply_conflicts(
    decisions: list[tuple[Path, Path, str]], archive_dir: Path
) -> tuple[list[str], list[str], list[str]]:
    """Apply resolved decisions. Returns (archived, superseded, replaced_canonical)."""
    archived: list[str] = []
    superseded: list[str] = []
    replaced: list[str] = []
    for loser, winner, decision in decisions:
        if decision == _BOTH:
            dest = archive_dir / _superseded_name(loser, winner)
            atomic_copy(loser, dest)
            superseded.append(str(dest))
        elif decision == _REPLACE:
            # Archive the canonical copy being replaced before overwriting it.
            dest = archive_dir / f"{winner.stem}.superseded-canonical.md"
            atomic_copy(winner, dest)
            archived.append(str(dest))
            atomic_copy(loser, winner)
            replaced.append(str(winner))
        else:
            dest = archive_dir / loser.name
            atomic_copy(loser, dest)
            archived.append(str(dest))
    return archived, superseded, replaced


def _index_copied(plan: ConsolidationPlan, copied: list[str]) -> None:
    """Append MEMORY.md entries to the canonical store for newly copied files."""
    index_path = plan.canonical.index_path
    if not index_path:
        candidate = Path(plan.canonical.root) / "memory" / "MEMORY.md"
        index_path = str(candidate) if candidate.exists() else None
    if not index_path:
        return
    indexed = {e.target for e in parse_index(index_path)}
    for dest_str in copied:
        dest = Path(dest_str)
        if dest.name in indexed:
            continue
        memory = parse_memory_file(dest, project_slug=plan.canonical.project_slug)
        append_entry(index_path, memory)


def _archive_store_contents(store_root: str, archive_dir: Path) -> None:
    """Copy a non-canonical store's memory files into the archive dir."""
    store_path = Path(store_root)
    if not store_path.exists():
        return
    dest = archive_dir / store_path.name
    dest.mkdir(parents=True, exist_ok=True)
    memory_subdir = store_path / "memory"
    if not memory_subdir.is_dir():
        return
    for src_file in memory_subdir.iterdir():
        if src_file.is_file():
            atomic_copy(src_file, dest / src_file.name)


def apply_plan(
    plan: ConsolidationPlan,
    *,
    archive_dest: str | Path | None = None,
    dry_run: bool = True,
    _stdin: IO[str] | None = None,
) -> ConsolidationResult:
    """Apply a ConsolidationPlan, archiving non-canonical stores and never deleting.

    TOCTOU SAFETY (required): before moving or archiving anything on a real
    apply, re-stats every file in the canonical store and aborts with a
    clear error if any mtime changed since plan.scanned_at. This check only
    runs when dry_run is False — a dry-run preview never acts on the plan,
    so it cannot be aborted by a concurrent write it would never have
    touched. Every mutated file is written via write-temp-then-os.replace(),
    never in-place truncate+write. Emits a warning if any store file was
    written within the last RECENT_WRITE_WARNING_WINDOW_SECONDS (real apply
    only). dry_run defaults to True; under dry_run nothing is written and
    the result enumerates exactly the actions that would have been taken.
    Conflicts are all resolved before the first write; ConsolidationAborted is
    raised (with nothing written) when the user quits a prompt. keep-newest
    replaces the canonical file with a strictly newer copy, archiving the
    replaced one first. Files copied into the canonical store are appended to
    its MEMORY.md.
    No code path here calls os.remove or unlink on a memory file.
    """
    if dry_run:
        return _preview_plan(plan)

    archive_root = Path(archive_dest) if archive_dest is not None else default_archive_root()
    timestamp = plan.scanned_at.strftime("%Y%m%dT%H%M%SZ")
    slug = plan.canonical.project_slug or "unknown"
    archive_dir = archive_root / f"{slug}-{timestamp}"

    # Resolve every conflict (including interactive prompts) before any write,
    # so a quit leaves the stores untouched.
    decisions = _resolve_conflicts(plan, stdin=_stdin)
    warnings = _check_no_concurrent_mutation(plan.canonical, plan.scanned_at)
    canonical_root = Path(plan.canonical.root) / "memory"

    copied: list[str] = []
    for src_str in plan.to_copy:
        src = Path(src_str)
        dest = canonical_root / src.name
        atomic_copy(src, dest)
        copied.append(str(dest))
    _index_copied(plan, copied)

    archived: list[str] = []
    for src_str in plan.identical:
        src = Path(src_str)
        dest = archive_dir / src.name
        atomic_copy(src, dest)
        archived.append(str(dest))

    conflict_archived, superseded, replaced = _apply_conflicts(decisions, archive_dir)
    archived.extend(conflict_archived)
    copied.extend(replaced)

    for store_root in plan.to_archive:
        _archive_store_contents(store_root, archive_dir)

    return ConsolidationResult(
        applied=True,
        archived=tuple(archived),
        copied=tuple(copied),
        superseded=tuple(superseded),
        warnings=tuple(warnings),
        dry_run=False,
    )
