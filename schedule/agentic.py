"""Agentic capsule helpers for the Schedule Assistant CLI."""
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

        return main_mod.app.build_parser()
    except Exception:
        return None


def _cli_tree() -> str:
    return _core_build_cli_tree(_get_parser())


def _cli_path_exists(path: List[str]) -> bool:
    return _core_cli_path_exists(_get_parser(), path)


def _flow_map() -> str:
    lines: List[str] = []
    if _cli_path_exists(["plan"]):
        lines.append("- Plan")
        lines.append("  - Build canonical plan: ./bin/schedule-assistant plan --source schedules/classes.csv --out out/schedule.plan.yaml")
    if _cli_path_exists(["apply"]):
        lines.append("- Apply")
        lines.append("  - Dry-run apply: ./bin/schedule-assistant apply --plan out/schedule.plan.yaml --dry-run")
        lines.append("  - Apply (create events): ./bin/schedule-assistant apply --plan out/schedule.plan.yaml --apply --calendar 'Your Family'")
    if _cli_path_exists(["verify"]):
        lines.append("- Verify")
        lines.append("  - Verify plan: ./bin/schedule-assistant verify --plan out/schedule.plan.yaml --calendar 'Your Family' --from 2025-10-01 --to 2025-12-31")
    if _cli_path_exists(["sync"]):
        lines.append("- Sync")
        lines.append("  - Safe dry-run: ./bin/schedule-assistant sync --plan out/schedule.plan.yaml --calendar 'Your Family' --from 2025-10-01 --to 2025-12-31")
    if _cli_path_exists(["export"]):
        lines.append("- Export")
        lines.append("  - Export Outlook window: ./bin/schedule-assistant export --calendar 'Activities' --from 2025-10-01 --to 2025-12-31 --out config/calendar/activities.yaml")
    if _cli_path_exists(["compress"]):
        lines.append("- Compress")
        lines.append("  - Infer recurring series: ./bin/schedule-assistant compress --in config/calendar/activities.yaml --out config/calendar/activities.compressed.yaml")
    return "\n".join(lines)


def build_agentic_capsule() -> str:
    commands = [
        "plan: ./bin/schedule-assistant plan --source schedules/classes.csv --out out/schedule.plan.yaml",
        "apply (dry-run): ./bin/schedule-assistant apply --plan out/schedule.plan.yaml --dry-run",
        "verify: ./bin/schedule-assistant verify --plan out/schedule.plan.yaml --calendar 'Your Family' --from 2025-10-01 --to 2025-12-31",
        "sync (dry-run): ./bin/schedule-assistant sync --plan out/schedule.plan.yaml --calendar 'Your Family' --from 2025-10-01 --to 2025-12-31 --dry-run",
    ]
    sections: List[Tuple[str, str]] = []
    tree = _cli_tree()
    if tree:
        sections.append(("CLI Tree", tree))
    flows = _flow_map()
    if flows:
        sections.append(("Flow Map", flows))
    return _build_capsule(
        "schedule_assistant",
        "Generate/verify/apply calendar plans (dry-run first)",
        commands,
        sections,
    )


def build_domain_map() -> str:
    sections: List[str] = []
    sections.append("Top-Level\n- schedule_assistant/__main__.py — CLI entry\n- schedule_assistant/README.md — usage examples\n- config/calendar/ — canonical plans")
    tree = _cli_tree()
    if tree:
        sections.append(_section("CLI Tree", tree))
    flows = _flow_map()
    if flows:
        sections.append(_section("Flow Map", flows))
    return "\n".join([s for s in sections if s])


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    # _fmt/_compact kept for signature parity but currently unused.
    print(build_agentic_capsule())
    return 0
