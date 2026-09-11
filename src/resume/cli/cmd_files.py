"""Files command group registration for the Resume Assistant CLI."""

from __future__ import annotations

import argparse

from core.cli_framework import CLIApp

from ..cleanup import build_tidy_plan, execute_archive, execute_delete, purge_temp_files


def cmd_files_tidy(args: argparse.Namespace) -> int:
    suffixes = [s.strip() for s in (args.suffixes or "").split(",") if s.strip()]
    plan = build_tidy_plan(
        dir_path=args.dir,
        prefix=args.prefix,
        suffixes=suffixes,
        keep=args.keep,
        archive_dir=args.archive_dir,
    )
    # Archive/delete old files
    if plan.move:
        if args.delete:
            execute_delete(plan)
        else:
            execute_archive(plan, subfolder=args.subfolder or args.prefix)
    # Purge temp files if requested
    if args.purge_temp:
        purge_temp_files(args.dir)
    return 0


def register_files_commands(app: CLIApp) -> object:
    """Register the files group and its subcommands on app."""
    files_group = app.group("files", help="File utilities for organizing outputs and data")

    files_group.register(
        "tidy",
        "Archive or delete old files to reduce noise",
        cmd_files_tidy,
        [
            (("--dir",), {"default": "_data", "help": "Directory to tidy (default: _data)"}),
            (("--prefix",), {"help": "Only match files starting with this prefix"}),
            (("--suffixes",), {"default": ".json,.docx", "help": "Comma-separated suffix list (e.g., .json,.docx)"}),
            (("--keep",), {"type": int, "default": 2, "help": "Keep most-recent N matches (default: 2)"}),
            (("--archive-dir",), {"help": "Archive destination directory (default: <dir>/archive)"}),
            (("--delete",), {"action": "store_true", "help": "Delete old files instead of archiving"}),
            (("--purge-temp",), {"action": "store_true", "help": "Remove temporary files (e.g., '~$*.docx', .DS_Store)"}),
            (("--subfolder",), {"help": "Subfolder under archive for moved files (e.g., profile name)"}),
        ],
    )
    return files_group
