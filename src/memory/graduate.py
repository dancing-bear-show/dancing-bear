"""Surgical single-memory graduation from a non-canonical store into the canonical store.

Unlike consolidate (which merges all non-canonical stores), graduate promotes
exactly one memory at a time — safe to run interactively and inside pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.fileutil import atomic_copy, file_sha256
from memory.index import append_entry, parse_index
from memory.models import Memory, MemoryStore

__all__ = [
    "GraduateResult",
    "graduate_memory",
]

_ACTION_GRADUATED = "graduated"
_ACTION_SKIPPED = "skipped"
_ACTION_DRY_RUN = "dry-run"


@dataclass(frozen=True)
class GraduateResult:
    """Outcome of a single graduate_memory call."""

    slug: str
    action: str
    source_path: str
    dest_path: str


class GraduateError(Exception):
    """Raised when graduation cannot proceed safely."""


def _find_memory_by_slug(store: MemoryStore, slug: str) -> Memory:
    """Resolve slug (exact or unique prefix match) in store; raise GraduateError on ambiguity or miss."""
    key = slug.removesuffix(".md")
    exact = [m for m in store.memories if m.slug == key]
    if len(exact) == 1:
        return exact[0]
    prefix = [m for m in store.memories if m.slug.startswith(key)]
    if len(prefix) == 1:
        return prefix[0]
    if not prefix:
        raise GraduateError(f"no memory matches '{slug}' in store '{store.project_slug}'")
    candidates = ", ".join(m.slug for m in prefix)
    raise GraduateError(f"ambiguous — matches: {candidates}")


def graduate_memory(
    slug: str,
    source: MemoryStore,
    canonical: MemoryStore,
    *,
    dry_run: bool = False,
    yes: bool = False,
) -> GraduateResult:
    """Graduate one memory from source into canonical.

    Raises GraduateError when:
    - source IS the canonical store (nothing to graduate)
    - the slug does not resolve, or resolves ambiguously
    - the destination has a diverged copy and yes=False

    With yes=True a diverged destination is copied to ``<name>.md.bak`` first.
    """
    if source.root == canonical.root:
        raise GraduateError(f"source store '{source.project_slug}' is already the canonical store")

    memory = _find_memory_by_slug(source, slug)
    src_path = Path(memory.path)

    canonical_memory_dir = Path(canonical.root) / "memory"
    dest_path = canonical_memory_dir / src_path.name

    if dest_path.exists():
        src_hash = file_sha256(src_path)
        dest_hash = file_sha256(dest_path)
        if src_hash == dest_hash:
            return GraduateResult(
                slug=memory.slug,
                action=_ACTION_SKIPPED,
                source_path=str(src_path),
                dest_path=str(dest_path),
            )
        # Diverged — require explicit confirmation
        if not yes:
            raise GraduateError(
                f"'{memory.slug}.md' exists in canonical store with different content. "
                "Run with --yes to overwrite."
            )

    if dry_run:
        return GraduateResult(
            slug=memory.slug,
            action=_ACTION_DRY_RUN,
            source_path=str(src_path),
            dest_path=str(dest_path),
        )

    if dest_path.exists():
        # Diverged copy being overwritten (--yes): keep a recoverable .bak,
        # the same convention validate --fix uses.
        atomic_copy(dest_path, dest_path.with_suffix(dest_path.suffix + ".bak"))
    atomic_copy(src_path, dest_path)

    # Update canonical index only when the memory was indexed in the source
    # store and the canonical index does not already list it (an overwrite
    # under --yes would otherwise add a duplicate entry).
    if memory.indexed and canonical.index_path:
        indexed = {e.target for e in parse_index(canonical.index_path)}
        if dest_path.name not in indexed:
            append_entry(canonical.index_path, memory)

    return GraduateResult(
        slug=memory.slug,
        action=_ACTION_GRADUATED,
        source_path=str(src_path),
        dest_path=str(dest_path),
    )
