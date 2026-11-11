"""Frozen dataclasses and StrEnums modelling Claude auto-memory files, stores, index entries, and export bundles."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

__all__ = [
    "BUNDLE_VERSION",
    "ExportProvenance",
    "ExportedMemory",
    "IndexEntry",
    "Memory",
    "MemoryBundle",
    "MemoryFrontmatter",
    "MemoryStore",
    "MemoryType",
    "Redaction",
    "SchemaShape",
]


class MemoryType(StrEnum):
    """Memory classification types matching on-disk frontmatter vocabulary."""

    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"


class SchemaShape(StrEnum):
    """Schema dialect variant for memory YAML structure."""

    NESTED = "nested"
    FLAT = "flat"
    ABSENT = "absent"
    NO_FRONTMATTER = "no_frontmatter"


@dataclass(frozen=True)
class MemoryFrontmatter:
    """Frontmatter metadata from a memory's --- YAML block."""

    name: str | None
    description: str | None
    type: MemoryType | None
    node_type: str | None
    origin_session_id: str | None
    modified: str | None
    shape: SchemaShape
    unknown_keys: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Memory:
    """Single memory file in the store with parsed frontmatter and body."""

    slug: str
    path: str
    project_slug: str
    frontmatter: MemoryFrontmatter
    body: str
    why: str | None
    how_to_apply: str | None
    wikilinks: tuple[str, ...]
    mtime: datetime
    size_bytes: int
    indexed: bool
    index_hook: str | None
    index_section: str | None

    @property
    def is_memory(self) -> bool:
        """Return True if this file is a valid memory (not just a scratch document)."""
        return self.frontmatter.shape not in (
            SchemaShape.NO_FRONTMATTER,
            SchemaShape.ABSENT,
        )


@dataclass(frozen=True)
class IndexEntry:
    """Single entry from a memory index linking to a fragment of another memory."""

    target: str
    title: str
    hook: str
    section: str
    line_no: int


@dataclass(frozen=True)
class MemoryStore:
    """Complete snapshot of a project's memory directory with parsed files and index."""

    project_slug: str
    root: str
    memories: tuple[Memory, ...]
    non_memory_files: tuple[str, ...]
    index_path: str | None
    index_entries: tuple[IndexEntry, ...]
    inferred_repo: str | None
    is_worktree_slug: bool


@dataclass(frozen=True)
class ExportProvenance:
    """Metadata tracking the origin and export context of a memory bundle."""

    origin_project_slug: str
    origin_repo: str | None
    origin_user: str
    origin_host: str | None
    origin_session_id: str | None
    exported_at: datetime
    exported_by_version: str
    source_sha256: str


@dataclass(frozen=True)
class Redaction:
    """Record of a single secret redaction applied during bundle export."""

    rule_id: str
    severity: str
    line_no: int
    matched: str
    replacement: str


@dataclass(frozen=True)
class ExportedMemory:
    """Memory after secret redaction, ready for export in a bundle."""

    frontmatter: MemoryFrontmatter
    body: str
    provenance: ExportProvenance
    redactions: tuple[Redaction, ...]


BUNDLE_VERSION = 1


@dataclass(frozen=True)
class MemoryBundle:
    """Serializable container for one or more exported memories."""

    bundle_version: int = BUNDLE_VERSION
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    memories: tuple[ExportedMemory, ...] = field(default_factory=tuple)
    notes: str | None = None
