from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from core import llm_cli
from core.textio import read_text

from .meta import (
    AGENTIC_FALLBACK,
    DOMAIN_MAP_FALLBACK,
    FAMILIAR_COMPACT_FALLBACK,
    FAMILIAR_EXTENDED_FALLBACK,
    INVENTORY_FALLBACK,
    POLICIES_FALLBACK,
)

LLM_DIR = Path(".llm")


def _agentic() -> str:
    from .agentic import build_agentic_capsule

    try:
        return build_agentic_capsule()
    except Exception:
        return AGENTIC_FALLBACK


def _domain_map() -> str:
    from .agentic import build_domain_map

    try:
        return build_domain_map()
    except Exception:
        return DOMAIN_MAP_FALLBACK


def _inventory() -> str:
    return read_text(LLM_DIR / "INVENTORY.md") or INVENTORY_FALLBACK


def _familiar_compact() -> str:
    return (
        read_text(LLM_DIR / "familiarize.yaml")
        or FAMILIAR_COMPACT_FALLBACK
    )


def _familiar_extended() -> str:
    return FAMILIAR_EXTENDED_FALLBACK


def _policies() -> str:
    return read_text(LLM_DIR / "PR_POLICIES.yaml") or POLICIES_FALLBACK


CONFIG = llm_cli.make_app_llm_config(
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
