"""Compile-cache subcommand for the workflow CLI.

Handles sha256-keyed compile caching, payload construction,
and the ``compile`` subcommand handler.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from workflow.cli_helpers import check_workflow_path
from workflow.compiler import validate_dag_contracts
from workflow.include import extract_include_entries, resolve_fragment_path


# ---------------------------------------------------------------------------
# Fragment + cache helpers
# ---------------------------------------------------------------------------


def _fragment_bytes(
    yaml_bytes: bytes,
    yaml_path: Path,
    _visited: frozenset[str] | None = None,
) -> bytes:
    """Return concatenated bytes of all fragment files referenced via include:."""
    visited = _visited if _visited is not None else frozenset()
    parts: list[bytes] = []
    for inc in extract_include_entries(yaml_bytes):
        if not isinstance(inc, dict) or "path" not in inc:
            continue
        p = resolve_fragment_path(str(inc["path"]), yaml_path)
        p_key = str(p.resolve())
        if p_key in visited:
            continue
        try:
            frag_content = p.read_bytes()
        except OSError:
            continue
        parts.append(frag_content)
        parts.append(_fragment_bytes(frag_content, p, _visited=visited | {p_key}))
    return b"".join(parts)


def _compile_cache_path(
    yaml_bytes: bytes,
    project_root: str,
    params: list[str],
    yaml_path: Path | None = None,
) -> Path:
    """Return the temp-dir cache file path keyed by YAML content, fragments, root, and params."""
    import tempfile
    frag_bytes = _fragment_bytes(yaml_bytes, yaml_path or Path.cwd())
    key_material = f"{project_root}:{':'.join(sorted(params))}:".encode() + yaml_bytes + frag_bytes
    sha = hashlib.sha256(key_material).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"workflow-compile-{sha}.json"


def _render_compile_output(payload: dict, fmt: str) -> None:
    """Render compile output in the requested format."""
    from workflow.cli import _emit_one, _emit_rows
    _excluded = ("groups", "resolutions", "contract_warnings_detail")
    summary = {k: v for k, v in payload.items() if k not in _excluded}
    groups_raw = payload.get("groups", [])
    resolutions_raw = payload.get("resolutions", [])
    warnings_raw = payload.get("contract_warnings_detail", [])
    groups: list[dict] = groups_raw if isinstance(groups_raw, list) else []
    resolutions: list[dict] = resolutions_raw if isinstance(resolutions_raw, list) else []
    warnings: list[dict] = [
        w for w in (warnings_raw if isinstance(warnings_raw, list) else [])
        if isinstance(w, dict) and w.get("message")
    ]
    for w in warnings:
        print(f"contract warning: {w['message']}", file=sys.stderr)
    if fmt == "table":
        _emit_one(summary, fmt=fmt)
        _emit_rows(groups, fmt=fmt, headers=["group", "stages", "parallelism"])
        _emit_rows(resolutions, fmt=fmt,
                   headers=["stage", "template_resolved", "guide_resolved", "cli_commands"])
        if warnings:
            _emit_rows(warnings, fmt=fmt, headers=["stage", "upstream", "message"])
    else:
        _emit_one(payload, fmt=fmt)


def _try_read_cached_compile(cache_path: Path) -> dict | None:
    """Return the cached compile payload, or None if missing/invalid."""
    if not cache_path.exists():
        return None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return cached if isinstance(cached, dict) else None


def _write_once(path: Path, content: bytes) -> None:
    """Write *content* to *path* only if it does not already exist."""
    import os
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, content)
        finally:
            os.close(fd)
    except OSError:
        pass  # nosec B110 - cache write failure is non-fatal


def _build_compile_payload(path: str) -> dict:
    """Load + compile the workflow and build the cache payload dict."""
    from workflow.cli_dispatch import _load_manifest
    defn, manifest = _load_manifest(path)
    max_par = max((len(g) for g in manifest.parallel_groups), default=0)

    contract_warnings = validate_dag_contracts(defn)

    summary = {
        "name": defn.name, "total_stages": len(manifest.resolved_stages),
        "total_groups": len(manifest.parallel_groups),
        "max_parallelism": max_par, "compiled_at": manifest.compiled_at,
        "contract_warnings": len(contract_warnings),
    }
    groups = [{"group": i, "stages": ", ".join(g), "parallelism": len(g)}
              for i, g in enumerate(manifest.parallel_groups)]
    resolutions = [{
        "stage": name, "template_resolved": r.template_content is not None,
        "guide_resolved": r.guide_content is not None, "cli_commands": len(r.cli_commands),
    } for name, r in manifest.resolved_stages.items()]
    warnings = [{"stage": w.stage, "upstream": w.upstream, "message": w.message}
                for w in contract_warnings]
    return {**summary, "groups": groups, "resolutions": resolutions, "contract_warnings_detail": warnings}


# ---------------------------------------------------------------------------
# Subcommand handler
# ---------------------------------------------------------------------------


def _cmd_compile(args: argparse.Namespace) -> int:
    """Parse + compile, showing the execution plan."""
    if not check_workflow_path(args.path):
        return 1
    yaml_path = Path(args.path)
    try:
        yaml_bytes = yaml_path.read_bytes()
    except OSError as exc:
        print(f"Error reading {args.path}: {exc}", file=sys.stderr)
        return 1

    cache_path = _compile_cache_path(
        yaml_bytes, str(Path.cwd()), getattr(args, "params", []) or [], yaml_path
    )
    if not args.no_cache:
        cached = _try_read_cached_compile(cache_path)
        if cached is not None:
            _render_compile_output(cached, args.format)
            return 0

    payload = _build_compile_payload(args.path)
    _write_once(cache_path, (json.dumps(payload) + "\n").encode())

    _render_compile_output(payload, args.format)
    return 0
