"""MEMORY.md index parsing and atomic mutation — entry parsing, line rendering, append/remove, duplicate-section merge."""

from __future__ import annotations

import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from memory.models import IndexEntry, Memory

__all__ = [
    "append_entry",
    "merge_duplicate_sections",
    "parse_index",
    "remove_entry",
    "render_index_line",
]

_SECTION_RE = re.compile(r"^## (.+)$")
_ENTRY_RE = re.compile(r"^- \[([^\]]+)\]\(([^)]+)\)(?:\s*—\s*(.*))?$")


def _section_header_name(line: str) -> str | None:
    """Return the stripped section name if line is a '## ' header, else None."""
    match = _SECTION_RE.match(line)
    return match.group(1).strip() if match else None


def parse_index(path: str | Path) -> tuple[IndexEntry, ...]:
    """Parse markdown list lines from MEMORY.md.

    Tracks the enclosing '## ' section header and a 1-indexed line_no on
    each entry. A repeated '## ' header is preserved as separate entries
    under each occurrence — never collapsed — because index-duplicate-section
    detection depends on seeing the repeat. Returns an empty tuple when the
    index file does not exist; a missing MEMORY.md is a normal state, not
    an error.
    """
    path = Path(path)
    if not path.exists():
        return ()

    entries: list[IndexEntry] = []
    current_section = ""

    with open(path, encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.rstrip("\n")
            section_match = _SECTION_RE.match(line)
            if section_match:
                current_section = section_match.group(1).strip()
                continue

            entry_match = _ENTRY_RE.match(line)
            if entry_match:
                title, target, hook = entry_match.groups()
                entries.append(
                    IndexEntry(
                        target=target,
                        title=title,
                        hook=(hook or "").strip(),
                        section=current_section,
                        line_no=line_no,
                    )
                )

    return tuple(entries)


def render_index_line(m: Memory) -> str:
    """Render a Memory as a markdown list line matching the MEMORY.md convention.

    Format: '- [<slug>.md](<slug>.md) — <description>'. Falls back to the
    memory's name when description is None, and never emits the literal
    string 'None' into the index.
    """
    filename = f"{m.slug}.md"
    hook = m.frontmatter.description or m.frontmatter.name or m.slug
    return f"- [{filename}]({filename}) — {hook}"


def _read_lines(path: Path) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f]


def _atomic_write_lines(path: Path, lines: list[str]) -> None:
    """Write lines to path via write-temp-then-os.replace(), never in-place."""
    parent_dir = path.parent
    with NamedTemporaryFile(
        mode="w", dir=parent_dir, delete=False, encoding="utf-8"
    ) as tmp:
        tmp_path = tmp.name
        for line in lines:
            tmp.write(line + "\n")
    os.replace(tmp_path, path)


def append_entry(path: str | Path, m: Memory, *, section: str | None = None) -> None:
    """Atomically append a Memory entry to MEMORY.md under the correct section.

    Inserts under the '## ' section matching the memory's type (defaulting
    from section when provided); creates the header if absent rather than
    appending to an arbitrary trailing section. A non-empty index with no
    '## ' headers at all is flat, so with section=None the line is appended
    at the end instead. Routes the write through
    write-temp-then-os.replace() — a concurrent Claude Code session writing
    MEMORY.md must never observe a half-written index.
    """
    path = Path(path)
    target_section = section or (
        m.frontmatter.type.value if m.frontmatter.type else "Reference"
    )

    lines = _read_lines(path) if path.exists() else []

    # Match section headers case-insensitively: MemoryType.value is lowercase
    # ("feedback", "project") but on-disk headers are capitalized ("## Feedback").
    # An exact-match comparison here would never find the existing section for
    # a memory whose type is the default enum value, creating a second,
    # differently-cased duplicate header instead of appending to the real one.
    target_key = target_section.casefold()
    header_names = [_section_header_name(line) for line in lines]

    # A flat index (no '## ' headers at all, as Claude Code writes today) gets
    # the entry appended at the end; inventing a first section would split it.
    if section is None and lines and not any(header_names):
        lines.append(render_index_line(m))
        _atomic_write_lines(path, lines)
        return

    section_idx = next(
        (
            i
            for i, name in enumerate(header_names)
            if name is not None and name.casefold() == target_key
        ),
        None,
    )
    # Preserve the on-disk header's existing casing if the section already
    # exists; otherwise create a new one in Title Case for consistency.
    header_text = (
        header_names[section_idx] if section_idx is not None else target_section.title()
    )

    if section_idx is None:
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines.append(f"## {header_text}")
        section_idx = len(lines) - 1

    insert_idx = len(lines)
    for i in range(section_idx + 1, len(lines)):
        if _SECTION_RE.match(lines[i]):
            insert_idx = i
            break

    lines.insert(insert_idx, render_index_line(m))
    _atomic_write_lines(path, lines)


def remove_entry(path: str | Path, target: str) -> bool:
    """Atomically remove an entry by target filename.

    Returns True when an entry was removed, False when no entry matched —
    never None, and never reports success for a no-op.
    """
    path = Path(path)
    if not path.exists():
        return False

    lines = _read_lines(path)
    new_lines: list[str] = []
    removed = False
    for line in lines:
        entry_match = _ENTRY_RE.match(line)
        if entry_match and entry_match.group(2) == target:
            removed = True
            continue
        new_lines.append(line)

    if not removed:
        return False

    _atomic_write_lines(path, new_lines)
    return True


def _group_lines_by_section(
    lines: list[str],
) -> tuple[list[str], list[str], dict[str, list[str]], int]:
    """Group entry lines under their canonical (case-folded) section header.

    Returns (section_order, preamble, section_entries, duplicate_count).
    Header matching is case-insensitive: MemoryType.value is lowercase but
    on-disk headers are capitalized, so "## Feedback" and a later
    "## feedback" must merge into one section rather than being treated as
    distinct.
    """
    section_order: list[str] = []
    section_entries: dict[str, list[str]] = {}
    canonical_name: dict[str, str] = {}
    preamble: list[str] = []
    duplicate_count = 0
    current_section: str | None = None

    for line in lines:
        section_match = _SECTION_RE.match(line)
        if section_match:
            name = section_match.group(1).strip()
            key = name.casefold()
            if key in canonical_name:
                duplicate_count += 1
            else:
                canonical_name[key] = name
                section_entries[name] = []
                section_order.append(name)
            current_section = canonical_name[key]
            continue

        if current_section is None:
            if line.strip():
                preamble.append(line)
        elif _ENTRY_RE.match(line):
            section_entries[current_section].append(line)

    return section_order, preamble, section_entries, duplicate_count


def merge_duplicate_sections(path: str | Path) -> int:
    """Merge repeated '## ' headers into the first occurrence.

    Preserves entry order within the merged section and returns the number
    of duplicate headers collapsed. Zero duplicates found means return 0
    and leave the file byte-identical rather than rewriting it. Atomic
    write via os.replace().
    """
    path = Path(path)
    if not path.exists():
        return 0

    lines = _read_lines(path)
    section_order, preamble, section_entries, duplicate_count = _group_lines_by_section(
        lines
    )

    if duplicate_count == 0:
        return 0

    new_lines: list[str] = list(preamble)
    for name in section_order:
        if new_lines and new_lines[-1].strip() != "":
            new_lines.append("")
        new_lines.append(f"## {name}")
        new_lines.extend(section_entries[name])

    _atomic_write_lines(path, new_lines)
    return duplicate_count
