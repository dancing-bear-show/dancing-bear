"""Agentic capsule builders for the WhatsApp Assistant CLI."""
from __future__ import annotations

from core.agentic import (
    build_capsule as _build_capsule,
    build_cli_tree as _build_cli_tree,
    build_domain_map as _core_build_domain_map,
    cached_parser_loader as _cached_parser_loader,
    cli_path_exists as _cli_path_exists,
    tree_and_flow_sections as _tree_and_flow_sections,
)
from .meta import META


def _load_parser():
    from . import __main__ as main_mod

    return main_mod.build_parser()


_get_parser = _cached_parser_loader(_load_parser)


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
    return _build_capsule(
        META.app_id,
        META.purpose,
        commands,
        _tree_and_flow_sections(_cli_tree(), _flow_map()),
    )


def build_domain_map() -> str:
    return _core_build_domain_map(
        "Top-Level\n- whatsapp/search.py — ChatStorage search helpers",
        _cli_tree(),
        _flow_map(),
    )


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit the agentic capsule (fmt/compact best-effort)."""
    # Currently only text output is supported; fmt/compact ignored.
    print(build_agentic_capsule())
    return 0
