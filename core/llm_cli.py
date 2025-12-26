"""Shared LLM CLI helpers (inventory, familiar, flows, policies)."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from core.textio import read_text as _read_text, write_text as _write_text

# Default filenames for LLM outputs
DEFAULT_AGENTIC_FILENAME = "AGENTIC.md"
DEFAULT_DOMAIN_MAP_FILENAME = "DOMAIN_MAP.md"
DEFAULT_INVENTORY_FILENAME = "INVENTORY.md"
DEFAULT_FAMILIAR_FILENAME = "familiarize.yaml"
DEFAULT_POLICIES_FILENAME = "PR_POLICIES.yaml"


@dataclass
class LlmConfig:
    prog: str
    description: str
    agentic: Callable[[], str]
    domain_map: Optional[Callable[[], str]] = None
    inventory: Optional[Callable[[], str]] = None
    familiar_compact: Optional[Callable[[], str]] = None
    familiar_extended: Optional[Callable[[], str]] = None
    policies: Optional[Callable[[], str]] = None
    agentic_filename: str = DEFAULT_AGENTIC_FILENAME
    domain_map_filename: str = DEFAULT_DOMAIN_MAP_FILENAME
    inventory_filename: str = DEFAULT_INVENTORY_FILENAME
    familiar_filename: str = DEFAULT_FAMILIAR_FILENAME
    policies_filename: str = DEFAULT_POLICIES_FILENAME


def make_app_llm_config(
    *,
    prog: str,
    description: str,
    agentic: Callable[[], str],
    domain_map: Optional[Callable[[], str]] = None,
    inventory: Optional[Callable[[], str]] = None,
    familiar_compact: Optional[Callable[[], str]] = None,
    familiar_extended: Optional[Callable[[], str]] = None,
    policies: Optional[Callable[[], str]] = None,
    agentic_filename: str = DEFAULT_AGENTIC_FILENAME,
    domain_map_filename: str = DEFAULT_DOMAIN_MAP_FILENAME,
    inventory_filename: str = DEFAULT_INVENTORY_FILENAME,
    familiar_filename: str = DEFAULT_FAMILIAR_FILENAME,
    policies_filename: str = DEFAULT_POLICIES_FILENAME,
) -> LlmConfig:
    """Helper to build a common app LLM config without repeating boilerplate."""
    return LlmConfig(
        prog=prog,
        description=description,
        agentic=agentic,
        domain_map=domain_map,
        inventory=inventory,
        familiar_compact=familiar_compact,
        familiar_extended=familiar_extended,
        policies=policies,
        agentic_filename=agentic_filename,
        domain_map_filename=domain_map_filename,
        inventory_filename=inventory_filename,
        familiar_filename=familiar_filename,
        policies_filename=policies_filename,
    )


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


def _extract_app_arg(argv: List[str]) -> Tuple[Optional[str], List[str]]:
    app: Optional[str] = None
    cleaned: List[str] = []
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


def _run_app_cli(app: str, argv: List[str]) -> int:
    module_name = _APP_MODULES.get(app)
    if not module_name:
        available = ", ".join(sorted(_APP_MODULES.keys()))
        print(f"Unknown app '{app}'. Available apps: {available}")
        return 2
    module = importlib.import_module(module_name)
    if hasattr(module, "main"):
        return module.main(argv)
    if hasattr(module, "CONFIG"):
        return run(module.CONFIG, argv)  # type: ignore[attr-defined]
    raise RuntimeError(f"App module {module_name} missing an entry point")


def _default_inventory() -> str:
    return "# LLM Agent Inventory\n\n(see .llm/INVENTORY.md)\n"


def _default_policies() -> str:
    return "policies:\n  style:\n    - Keep public CLI stable\n"


def _familiar_content(verbose: bool, compact: bool = False) -> str:
    if compact:
        return (
            "agent_note: Read-only familiarization. Open heavy files only when needed.\n"
            "meta:\n"
            "  name: assistants_familiarize\n"
            "  version: 3\n"
            "skip_paths: [.venv/, .git/, .cache/, maker/, _disasm/, out/, _out/, backups/]\n"
            "heavy_files: [README.md, AGENTS.md, config/*.yaml, out/**]\n"
            "steps:\n"
            "  - run: ./bin/llm agentic --stdout\n"
        )
    base = (
        "agent_note: Familiarization is read-only; fast path loads core LLM + calendar/schedule capsules (skim .llm context files). Use --verbose or per-app agentic for deeper context.\n"
        "meta:\n"
        "  name: assistants_familiarize\n"
        "  version: 3\n"
        "steps:\n"
    )
    steps = ["  - run: ./bin/llm agentic --stdout"]
    for cmd in ASSISTANT_AGENTIC_CORE_CMDS:
        steps.append(f"  - run: {cmd} || true")
    if verbose:
        for cmd in ASSISTANT_AGENTIC_EXTENDED_CMDS:
            steps.append(f"  - run: {cmd} || true")
        steps.extend(
            [
                "  - run: ./bin/mail-assistant config inspect --only-mail || true",
                "  - run: ./bin/mail-assistant workflows from-unified --config config/filters_unified.yaml || true",
            ]
        )
    return base + "\n".join(steps) + "\n"


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


def _mail_agentic_capsule() -> str:
    try:
        from mail.agentic import build_agentic_capsule

        return build_agentic_capsule()
    except Exception:
        return "agentic: mail\n(pending capsule)"


def _mail_domain_map() -> str:
    try:
        from mail.agentic import build_domain_map

        return build_domain_map()
    except Exception:
        return "Domain Map not available"


def _mail_flows() -> List[Dict[str, any]]:
    try:
        from mail.agentic import build_flows

        return build_flows()
    except Exception:
        return []


def _parse_sla_env() -> dict:
    env = os.environ.get("LLM_SLA", "")
    overrides: dict = {}
    for part in env.replace(";", ",").split(","):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        try:
            overrides[key.strip()] = int(value.strip())
        except ValueError:
            continue
    return overrides


def _split_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    parts: List[str] = []
    for raw in value.replace(";", ",").split(","):
        entry = raw.strip()
        if entry:
            parts.append(entry)
    return parts


def _collect_excludes() -> set:
    excludes = set(DEFAULT_SKIP_DIRS)
    env_val = os.environ.get("LLM_EXCLUDE")
    if env_val:
        excludes.update(_split_list(env_val))
    return excludes


def _iter_candidate_dirs(root: Path, include: Optional[Iterable[str]] = None) -> List[Tuple[str, Path]]:
    include_set = {name.strip() for name in include or [] if name.strip()}
    excludes = _collect_excludes()
    entries: List[Tuple[str, Path]] = []
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
        except Exception:
            continue
    return latest


def _collect_stale_stats(root: Path, include: Optional[List[str]], limit: int) -> List[Dict[str, object]]:
    now = time.time()
    stats: List[Dict[str, object]] = []
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
                "latest_ts": datetime.fromtimestamp(latest).isoformat(timespec="seconds"),
            }
        )
    stats.sort(key=lambda entry: entry["staleness_days"], reverse=True)
    if limit > 0:
        stats = stats[:limit]
    return stats


def _collect_dep_stats(root: Path, limit: int, order: str) -> List[Dict[str, int]]:
    stats: List[Dict[str, int]] = []
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


def _fail_on_stale(stats: List[Dict[str, object]], overrides: dict) -> bool:
    for entry in stats:
        area = entry["area"]
        days = float(entry["staleness_days"])
        threshold = overrides.get(area, overrides.get("Root", DEFAULT_SLA_DAYS))
        if threshold is not None and days > threshold:
            return True
    return False


def _emit_content(content: str, write_path: Optional[str], stdout: bool) -> None:
    if write_path:
        target = Path(write_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    if stdout or not write_path:
        print(content)


def _safe_call(builder: Optional[Callable[[], str]], fallback: str) -> str:
    if builder is None:
        return fallback
    try:
        text = builder()
    except Exception as exc:
        return fallback or f"(error generating content: {exc})"
    return text or fallback


def _build_app_parser(config: LlmConfig) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=config.prog, description=config.description)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def _add_emit_cmd(
        name: str,
        help_text: str,
        builder: Optional[Callable[[], str]],
        fallback: str,
    ) -> None:
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--write", help="Write output path")
        cmd.add_argument("--stdout", action="store_true", help="Print to stdout")

        def _run(args):
            content = _safe_call(builder, fallback)
            _emit_content(content, getattr(args, "write", None), getattr(args, "stdout", False))
            return 0

        cmd.set_defaults(func=_run)

    _add_emit_cmd(
        "agentic",
        "Emit the agentic capsule",
        config.agentic,
        "agentic: (not available)",
    )
    _add_emit_cmd(
        "domain-map",
        "Emit domain map",
        config.domain_map,
        "Domain Map not available",
    )
    _add_emit_cmd(
        "inventory",
        "Emit LLM inventory",
        config.inventory,
        "# LLM Agent Inventory\n\n(no data)",
    )
    _add_emit_cmd(
        "policies",
        "Emit PR/testing policies",
        config.policies,
        _default_policies(),
    )

    fam = sub.add_parser("familiar", help="Emit familiarization capsule")
    fam.add_argument("--write", help="Write output path")
    fam.add_argument("--stdout", action="store_true", help="Print to stdout")
    fam.add_argument("--verbose", action="store_true", help="Include extended steps")

    def _run_familiar(args):
        verbose = bool(getattr(args, "verbose", False))
        builder = config.familiar_extended if verbose and config.familiar_extended else config.familiar_compact
        fallback = "meta:\n  name: familiar\n  version: 1\nsteps:\n  - run: ./bin/llm agentic --stdout\n"
        content = _safe_call(builder, fallback)
        _emit_content(content, getattr(args, "write", None), getattr(args, "stdout", False))
        return 0

    fam.set_defaults(func=_run_familiar)

    derive = sub.add_parser("derive-all", help="Generate agentic + domain map artifacts")
    derive.add_argument("--out-dir", default=".llm", help="Directory for generated files (default .llm)")
    derive.add_argument("--include-generated", action="store_true", help="Write artifacts to --out-dir")
    derive.add_argument("--stdout", action="store_true", help="Print summary to stdout")

    def _run_derive(args):
        outputs: List[Tuple[str, str]] = []

        def add(filename: Optional[str], builder: Optional[Callable[[], str]], fallback: str = "") -> None:
            if not filename or not builder:
                return
            content = _safe_call(builder, fallback)
            if content:
                outputs.append((filename, content))

        add(config.agentic_filename, config.agentic)
        add(config.domain_map_filename, config.domain_map)
        add(config.inventory_filename, config.inventory)
        fam_builder = config.familiar_extended or config.familiar_compact
        add(config.familiar_filename, fam_builder)
        add(config.policies_filename, config.policies, _default_policies())

        if hasattr(config, "extra_generators"):
            extra: Sequence[Tuple[str, Callable[[], str]]] = getattr(config, "extra_generators")
            for fname, builder in extra:
                add(fname, builder)

        if getattr(args, "include_generated", False) and outputs:
            out_dir = Path(getattr(args, "out_dir", ".llm") or ".llm")
            out_dir.mkdir(parents=True, exist_ok=True)
            for fname, content in outputs:
                target = out_dir / fname
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

        summary_lines = ["Generated:"]
        if outputs:
            summary_lines.extend(f"- {fname}" for fname, _ in outputs)
        else:
            summary_lines.append("- (none)")
        summary = "\n".join(summary_lines)
        if getattr(args, "stdout", False) or not getattr(args, "include_generated", False):
            print(summary)
        return 0

    derive.set_defaults(func=_run_derive)

    return parser


def build_parser(config: LlmConfig) -> argparse.ArgumentParser:
    return _build_app_parser(config)


def run(config: LlmConfig, argv: Optional[List[str]] = None) -> int:
    parser = build_parser(config)
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return int(func(args))


def main(argv: Optional[List[str]] = None) -> int:
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

    if args.cmd == "inventory":
        if getattr(args, "format", "md") == "json":
            data = {
                "wrappers": ["bin/mail-assistant"],
                "areas": ["mail", "calendar"],
                "mail_groups": ["labels", "filters", "messages"],
            }
            print(json.dumps(data, indent=2))
            return 0
        content = _default_inventory()
        target = Path(args.write or (llm_dir / DEFAULT_INVENTORY_FILENAME))
        if args.write:
            _write_text(target, content)
        if args.stdout or not args.write:
            print(content)
        return 0

    if args.cmd == "familiar":
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

    if args.cmd == "policies":
        target = Path(args.write or (llm_dir / DEFAULT_POLICIES_FILENAME))
        content = _read_text(target) or _default_policies()
        if args.write:
            _write_text(target, content)
        if args.stdout or not args.write:
            print(content)
        return 0

    if args.cmd == "agentic":
        content = _mail_agentic_capsule()
        target = Path(args.write or (llm_dir / DEFAULT_AGENTIC_FILENAME))
        if args.write:
            _write_text(target, content)
        if args.stdout or not args.write:
            print(content)
        return 0

    if args.cmd == "domain-map":
        content = _mail_domain_map()
        target = Path(args.write or (llm_dir / DEFAULT_DOMAIN_MAP_FILENAME))
        if args.write:
            _write_text(target, content)
        if args.stdout or not args.write:
            print(content)
        return 0

    if args.cmd == "flows":
        flows = _mail_flows()
        if args.tags:
            tags = {t.strip() for t in args.tags.split(",") if t.strip()}
            flows = [f for f in flows if tags.issubset(set(f.get("tags") or []))]
        if args.list:
            lines = [f"- {f.get('id')} ({', '.join(f.get('tags') or [])})" for f in flows] or ["(no flows)"]
            content = "\n".join(lines)
        elif args.id:
            flow = next((f for f in flows if f.get("id") == args.id), None)
            if not flow:
                content = "(flow not found)"
            elif args.format == "json":
                content = json.dumps(flow, indent=2)
            elif args.format == "yaml":
                import yaml  # type: ignore

                content = yaml.safe_dump(flow, sort_keys=False)
            else:
                content = (
                    f"id: {flow.get('id')}\n"
                    f"title: {flow.get('title')}\n"
                    f"tags: {', '.join(flow.get('tags') or [])}\n"
                    + "\n".join(flow.get("commands") or [])
                )
        else:
            content = "(no flows)"
        if args.write:
            _write_text(Path(args.write), content)
        if args.stdout or not args.write:
            print(content)
        return 0

    if args.cmd == "derive-all":
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

    if args.cmd == "deps":
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
            rows = [f"| {e['area']} | {e['dependencies']} | {e['dependents']} | {e['combined']} |" for e in entries]
            print("\n".join(header + rows))
        return 0

    if args.cmd == "stale":
        overrides = _parse_sla_env()
        include = _split_list(getattr(args, "include", None))
        entries = _collect_stale_stats(Path(args.root), include, args.limit)
        if args.format == "json":
            print(json.dumps(entries, indent=2))
        elif args.format == "text":
            for entry in entries:
                status = (
                    _status_for_area(entry["area"], entry["staleness_days"], overrides)
                    if getattr(args, "with_status", False)
                    else ""
                )
                priority = ""
                if getattr(args, "with_priority", False):
                    priority = f"\tpriority={int(round(entry['staleness_days']))}"
                line = f"{entry['area']}\t{entry['staleness_days']}d"
                if status:
                    line += f"\t{status}"
                if priority:
                    line += priority
                print(line)
        else:
            header = ["| Area | Days | Status | Priority |", "| --- | --- | --- | --- |"]
            rows = []
            for entry in entries:
                status = _status_for_area(entry["area"], entry["staleness_days"], overrides)
                priority = int(round(entry["staleness_days"])) if getattr(args, "with_priority", False) else ""
                rows.append(f"| {entry['area']} | {entry['staleness_days']} | {status} | {priority} |")
            print("\n".join(header + rows))
        if getattr(args, "fail_on_stale", False) and _fail_on_stale(entries, overrides):
            return 2
        return 0

    if args.cmd == "check":
        overrides = _parse_sla_env()
        if not overrides:
            return 0
        stats = _collect_stale_stats(Path(args.root), list(overrides.keys()), args.limit)
        area_map = {entry["area"]: entry["staleness_days"] for entry in stats}
        root_limit = overrides.pop("Root", None)
        if root_limit is not None and stats:
            values = [entry["staleness_days"] for entry in stats]
            if args.agg == "min":
                agg_value = min(values)
            elif args.agg == "avg":
                agg_value = sum(values) / len(values)
            else:
                agg_value = max(values)
            if agg_value > root_limit:
                return 2
        for area, limit in overrides.items():
            days = area_map.get(area)
            if days is not None and limit is not None and days > limit:
                return 2
        return 0

    return 2
