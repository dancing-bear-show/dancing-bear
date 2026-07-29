"""Repo-level LLM CLI: agentic/domain-map/familiar content and command dispatch.

Handles the top-level `llm` command (no --app flag), including inventory,
familiar, policies, agentic, domain-map, flows, derive-all, deps, stale,
and check subcommands.  Also wires --app routing to per-domain llm_cli modules.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from core.textio import read_text as _read_text, write_text as _write_text
from core.llm_builders import (
    DEFAULT_AGENTIC_FILENAME,
    DEFAULT_DOMAIN_MAP_FILENAME,
    DEFAULT_FAMILIAR_FILENAME,
    DEFAULT_INVENTORY_FILENAME,
    DEFAULT_POLICIES_FILENAME,
    _DOMAIN_MAP_UNAVAILABLE,
    _DEFAULT_POLICIES_YAML,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SKIP_DIRS = {
    "backups",
    "_disasm",
    "out",
    "_out",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "logs",
    "reports",
    "personal_assistants.egg-info",
}
DEFAULT_SLA_DAYS = 90

ASSISTANT_AGENTIC_CORE_CMDS = [
    "./bin/llm --app calendar agentic --stdout",
    "./bin/llm --app schedule agentic --stdout",
]

ASSISTANT_AGENTIC_EXTENDED_CMDS = [
    "./bin/llm --app resume agentic --stdout",
    "./bin/llm --app desk agentic --stdout",
    "./bin/llm --app maker agentic --stdout",
    "./bin/llm --app phone agentic --stdout",
    "./bin/llm --app wifi agentic --stdout",
    "./bin/llm --app whatsapp agentic --stdout",
]

# Standalone visualization + orchestration wrappers (own argparse CLIs, not llm --app
# routes, so discovered via --help rather than agentic schemas).
ASSISTANT_VIZ_ORCHESTRATION_CMDS = [
    "./bin/charts --help",
    "./bin/diagrams --help",
    "./bin/workflow --help",
]

_APP_MODULES = {
    "calendar": "calendars.llm_cli",
    "schedule": "schedule.llm_cli",
    "resume": "resume.llm_cli",
    "desk": "desk.llm_cli",
    "maker": "maker.llm_cli",
    "phone": "phone.llm_cli",
    "whatsapp": "whatsapp.llm_cli",
    "mail": "mail.llm_cli",
    "wifi": "wifi.llm_cli",
}


# ---------------------------------------------------------------------------
# App-arg extraction and dispatch
# ---------------------------------------------------------------------------

def _extract_app_arg(argv: list[str]) -> tuple[str | None, list[str]]:
    app: str | None = None
    cleaned: list[str] = []
    skip_next = False
    for idx, arg in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if arg in ("--app", "-a"):
            if idx + 1 >= len(argv):
                raise ValueError("Missing value for --app")
            app = argv[idx + 1]
            skip_next = True
            continue
        if arg.startswith("--app="):
            app = arg.split("=", 1)[1]
            continue
        cleaned.append(arg)
    return app, cleaned


def _run_app_cli(app: str, argv: list[str]) -> int:
    module_name = _APP_MODULES.get(app)
    if not module_name:
        available = ", ".join(sorted(_APP_MODULES.keys()))
        print(f"Unknown app '{app}'. Available apps: {available}", file=sys.stderr)
        return 2
    module = importlib.import_module(module_name)
    if hasattr(module, "main"):
        return module.main(argv)
    if hasattr(module, "CONFIG"):
        from core.llm_cli import run
        return run(module.CONFIG, argv)  # type: ignore[attr-defined]
    raise RuntimeError(f"App module {module_name} missing an entry point")


# ---------------------------------------------------------------------------
# Mail helpers (lazy-imported)
# ---------------------------------------------------------------------------

def _mail_agentic_capsule(compact: bool = False) -> str:
    try:
        from mail.agentic import build_agentic_capsule
        return build_agentic_capsule(compact=compact)
    except Exception as exc:  # nosec B110 - fallback on import/build failure
        import logging
        logging.getLogger(__name__).warning("_mail_agentic_capsule failed: %s", exc)
        return "agentic: mail\n(pending capsule)"


def _mail_domain_map() -> str:
    try:
        from mail.agentic import build_domain_map
        return build_domain_map()
    except Exception:  # nosec B110 - fallback on import/build failure
        return _DOMAIN_MAP_UNAVAILABLE


def _mail_flows() -> list[dict[str, Any]]:
    try:
        from mail.agentic import build_flows
        return build_flows()
    except Exception as exc:  # nosec B110 - fallback on import/build failure
        import logging
        logging.getLogger(__name__).warning("_mail_flows failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Content builders
# ---------------------------------------------------------------------------

def _default_inventory() -> str:
    return "# LLM Agent Inventory\n\n(see .llm/INVENTORY.md)\n"


def _default_policies() -> str:
    return _DEFAULT_POLICIES_YAML


def _familiar_content(verbose: bool, compact: bool = False) -> str:
    # Version history: v1=initial, v2=calendar/schedule cmds, v3=--compact flag,
    # v4=charts/diagrams/workflow viz+orchestration wrappers (verbose)
    if compact:
        return (
            "agent_note: Read-only familiarization. Open heavy files only when needed.\n"
            "meta:\n"
            "  name: assistants_familiarize\n"
            "  version: 4\n"
            "skip_paths: [.venv/, .git/, .cache/, maker/, _disasm/, out/, _out/, backups/]\n"
            "heavy_files: [README.md, AGENTS.md, config/*.yaml, out/**]\n"
            "steps:\n"
            "  - run: ./bin/llm agentic --stdout\n"
        )
    base = (
        "agent_note: Familiarization is read-only; fast path loads core LLM + calendar/schedule capsules"
        " (skim .llm context files). Use --verbose or per-app agentic for deeper context."
        " Visualization + orchestration wrappers (charts/diagrams/workflow) surface under --verbose.\n"
        "meta:\n"
        "  name: assistants_familiarize\n"
        "  version: 4\n"
        "steps:\n"
    )
    steps = ["  - run: ./bin/llm agentic --stdout"]
    for cmd in ASSISTANT_AGENTIC_CORE_CMDS:
        steps.append(f"  - run: {cmd} || true")
    if verbose:
        for cmd in ASSISTANT_AGENTIC_EXTENDED_CMDS:
            steps.append(f"  - run: {cmd} || true")
        for cmd in ASSISTANT_VIZ_ORCHESTRATION_CMDS:
            steps.append(f"  - run: {cmd} || true")
        steps.extend(
            [
                "  - run: ./bin/mail-assistant config inspect --only-mail || true",
                "  - run: ./bin/mail-assistant workflows from-unified --config config/filters_unified.yaml || true",
            ]
        )
    return base + "\n".join(steps) + "\n"


# ---------------------------------------------------------------------------
# Staleness / dependency stats helpers
# ---------------------------------------------------------------------------

def _parse_sla_env() -> dict[str, int]:
    env = os.environ.get("LLM_SLA", "")
    overrides: dict[str, int] = {}
    for part in env.replace(";", ",").split(","):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        try:
            overrides[key.strip()] = int(value.strip())
        except ValueError:
            continue
    return overrides


def _split_list(value: str | None) -> list[str]:
    if not value:
        return []
    parts: list[str] = []
    for raw in value.replace(";", ",").split(","):
        entry = raw.strip()
        if entry:
            parts.append(entry)
    return parts


def _collect_excludes() -> set[str]:
    excludes = set(DEFAULT_SKIP_DIRS)
    env_val = os.environ.get("LLM_EXCLUDE")
    if env_val:
        excludes.update(_split_list(env_val))
    return excludes


def _iter_candidate_dirs(root: Path, include: Iterable[str] | None = None) -> list[tuple[str, Path]]:
    include_set = {name.strip() for name in include or [] if name.strip()}
    excludes = _collect_excludes()
    entries: list[tuple[str, Path]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        name = child.name
        if include_set:
            if name not in include_set:
                continue
        elif name in excludes:
            continue
        entries.append((name, child))
    return entries


def _latest_mtime(path: Path) -> float:
    latest = path.stat().st_mtime
    for sub in path.rglob("*"):
        try:
            latest = max(latest, sub.stat().st_mtime)
        except Exception:  # nosec B112 - skip inaccessible files (permissions, broken symlinks)
            continue
    return latest


def _collect_stale_stats(root: Path, include: list[str] | None, limit: int) -> list[dict[str, object]]:
    now = time.time()
    stats: list[dict[str, object]] = []
    for name, path in _iter_candidate_dirs(root, include):
        try:
            latest = _latest_mtime(path)
        except OSError:
            continue
        days = max(0.0, (now - latest) / 86400.0)
        stats.append(
            {
                "area": name,
                "staleness_days": round(days, 2),
                "latest_ts": datetime.fromtimestamp(latest, tz=timezone.utc).isoformat(timespec="seconds"),
            }
        )
    stats.sort(key=lambda entry: entry["staleness_days"], reverse=True)
    if limit > 0:
        stats = stats[:limit]
    return stats


def _collect_dep_stats(root: Path, limit: int, order: str) -> list[dict[str, int]]:
    stats: list[dict[str, int]] = []
    for name, path in _iter_candidate_dirs(root):
        py_files = 0
        try:
            for _ in path.rglob("*.py"):
                py_files += 1
        except OSError:
            continue
        dependencies = py_files
        dependents = max(0, py_files // 2)
        stats.append(
            {
                "area": name,
                "dependencies": dependencies,
                "dependents": dependents,
                "combined": dependencies + dependents,
            }
        )
    reverse = order == "desc"
    stats.sort(key=lambda entry: entry["combined"], reverse=reverse)
    if limit > 0:
        stats = stats[:limit]
    return stats


def _status_for_area(area: str, days: float, overrides: dict) -> str:
    threshold = overrides.get(area, overrides.get("Root", DEFAULT_SLA_DAYS))
    return "STALE" if threshold is not None and days > threshold else "OK"


def _fail_on_stale(stats: list[dict[str, object]], overrides: dict) -> bool:
    for entry in stats:
        area = entry["area"]
        days = float(entry["staleness_days"])
        threshold = overrides.get(area, overrides.get("Root", DEFAULT_SLA_DAYS))
        if threshold is not None and days > threshold:
            return True
    return False


# ---------------------------------------------------------------------------
# Emit helper
# ---------------------------------------------------------------------------

def _emit_content(content: str, write_path: str | None, stdout: bool) -> None:
    if write_path:
        target = Path(write_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    if stdout or not write_path:
        print(content)


# ---------------------------------------------------------------------------
# Repo-level argument parser
# ---------------------------------------------------------------------------

def _build_repo_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="llm", description="Unified LLM utilities")
    sp = p.add_subparsers(dest="cmd", required=True)

    inv = sp.add_parser("inventory", help="Generate .llm/INVENTORY.md")
    inv.add_argument("--write", help="Write path (default .llm/INVENTORY.md)")
    inv.add_argument("--stdout", action="store_true")
    inv.add_argument("--format", choices=["md", "json"], default="md")

    fam = sp.add_parser("familiar", help="Show/write familiarization capsule")
    fam.add_argument("--write", help="Write path (default .llm/familiarize.yaml)")
    fam.add_argument("--stdout", action="store_true")
    fam.add_argument("--verbose", action="store_true")
    fam.add_argument("--compact", action="store_true", help="Minimal output for token efficiency")

    pol = sp.add_parser("policies", help="Show/write PR policies capsule")
    pol.add_argument("--write", help="Write path (default .llm/PR_POLICIES.yaml)")
    pol.add_argument("--stdout", action="store_true")

    agent = sp.add_parser("agentic", help="Show/write aggregated agentic capsule")
    agent.add_argument("--write", help="Write path (default .llm/AGENTIC.md)")
    agent.add_argument("--stdout", action="store_true")
    agent.add_argument("--compact", action="store_true", help="Emit a more compact capsule")

    dmap = sp.add_parser("domain-map", help="Show/write domain map")
    dmap.add_argument("--write", help="Write path (default .llm/DOMAIN_MAP.md)")
    dmap.add_argument("--stdout", action="store_true")

    flows = sp.add_parser("flows", help="List or display flows")
    flows.add_argument("--list", action="store_true")
    flows.add_argument("--id")
    flows.add_argument("--tags")
    flows.add_argument("--format", choices=["md", "yaml", "json"], default="md")
    flows.add_argument("--write")
    flows.add_argument("--stdout", action="store_true")

    derive = sp.add_parser("derive-all", help="Generate .llm artifacts")
    derive.add_argument("--out-dir", default=".llm")
    derive.add_argument("--include-generated", action="store_true")
    derive.add_argument("--stdout", action="store_true")

    deps = sp.add_parser("deps", help="Approximate dependencies by area")
    deps.add_argument("--root", default=".")
    deps.add_argument("--limit", type=int, default=10)
    deps.add_argument("--order", choices=["asc", "desc"], default="desc")
    deps.add_argument("--format", choices=["table", "text", "json"], default="table")

    stale = sp.add_parser("stale", help="Approximate staleness by area or file")
    stale.add_argument("--root", default=".")
    stale.add_argument("--limit", type=int, default=10)
    stale.add_argument("--format", choices=["table", "text", "json"], default="table")
    stale.add_argument("--include", help="Comma-separated area names to include")
    stale.add_argument("--with-status", action="store_true")
    stale.add_argument("--with-priority", action="store_true")
    stale.add_argument("--fail-on-stale", action="store_true")

    chk = sp.add_parser("check", help="CI helper for staleness (passes/fails based on SLA)")
    chk.add_argument("--root", default=".")
    chk.add_argument("--limit", type=int, default=10)
    chk.add_argument("--agg", choices=["max", "min", "avg"], default="max")

    return p


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _handle_inventory(args: argparse.Namespace, llm_dir: Path) -> int:
    """Handle inventory command."""
    if getattr(args, "format", "md") == "json":
        data = {
            "wrappers": ["bin/mail-assistant"],
            "areas": ["mail", "calendar"],
            "mail_groups": ["labels", "filters", "messages"],
        }
        print(json.dumps(data, indent=2))
        return 0
    content = _default_inventory()
    if not content:
        return 1
    target = Path(args.write or (llm_dir / DEFAULT_INVENTORY_FILENAME))
    if args.write:
        _write_text(target, content)
    if args.stdout or not args.write:
        print(content)
    return 0


def _handle_familiar(args: argparse.Namespace, llm_dir: Path) -> int:
    """Handle familiar command."""
    content = _familiar_content(
        verbose=getattr(args, "verbose", False),
        compact=getattr(args, "compact", False),
    )
    target = Path(args.write or (llm_dir / DEFAULT_FAMILIAR_FILENAME))
    if args.write:
        _write_text(target, content)
    if args.stdout or not args.write:
        print(content)
    return 0


def _handle_policies(args: argparse.Namespace, llm_dir: Path) -> int:
    """Handle policies command."""
    target = Path(args.write or (llm_dir / DEFAULT_POLICIES_FILENAME))
    content = _read_text(target) or _default_policies()
    if args.write:
        _write_text(target, content)
    if args.stdout or not args.write:
        print(content)
    return 0


def _handle_agentic(args: argparse.Namespace, llm_dir: Path) -> int:
    """Handle agentic command."""
    compact = getattr(args, "compact", False)
    content = _mail_agentic_capsule(compact=compact)
    target = Path(args.write or (llm_dir / DEFAULT_AGENTIC_FILENAME))
    if args.write:
        _write_text(target, content)
    if args.stdout or not args.write:
        print(content)
    return 0


def _handle_domain_map(args: argparse.Namespace, llm_dir: Path) -> int:
    """Handle domain-map command."""
    content = _mail_domain_map()
    target = Path(args.write or (llm_dir / DEFAULT_DOMAIN_MAP_FILENAME))
    if args.write:
        _write_text(target, content)
    if args.stdout or not args.write:
        print(content)
    return 0


def _render_flow_content(flow: dict[str, Any], fmt: str) -> str:
    """Render a single flow dict to string in the requested format."""
    if fmt == "json":
        return json.dumps(flow, indent=2)
    if fmt == "yaml":
        import yaml  # type: ignore
        return yaml.safe_dump(flow, sort_keys=False)
    return (
        f"id: {flow.get('id')}\n"
        f"title: {flow.get('title')}\n"
        f"tags: {', '.join(flow.get('tags') or [])}\n"
        + "\n".join(flow.get("commands") or [])
    )


def _handle_flows(args: argparse.Namespace, _llm_dir: Path) -> int:
    """Handle flows command."""
    flows = _mail_flows()
    if args.tags:
        tags = {t.strip() for t in args.tags.split(",") if t.strip()}
        flows = [f for f in flows if tags.issubset(set(f.get("tags") or []))]

    if args.list:
        lines = [f"- {f.get('id')} ({', '.join(f.get('tags') or [])})" for f in flows] or ["(no flows)"]
        content = "\n".join(lines)
    elif args.id:
        flow = next((f for f in flows if f.get("id") == args.id), None)
        content = _render_flow_content(flow, args.format) if flow else "(flow not found)"
    else:
        content = "(no flows)"

    if args.write:
        _write_text(Path(args.write), content)
    if args.stdout or not args.write:
        print(content)
    return 0


def _handle_derive_all(args: argparse.Namespace, llm_dir: Path) -> int:
    """Handle derive-all command."""
    outputs = [
        (llm_dir / DEFAULT_AGENTIC_FILENAME, _mail_agentic_capsule()),
        (llm_dir / DEFAULT_DOMAIN_MAP_FILENAME, _mail_domain_map()),
        (llm_dir / DEFAULT_INVENTORY_FILENAME, _default_inventory()),
        (llm_dir / DEFAULT_FAMILIAR_FILENAME, _familiar_content(verbose=False)),
        (llm_dir / DEFAULT_POLICIES_FILENAME, _default_policies()),
    ]
    if getattr(args, "include_generated", False):
        out_dir = Path(getattr(args, "out_dir", ".llm") or ".llm")
        out_dir.mkdir(parents=True, exist_ok=True)
        for target, content in outputs:
            target_path = out_dir / target.name
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
    if getattr(args, "stdout", False):
        print("Generated:")
        for target, _ in outputs:
            print(f"- {target}")
    return 0


def _handle_deps(args: argparse.Namespace, _llm_dir: Path) -> int:
    """Handle deps command."""
    entries = _collect_dep_stats(Path(args.root), args.limit, args.order)
    if args.format == "json":
        print(json.dumps(entries, indent=2))
    elif args.format == "text":
        lines = [
            f"{e['area']}\t{e['dependencies']}\t{e['dependents']}\t{e['combined']}" for e in entries
        ] or ["(no data)"]
        print("\n".join(lines))
    else:
        header = ["| Area | Dependencies | Dependents | Combined |", "| --- | --- | --- | --- |"]
        rows = [
            f"| {e['area']} | {e['dependencies']} | {e['dependents']} | {e['combined']} |"
            for e in entries
        ]
        print("\n".join(header + rows))
    return 0


def _stale_text_line(entry: dict, overrides: dict, with_status: bool, with_priority: bool) -> str:
    """Format a single stale entry as a text line."""
    status = _status_for_area(entry["area"], entry["staleness_days"], overrides) if with_status else ""
    priority = f"\tpriority={int(round(entry['staleness_days']))}" if with_priority else ""
    line = f"{entry['area']}\t{entry['staleness_days']}d"
    if status:
        line += f"\t{status}"
    return line + priority


def _stale_md_row(entry: dict, overrides: dict, with_priority: bool) -> str:
    """Format a single stale entry as a markdown table row."""
    status = _status_for_area(entry["area"], entry["staleness_days"], overrides)
    priority = int(round(entry["staleness_days"])) if with_priority else ""
    return f"| {entry['area']} | {entry['staleness_days']} | {status} | {priority} |"


def _handle_stale(args: argparse.Namespace, _llm_dir: Path) -> int:
    """Handle stale command."""
    overrides = _parse_sla_env()
    include = _split_list(getattr(args, "include", None))
    entries = _collect_stale_stats(Path(args.root), include, args.limit)
    with_status = getattr(args, "with_status", False)
    with_priority = getattr(args, "with_priority", False)

    if args.format == "json":
        print(json.dumps(entries, indent=2))
    elif args.format == "text":
        for entry in entries:
            print(_stale_text_line(entry, overrides, with_status, with_priority))
    else:
        header = ["| Area | Days | Status | Priority |", "| --- | --- | --- | --- |"]
        rows = [_stale_md_row(entry, overrides, with_priority) for entry in entries]
        print("\n".join(header + rows))

    if getattr(args, "fail_on_stale", False) and _fail_on_stale(entries, overrides):
        return 2
    return 0


def _aggregate_values(values: list, agg: str) -> float:
    """Aggregate a list of numeric values using the specified aggregation method."""
    if agg == "min":
        return min(values)
    if agg == "avg":
        return sum(values) / len(values)
    return max(values)


def _handle_check(args: argparse.Namespace, _llm_dir: Path) -> int:
    """Handle check command."""
    overrides = _parse_sla_env()
    if not overrides:
        return 0

    stats = _collect_stale_stats(Path(args.root), list(overrides.keys()), args.limit)
    area_map = {entry["area"]: entry["staleness_days"] for entry in stats}
    root_limit = overrides.pop("Root", None)

    if root_limit is not None and stats:
        values = [entry["staleness_days"] for entry in stats]
        if _aggregate_values(values, args.agg) > root_limit:
            return 2

    for area, limit in overrides.items():
        days = area_map.get(area)
        if days is not None and limit is not None and days > limit:
            return 2
    return 0


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Main entry point for LLM CLI.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    try:
        app, remaining = _extract_app_arg(raw_args)
    except ValueError as exc:
        print(str(exc))
        return 2

    if app and app != "mail":
        return _run_app_cli(app, remaining)

    args = _build_repo_parser().parse_args(remaining)
    root = Path.cwd()
    llm_dir = root / ".llm"

    # Command dispatch table
    handlers = {
        "inventory": _handle_inventory,
        "familiar": _handle_familiar,
        "policies": _handle_policies,
        "agentic": _handle_agentic,
        "domain-map": _handle_domain_map,
        "flows": _handle_flows,
        "derive-all": _handle_derive_all,
        "deps": _handle_deps,
        "stale": _handle_stale,
        "check": _handle_check,
    }

    handler = handlers.get(args.cmd)
    if handler:
        return handler(args, llm_dir)

    return 2
