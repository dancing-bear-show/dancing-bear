from __future__ import annotations

"""Agentic capsule builders for the WhatsApp Assistant CLI."""

from functools import lru_cache
from typing import List, Tuple

from core.agentic import (
    build_capsule as _build_capsule,
    build_cli_tree as _build_cli_tree,
    cli_path_exists as _cli_path_exists,
    section as _section,
)
from .meta import APP_ID, PURPOSE


@lru_cache(maxsize=1)
def _get_parser():
    try:
        from . import __main__ as main_mod

        return main_mod.build_parser()
    except Exception:
        return None


def _cli_tree() -> str:
    return _build_cli_tree(_get_parser())


def _flow_map() -> str:
    if not _cli_path_exists(_get_parser(), ["search"]):
        return ""
    return "\n".join(
        [
            "- Local search",
            "  - Search ChatStorage: ./bin/whatsapp search --contains school --limit 20",
        ]
    )


def build_agentic_capsule() -> str:
    commands = [
        "help: ./bin/whatsapp --help",
        "search text: ./bin/whatsapp search --contains school --limit 20",
        "search contact: ./bin/whatsapp search --contact 'Teacher' --since-days 30",
    ]
    sections: List[Tuple[str, str]] = []
    tree = _cli_tree()
    if tree:
        sections.append(("CLI Tree", tree))
    flows = _flow_map()
    if flows:
        sections.append(("Flow Map", flows))
    return _build_capsule(
        APP_ID,
        PURPOSE,
        commands,
        sections,
    )


def build_domain_map() -> str:
    sections: List[str] = []
    sections.append(
        "Top-Level\n- whatsapp/search.py — ChatStorage search helpers"
    )
    tree = _cli_tree()
    if tree:
        sections.append(_section("CLI Tree", tree))
    flows = _flow_map()
    if flows:
        sections.append(_section("Flow Map", flows))
    return "\n".join([s for s in sections if s])


def emit_agentic_context(fmt: str = "text", compact: bool = False) -> int:
    """Emit the agentic capsule (fmt/compact best-effort)."""
    # Currently only text output is supported; fmt/compact ignored.
    print(build_agentic_capsule())
    return 0
