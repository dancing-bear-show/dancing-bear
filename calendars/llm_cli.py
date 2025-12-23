from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from core import llm_cli
from core.textio import read_text


LLM_DIR = Path(".llm")


def _inventory_md() -> str:
    return read_text(LLM_DIR / "INVENTORY.md") or (
        "# LLM Agent Inventory (Calendar)\n\nSee repo .llm/INVENTORY.md for shared guidance.\n"
    )


def _familiar_compact() -> str:
    return (
        read_text(LLM_DIR / "familiarize.yaml")
        or "meta:\n  name: calendar_familiarize\n  version: 4\nsteps:\n  - run: ./bin/calendar --agentic\n  - run: ./bin/llm-calendar agentic --stdout\n"
    )


def _familiar_extended() -> str:
    return (
        "meta:\n"
        "  name: calendar_familiarize\n"
        "  version: 4\n"
        "steps:\n"
        "  - run: ./bin/calendar --agentic\n"
        "  - run: ./bin/llm-calendar agentic --stdout\n"
        "  - run: ./bin/mail-assistant --profile outlook_personal outlook auth ensure || true\n"
        "  - run: ./bin/mail-assistant --profile outlook_personal outlook auth validate || true\n"
    )


def _policies_md() -> str:
    return (
        read_text(LLM_DIR / "PR_POLICIES.yaml")
        or "policies:\n  style:\n    - Keep CLI stable; add only\n  tests:\n    - Add lightweight unittest for new CLI\n"
    )


def _agentic_capsule() -> str:
    try:
        from .agentic import build_agentic_capsule

        return build_agentic_capsule()
    except Exception:
        return "agentic: calendar\npurpose: Outlook calendars + Gmail scans → plans"


def _domain_map() -> str:
    try:
        from .agentic import build_domain_map

        return build_domain_map()
    except Exception:
        return "Domain Map not available"


CONFIG = llm_cli.make_app_llm_config(
    prog="llm-calendar",
    description="Calendar LLM utilities (inventory, familiar, policies, agentic, domain-map)",
    agentic=_agentic_capsule,
    domain_map=_domain_map,
    inventory=_inventory_md,
    familiar_compact=_familiar_compact,
    familiar_extended=_familiar_extended,
    policies=_policies_md,
    agentic_filename="AGENTIC_CALENDAR.md",
    domain_map_filename="DOMAIN_MAP_CALENDAR.md",
)


def build_parser() -> argparse.ArgumentParser:
    return llm_cli.build_parser(CONFIG)


def main(argv: Optional[list[str]] = None) -> int:
    return llm_cli.run(CONFIG, argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
