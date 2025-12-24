from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from core import llm_cli
from core.textio import read_text

LLM_DIR = Path(".llm")


def _agentic() -> str:
    from .agentic import build_agentic_capsule

    try:
        return build_agentic_capsule()
    except Exception:
        return "agentic: wifi\npurpose: Wi-Fi and LAN diagnostics"


def _domain_map() -> str:
    from .agentic import build_domain_map

    try:
        return build_domain_map()
    except Exception:
        return "Domain Map not available"


def _inventory() -> str:
    return read_text(LLM_DIR / "INVENTORY.md") or "# LLM Agent Inventory (Wi-Fi Assistant)\n\nSee repo .llm/INVENTORY.md.\n"


def _familiar_compact() -> str:
    return (
        read_text(LLM_DIR / "familiarize.yaml")
        or "meta:\n  name: wifi_familiarize\n  version: 2\nsteps:\n  - run: ./bin/wifi --help\n"
    )


def _familiar_extended() -> str:
    return (
        "meta:\n"
        "  name: wifi_familiarize\n"
        "  version: 2\n"
        "steps:\n"
        "  - run: ./bin/wifi --ping-count 8\n"
        "  - run: ./bin/wifi --json --out out/wifi.diag.json\n"
    )


def _policies() -> str:
    return read_text(LLM_DIR / "PR_POLICIES.yaml") or "policies:\n  style:\n    - Keep CLI flags stable; avoid new dependencies\n  tests:\n    - Add lightweight unittest for new probes and CLI output\n"


CONFIG = llm_cli.LlmConfig(
    prog="llm",
    description="Wi-Fi LLM utilities (agentic/domain-map/familiar)",
    agentic=_agentic,
    domain_map=_domain_map,
    inventory=_inventory,
    familiar_compact=_familiar_compact,
    familiar_extended=_familiar_extended,
    policies=_policies,
    agentic_filename="AGENTIC_WIFI.md",
    domain_map_filename="DOMAIN_MAP_WIFI.md",
)


def build_parser() -> argparse.ArgumentParser:
    return llm_cli.build_parser(CONFIG)


def main(argv: Optional[list[str]] = None) -> int:
    return llm_cli.run(CONFIG, argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
