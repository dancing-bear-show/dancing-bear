"""Agentic capsule builders for the Desk Assistant CLI."""
from __future__ import annotations

from functools import lru_cache
from typing import List

from core.agentic import (
    build_cli_tree as _core_build_cli_tree,
    cli_path_exists as _core_cli_path_exists,
    section as _section,
)


@lru_cache(maxsize=1)
def _get_parser():
    try:
        from . import cli as cli_mod

        return cli_mod.build_parser()
    except Exception:
        return None


def _cli_tree() -> str:
    return _core_build_cli_tree(_get_parser())


def _cli_path_exists(path: List[str]) -> bool:
    return _core_cli_path_exists(_get_parser(), path)


def _flow_map() -> str:
    lines: List[str] = []
    if _cli_path_exists(["scan"]):
        lines.append("- Scan clutter: ./bin/desk-assistant scan --paths ~/Downloads ~/Desktop --duplicates --out out/desk.scan.yaml")
    if _cli_path_exists(["plan"]):
        lines.append("- Plan cleanup: ./bin/desk-assistant plan --config config/rules.yaml --out out/desk.plan.yaml")
    if _cli_path_exists(["apply"]):
        lines.append("- Apply plan (dry-run first): ./bin/desk-assistant apply --plan out/desk.plan.yaml --dry-run")
    if _cli_path_exists(["rules", "export"]):
        lines.append("- Starter rules: ./bin/desk-assistant rules export --out config/rules.example.yaml")
    return "\n".join(lines)


def build_agentic_capsule() -> str:
    commands = [
        "scan: ./bin/desk-assistant scan --paths ~/Downloads ~/Desktop --duplicates --out out/desk.scan.yaml",
        "plan: ./bin/desk-assistant plan --config config/desk_rules.yaml --out out/desk.plan.yaml",
        "apply: ./bin/desk-assistant apply --plan out/desk.plan.yaml --dry-run",
        "rules export: ./bin/desk-assistant rules export --out config/desk_rules.example.yaml",
    ]
    sections: List[Tuple[str, str]] = []
    tree = _cli_tree()
    if tree:
        sections.append(("CLI Tree", tree))
    flows = _flow_map()
    if flows:
        sections.append(("Flow Map", flows))
    return _build_capsule(
        "desk",
        "Scan, plan, and tidy macOS folders (Downloads, Desktop)",
        commands,
        sections,
    )


def build_domain_map() -> str:
    sections: List[str] = []
    sections.append("Top-Level\n- desk/scan.py — disk scan logic\n- desk/planner.py — rules → plan\n- desk/apply_ops.py — filesystem actions\n- config/desk_rules.yaml — example rules\n- out/desk.* — scan/plan artifacts")
    tree = _cli_tree()
    if tree:
        sections.append(_section("CLI Tree", tree))
    flows = _flow_map()
    if flows:
        sections.append(_section("Flow Map", flows))
    return "\n".join([s for s in sections if s])


def emit_agentic_context(fmt: str = "text", compact: bool = False) -> int:
    print(build_agentic_capsule())
    return 0
