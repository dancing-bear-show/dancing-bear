"""Agentic capsule builders for the Desk Assistant CLI."""
from __future__ import annotations

from core.agentic import (
    build_capsule as _build_capsule,
    build_cli_tree as _core_build_cli_tree,
    build_domain_map as _core_build_domain_map,
    cached_parser_loader as _cached_parser_loader,
    cli_path_exists as _core_cli_path_exists,
    tree_and_flow_sections as _tree_and_flow_sections,
)


def _load_parser():
    from . import cli as cli_mod

    return cli_mod.build_parser()


_get_parser = _cached_parser_loader(_load_parser)


def _cli_tree() -> str:
    return _core_build_cli_tree(_get_parser())


def _cli_path_exists(path: list[str]) -> bool:
    return _core_cli_path_exists(_get_parser(), path)


def _flow_map() -> str:
    lines: list[str] = []
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
    return _build_capsule(
        "desk",
        "Scan, plan, and tidy macOS folders (Downloads, Desktop)",
        commands,
        _tree_and_flow_sections(_cli_tree(), _flow_map()),
    )


def build_domain_map() -> str:
    return _core_build_domain_map(
        "Top-Level\n- desk/scan.py — disk scan logic\n- desk/planner.py — rules → plan\n- desk/apply_ops.py — filesystem actions\n- config/desk_rules.yaml — example rules\n- out/desk.* — scan/plan artifacts",
        _cli_tree(),
        _flow_map(),
    )


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit agentic capsule. Format/compact params for API consistency."""
    print(build_agentic_capsule())
    return 0
