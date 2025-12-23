from __future__ import annotations

"""Shared CLI argument helpers for auth flags and common arguments.

Provides reusable argument groups for:
- Authentication (Gmail, Outlook)
- Output formatting (--output, --verbose, --quiet)
- Date ranges (--from-date, --to-date, --days-back)
- Operation modes (--dry-run, --force)
"""

from typing import Optional, List, Any
import argparse


def add_outlook_auth_args(
    parser,
    *,
    include_profile: bool = False,
    profile_help: Optional[str] = None,
    client_id_help: Optional[str] = "Azure app (client) ID; defaults from profile or env",
    tenant_help: Optional[str] = "AAD tenant (default: consumers)",
    tenant_default: Optional[str] = "consumers",
    token_help: Optional[str] = "Path to token cache JSON (optional)",
):
    if include_profile:
        if profile_help is None:
            parser.add_argument("--profile")
        else:
            parser.add_argument("--profile", help=profile_help)
    if client_id_help is None:
        parser.add_argument("--client-id")
    else:
        parser.add_argument("--client-id", help=client_id_help)
    if tenant_default is None:
        if tenant_help is None:
            parser.add_argument("--tenant")
        else:
            parser.add_argument("--tenant", help=tenant_help)
    else:
        if tenant_help is None:
            parser.add_argument("--tenant", default=tenant_default)
        else:
            parser.add_argument("--tenant", default=tenant_default, help=tenant_help)
    if token_help is None:
        parser.add_argument("--token")
    else:
        parser.add_argument("--token", help=token_help)
    return parser


def add_gmail_auth_args(
    parser,
    *,
    include_cache: bool = True,
    credentials_help: Optional[str] = None,
    token_help: Optional[str] = None,
    cache_help: Optional[str] = None,
):
    if credentials_help is None:
        parser.add_argument("--credentials", type=str)
    else:
        parser.add_argument("--credentials", type=str, help=credentials_help)
    if token_help is None:
        parser.add_argument("--token", type=str)
    else:
        parser.add_argument("--token", type=str, help=token_help)
    if include_cache:
        if cache_help is None:
            parser.add_argument("--cache", type=str)
        else:
            parser.add_argument("--cache", type=str, help=cache_help)
    return parser


def add_output_args(
    parser,
    *,
    formats: Optional[List[str]] = None,
    default_format: str = "text",
    include_verbose: bool = True,
    include_quiet: bool = True,
):
    """Add output formatting arguments.

    Args:
        parser: ArgumentParser to add arguments to.
        formats: List of supported formats (default: text, json, yaml, table).
        default_format: Default output format.
        include_verbose: Include --verbose flag.
        include_quiet: Include --quiet flag.

    Returns:
        The parser for chaining.
    """
    if formats is None:
        formats = ["text", "json", "yaml", "table"]

    parser.add_argument(
        "--output", "-o",
        choices=formats,
        default=default_format,
        help=f"Output format (default: {default_format})",
    )
    if include_verbose:
        parser.add_argument(
            "--verbose", "-v",
            action="store_true",
            help="Enable verbose output",
        )
    if include_quiet:
        parser.add_argument(
            "--quiet", "-q",
            action="store_true",
            help="Suppress non-essential output",
        )
    return parser


def add_dry_run_args(
    parser,
    *,
    include_force: bool = False,
):
    """Add dry-run and force arguments.

    Args:
        parser: ArgumentParser to add arguments to.
        include_force: Include --force flag.

    Returns:
        The parser for chaining.
    """
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them",
    )
    if include_force:
        parser.add_argument(
            "--force", "-f",
            action="store_true",
            help="Force operation without confirmation",
        )
    return parser


def add_date_range_args(
    parser,
    *,
    include_days_back: bool = True,
    include_days_forward: bool = False,
    default_days_back: int = 30,
    default_days_forward: int = 180,
):
    """Add date range arguments.

    Args:
        parser: ArgumentParser to add arguments to.
        include_days_back: Include --days-back option.
        include_days_forward: Include --days-forward option.
        default_days_back: Default days to look back.
        default_days_forward: Default days to look forward.

    Returns:
        The parser for chaining.
    """
    parser.add_argument(
        "--from-date",
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--to-date",
        help="End date (YYYY-MM-DD)",
    )
    if include_days_back:
        parser.add_argument(
            "--days-back",
            type=int,
            default=default_days_back,
            help=f"Days to look back (default: {default_days_back})",
        )
    if include_days_forward:
        parser.add_argument(
            "--days-forward",
            type=int,
            default=default_days_forward,
            help=f"Days to look forward (default: {default_days_forward})",
        )
    return parser


def add_profile_args(
    parser,
    *,
    profile_help: Optional[str] = None,
):
    """Add profile argument.

    Args:
        parser: ArgumentParser to add arguments to.
        profile_help: Custom help text for profile argument.

    Returns:
        The parser for chaining.
    """
    parser.add_argument(
        "--profile", "-p",
        help=profile_help or "Credentials profile name",
    )
    return parser


def add_filter_args(
    parser,
    *,
    include_limit: bool = True,
    include_offset: bool = False,
    default_limit: int = 100,
):
    """Add filtering/pagination arguments.

    Args:
        parser: ArgumentParser to add arguments to.
        include_limit: Include --limit option.
        include_offset: Include --offset option.
        default_limit: Default limit value.

    Returns:
        The parser for chaining.
    """
    if include_limit:
        parser.add_argument(
            "--limit", "-n",
            type=int,
            default=default_limit,
            help=f"Maximum number of results (default: {default_limit})",
        )
    if include_offset:
        parser.add_argument(
            "--offset",
            type=int,
            default=0,
            help="Skip first N results (default: 0)",
        )
    return parser


class ArgumentGroup:
    """Helper for creating argument groups with the CLI framework.

    Example:
        class MyApp(CLIApp):
            def __init__(self):
                super().__init__("myapp", "My CLI")
                self.auth_group = ArgumentGroup([
                    Argument(("--profile", "-p"), help="Profile name"),
                    Argument(("--token",), help="Token path"),
                ])

        @app.command("list")
        @app.with_group(app.auth_group)
        def cmd_list(args):
            ...
    """

    def __init__(self, arguments: List[Any]):
        """Initialize with a list of arguments.

        Args:
            arguments: List of Argument instances or (name_or_flags, kwargs) tuples.
        """
        self.arguments = arguments

    def add_to_parser(self, parser: argparse.ArgumentParser) -> None:
        """Add all arguments in this group to a parser.

        Args:
            parser: The parser to add arguments to.
        """
        for arg in self.arguments:
            if hasattr(arg, "name_or_flags"):
                parser.add_argument(*arg.name_or_flags, **arg.kwargs)
            elif isinstance(arg, tuple) and len(arg) == 2:
                name_or_flags, kwargs = arg
                if isinstance(name_or_flags, str):
                    name_or_flags = (name_or_flags,)
                parser.add_argument(*name_or_flags, **kwargs)
