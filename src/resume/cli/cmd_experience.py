"""Experience command group registration for the Resume Assistant CLI."""

from __future__ import annotations

import argparse

from core.cli_framework import CLIApp

from ..io_utils import read_text_any, write_yaml_or_json
from ..parsing_experience_text import parse_resume_text
from ..experience_summary import build_experience_summary
from ..overlays import apply_profile_overlays
from .args import PROFILE_HELP_OUT, OUT_DIR_HELP, EXT_YAML
from .helpers import _load_candidate_data, _resolve_out


def cmd_experience_export(args: argparse.Namespace) -> int:
    if not args.data and not args.resume:
        raise SystemExit("Provide --data or --resume")
    if args.data:
        data = _load_candidate_data(args)
        prof = getattr(args, "profile", None)
        if prof:
            data = apply_profile_overlays(data, prof)
    else:
        # parse from resume file
        resume_text = read_text_any(args.resume)
        if str(args.resume).lower().endswith(".docx"):
            from ..parsing_experience_docx import parse_resume_docx

            data = parse_resume_docx(args.resume)
        else:
            data = parse_resume_text(resume_text)
    summary = build_experience_summary(data, max_bullets=args.max_bullets)
    out = _resolve_out(args, EXT_YAML, kind="experience")
    write_yaml_or_json(summary, out)
    return 0


def register_experience_commands(app: CLIApp) -> object:
    """Register the experience group and its subcommands on app."""
    experience_group = app.group("experience", help="Experience tools")

    experience_group.register(
        "export",
        "Export a YAML/JSON summary of job history from data or resume",
        cmd_experience_export,
        [
            (("--data",), {"help": "Unified data file (YAML/JSON)"}),
            (("--resume",), {"help": "Resume file to parse (txt/md/html/docx/pdf)"}),
            (("--max-bullets",), {"type": int, "default": None, "help": "Limit bullets per role in summary"}),
            (("--out",), {"help": "Output file path (overrides --profile)"}),
            (("--profile",), {"help": PROFILE_HELP_OUT}),
            (("--out-dir",), {"help": OUT_DIR_HELP}),
        ],
    )
    return experience_group
