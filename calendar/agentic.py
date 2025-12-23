from __future__ import annotations

"""Agentic capsule builders for the Calendar Assistant.

These functions dynamically introspect the CLI to produce concise
capsules and domain maps for LLM agents. They avoid heavy imports and
execute only lightweight parsing logic.
"""

from functools import lru_cache
from pathlib import Path
from typing import List

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
    # Outlook flows: add/add-recurring/from-config/verify/update/apply/dedup/list/remove/share
    if _cli_path_exists(["outlook", "add"]) or _cli_path_exists(["outlook", "add-recurring"]):
        lines.append("- Outlook add")
        if _cli_path_exists(["outlook", "add"]):
            lines.append("  - One-off: ./bin/calendar outlook add --subject 'Title' --start 2025-01-01T10:00 --end 2025-01-01T11:00 --calendar 'Your Family'")
        if _cli_path_exists(["outlook", "add-recurring"]):
            lines.append("  - Recurring: ./bin/calendar outlook add-recurring --subject 'Class' --repeat weekly --byday MO --start-time 17:00 --end-time 17:30 --range-start 2025-10-01 --until 2025-12-15 --calendar 'Your Family'")
    if _cli_path_exists(["outlook", "add-from-config"]) and _cli_path_exists(["outlook", "verify-from-config"]):
        lines.append("- Outlook from YAML")
        lines.append("  - Add from config: ./bin/calendar outlook add-from-config --config schedules/plan.yaml")
        lines.append("  - Verify plan: ./bin/calendar outlook verify-from-config --config schedules/plan.yaml")
    if _cli_path_exists(["outlook", "update-locations"]) and _cli_path_exists(["outlook", "apply-locations"]):
        lines.append("- Locations")
        lines.append("  - Update from Outlook: ./bin/calendar outlook update-locations --config schedules/plan.yaml")
        lines.append("  - Apply to Outlook: ./bin/calendar outlook apply-locations --config schedules/plan.yaml")
    if _cli_path_exists(["outlook", "reminders-off"]):
        lines.append("- Reminders")
        lines.append("  - Turn off: ./bin/calendar outlook reminders-off --calendar 'Your Family' --from 2025-01-01 --to 2025-12-31 --all-occurrences")
    if _cli_path_exists(["outlook", "dedup"]):
        lines.append("- Deduplicate")
        lines.append("  - Remove dup series: ./bin/calendar outlook dedup --calendar 'Your Family' --apply")
    if _cli_path_exists(["outlook", "list-one-offs"]):
        lines.append("- List one-offs")
        lines.append("  - List: ./bin/calendar outlook list-one-offs --calendar 'Your Family' --from 2025-01-01 --to 2025-12-31 --out out/one_offs.yaml")
    if _cli_path_exists(["outlook", "remove-from-config"]):
        lines.append("- Remove from YAML")
        lines.append("  - Delete: ./bin/calendar outlook remove-from-config --config schedules/plan.yaml --apply")
    if _cli_path_exists(["outlook", "calendar-share"]):
        lines.append("- Share")
        lines.append("  - Share calendar: ./bin/calendar outlook calendar-share --calendar 'Your Family' --user someone@example.com --role reviewer")

    # Gmail scan flows
    if _cli_path_exists(["gmail", "scan-classes"]) or _cli_path_exists(["gmail", "scan-receipts"]) or _cli_path_exists(["gmail", "scan-activerh"]):
        lines.append("- Gmail scan")
        if _cli_path_exists(["gmail", "scan-classes"]):
            lines.append("  - Classes: ./bin/calendar gmail scan-classes --days 60 --out out/classes.plan.yaml")
        if _cli_path_exists(["gmail", "scan-receipts"]):
            lines.append("  - Receipts: ./bin/calendar gmail scan-receipts --days 365 --out out/receipts.plan.yaml")
        if _cli_path_exists(["gmail", "scan-activerh"]):
            lines.append("  - ActiveRH: ./bin/calendar gmail scan-activerh --days 365 --out out/activerh.plan.yaml")

    return "\n".join(lines)


def emit_agentic_context(fmt: str = "text", compact: bool = False) -> int:
    """Emit a compact agentic capsule (best-effort format/compact params)."""
    print(build_agentic_capsule())
    return 0


def build_agentic_capsule() -> str:
    """Construct a compact agentic capsule string.

    The capsule summarizes purpose, key commands, a CLI tree, and a flow map.
    """
    commands = [
        "help: ./bin/calendar --help",
        "add: ./bin/calendar outlook add --help",
        "scan: ./bin/calendar gmail scan-classes --help",
    ]
    sections: List[Tuple[str, str]] = []
    tree = _cli_tree()
    if tree:
        sections.append(("CLI Tree", tree))
    flows = _flow_map()
    if flows:
        sections.append(("Flow Map", flows))
    return _build_capsule(
        "calendar_assistant",
        "Outlook calendars + Gmail scans → plans",
        commands,
        sections,
    )


def build_domain_map() -> str:
    """Construct a programmatic domain map for Calendar Assistant."""
    out: List[str] = []
    out.append("Top-Level\n- bin/ — wrappers (calendar, calendar-assistant, schedule-assistant)\n- out/ — curated artifacts and plans\n- .llm/ — agent context (shared at repo root)")
    tree = _cli_tree()
    if tree:
        out.append(_section("CLI Tree", tree))
    flows = _flow_map()
    if flows:
        out.append(_section("Flow Map", flows))
    return "\n".join([s for s in out if s])
