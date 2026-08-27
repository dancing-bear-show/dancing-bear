"""CLI handler functions for the LLM CLI (repo-level `llm` command).

Handles inventory, familiar, policies, agentic, domain-map, flows, derive-all,
and dispatches --app routing to per-domain llm_cli modules.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

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
from core.llm_staleness import (
    _handle_check,
    _handle_deps,
    _handle_stale,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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

# Standalone visualization + orchestration wrappers: own argparse CLIs rather than
# llm --app routes, but they emit agentic schemas like every other app.
ASSISTANT_VIZ_ORCHESTRATION_CMDS = [
    "./bin/charts --agentic --agentic-compact",
    "./bin/diagrams --agentic --agentic-compact",
    "./bin/workflow --agentic --agentic-compact",
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

# Every app supports `--agentic`. Broader than _APP_MODULES, which is only the
# `llm --app <name>` routing table — the apps below are not reachable that way
# but still emit a schema.
#
# Value is the invocation, because `./bin/<app>` is wrong for four of them:
# apple-music and qlty use -assistant wrappers (bin/qlty would shadow the real
# qlty binary), resume ships no wrapper and goes through bin/assistant, and desk
# has no wrapper at all. Verified by running each one.
_AGENTIC_APPS: dict[str, str] = {
    "apple-music": "./bin/apple-music-assistant",
    "calendar": "./bin/calendar",
    "charts": "./bin/charts",
    "desk": "python3 -m desk",
    "diagrams": "./bin/diagrams",
    "mail": "./bin/mail",
    "maker": "./bin/maker",
    "phone": "./bin/phone",
    "qlty": "./bin/qlty-assistant",
    "resume": "./bin/assistant resume",
    "schedule": "./bin/schedule",
    "sheets": "./bin/sheets",
    "slides": "./bin/slides",
    "telemetry": "./bin/telemetry",
    "whatsapp": "./bin/whatsapp",
    "wifi": "./bin/wifi",
    "worker": "./bin/worker",
    "workflow": "./bin/workflow",
}

# No CLI is agentic-less any more. Kept so the inventory renders an explicit
# "none" instead of silently dropping the section if one ever regresses.
_NO_AGENTIC_CLIS: frozenset[str] = frozenset()


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

def _repo_root() -> Path:
    # llm_handlers.py lives at <root>/src/core/; two parents up is <root>.
    return Path(__file__).resolve().parents[2]


def _inventory_data() -> dict[str, Any]:
    """Collect inventory facts from the canonical registries, not a hardcoded list."""
    root = _repo_root()
    bin_dir = root / "bin"
    wrappers = sorted(
        f"bin/{p.name}"
        for p in bin_dir.iterdir()
        if p.is_file() and not p.name.startswith("_") and not p.suffix
    ) if bin_dir.is_dir() else []

    src_dir = root / "src"
    packages = sorted(
        p.name
        for p in src_dir.iterdir()
        if p.is_dir() and (p / "__init__.py").exists()
    ) if src_dir.is_dir() else []

    return {
        "wrappers": wrappers,
        "areas": sorted(_APP_MODULES),
        "packages": packages,
        "agentic_apps": [_AGENTIC_APPS[k] for k in sorted(_AGENTIC_APPS)],
        "no_agentic_clis": sorted(_NO_AGENTIC_CLIS),
    }


def _default_inventory() -> str:
    """Render the LLM agent inventory as markdown."""
    data = _inventory_data()
    lines = [
        "# LLM Agent Inventory",
        "",
        "Generated by `./bin/llm inventory`. Do not edit by hand.",
        "",
        f"## Packages ({len(data['packages'])})",
        "",
        ", ".join(f"`{p}`" for p in data["packages"]) or "_none found_",
        "",
        f"## Agentic-schema apps ({len(data['agentic_apps'])})",
        "",
        "Append `--agentic --agentic-format yaml --agentic-compact` to any invocation below.",
        "Most are `./bin/<app>`; the four exceptions are spelled out.",
        "",
        *(f"- `{cmd}`" for cmd in data["agentic_apps"]),
        "",
        "## Standalone CLIs (no agentic schema)",
        "",
        ", ".join(f"`{v}`" for v in data["no_agentic_clis"])
        or "_none — every CLI emits an agentic schema._",
        "",
        f"## Wrappers ({len(data['wrappers'])})",
        "",
        ", ".join(f"`{w}`" for w in data["wrappers"]) or "_none found_",
        "",
    ]
    return "\n".join(lines)


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
            "  - run: ./bin/llm agentic --stdout --compact\n"
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
    # --compact keeps this at ~2KB; the uncompacted capsule inlines CONTEXT.md,
    # MIGRATION_STATE.md, PATTERNS.md and AGENTS.md for ~38KB. Those are
    # deep-dive reads, loaded on demand rather than at every session start.
    steps = ["  - run: ./bin/llm agentic --stdout --compact"]
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
                "  - run: ./bin/mail-assistant workflows from-unified || true",
            ]
        )
    return base + "\n".join(steps) + "\n"


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


def _write_and_print(content: str, args: argparse.Namespace, default_target: Path) -> None:
    """Write content to args.write (or default_target) and/or print to stdout.

    Mirrors the write-then-print pattern shared by the simple capsule handlers:
    always writes when --write is given; prints when --stdout is given or no
    --write path was provided at all.
    """
    target = Path(args.write or default_target)
    if args.write:
        _write_text(target, content)
    if args.stdout or not args.write:
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
        data = _inventory_data()
        data["mail_groups"] = ["labels", "filters", "messages"]
        print(json.dumps(data, indent=2))
        return 0
    content = _default_inventory()
    if not content:
        return 1
    _write_and_print(content, args, llm_dir / DEFAULT_INVENTORY_FILENAME)
    return 0


def _handle_familiar(args: argparse.Namespace, llm_dir: Path) -> int:
    """Handle familiar command."""
    content = _familiar_content(
        verbose=getattr(args, "verbose", False),
        compact=getattr(args, "compact", False),
    )
    _write_and_print(content, args, llm_dir / DEFAULT_FAMILIAR_FILENAME)
    return 0


def _handle_policies(args: argparse.Namespace, llm_dir: Path) -> int:
    """Handle policies command."""
    default_target = llm_dir / DEFAULT_POLICIES_FILENAME
    content = _read_text(Path(args.write or default_target)) or _default_policies()
    _write_and_print(content, args, default_target)
    return 0


def _handle_agentic(args: argparse.Namespace, llm_dir: Path) -> int:
    """Handle agentic command."""
    compact = getattr(args, "compact", False)
    content = _mail_agentic_capsule(compact=compact)
    _write_and_print(content, args, llm_dir / DEFAULT_AGENTIC_FILENAME)
    return 0


def _handle_domain_map(args: argparse.Namespace, llm_dir: Path) -> int:
    """Handle domain-map command."""
    content = _mail_domain_map()
    _write_and_print(content, args, llm_dir / DEFAULT_DOMAIN_MAP_FILENAME)
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


def _filter_flows_by_tags(flows: list[dict[str, Any]], tags_arg: str | None) -> list[dict[str, Any]]:
    """Filter flows to those whose tags include every comma-separated tag in tags_arg."""
    if not tags_arg:
        return flows
    tags = {t.strip() for t in tags_arg.split(",") if t.strip()}
    return [f for f in flows if tags.issubset(set(f.get("tags") or []))]


def _flows_list_content(flows: list[dict[str, Any]]) -> str:
    """Render flows as a bulleted id/tags listing."""
    lines = [f"- {f.get('id')} ({', '.join(f.get('tags') or [])})" for f in flows] or ["(no flows)"]
    return "\n".join(lines)


def _flow_detail_content(flows: list[dict[str, Any]], flow_id: str, fmt: str) -> str:
    """Render a single flow's detail content, or a not-found message."""
    flow = next((f for f in flows if f.get("id") == flow_id), None)
    return _render_flow_content(flow, fmt) if flow else "(flow not found)"


def _handle_flows(args: argparse.Namespace, _llm_dir: Path) -> int:
    """Handle flows command."""
    flows = _filter_flows_by_tags(_mail_flows(), args.tags)

    if args.list:
        content = _flows_list_content(flows)
    elif args.id:
        content = _flow_detail_content(flows, args.id, args.format)
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
