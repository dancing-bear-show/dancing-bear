"""CLI subcommand: import a MemoryBundle into the current store.

Re-scans every body for block-severity redactions on ingest regardless of
what the bundle reports. Renders as nested-dialect markdown with namespaced
provenance. Disposition table (slug/action/target/reason) is emitted for
every processed memory.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from core.cli_output import emit_rows
from core.fileutil import atomic_write_text
from core.text_utils import slugify
from memory.commands._common import DRY_RUN_ARG, ArgSpec, format_arg, validation_error
from memory.bundle import IMPORT_MARKER_KEY, load_bundle, render_imported_memory
from memory.discovery import discover_stores, resolve_current_store
from memory.index import append_entry
from memory.models import ExportedMemory, MemoryStore
from memory.redaction import has_blocking, scan

_IMPORT_HEADERS = ["slug", "action", "target", "reason"]
_NATIVE_GUARD_MARKER = IMPORT_MARKER_KEY
_OVERWRITE_ERROR = (
    "{slug}.md is a native memory (no metadata." + IMPORT_MARKER_KEY + "). "
    "import --on-conflict overwrite cannot replace native memories. "
    "Use `rename` or manual deletion, then re-import."
)


def _disposition(slug: str, action: str, target: str, reason: str) -> dict:
    """Build one import disposition row (keys match _IMPORT_HEADERS)."""
    return {"slug": slug, "action": action, "target": target, "reason": reason}


def _slugify(name: str) -> str:
    """Convert a frontmatter name to a safe filename stem."""
    slug = slugify(name)
    return slug or "memory"


def _prefix_issue(prefix: str) -> str | None:
    """Return why *prefix* is unsafe as a filename prefix, or None if it is safe.

    The prefix is joined straight into ``<store>/memory/<prefix><slug>.md``.
    The slug is already reduced to ``[a-z0-9_]``, so the prefix is the only
    way that join can leave the memory directory: a path separator
    (``../../x`` or an absolute ``/tmp/x``) or, on Windows, a drive
    qualifier (``D:`` has no separator, yet ``D:x.md`` joined to a store on
    C: lands in D:'s current directory). Refuse both before any write.
    """
    separators = [sep for sep in ("/", os.sep, os.altsep) if sep]
    if any(sep in prefix for sep in separators):
        return (
            f"must be a plain filename prefix without path separators (got {prefix!r})"
        )
    if os.path.splitdrive(prefix)[0]:
        return f"must not be drive-qualified (got {prefix!r})"
    return None


def _derive_slug(em: ExportedMemory, counter: int) -> str:
    """Derive a slug from the exported memory's frontmatter name or a counter."""
    name = em.frontmatter.name
    if name:
        return _slugify(name)
    return f"memory_{counter:04d}"


def _is_native_file(path: Path) -> bool:
    """Return True if the file lacks the import provenance marker."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return _NATIVE_GUARD_MARKER not in text
    except OSError:
        return True  # Treat unreadable as native to be safe


def _write_atomic(content: str, dest: Path) -> None:
    """Write content to dest atomically, refusing a symlink at dest.

    New memory files stay owner-only, matching the NamedTemporaryFile-based
    writer this replaced; memory bodies can quote internal context.
    """
    atomic_write_text(dest, content, refuse_symlink=True, new_file_mode=0o600)


def _resolve_conflict(
    target_path: Path,
    target_filename: str,
    slug: str,
    prefix: str,
    on_conflict: str,
    *,
    dry_run: bool,
) -> tuple[Path, str, str, str] | dict:
    """Resolve a potential filename conflict for one import.

    Returns (target_path, target_filename, action, reason) on success, or a
    disposition dict the caller must return immediately (skip/error cases).
    """
    if not target_path.exists():
        return target_path, target_filename, "imported", "new memory"

    if on_conflict == "skip":
        return _disposition(slug, "skipped", target_filename, "file exists")

    if on_conflict == "rename":
        n = 1
        while target_path.exists():
            target_filename = f"{prefix}{slug}_{n}.md"
            target_path = target_path.parent / target_filename
            n += 1
        return (
            target_path,
            target_filename,
            "renamed",
            f"conflict resolved to {target_filename}",
        )

    # on_conflict == "overwrite" (the only remaining argparse choice)
    if _is_native_file(target_path):
        return _disposition(
            slug, "error", target_filename, _OVERWRITE_ERROR.format(slug=slug)
        )
    if not dry_run:
        shutil.copy2(str(target_path), str(target_path) + ".bak")
    return (
        target_path,
        target_filename,
        "overwrite",
        "replacing previously-imported memory",
    )


def _reindex_written_memory(
    target_path: Path, target_filename: str, store: MemoryStore
) -> None:
    """Best-effort: append the written memory to MEMORY.md. Import already
    succeeded by the time this runs — a reindex failure is a warning, not a
    reason to fail the import."""
    if not store.index_path:
        return
    try:
        from memory.parser import parse_memory_file

        written_memory = parse_memory_file(target_path, project_slug=store.project_slug)
        append_entry(store.index_path, written_memory, section=None)
    except (
        Exception
    ) as exc:  # NOSONAR - reindex is best-effort; import succeeds regardless
        print(f"Warning: reindex failed for {target_filename}: {exc}", file=sys.stderr)


def _process_memory(
    em: ExportedMemory,
    counter: int,
    *,
    store: MemoryStore,
    prefix: str,
    on_conflict: str,
    dry_run: bool,
    reindex: bool,
) -> dict:
    """Process a single ExportedMemory; return a disposition row dict."""
    slug = _derive_slug(em, counter)
    target_filename = f"{prefix}{slug}.md"
    target_path = Path(store.root) / "memory" / target_filename

    resolved = _resolve_conflict(
        target_path, target_filename, slug, prefix, on_conflict, dry_run=dry_run
    )
    if isinstance(resolved, dict):
        return resolved
    target_path, target_filename, action, reason = resolved

    if not dry_run:
        rendered = render_imported_memory(em, prefix=prefix)
        try:
            _write_atomic(rendered, target_path)
        except OSError as exc:
            return _disposition(slug, "error", target_filename, str(exc))

        if reindex:
            _reindex_written_memory(target_path, target_filename, store)

    return _disposition(slug, action, target_filename, reason)


ARGUMENTS: list[ArgSpec] = [
    (("bundle_path",), {"help": "Bundle file (YAML or JSON)"}),
    (("--on-conflict",), {"choices": ["skip", "rename", "overwrite"], "default": "skip", "help": "Existing-file policy"}),
    (("--reindex",), {"action": "store_true", "help": "Append imports to MEMORY.md"}),
    (("--prefix",), {"default": "imported_", "help": "Filename prefix for imports"}),
    format_arg(["json", "table", "csv"], "json"),
    DRY_RUN_ARG,
]


def run(args: argparse.Namespace) -> int:
    """Import a memory bundle into the current repo's store."""
    prefix_issue = _prefix_issue(args.prefix)
    if prefix_issue is not None:
        return validation_error("--prefix", prefix_issue)

    try:
        bundle = load_bundle(args.bundle_path)
    except Exception as exc:  # NOSONAR - CLI boundary: surface as a validation error, never a raw traceback
        return validation_error("bundle_path", f"could not load bundle: {exc}")

    # Re-scan every body — never trust the bundle's self-reported cleanliness
    combined_redactions = tuple(r for em in bundle.memories for r in scan(em.body))
    if has_blocking(combined_redactions):
        return validation_error("bundle", "contains blocking redaction issues and cannot be imported")

    all_stores = discover_stores()
    store = resolve_current_store(all_stores)
    if store is None:
        print("No memory stores found.", file=sys.stderr)
        return 1

    dispositions: list[dict] = []
    for counter, em in enumerate(bundle.memories, start=1):
        row = _process_memory(
            em,
            counter,
            store=store,
            prefix=args.prefix,
            on_conflict=args.on_conflict,
            dry_run=args.dry_run,
            reindex=args.reindex,
        )
        dispositions.append(row)

    return emit_rows(dispositions, args.format, headers=_IMPORT_HEADERS, structured_empty=True)
