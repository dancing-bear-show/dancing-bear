"""Extract command registration for the Resume Assistant CLI."""

from __future__ import annotations

import argparse

from core.cli_framework import CLIApp

from ..schema import CandidateData
from ..parsing_linkedin import parse_linkedin_text
from ..parsing_experience_text import merge_profiles
from ..io_utils import read_text_any, write_yaml_or_json
from .args import PROFILE_HELP_OUT, OUT_DIR_HELP, EXT_JSON
from .helpers import _read_linkedin_text, _parse_resume_source, _resolve_out


def cmd_extract(args: argparse.Namespace) -> int:
    linkedin_text = _read_linkedin_text(args.linkedin) if args.linkedin else ""
    resume_text = read_text_any(args.resume) if args.resume else ""
    li = parse_linkedin_text(linkedin_text) if linkedin_text else {}
    rs = _parse_resume_source(args.resume, resume_text) if args.resume else {}
    data: CandidateData = merge_profiles(li, rs)
    out_path = _resolve_out(args, EXT_JSON, kind="data")
    write_yaml_or_json(data, out_path)
    return 0


def register_extract_commands(app: CLIApp) -> None:
    """Register the extract command on app."""
    _ARGS = [
        (("--linkedin",), {"help": "Path to LinkedIn profile (txt/md/html/docx/pdf)"}),
        (("--resume",), {"help": "Path to resume (txt/md/html/docx/pdf)"}),
        (("--out",), {"help": "Output file path (overrides --profile)"}),
        (("--profile",), {"help": PROFILE_HELP_OUT}),
        (("--out-dir",), {"help": OUT_DIR_HELP}),
    ]
    app.add_arguments(_ARGS)
    app.command("extract", help="Parse LinkedIn and resume sources and produce unified data (YAML/JSON)")(cmd_extract)
