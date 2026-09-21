"""Summarize command registration for the Resume Assistant CLI."""

from __future__ import annotations

import argparse

from core.cli_framework import CLIApp
from core.textio import write_text

from ..io_utils import write_yaml_or_json
from ..summarizer import build_summary
from ..templating import parse_seed_criteria
from .args import PROFILE_HELP_DATA, OUT_DIR_HELP, DATA_HELP, EXT_YAML, EXT_JSON
from .helpers import _load_candidate_data, _apply_filter_pipeline, _extend_seed_with_style, _resolve_out


def cmd_summarize(args: argparse.Namespace) -> int:
    data = _load_candidate_data(args)
    # build_summary still takes a dict; converting it is a later step.
    data = _apply_filter_pipeline(data, args).to_dict()

    seed = parse_seed_criteria(args.seed) if args.seed else {}
    seed = _extend_seed_with_style(seed, getattr(args, "style_profile", None))
    summary = build_summary(data, seed)
    out = _resolve_out(args, ".md", kind="summary")
    if out.suffix.lower() in {EXT_YAML, ".yml", EXT_JSON}:
        write_yaml_or_json(summary, out)
    else:
        # Default to markdown/text
        lines = ["# Resume Summary"]
        if summary.get("headline"):
            lines.append(f"\n## Headline\n{summary['headline']}")
        if summary.get("top_skills"):
            skills = ", ".join(summary["top_skills"]) or ""
            lines.append(f"\n## Top Skills\n{skills}")
        if summary.get("experience_highlights"):
            lines.append("\n## Experience Highlights")
            for item in summary["experience_highlights"]:
                lines.append(f"- {item}")
        write_text(out, "\n".join(lines))
    return 0


def register_summarize_commands(app: CLIApp) -> None:
    """Register the summarize command on app."""
    _ARGS = [
        (("--data",), {"help": DATA_HELP}),
        (("--seed",), {"help": "Seed criteria as JSON string or KEY=VALUE pairs (comma-separated)"}),
        (("--style-profile",), {"help": "Style profile JSON from 'style build' (optional)"}),
        (("--filter-skills-alignment",), {"help": "Alignment JSON to filter Skills"}),
        (("--filter-skills-job",), {"help": "Job YAML/JSON to supplement synonyms"}),
        (("--filter-exp-alignment",), {"help": "Alignment JSON to filter Experience"}),
        (("--filter-exp-job",), {"help": "Job YAML/JSON for experience filter"}),
        (("--out",), {"help": "Output file path (overrides --profile)"}),
        (("--profile",), {"help": PROFILE_HELP_DATA}),
        (("--out-dir",), {"help": OUT_DIR_HELP}),
    ]
    app.add_arguments(_ARGS)
    app.command("summarize", help="Build heuristically-derived summary output")(cmd_summarize)
