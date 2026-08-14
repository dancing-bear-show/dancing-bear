from __future__ import annotations

from pathlib import Path

from core import llm_cli
from core.textio import read_text

LLM_DIR = Path(".llm")


_AGENTIC_FALLBACK = "agentic: maker\npurpose: Utility generators and print helpers"


def _agentic() -> str:
    try:
        from .agentic import build_agentic_capsule

        return build_agentic_capsule()
    except Exception:  # nosec B110 - graceful fallback when agentic module unavailable
        return _AGENTIC_FALLBACK


def _domain_map() -> str:
    try:
        from .agentic import build_domain_map

        return build_domain_map()
    except Exception:  # nosec B110 - graceful fallback when agentic module unavailable
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


build_parser, main = llm_cli.bind_entrypoints(CONFIG)


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
