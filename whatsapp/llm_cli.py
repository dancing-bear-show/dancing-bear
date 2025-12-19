from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from personal_core import llm_cli
from personal_core.textio import read_text

LLM_DIR = Path(".llm")


def _agentic() -> str:
    from .agentic import build_agentic_capsule

    try:
        return build_agentic_capsule()
    except Exception:
        return "agentic: whatsapp\npurpose: Local WhatsApp ChatStorage search helpers"


def _domain_map() -> str:
    from .agentic import build_domain_map

    try:
        return build_domain_map()
    except Exception:
        return "Domain Map not available"


def _inventory() -> str:
    return read_text(LLM_DIR / "INVENTORY.md") or "# LLM Agent Inventory (WhatsApp)\n\nSee repo .llm/INVENTORY.md for shared guidance.\n"


def _familiar_compact() -> str:
    return (
        read_text(LLM_DIR / "familiarize.yaml")
        or "meta:\n  name: whatsapp_familiarize\n  version: 1\nsteps:\n  - run: ./bin/whatsapp --help\n"
    )


def _familiar_extended() -> str:
    return (
        "meta:\n"
        "  name: whatsapp_familiarize\n"
        "  version: 1\n"
        "steps:\n"
        "  - run: ./bin/whatsapp search --contains school --limit 20\n"
    )


def _policies() -> str:
    return read_text(LLM_DIR / "PR_POLICIES.yaml") or "policies:\n  style:\n    - Keep CLI stable; prefer dry-run flows\n  tests:\n    - Add lightweight unittest for new CLI surfaces\n"


CONFIG = llm_cli.LlmConfig(
    prog="llm-whatsapp",
    description="WhatsApp Assistant LLM utilities (inventory, familiar, policies, agentic, domain-map)",
    agentic=_agentic,
    domain_map=_domain_map,
    inventory=_inventory,
    familiar_compact=_familiar_compact,
    familiar_extended=_familiar_extended,
    policies=_policies,
    agentic_filename="AGENTIC_WHATSAPP.md",
    domain_map_filename="DOMAIN_MAP_WHATSAPP.md",
)


def build_parser() -> argparse.ArgumentParser:
    return llm_cli.build_parser(CONFIG)


def main(argv: Optional[list[str]] = None) -> int:
    return llm_cli.run(CONFIG, argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
