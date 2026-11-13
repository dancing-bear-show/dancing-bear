"""Discovers Claude memory stores under ~/.claude/projects, decodes project slugs to repo paths, detects worktree slugs, and elects the canonical store per repo."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from memory.index import parse_index
from memory.models import Memory, MemoryStore
from memory.parser import parse_memory_file

__all__ = [
    "decode_project_slug",
    "discover_stores",
    "elect_canonical",
    "is_worktree_slug",
    "load_store",
    "resolve_current_store",
]

# The on-disk slug encoding replaces every '/' with '-', so a worktree path
# segment ('.claude/worktrees/<name>') survives as this hyphenated substring
# in the RAW slug — it can never be recovered from the decoded path, because
# decode_project_slug only reconstructs the '/' separators around the 'code'
# boundary and leaves every other '/' collapsed to '-' (see its docstring:
# the decoding is inherently lossy).
_WORKTREE_MARKER = "-claude-worktrees-"


def decode_project_slug(slug: str) -> str | None:
    """Decode the '-Users-<name>-code-<repo>' slug encoding to a filesystem path.

    This decoding is inherently lossy — a literal '-' in a directory name is
    indistinguishable from a path separator — so treat existence-on-disk as
    the authority rather than trusting a perfect round-trip. Returns None
    (never '' or '/') when the slug does not encode a decodable path, so
    callers can distinguish "no repo" from "repo at root".
    """
    if not slug:
        return None

    parts = slug.split("-")
    if len(parts) < 4 or parts[0] != "" or parts[1] != "Users":
        return None

    try:
        code_idx = parts.index("code", 2)
    except ValueError:
        return None

    name = "-".join(parts[2:code_idx])
    repo = "-".join(parts[code_idx + 1 :])
    if not name or not repo:
        return None

    return f"/Users/{name}/code/{repo}"


def is_worktree_slug(slug: str) -> bool:
    """Return True when the slug encodes a '.claude/worktrees/<name>' segment.

    Matches on the hyphenated path-segment marker as it actually survives
    in the raw slug (never on a hardcoded absolute prefix such as
    /Users/<name>) — decode_project_slug cannot recover this segment since
    its '/' separators are indistinguishable from ordinary hyphens once
    encoded.
    """
    return _WORKTREE_MARKER in slug


def load_store(slug: str, *, projects_root: str | Path | None = None) -> MemoryStore:
    """Load a MemoryStore from a project slug.

    Parses MEMORY.md first, then each *.md in memory/, passing the index
    entries so indexed/index_hook/index_section are populated. Files whose
    is_memory is False land in non_memory_files rather than being dropped.
    A store whose memory/ directory does not exist yields empty tuples and
    index_path=None rather than raising — "no-memory" is a reportable role.

    Raises ValueError if slug is empty or resolves outside projects_root —
    slug is user-controlled (the --store CLI flag), and unvalidated path
    joining would let a value like "../../etc" escape the projects
    directory entirely.
    """
    root = (
        Path(projects_root)
        if projects_root is not None
        else Path.home() / ".claude" / "projects"
    )
    if not slug:
        raise ValueError("slug must not be empty")
    root_resolved = root.resolve()
    store_dir = (root / slug).resolve()
    if store_dir != root_resolved and root_resolved not in store_dir.parents:
        raise ValueError(f"slug {slug!r} resolves outside the projects root")
    inferred_repo = decode_project_slug(slug)
    memory_dir = store_dir / "memory"

    if not memory_dir.is_dir():
        return MemoryStore(
            project_slug=slug,
            root=str(store_dir),
            memories=(),
            non_memory_files=(),
            index_path=None,
            index_entries=(),
            inferred_repo=inferred_repo,
            is_worktree_slug=is_worktree_slug(slug),
        )

    index_path = memory_dir / "MEMORY.md"
    index_entries = parse_index(index_path) if index_path.exists() else ()

    memories: list[Memory] = []
    non_memory_files: list[str] = []
    for md_file in sorted(memory_dir.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue
        memory = parse_memory_file(
            md_file, project_slug=slug, index_entries=index_entries
        )
        if memory.is_memory:
            memories.append(memory)
        else:
            non_memory_files.append(str(md_file))

    return MemoryStore(
        project_slug=slug,
        root=str(store_dir),
        memories=tuple(memories),
        non_memory_files=tuple(non_memory_files),
        index_path=str(index_path) if index_path.exists() else None,
        index_entries=index_entries,
        inferred_repo=inferred_repo,
        is_worktree_slug=is_worktree_slug(slug),
    )


def discover_stores(root: str | Path | None = None) -> tuple[MemoryStore, ...]:
    """Enumerate every project-slug directory under root and load each store.

    Returns a tuple sorted deterministically by project_slug so table output
    and consolidate planning are reproducible across runs. A missing or
    unreadable projects root prints a warning to stderr and returns an empty
    tuple — never a silent empty result that reads as "no stores exist".
    """
    projects_root = (
        Path(root) if root is not None else Path.home() / ".claude" / "projects"
    )

    if not projects_root.is_dir():
        print(f"Warning: projects root {projects_root} does not exist", file=sys.stderr)
        return ()

    try:
        slugs = sorted(
            entry.name for entry in projects_root.iterdir() if entry.is_dir()
        )
    except OSError as exc:
        print(
            f"Warning: could not read projects root {projects_root}: {exc}",
            file=sys.stderr,
        )
        return ()

    stores: list[MemoryStore] = []
    for slug in slugs:
        try:
            stores.append(load_store(slug, projects_root=projects_root))
        except Exception as exc:  # NOSONAR - one malformed store must not abort discovery for all others; surfaced as a stderr warning, never a silent drop
            print(f"Warning: skipping store {slug!r}: {exc}", file=sys.stderr)
    return tuple(stores)


def _newest_mtime(store: MemoryStore) -> float:
    if not store.memories:
        return 0.0
    return max(m.mtime.timestamp() for m in store.memories)


def elect_canonical(stores: tuple[MemoryStore, ...]) -> MemoryStore | None:
    """Elect the canonical memory store from a set of candidates.

    Selects the store whose decoded inferred_repo path EXISTS on disk,
    tie-broken on newest memory mtime. When no store's repo path exists,
    falls back to the newest-mtime store overall (deterministic, total).
    Returns None only for empty input.
    """
    if not stores:
        return None

    existing = tuple(
        s for s in stores if s.inferred_repo and Path(s.inferred_repo).exists()
    )
    candidates = existing or stores
    return max(candidates, key=lambda s: (_newest_mtime(s), s.project_slug))


def resolve_current_store(stores: tuple[MemoryStore, ...]) -> MemoryStore | None:
    """Pick the store most relevant to the current working directory.

    Prefers a store whose inferred_repo is a path prefix of cwd. Falls back
    to elect_canonical when no repo prefix matches.
    """
    cwd = os.getcwd()
    for store in stores:
        if store.inferred_repo and (
            cwd == store.inferred_repo or cwd.startswith(store.inferred_repo + "/")
        ):
            return store
    return elect_canonical(stores)
