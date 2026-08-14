"""Agentic capsule helpers for the Resume Assistant CLI."""
from __future__ import annotations

from core.agentic import (
    build_capsule as _build_capsule,
    build_cli_tree as _core_build_cli_tree,
    build_domain_map as _core_build_domain_map,
    cached_parser_loader as _cached_parser_loader,
    cli_path_exists as _core_cli_path_exists,
    tree_and_flow_sections as _tree_and_flow_sections,
)


def _load_parser():
    from .cli.main import build_parser

    return build_parser()


_get_parser = _cached_parser_loader(_load_parser)


def _cli_tree() -> str:
    return _core_build_cli_tree(_get_parser())


def _cli_path_exists(path: list[str]) -> bool:
    return _core_cli_path_exists(_get_parser(), path)


def _flow_map() -> str:
    lines: list[str] = []
    if all(_cli_path_exists([cmd]) for cmd in [["extract"], ["summarize"], ["render"]]):
        lines.append("- Resume workflow")
        lines.append("  - Extract: ./bin/resume-assistant extract --linkedin data/linkedin.txt --resume data/resume.pdf --out out/profile.json")
        lines.append("  - Summarize: ./bin/resume-assistant summarize --data out/profile.json --seed seeds/general.yaml")
        lines.append("  - Render DOCX: ./bin/resume-assistant render --data out/profile.json --template templates/modern.yaml --profile default")
    if _cli_path_exists(["align"]):
        lines.append("- Align to job posting: ./bin/resume-assistant align --data out/profile.json --job jobs/default.yaml --out out/alignment.yaml")
    if _cli_path_exists(["style"]):
        lines.append("- Style profile: ./bin/resume-assistant style build --templates templates/style.json --out out/style_profile.json")
    if _cli_path_exists(["cleanup"]):
        lines.append("- Cleanup workspace: ./bin/resume-assistant cleanup tidy --plan out/cleanup.plan.yaml --apply")
    return "\n".join(lines)


def build_agentic_capsule() -> str:
    commands = [
        "extract: ./bin/resume-assistant extract --linkedin data/linkedin.txt --resume data/resume.pdf --out out/profile.json",
        "summarize: ./bin/resume-assistant summarize --data out/profile.json --seed seeds/general.yaml",
        "render: ./bin/resume-assistant render --data out/profile.json --template templates/modern.yaml --profile default",
        "align: ./bin/resume-assistant align --data out/profile.json --job jobs/default.yaml",
    ]
    return _build_capsule(
        "resume",
        "Extract, summarize, and render resumes (DOCX/YAML/JSON)",
        commands,
        _tree_and_flow_sections(_cli_tree(), _flow_map()),
    )


def build_domain_map() -> str:
    return _core_build_domain_map(
        "Top-Level\n- resume/cli/main.py — CLI entry\n- config/ — seeds, templates, job specs\n- corpus/ — sample resumes\n- out/ — generated outputs (summaries, DOCX)",
        _cli_tree(),
        _flow_map(),
    )


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit the agentic capsule (fmt/compact not yet implemented)."""
    from core.cli_output import OutputWriter
    OutputWriter().print_data(build_agentic_capsule())
    return 0
