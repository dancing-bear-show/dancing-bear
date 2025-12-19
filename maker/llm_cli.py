from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from personal_core import llm_cli
from personal_core.textio import read_text

LLM_DIR = Path(".llm")


def _agentic() -> str:
    try:
        from .agentic import build_agentic_capsule

        return build_agentic_capsule()
    except Exception:
        return "agentic: maker\npurpose: Utility generators and print helpers"


def _domain_map() -> str:
    try:
        from .agentic import build_domain_map

        return build_domain_map()
    except Exception:
        return "Domain Map not available"


CONFIG = llm_cli.make_app_llm_config(
    prog="llm-maker",
    description="Maker LLM utilities (agentic, domain-map, derive-all)",
    agentic=_agentic,
    domain_map=_domain_map,
    inventory=lambda: read_text(LLM_DIR / "INVENTORY.md") or "",
    familiar_compact=lambda: read_text(LLM_DIR / "familiarize.yaml") or "",
    policies=lambda: read_text(LLM_DIR / "PR_POLICIES.yaml") or "",
    agentic_filename="AGENTIC_MAKER.md",
    domain_map_filename="DOMAIN_MAP_MAKER.md",
)


def build_parser() -> argparse.ArgumentParser:
    return llm_cli.build_parser(CONFIG)


def main(argv: Optional[list[str]] = None) -> int:
    return llm_cli.run(CONFIG, argv)


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
