from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
import ast

from core.agentic import (
    build_capsule as _build_capsule,
    build_cli_tree as _core_build_cli_tree,
    cli_path_exists as _core_cli_path_exists,
    read_text as _read_text,
    section as _section,
)


def build_agentic_capsule() -> str:
    """Return a compact, LLM-friendly capsule of repo context as a string."""
    root = Path(os.getcwd())
    llm = root / ".llm"

    files: List[Path] = [
        llm / "CONTEXT.md",
        llm / "UNIFIED.llm",
        llm / "DOMAIN_MAP.md",
        llm / "MIGRATION_STATE.md",
        llm / "PATTERNS.md",
        root / "AGENTS.md",
    ]

    commands = [
        "setup venv: python3 -m venv .venv && source .venv/bin/activate",
        "install: pip install -e .",
        "help: ./bin/mail-assistant --help",
        "labels export: python3 -m mail_assistant labels export --out labels.yaml",
        "labels sync: python3 -m mail_assistant labels sync --config labels.yaml --dry-run",
        "filters export: python3 -m mail_assistant filters export --out filters.yaml",
    ]

    sections: List[Tuple[str, str]] = []
    for p in files:
        if not p.exists():
            continue
        title = f"{p.parent.name}/{p.name}" if p.parent.name == ".llm" else p.name
        sections.append((title, _read_text(p)))
    cli_tree = _build_cli_tree()
    if cli_tree.strip():
        sections.append(("CLI Tree", cli_tree))
    # Instead of emitting the full Flow Map (large), include a compact Flows Index
    flows_idx = _build_flows_index()
    if flows_idx.strip():
        sections.append(("Flows Index", flows_idx + "\n\nUse './bin/llm flows --list' or '--id <flow_id>' for details."))
    return _build_capsule("mail_assistant", "Gmail/Outlook CLI (labels, filters, signatures)", commands, sections)


def emit_agentic_context(fmt: str = "text", compact: bool = False) -> int:
    """Emit the agentic capsule.

    Parameters are currently best-effort and may be ignored. Accepts
    fmt ("text"|"yaml") and compact (bool) to align with documented flags.
    """
    content = build_agentic_capsule()
    # For now, only text output is implemented; ignore fmt/compact gracefully.
    print(content)
    return 0


@lru_cache(maxsize=1)
def _get_parser():
    try:
        from . import __main__ as main_mod
        return main_mod.build_parser()
    except Exception:
        return None


def _build_cli_tree() -> str:
    """Return a compact, single-level CLI tree (top-level → subcommands)."""
    return _core_build_cli_tree(_get_parser())


def build_domain_map() -> str:
    """Programmatically build a minimal domain map with CLI tree and key modules."""
    root = Path(os.getcwd())
    parts: List[str] = []
    parts.append("Top-Level\n- bin/ — wrappers (mail-assistant, mail-assistant-auth, llm)\n- config/ — unified YAML inputs\n- out/ — derived artifacts\n- tests/ — unit tests\n- .llm/ — agent context")
    parts.append(_section("CLI Tree", _build_cli_tree()))
    parts.append(_section("Flows Index", _build_flows_index() + "\n\nUse './bin/llm flows --list' or '--id <flow_id>' for details."))
    # Key modules (heuristic set)
    key_files = [
        "__main__.py",
        "config_resolver.py",
        "gmail_api.py",
        "outlook_api.py",
        "dsl.py",
        "yamlio.py",
        "applog.py",
        "cache.py",
        "paging.py",
        "llm_cli.py",
        "agentic.py",
    ]
    lines: List[str] = []
    for fn in key_files:
        p = root / fn
        if p.exists():
            lines.append(f"- {fn}")
    if lines:
        parts.append(_section("Key Modules", "\n".join(lines)))

    # Enumerate modules in common utility folders with first docstring line
    def _mods(folder: str) -> List[Tuple[str, str]]:
        items: List[Tuple[str, str]] = []
        d = root / folder
        if not d.exists() or not d.is_dir():
            return items
        for py in sorted(d.glob("*.py")):
            name = f"{folder}/{py.name}"
            doc = ""
            try:
                txt = py.read_text(encoding="utf-8")
                mod = ast.parse(txt)
                ds = ast.get_docstring(mod) or ""
                doc = (ds.strip().splitlines() or [""])[0]
            except Exception:
                doc = ""
            items.append((name, doc))
        return items

    for title, folder in (
        ("CLI Modules", "cli"),
        ("Provider Modules", "providers"),
        ("Utility Modules", "utils"),
    ):
        mods = _mods(folder)
        if mods:
            parts.append(_section(title, "\n".join(f"- {n}" + (f" — {d}" if d else "") for n, d in mods)))

    # Binaries
    bin_dir = root / "bin"
    if bin_dir.exists():
        bins = sorted(p.name for p in bin_dir.iterdir() if p.is_file())
        if bins:
            parts.append(_section("Binaries", "\n".join(f"- bin/{b}" for b in bins)))
    return "\n".join([s for s in parts if s.strip()])


def _cli_path_exists(path: List[str]) -> bool:
    return _core_cli_path_exists(_get_parser(), path)


def build_flows() -> List[Dict[str, Any]]:
    """Return a list of composable flow specs (small, parameterized)."""
    flows: List[Dict[str, Any]] = []
    def add(flow: Dict[str, Any]):
        # Only include flows if all referenced CLI paths exist
        for p in flow.get('requires', []):
            if not _cli_path_exists(p):
                return
        flows.append(flow)

    def _bin_exists(name: str) -> bool:
        try:
            root = Path(os.getcwd())
            p = root / 'bin' / name
            return p.exists()
        except Exception:
            return False

    # Unified → derive provider configs
    add({
        'id': 'unified.derive',
        'title': 'Derive provider configs from unified',
        'tags': ['unified','derive','gmail','outlook','safe'],
        'requires': [["config","derive","filters"]],
        'commands': [
            "./bin/mail-assistant config derive filters --in config/filters_unified.yaml --out-gmail out/filters.gmail.from_unified.yaml --out-outlook out/filters.outlook.from_unified.yaml",
        ],
        'notes': 'Generates provider-specific YAMLs from the canonical unified config.'
    })
    # Optionally derive labels too
    if _cli_path_exists(["config","derive","filters"]) and _cli_path_exists(["config","derive","labels"]):
        add({
            'id': 'labels.derive',
            'title': 'Derive labels for providers',
            'tags': ['labels','derive','gmail','outlook','safe'],
            'requires': [["config","derive","labels"]],
            'commands': [
                "./bin/mail-assistant config derive labels --out-gmail out/labels.gmail.from_unified.yaml --out-outlook out/labels.outlook.from_unified.yaml",
            ],
        })

    # Gmail filters plan/apply/verify
    if all(_cli_path_exists(p) for p in [["filters","plan"],["filters","sync"],["filters","export"]]):
        add({
            'id': 'gmail.filters.plan-apply-verify',
            'title': 'Gmail Filters — Plan → Apply → Verify',
            'tags': ['gmail','filters','plan','apply','verify','safe'],
            'requires': [["filters","plan"],["filters","sync"],["filters","export"]],
            'commands': [
                "./bin/mail-assistant filters plan --config out/filters.gmail.from_unified.yaml --delete-missing",
                "./bin/mail-assistant filters sync --config out/filters.gmail.from_unified.yaml --delete-missing",
                "./bin/mail-assistant filters export --out out/filters.gmail.export.after.yaml",
            ],
            'notes': 'Always run plan first; delete-missing removes unmanaged rules.'
        })

    # Outlook rules plan/apply/verify
    if all(_cli_path_exists(p) for p in [["outlook","rules","plan"],["outlook","rules","sync"],["outlook","rules","list"]]):
        add({
            'id': 'outlook.rules.plan-apply-verify',
            'title': 'Outlook Rules — Plan → Apply → Verify',
            'tags': ['outlook','rules','plan','apply','verify','safe'],
            'requires': [["outlook","rules","plan"],["outlook","rules","sync"],["outlook","rules","list"]],
            'commands': [
                "./bin/mail-assistant outlook rules plan --config out/filters.outlook.from_unified.yaml --move-to-folders",
                "./bin/mail-assistant outlook rules sync --config out/filters.outlook.from_unified.yaml --move-to-folders --delete-missing",
                "./bin/mail-assistant outlook rules list",
            ],
            'notes': 'Use --categories-only on plan/sync when folder moves are restricted.'
        })

    # Filters sweep (existing mail)
    if _cli_path_exists(["filters","sweep"]):
        add({
            'id': 'gmail.filters.sweep-recent',
            'title': 'Filters Sweep — Recent window',
            'tags': ['gmail','filters','sweep','dry-run','safe'],
            'requires': [["filters","sweep"]],
            'commands': [
                "./bin/mail-assistant filters sweep --config out/filters.gmail.from_unified.yaml --days 90 --only-inbox --dry-run",
            ],
        })
    if _cli_path_exists(["filters","sweep-range"]):
        add({
            'id': 'gmail.filters.sweep-range',
            'title': 'Filters Sweep — Progressive windows',
            'tags': ['gmail','filters','sweep','range','dry-run','safe'],
            'requires': [["filters","sweep-range"]],
            'commands': [
                "./bin/mail-assistant filters sweep-range --config out/filters.gmail.from_unified.yaml --from-days 0 --to-days 3650 --step-days 90 --dry-run",
            ],
        })

    # Labels
    if all(_cli_path_exists(p) for p in [["labels","plan"],["labels","sync"],["labels","export"]]):
        add({
            'id': 'gmail.labels.plan-apply-verify',
            'title': 'Labels — Plan → Apply → Verify',
            'tags': ['gmail','labels','plan','apply','verify','safe'],
            'requires': [["labels","plan"],["labels","sync"],["labels","export"]],
            'commands': [
                "./bin/mail-assistant labels plan --config config/labels_current.yaml --delete-missing",
                "./bin/mail-assistant labels sync --config config/labels_current.yaml --delete-missing",
                "./bin/mail-assistant labels export --out out/labels.export.after.yaml",
            ],
            'notes': "Add --sweep-redirects to relabel old→new per 'redirects' then delete old."
        })

    # Signatures
    if all(_cli_path_exists(p) for p in [["signatures","export"],["signatures","normalize"],["signatures","sync"]]):
        add({
            'id': 'gmail.signatures.export-normalize-sync',
            'title': 'Signatures — Export → Normalize → Sync',
            'tags': ['gmail','signatures','export','normalize','sync','safe'],
            'requires': [["signatures","export"],["signatures","normalize"],["signatures","sync"]],
            'commands': [
                "./bin/mail-assistant signatures export --out out/signatures.export.yaml",
                "./bin/mail-assistant signatures normalize --config config/signatures.yaml --out-html out/signature.preview.html",
                "./bin/mail-assistant signatures sync --config config/signatures.yaml",
            ],
        })

    # Outlook categories and folders
    if all(_cli_path_exists(p) for p in [["outlook","categories","list"],["outlook","categories","export"],["outlook","categories","sync"]]):
        add({
            'id': 'outlook.categories.list-export-sync',
            'title': 'Outlook Categories — List → Export → Sync',
            'tags': ['outlook','categories','list','export','sync','safe'],
            'requires': [["outlook","categories","list"],["outlook","categories","export"],["outlook","categories","sync"]],
            'commands': [
                "./bin/mail-assistant outlook categories list",
                "./bin/mail-assistant outlook categories export --out out/outlook.categories.export.yaml",
                "./bin/mail-assistant outlook categories sync --config out/labels.outlook.from_unified.yaml",
            ],
        })
    if _cli_path_exists(["outlook","folders","sync"]):
        add({
            'id': 'outlook.folders.sync',
            'title': 'Outlook Folders — Sync from labels',
            'tags': ['outlook','folders','sync','safe'],
            'requires': [["outlook","folders","sync"]],
            'commands': [
                "./bin/mail-assistant outlook folders sync --config out/labels.outlook.from_unified.yaml --dry-run",
            ],
        })

    # Forwarding
    if all(_cli_path_exists(p) for p in [["forwarding","list"],["forwarding","add"],["forwarding","status"]]):
        add({
            'id': 'gmail.forwarding.list-add-status',
            'title': 'Forwarding — List/Add/Status',
            'tags': ['gmail','forwarding','safe'],
            'requires': [["forwarding","list"],["forwarding","add"],["forwarding","status"]],
            'commands': [
                "./bin/mail-assistant forwarding list",
                "./bin/mail-assistant forwarding add --email you@example.com",
                "./bin/mail-assistant forwarding status",
            ],
            'notes': 'Verified forwarding address required for filter-based forwarding.'
        })
    if all(_cli_path_exists(p) for p in [["filters","add-forward-by-label"],["filters","sync"]]):
        add({
            'id': 'gmail.forwarding.filters-combo',
            'title': 'Forwarding + Filters — Add/Enforce',
            'tags': ['gmail','forwarding','filters','safe'],
            'requires': [["filters","add-forward-by-label"],["filters","sync"]],
            'commands': [
                "./bin/mail-assistant filters add-forward-by-label --label Finance/Statements --forward you@example.com --dry-run",
                "# Enforce verified forwarders on sync:",
                "./bin/mail-assistant filters sync --config out/filters.gmail.from_unified.yaml --require-forward-verified --dry-run",
            ],
        })

    # Auto categorize/archive
    if all(_cli_path_exists(p) for p in [["auto","propose"],["auto","summary"],["auto","apply"]]):
        add({
            'id': 'gmail.auto.propose-summary-apply',
            'title': 'Auto (categorize + archive) — Propose → Summary → Apply',
            'tags': ['gmail','auto','propose','apply','dry-run','safe'],
            'requires': [["auto","propose"],["auto","summary"],["auto","apply"]],
            'commands': [
                "./bin/mail-assistant auto propose --out out/auto.proposal.json --days 7 --only-inbox --dry-run",
                "./bin/mail-assistant auto summary --proposal out/auto.proposal.json",
                "./bin/mail-assistant auto apply --proposal out/auto.proposal.json --cutoff-days 7 --dry-run",
            ],
        })

    # iOS Home Screen organization flows (detected via bin/phone)
    if _bin_exists('phone'):
        flows.extend([
            {
                'id': 'ios_export_layout',
                'title': 'iOS — Export current layout',
                'tags': ['ios','phone','layout','safe'],
                'commands': [
                    "./bin/phone export-device --out out/ios.IconState.yaml",
                    "./bin/phone iconmap --out out/ios.iconmap.json",
                ],
                'notes': 'Uses cfgutil to read device layout; no device writes.'
            },
            {
                'id': 'ios_scaffold_plan',
                'title': 'iOS — Scaffold plan (pins + folders)',
                'tags': ['ios','phone','plan','safe'],
                'commands': [
                    "./bin/phone plan --layout out/ios.IconState.yaml --out out/ios.plan.yaml",
                    "echo 'Edit out/ios.plan.yaml to arrange pins and folder contents.'",
                ],
                'notes': 'Edit-friendly YAML; categories pre-seeded (Work, Finance, Travel, etc.).'
            },
            {
                'id': 'ios_manual_checklist',
                'title': 'iOS — Generate manual move checklist',
                'tags': ['ios','phone','checklist','safe'],
                'commands': [
                    "./bin/phone checklist --plan out/ios.plan.yaml --layout out/ios.IconState.yaml --out out/ios.checklist.txt",
                ],
                'notes': 'Use this checklist to manually organize apps on device.'
            },
            {
                'id': 'ios_profile_build',
                'title': 'iOS — Build Home Screen Layout .mobileconfig',
                'tags': ['ios','phone','profile','advanced'],
                'commands': [
                    "./bin/phone profile build --plan out/ios.plan.yaml --layout out/ios.IconState.yaml --out out/ios.hslayout.mobileconfig --identifier com.example.profile --hs-identifier com.example.hslayout --display-name 'Home Screen Layout' --organization 'Personal'",
                ],
                'notes': 'Applying Home Screen Layout profiles requires supervised devices (MDM/Configurator).'
            },
            {
                'id': 'ios_unused_candidates',
                'title': 'iOS — Unused app candidates (heuristic)',
                'tags': ['ios','phone','unused','analysis','safe'],
                'commands': [
                    "./bin/phone unused --layout out/ios.IconState.yaml --limit 50",
                ],
                'notes': 'Heuristic: page depth, folders, dock, and user-supplied recent/keep lists.'
            },
            {
                'id': 'ios_unused_prune_offload',
                'title': 'iOS — OFFLOAD unused app checklist',
                'tags': ['ios','phone','unused','prune','offload','safe'],
                'commands': [
                    "./bin/phone prune --layout out/ios.IconState.yaml --mode offload --limit 50",
                ],
                'notes': 'Generates a manual offload checklist; no device writes.'
            },
            {
                'id': 'ios_unused_prune_delete',
                'title': 'iOS — DELETE unused app checklist',
                'tags': ['ios','phone','unused','prune','delete','safe'],
                'commands': [
                    "./bin/phone prune --layout out/ios.IconState.yaml --mode delete --limit 50",
                ],
                'notes': 'Generates a manual delete checklist; no device writes.'
            },
            {
                'id': 'ios_analyze_layout',
                'title': 'iOS — Analyze layout balance and folders',
                'tags': ['ios','phone','analyze','safe'],
                'commands': [
                    "./bin/phone analyze --layout out/ios.IconState.yaml",
                ],
                'notes': 'Summarizes dock, page balance, folders, duplicates, and plan alignment when provided.'
            },
            {
                'id': 'ios.organize-apps',
                'title': 'iOS — Organize Apps (end-to-end)',
                'tags': ['ios','phone','organize','safe'],
                'commands': [
                    "./bin/phone export-device --out out/ios.IconState.yaml",
                    "./bin/phone plan --layout out/ios.IconState.yaml --out out/ios.plan.yaml",
                    "echo 'Edit out/ios.plan.yaml to finalize folders and pins.'",
                    "./bin/phone checklist --plan out/ios.plan.yaml --layout out/ios.IconState.yaml --out out/ios.checklist.txt",
                ],
                'notes': 'Checklist-driven by default; see ios_profile_build for supervised devices.'
            },
        ])

    return flows


def _build_flows_index() -> str:
    flows = build_flows()
    lines: List[str] = []
    for f in flows:
        tags = ",".join(f.get('tags', []))
        lines.append(f"- {f['id']}: {f.get('title','')} [{tags}]")
    return "\n".join(lines)


def render_flow(flow: Dict[str, Any], fmt: str = 'md') -> str:
    """Render a single flow in md|yaml|json."""
    fmt = (fmt or 'md').lower()
    if fmt == 'json':
        try:
            import json as _json
            return _json.dumps(flow, indent=2)
        except Exception:
            pass
    if fmt == 'yaml':
        try:
            import yaml as _yaml  # type: ignore
            return _yaml.safe_dump(flow, sort_keys=False)
        except Exception:
            # fall back to md
            pass
    # md
    lines = [f"# {flow.get('title', flow.get('id'))}"]
    lines.append(f"id: {flow.get('id')}")
    if flow.get('tags'):
        lines.append(f"tags: {', '.join(flow['tags'])}")
    if flow.get('notes'):
        lines.append("")
        lines.append(f"note: {flow['notes']}")
    if flow.get('preconditions'):
        lines.append("")
        lines.append("preconditions:")
        for p in flow['preconditions']:
            lines.append(f"- {p}")
    if flow.get('commands'):
        lines.append("")
        lines.append("commands:")
        for c in flow['commands']:
            lines.append(f"- {c}")
    return "\n".join(lines)
