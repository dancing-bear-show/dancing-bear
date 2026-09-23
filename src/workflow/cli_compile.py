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

from core.fileutil import write_once
from workflow.cli_helpers import check_workflow_path
from workflow.compiler import match_when_expression, validate_dag_contracts
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


# Bump whenever _build_compile_payload's key set OR the meaning of an
# existing value changes. Schema 5 kept the key set of 4 but made will_run
# depend on --params overrides and on whitespace-normalised when expressions,
# so a v4 entry can hold a stale decision for the same YAML. The cache key is
# derived from YAML + root + params, so without this a payload cached before a
# schema change is still served and silently lacks the new fields — e.g. a
# pre-existing cache would drop agent_isolation, making `isolation: worktree` a
# no-op again for any workflow that had already been compiled once.
# Schema 6 changes no key: it invalidates entries cached before compile
# enforced trigger param_rules, which were written without that check.
_COMPILE_PAYLOAD_SCHEMA = 6


def _compile_cache_path(
    yaml_bytes: bytes,
    project_root: str,
    params: list[str],
    yaml_path: Path | None = None,
) -> Path:
    """Return the temp-dir cache file path keyed by payload schema, YAML content, fragments, root, and params."""
    import tempfile
    frag_bytes = _fragment_bytes(yaml_bytes, yaml_path or Path.cwd())
    key_material = (
        f"v{_COMPILE_PAYLOAD_SCHEMA}:{project_root}:{':'.join(sorted(params))}:".encode()
        + yaml_bytes
        + frag_bytes
    )
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
    try:
        write_once(path, content)
    except OSError:  # nosec B110 - cache write failure (incl. already-exists race) is non-fatal
        pass


def _eval_when_for_manifest(when: str | None, params: dict[str, str]) -> bool:
    """Whether a stage's ``when`` holds, for the compiled manifest.

    Shares ``compiler.match_when_expression`` with ``orchestrator._eval_when``
    so the manifest cannot disagree with the runtime about which branch
    executes. An unrecognised expression returns True (run it) rather than
    raising: the compiler already rejects malformed ``when`` clauses via
    ``_validate_when``, and a manifest field is not the place to fail a build.
    """
    if when is None:
        return True

    result = match_when_expression(when, params)
    return True if result is None else result


def _parse_param_overrides(raw: list[str] | None) -> dict[str, str]:
    """Parse repeatable ``--params key=value`` into a dict.

    Entries without "=" are ignored rather than raising: the run path already
    reports malformed params. Silently dropping one here cannot select a wrong
    branch — an unresolved {placeholder} is left as-is by resolve_params,
    which the evaluators treat as a non-match — nor bypass param_rules, since
    a dropped entry never reaches the compiled output at all.
    """
    out: dict[str, str] = {}
    for item in raw or []:
        key, sep, value = item.partition("=")
        if sep:
            out[key.strip()] = value
    return out


def _build_compile_payload(path: str, param_overrides: list[str] | None = None) -> dict:
    """Load + compile the workflow and build the cache payload dict.

    *param_overrides* are the caller's ``--params key=value`` entries. They
    must reach `will_run`: the runtime merges overrides over the declared
    trigger params, so computing the manifest from declared params alone
    would advertise the default branch while execution took the other one.
    """
    from workflow.cli_dispatch import _load_manifest
    overrides = _parse_param_overrides(param_overrides)
    # Overrides go through compile_workflow so its param_rules/required check
    # sees them: compiling with defaults only would accept a hostile override
    # here and reject a legitimately supplied required param.
    defn, manifest = _load_manifest(path, trigger_params=overrides or None)
    max_par = max((len(g) for g in manifest.parallel_groups), default=0)

    contract_warnings = validate_dag_contracts(defn)

    # Caller overrides win over declared defaults, mirroring the run path.
    effective_params = {**defn.trigger.params, **overrides}

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
        # Everything the orchestrator needs to dispatch a stage without
        # re-reading the YAML. Omitting any of these forces it back to the
        # parsed definition, which defeats the point of a compiled manifest —
        # and isolation in particular must reach the Agent() call, or
        # `isolation: worktree` silently does nothing.
        "index": r.index,
        "kind": r.spec.kind.value,
        "executor": r.spec.executor,
        "human_gate": r.spec.human_gate,
        "sub_workflow": r.spec.sub_workflow or None,
        "agent_role": r.spec.agent.role if r.spec.agent else None,
        "agent_model": r.spec.agent.model if r.spec.agent else None,
        "agent_isolation": r.spec.agent.isolation if r.spec.agent else None,
        # A conditional stage is only dispatchable if its `when` holds. Without
        # these two fields the manifest lists mutually-exclusive stages as
        # equally runnable, so an orchestrator trusting `resolutions` alone
        # runs BOTH branches -- and two stages writing the same declared output
        # silently clobber each other. `when` carries the raw expression;
        # `will_run` carries the decision against the resolved trigger params.
        "when": r.spec.when,
        "will_run": _eval_when_for_manifest(r.spec.when, effective_params),
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

    payload = _build_compile_payload(args.path, getattr(args, "params", []) or [])
    _write_once(cache_path, (json.dumps(payload) + "\n").encode())

    _render_compile_output(payload, args.format)
    return 0
