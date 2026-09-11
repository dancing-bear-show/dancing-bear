"""Style command group registration for the Resume Assistant CLI."""

from __future__ import annotations

import argparse

from core.cli_framework import CLIApp

from ..io_utils import write_yaml_or_json
from .args import PROFILE_HELP_OUT, OUT_DIR_HELP, EXT_JSON
from .helpers import _resolve_out


def cmd_style_build(args: argparse.Namespace) -> int:
    from ..style import build_style_profile
    prof = build_style_profile(args.corpus_dir)
    out = _resolve_out(args, EXT_JSON, kind="style")
    write_yaml_or_json(prof, out)
    return 0


def register_style_commands(app: CLIApp) -> object:
    """Register the style group and its subcommands on app."""
    style_group = app.group("style", help="Build or manage style profiles from a prose corpus")

    style_group.register(
        "build",
        "Build style profile JSON from a corpus directory",
        cmd_style_build,
        [
            (("--corpus-dir",), {"required": True, "help": "Directory of prose samples (.txt/.md/.docx)"}),
            (("--out",), {"help": "Output file path (overrides --profile)"}),
            (("--profile",), {"help": PROFILE_HELP_OUT}),
            (("--out-dir",), {"help": OUT_DIR_HELP}),
        ],
    )
    return style_group
