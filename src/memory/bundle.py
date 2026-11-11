"""Export bundle construction, serialization/deserialization, and rendering of an imported memory back to nested-dialect markdown."""

from __future__ import annotations

import getpass
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from memory.models import (
    BUNDLE_VERSION,
    ExportedMemory,
    ExportProvenance,
    Memory,
    MemoryBundle,
    Redaction,
)
from memory.redaction import scrub

__all__ = ["build_bundle", "load_bundle", "render_imported_memory", "serialize_bundle"]

_SUPPORTED_FORMATS = ("yaml", "json")

# Namespaced metadata subkey carrying import provenance. Also the marker
# `import --on-conflict overwrite` requires before replacing a file.
IMPORT_MARKER_KEY = "bundle_import"


def _scrub_unknown_keys(
    unknown_keys: dict[str, object], *, anonymize: bool
) -> tuple[dict[str, object], list[Redaction]]:
    scrubbed: dict[str, object] = {}
    redactions: list[Redaction] = []
    for key, value in unknown_keys.items():
        if isinstance(value, str):
            scrubbed_value, found = scrub(value, anonymize=anonymize)
            scrubbed[key] = scrubbed_value
            redactions.extend(found)
        else:
            scrubbed[key] = value
    return scrubbed, redactions


def build_bundle(
    memories: tuple[Memory, ...],
    *,
    anonymize: bool = False,
    include_host: bool = False,
    notes: str | None = None,
) -> MemoryBundle:
    """Build an export bundle from a tuple of Memory objects.

    Scrubs the body AND every frontmatter string value including
    unknown_keys — scrubbing only the body would leak secrets stored in
    metadata. origin_session_id is dropped unconditionally (never scrubbed-
    and-kept — it is a pointer into private transcripts). origin_host is
    populated only under include_host; source_sha256 is computed over the
    pre-scrub in-memory body text (not the on-disk file bytes) so an
    importer can detect divergence from what was exported.
    """
    import socket

    exported: list[ExportedMemory] = []
    exported_at = datetime.now(UTC)
    origin_user = getpass.getuser()
    origin_host = socket.gethostname() if include_host else None
    if anonymize:
        origin_user, _ = scrub(origin_user, anonymize=True)

    for memory in memories:
        scrubbed_body, body_redactions = scrub(memory.body, anonymize=anonymize)
        scrubbed_unknown, unknown_redactions = _scrub_unknown_keys(
            memory.frontmatter.unknown_keys, anonymize=anonymize
        )

        frontmatter = memory.frontmatter
        scrubbed_name, name_redactions = (
            scrub(frontmatter.name, anonymize=anonymize)
            if frontmatter.name
            else (frontmatter.name, [])
        )
        scrubbed_description, description_redactions = (
            scrub(frontmatter.description, anonymize=anonymize)
            if frontmatter.description
            else (frontmatter.description, [])
        )
        scrubbed_frontmatter = type(frontmatter)(
            name=scrubbed_name,
            description=scrubbed_description,
            type=frontmatter.type,
            node_type=frontmatter.node_type,
            origin_session_id=None,
            modified=frontmatter.modified,
            shape=frontmatter.shape,
            unknown_keys=scrubbed_unknown,
        )

        source_sha256 = sha256(memory.body.encode("utf-8")).hexdigest()

        provenance = ExportProvenance(
            origin_project_slug=memory.project_slug,
            origin_repo=None,
            origin_user=origin_user,
            origin_host=origin_host,
            origin_session_id=None,
            exported_at=exported_at,
            exported_by_version=str(BUNDLE_VERSION),
            source_sha256=source_sha256,
        )

        exported.append(
            ExportedMemory(
                frontmatter=scrubbed_frontmatter,
                body=scrubbed_body,
                provenance=provenance,
                redactions=(
                    tuple(body_redactions)
                    + tuple(unknown_redactions)
                    + tuple(name_redactions)
                    + tuple(description_redactions)
                ),
            )
        )

    return MemoryBundle(
        bundle_version=BUNDLE_VERSION,
        created_at=exported_at,
        memories=tuple(exported),
        notes=notes,
    )


def _frontmatter_to_dict(fm: Any) -> dict[str, Any]:
    return {
        "name": fm.name,
        "description": fm.description,
        "type": fm.type.value if fm.type else None,
        "node_type": fm.node_type,
        "modified": fm.modified,
        "shape": fm.shape.value,
        "unknown_keys": fm.unknown_keys,
    }


def _frontmatter_from_dict(data: dict[str, Any]) -> Any:
    from memory.models import MemoryFrontmatter, MemoryType, SchemaShape

    raw_type = data.get("type")
    return MemoryFrontmatter(
        name=data.get("name"),
        description=data.get("description"),
        type=MemoryType(raw_type) if raw_type else None,
        node_type=data.get("node_type"),
        origin_session_id=None,
        modified=data.get("modified"),
        shape=SchemaShape(data.get("shape", "absent")),
        unknown_keys=data.get("unknown_keys") or {},
    )


def serialize_bundle(b: MemoryBundle, fmt: str) -> str:
    """Serialize a MemoryBundle to YAML or JSON wire format.

    The wire format is a YAML/JSON bundle, NOT raw markdown — provenance
    cannot live in frontmatter we do not own without namespace collision
    risk. Datetimes are ISO-8601 strings; unknown_keys are preserved
    verbatim. bundle_version comes from the BUNDLE_VERSION constant.
    """
    if fmt not in _SUPPORTED_FORMATS:
        raise ValueError(
            f"unsupported format: {fmt!r} (expected one of {_SUPPORTED_FORMATS})"
        )

    payload: dict[str, Any] = {
        "bundle_version": b.bundle_version,
        "created_at": b.created_at.isoformat(),
        "notes": b.notes,
        "memories": [
            {
                "frontmatter": _frontmatter_to_dict(em.frontmatter),
                "body": em.body,
                "provenance": {
                    "origin_project_slug": em.provenance.origin_project_slug,
                    "origin_repo": em.provenance.origin_repo,
                    "origin_user": em.provenance.origin_user,
                    "origin_host": em.provenance.origin_host,
                    "origin_session_id": em.provenance.origin_session_id,
                    "exported_at": em.provenance.exported_at.isoformat(),
                    "exported_by_version": em.provenance.exported_by_version,
                    "source_sha256": em.provenance.source_sha256,
                },
                "redactions": [
                    {
                        "rule_id": r.rule_id,
                        "severity": r.severity,
                        "line_no": r.line_no,
                        "matched": r.matched,
                        "replacement": r.replacement,
                    }
                    for r in em.redactions
                ],
            }
            for em in b.memories
        ],
    }

    if fmt == "json":
        return json.dumps(payload, indent=2)
    import yaml

    return yaml.dump(payload, default_flow_style=False, sort_keys=False)


def load_bundle(path: str | Path) -> MemoryBundle:
    """Load a MemoryBundle from a YAML or JSON file.

    Reads every field with .get() and validates bundle_version, raising a
    clear error on mismatch rather than KeyError-ing deep in reconstruction.
    A top level that parses to a non-mapping raises rather than normalizing
    to an empty bundle. Never trust the bundle's self-claimed cleanliness —
    the import CLI re-runs the block-severity scan on ingest regardless of
    what this bundle reports.
    """
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        content = f.read()

    try:
        import yaml

        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError(f"failed to parse bundle at {path}: {exc}") from exc

    if not isinstance(data, dict):
        # ValueError, not TypeError: this is a bundle-schema validation failure,
        # not a Python type error — callers branch on ValueError elsewhere in
        # this function (bundle_version mismatch) and expect the same type.
        raise ValueError(  # noqa: TRY004
            f"bundle at {path} top level must be a mapping, got {type(data).__name__}"
        )

    bundle_version = data.get("bundle_version")
    if bundle_version != BUNDLE_VERSION:
        raise ValueError(
            f"unsupported bundle_version: {bundle_version!r} (expected {BUNDLE_VERSION!r})"
        )

    memories_data = data.get("memories", [])
    if not isinstance(memories_data, list):
        raise ValueError("bundle 'memories' field must be a list")  # noqa: TRY004

    exported: list[ExportedMemory] = []
    for entry in memories_data:
        if not isinstance(entry, dict):
            raise ValueError("each memory in a bundle must be a mapping")  # noqa: TRY004

        frontmatter = _frontmatter_from_dict(entry.get("frontmatter") or {})
        provenance_data = entry.get("provenance") or {}
        provenance = ExportProvenance(
            origin_project_slug=provenance_data.get("origin_project_slug", ""),
            origin_repo=provenance_data.get("origin_repo"),
            origin_user=provenance_data.get("origin_user", ""),
            origin_host=provenance_data.get("origin_host"),
            origin_session_id=None,
            exported_at=datetime.fromisoformat(provenance_data["exported_at"])
            if provenance_data.get("exported_at")
            else datetime.now(UTC),
            exported_by_version=provenance_data.get("exported_by_version", ""),
            source_sha256=provenance_data.get("source_sha256", ""),
        )
        redactions = tuple(
            Redaction(
                rule_id=r.get("rule_id", ""),
                severity=r.get("severity", "warn"),
                line_no=r.get("line_no", 0),
                matched=r.get("matched", ""),
                replacement=r.get("replacement", ""),
            )
            for r in entry.get("redactions", [])
        )

        exported.append(
            ExportedMemory(
                frontmatter=frontmatter,
                body=entry.get("body", ""),
                provenance=provenance,
                redactions=redactions,
            )
        )

    created_at_raw = data.get("created_at")
    created_at = (
        datetime.fromisoformat(created_at_raw) if created_at_raw else datetime.now(UTC)
    )

    return MemoryBundle(
        bundle_version=bundle_version,
        created_at=created_at,
        memories=tuple(exported),
        notes=data.get("notes"),
    )


def render_imported_memory(
    em: ExportedMemory, *, prefix: str = "imported_"
) -> str:  # NOSONAR - prefix is part of the public render_imported_memory/import contract for the caller's slug/filename construction (see cli/import_cmd.py), not the rendered body; kept for interface symmetry, intentionally unused here.
    """Render an imported ExportedMemory back to NESTED-dialect markdown.

    Always emits the NESTED dialect (metadata.type, node_type: memory)
    regardless of the source's original shape — files written by this CLI
    are canonical-shaped. Provenance is written under a namespaced
    metadata.bundle_import subkey so it can never collide with a native
    Claude Code frontmatter field; that subkey is also the marker
    `import --on-conflict overwrite` checks before replacing a file.
    originSessionId is never written, in either dialect or the namespaced
    subkey.
    """
    fm = em.frontmatter
    reserved_keys = {"node_type", "type", IMPORT_MARKER_KEY}
    safe_unknown_keys = {
        k: v for k, v in fm.unknown_keys.items() if k not in reserved_keys
    }
    metadata: dict[str, Any] = {"node_type": "memory"}
    if fm.type:
        metadata["type"] = fm.type.value
    metadata.update(safe_unknown_keys)
    metadata[IMPORT_MARKER_KEY] = {
        "origin_project_slug": em.provenance.origin_project_slug,
        "origin_repo": em.provenance.origin_repo,
        "origin_user": em.provenance.origin_user,
        "origin_host": em.provenance.origin_host,
        "exported_at": em.provenance.exported_at.isoformat(),
        "exported_by_version": em.provenance.exported_by_version,
        "source_sha256": em.provenance.source_sha256,
    }

    frontmatter_dict: dict[str, Any] = {"metadata": metadata}
    if fm.name:
        frontmatter_dict["name"] = fm.name
    if fm.description:
        frontmatter_dict["description"] = fm.description

    import yaml

    frontmatter_yaml = yaml.dump(
        frontmatter_dict, default_flow_style=False, sort_keys=False
    ).rstrip("\n")
    return f"---\n{frontmatter_yaml}\n---\n\n{em.body}"
