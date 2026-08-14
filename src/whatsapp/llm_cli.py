from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from core import llm_cli
from core.textio import read_text

from .meta import META

LLM_DIR = Path(".llm")


def _agentic() -> str:
    from .agentic import build_agentic_capsule

    try:
        return build_agentic_capsule()
    except Exception:  # nosec B110 - fall back to static capsule if dynamic build fails
        return META.agentic_fallback


def _domain_map() -> str:
    from .agentic import build_domain_map

    try:
        return build_domain_map()
    except Exception:  # nosec B110 - fall back to static domain map if dynamic build fails
        return META.domain_map_fallback


def _inventory() -> str:
    return read_text(LLM_DIR / "INVENTORY.md") or META.inventory_fallback


def _familiar_compact() -> str:
    return (
        read_text(LLM_DIR / "familiarize.yaml")
        or META.familiar_compact_fallback
    )


def _familiar_extended() -> str:
    return META.familiar_extended_fallback


def _policies() -> str:
    return read_text(LLM_DIR / "PR_POLICIES.yaml") or META.policies_fallback


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
