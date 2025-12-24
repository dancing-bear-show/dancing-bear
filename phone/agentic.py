"""Agentic capsule builders for the Phone Assistant CLI."""
from __future__ import annotations

from functools import lru_cache
from typing import List, Tuple

from core.agentic import (
    build_capsule as _build_capsule,
    build_cli_tree as _core_build_cli_tree,
    cli_path_exists as _core_cli_path_exists,
    section as _section,
)


@lru_cache(maxsize=1)
def _get_parser():
    try:
        from . import __main__ as main_mod

        return main_mod.build_parser()
    except Exception:
        return None


def _cli_tree() -> str:
    return _core_build_cli_tree(_get_parser())


def _cli_path_exists(path: List[str]) -> bool:
    return _core_cli_path_exists(_get_parser(), path)


def _flow_map() -> str:
    lines: List[str] = []
    layout_cmds = [
        ("export-device", "Export layout (device)", "./bin/phone export-device --out out/ios.IconState.yaml"),
        ("iconmap", "Download icon map", "./bin/phone iconmap --out out/ios.iconmap.json"),
        ("plan", "Scaffold plan", "./bin/phone plan --layout out/ios.IconState.yaml --out out/ios.plan.yaml"),
        ("checklist", "Checklist", "./bin/phone checklist --plan out/ios.plan.yaml --layout out/ios.IconState.yaml --out out/ios.checklist.txt"),
    ]
    if all(_cli_path_exists([cmd]) for cmd, *_ in layout_cmds):
        lines.append("- Layout workflow")
        for _, title, cmd in layout_cmds:
            lines.append(f"  - {title}: {cmd}")
    if _cli_path_exists(["auto-folders"]) or _cli_path_exists(["analyze"]):
        lines.append("- Layout insights")
        if _cli_path_exists(["analyze"]):
            lines.append("  - Analyze balance: ./bin/phone analyze --layout out/ios.IconState.yaml --format text")
        if _cli_path_exists(["auto-folders"]):
            lines.append("  - Auto folders: ./bin/phone auto-folders --layout out/ios.IconState.yaml --plan out/ios.plan.yaml")
    if _cli_path_exists(["profile", "build"]):
        lines.append("- Profiles")
        lines.append("  - Build .mobileconfig: ./bin/phone profile build --plan out/ios.plan.yaml --out out/ios.mobileconfig")
    if _cli_path_exists(["export-device"]):
        lines.append("- Device snapshot")
        lines.append("  - Refresh icon map + YAML: ./bin/ios-iconmap-refresh")
    if _cli_path_exists(["manifest", "create"]):
        lines.append("- Manifests")
        lines.append("  - Create manifest: ./bin/phone manifest create --plan out/ios.plan.yaml --out out/ios.manifest.yaml")
        if _cli_path_exists(["manifest", "install"]):
            lines.append("  - Install profile: ./bin/phone manifest install --manifest out/ios.manifest.yaml --device-label ipad2025")
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
    sections: List[Tuple[str, str]] = []
    tree = _cli_tree()
    if tree:
        sections.append(("CLI Tree", tree))
    flows = _flow_map()
    if flows:
        sections.append(("Flow Map", flows))
    return _build_capsule(
        "phone",
        "Home Screen layout planning, manifests, and identity flows",
        commands,
        sections,
    )


def build_domain_map() -> str:
    """Programmatically build a minimal domain map for Phone Assistant."""
    sections: List[str] = []
    sections.append("Top-Level\n- phone/backup.py — Finder backup helpers\n- phone/layout.py — normalization + plan scaffolds\n- phone/profile.py — .mobileconfig builders")
    tree = _cli_tree()
    if tree:
        sections.append(_section("CLI Tree", tree))
    flows = _flow_map()
    if flows:
        sections.append(_section("Flow Map", flows))
    return "\n".join([s for s in sections if s])


def emit_agentic_context(fmt: str = "text", compact: bool = False) -> int:
    """Emit the agentic capsule (fmt/compact best-effort for parity)."""
    # Currently only text output is supported; fmt/compact are ignored.
    print(build_agentic_capsule())
    return 0
