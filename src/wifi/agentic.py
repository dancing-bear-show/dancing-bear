"""Agentic capsule builders for the Wi-Fi Assistant CLI."""
from __future__ import annotations

from core.agentic import (
    build_capsule as _build_capsule,
    build_cli_tree as _core_build_cli_tree,
    build_domain_map as _core_build_domain_map,
    cached_parser_loader as _cached_parser_loader,
    tree_and_flow_sections as _tree_and_flow_sections,
)


def _load_parser():
    from .cli import app

    return app.build_parser()


_get_parser = _cached_parser_loader(_load_parser)


def _cli_tree() -> str:
    return _core_build_cli_tree(_get_parser())


def build_agentic_capsule() -> str:
    commands = [
        "quick diag: ./bin/wifi diagnose --ping-count 12",
        "trim trace/http: ./bin/wifi diagnose --no-trace --no-http",
        "JSON output: ./bin/wifi diagnose --json --out wifi.diag.json",
    ]
    probes_body = "\n".join(
        [
            "- gateway detection via route/ip",
            "- Wi-Fi info: airport|nmcli|iwconfig",
            "- ping sweep: gateway + 1.1.1.1 + 8.8.8.8 + google.com",
            "- DNS timing: configurable host (default google.com)",
            "- Tracepath/traceroute and HTTPS smoke",
        ]
    )
    return _build_capsule(
        "wifi",
        "Wi-Fi and LAN diagnostics (gateway vs upstream vs DNS)",
        commands,
        [("Probes", probes_body)] + _tree_and_flow_sections(_cli_tree(), None),
    )


def build_domain_map() -> str:
    return _core_build_domain_map(
        "Top-Level\n"
        "- bin/wifi — CLI wrapper\n"
        "- wifi/cli.py — argparse entry\n"
        "- wifi/pipeline.py — pipeline components\n"
        "- wifi/diagnostics_probes.py — probes (wifi info, ping, dns, trace, http)\n"
        "- wifi/diagnostics_report.py — report derivation and rendering\n"
        "- wifi/agentic.py — capsule + domain map\n"
        "- wifi/llm_cli.py — LLM wiring",
        _cli_tree(),
        None,
    )


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit agentic capsule. Format/compact params for API consistency."""
    print(build_agentic_capsule())
    return 0
