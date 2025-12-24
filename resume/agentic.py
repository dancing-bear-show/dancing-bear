"""Agentic capsule helpers for the Resume Assistant CLI."""
from __future__ import annotations

from functools import lru_cache
from typing import List, Tuple

from core.agentic import (
    build_capsule as _build_capsule,
    build_cli_tree as _core_build_cli_tree,
    cli_path_exists as _core_cli_path_exists,
    section as _section,
)


@lru_cache(maxsize=1)
def _get_parser():
    try:
        from .cli.main import build_parser

        return build_parser()
    except Exception:
        return None


def _cli_tree() -> str:
    return _core_build_cli_tree(_get_parser())


def _cli_path_exists(path: List[str]) -> bool:
    return _core_cli_path_exists(_get_parser(), path)


def _flow_map() -> str:
    lines: List[str] = []
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
    sections: List[Tuple[str, str]] = []
    tree = _cli_tree()
    if tree:
        sections.append(("CLI Tree", tree))
    flows = _flow_map()
    if flows:
        sections.append(("Flow Map", flows))
    return _build_capsule(
        "resume",
        "Extract, summarize, and render resumes (DOCX/YAML/JSON)",
        commands,
        sections,
    )


def build_domain_map() -> str:
    sections: List[str] = []
    sections.append("Top-Level\n- resume/cli/main.py — CLI entry\n- config/ — seeds, templates, job specs\n- corpus/ — sample resumes\n- out/ — generated outputs (summaries, DOCX)")
    tree = _cli_tree()
    if tree:
        sections.append(_section("CLI Tree", tree))
    flows = _flow_map()
    if flows:
        sections.append(_section("Flow Map", flows))
    return "\n".join([s for s in sections if s])


def emit_agentic_context(fmt: str = "text", compact: bool = False) -> int:
    print(build_agentic_capsule())
    return 0
