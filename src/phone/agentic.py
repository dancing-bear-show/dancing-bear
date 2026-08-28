"""Agentic capsule builders for the Phone Assistant CLI."""

from __future__ import annotations

import argparse

from core.agentic import (
    build_capsule as _build_capsule,
    build_cli_tree as _core_build_cli_tree,
    build_domain_map as _core_build_domain_map,
    cached_parser_loader as _cached_parser_loader,
    cli_path_exists as _core_cli_path_exists,
    tree_and_flow_sections as _tree_and_flow_sections,
)


def _load_parser() -> argparse.ArgumentParser:
    # Load from cli.main's CLIApp, matching calendars/schedule. Importing
    # __main__ and calling build_parser() on it raised AttributeError —
    # __main__ only re-exports main() — which _cached_parser_loader swallowed,
    # so _get_parser() returned None and _cli_tree()/_flow_map() silently
    # produced empty strings.
    from .cli.main import app

    return app.build_parser()


_get_parser = _cached_parser_loader(_load_parser)


def _cli_tree() -> str:
    return _core_build_cli_tree(_get_parser())


def _cli_path_exists(path: list[str]) -> bool:
    return _core_cli_path_exists(_get_parser(), path)


def _flow_map() -> str:
    lines: list[str] = []
    layout_cmds = [
        (
            "export-device",
            "Export layout (device)",
            "./bin/phone export-device --out out/ios.IconState.yaml",
        ),
        (
            "iconmap",
            "Download icon map",
            "./bin/phone iconmap --out out/ios.iconmap.json",
        ),
        (
            "plan",
            "Scaffold plan",
            "./bin/phone plan --layout out/ios.IconState.yaml --out out/ios.plan.yaml",
        ),
        (
            "checklist",
            "Checklist",
            "./bin/phone checklist --plan out/ios.plan.yaml --layout out/ios.IconState.yaml --out out/ios.checklist.txt",
        ),
    ]
    if all(_cli_path_exists([cmd]) for cmd, *_ in layout_cmds):
        lines.append("- Layout workflow")
        for _, title, cmd in layout_cmds:
            lines.append(f"  - {title}: {cmd}")
    if _cli_path_exists(["auto-folders"]) or _cli_path_exists(["analyze"]):
        lines.append("- Layout insights")
        if _cli_path_exists(["analyze"]):
            lines.append(
                "  - Analyze balance: ./bin/phone analyze --layout out/ios.IconState.yaml --format text"
            )
        if _cli_path_exists(["auto-folders"]):
            lines.append(
                "  - Auto folders: ./bin/phone auto-folders --layout out/ios.IconState.yaml --plan out/ios.plan.yaml"
            )
    if _cli_path_exists(["profile", "build"]):
        lines.append("- Profiles")
        lines.append(
            "  - Build .mobileconfig: ./bin/phone profile build --plan out/ios.plan.yaml --out out/ios.mobileconfig"
        )
    if _cli_path_exists(["export-device"]):
        lines.append("- Device snapshot")
        lines.append("  - Refresh icon map + YAML: ./bin/ios-iconmap-refresh")
    if _cli_path_exists(["manifest", "create"]):
        lines.append("- Manifests")
        lines.append(
            "  - Create manifest: ./bin/phone manifest create --from-plan ios.plan.yaml --out ios.manifest.yaml"
        )
        if _cli_path_exists(["manifest", "install"]):
            lines.append(
                "  - Install profile: ./bin/phone manifest install --manifest out/ios.manifest.yaml --device-label ipad2025"
            )
    return "\n".join(lines)


def build_agentic_capsule() -> str:
    """Construct a compact capsule for LLM agents."""
    commands = [
        "help: ./bin/phone --help",
        "export-device: ./bin/phone export-device --out out/ios.IconState.yaml",
        "iconmap: ./bin/phone iconmap --out out/ios.iconmap.json",
        "plan: ./bin/phone plan --layout out/ios.IconState.yaml --out out/ios.plan.yaml",
        "checklist: ./bin/phone checklist --plan out/ios.plan.yaml",
    ]
    return _build_capsule(
        "phone",
        "Home Screen layout planning, manifests, and identity flows",
        commands,
        _tree_and_flow_sections(_cli_tree(), _flow_map()),
    )


def build_domain_map() -> str:
    """Programmatically build a minimal domain map for Phone Assistant."""
    return _core_build_domain_map(
        "Top-Level\n- phone/backup.py — Finder backup helpers\n- phone/layout_normalize.py — layout normalization\n- phone/layout_plan_analyze.py — plan analysis + ranking\n- phone/layout_plan_scaffold.py — plan scaffolds\n- phone/profile.py — .mobileconfig builders",
        _cli_tree(),
        _flow_map(),
    )


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit the agentic capsule (fmt/compact not yet implemented)."""
    print(build_agentic_capsule())
    return 0
