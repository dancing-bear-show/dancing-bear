"""Shared CLI argument helpers for auth flags and common arguments.

Provides reusable argument groups for:
- Authentication (Gmail, Outlook)
- Output formatting (--output, --verbose, --quiet)
- Date ranges (--from-date, --to-date, --days-back)
- Operation modes (--dry-run, --force)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List, Any
import argparse


@dataclass
class OutlookAuthConfig:
    """Configuration for Outlook authentication arguments."""

    include_profile: bool = False
    profile_help: Optional[str] = None
    client_id_help: Optional[str] = "Azure app (client) ID; defaults from profile or env"
    tenant_help: Optional[str] = "AAD tenant (default: consumers)"
    tenant_default: Optional[str] = "consumers"
    token_help: Optional[str] = "Path to token cache JSON (optional)"  # noqa: S107 - help text, not a password


@dataclass
class GmailAuthConfig:
    """Configuration for Gmail authentication arguments."""

    include_cache: bool = True
    credentials_help: Optional[str] = None
    token_help: Optional[str] = None
    cache_help: Optional[str] = None


@dataclass
class OutputConfig:
    """Configuration for output formatting arguments."""

    formats: Optional[List[str]] = None
    default_format: str = "text"
    include_verbose: bool = True
    include_quiet: bool = True


@dataclass
class DateRangeConfig:
    """Configuration for date range arguments."""

    include_days_back: bool = True
    include_days_forward: bool = False
    default_days_back: int = 30
    default_days_forward: int = 180


def _add_argument_with_help(parser, flag: str, help_text: Optional[str], **kwargs) -> None:
    """Add argument to parser with optional help text.

    Args:
        parser: ArgumentParser to add argument to.
        flag: Argument flag (e.g., "--profile").
        help_text: Help text (None = no help).
        **kwargs: Additional arguments for add_argument.
    """
    if help_text is None:
        parser.add_argument(flag, **kwargs)
    else:
        parser.add_argument(flag, help=help_text, **kwargs)


def add_outlook_auth_args(parser, config: Optional[OutlookAuthConfig] = None):
    """Add Outlook authentication arguments to parser.

    Args:
        parser: ArgumentParser to add arguments to.
        config: OutlookAuthConfig with argument specifications.

    Returns:
        The parser for chaining.
    """
    if config is None:
        config = OutlookAuthConfig()

    # Add profile argument if requested
    if config.include_profile:
        _add_argument_with_help(parser, "--profile", config.profile_help)

    # Add client-id argument
    _add_argument_with_help(parser, "--client-id", config.client_id_help)

    # Add tenant argument with optional default
    tenant_kwargs = {"default": config.tenant_default} if config.tenant_default is not None else {}
    _add_argument_with_help(parser, "--tenant", config.tenant_help, **tenant_kwargs)

    # Add token argument
    _add_argument_with_help(parser, "--token", config.token_help)

    return parser


def add_gmail_auth_args(parser, config: Optional[GmailAuthConfig] = None):
    """Add Gmail authentication arguments to parser.

    Args:
        parser: ArgumentParser to add arguments to.
        config: GmailAuthConfig with argument specifications.

    Returns:
        The parser for chaining.
    """
    if config is None:
        config = GmailAuthConfig()

    if config.credentials_help is None:
        parser.add_argument("--credentials", type=str)
    else:
        parser.add_argument("--credentials", type=str, help=config.credentials_help)
    if config.token_help is None:
        parser.add_argument("--token", type=str)
    else:
        parser.add_argument("--token", type=str, help=config.token_help)
    if config.include_cache:
        if config.cache_help is None:
            parser.add_argument("--cache", type=str)
        else:
            parser.add_argument("--cache", type=str, help=config.cache_help)
    return parser


def add_output_args(parser, config: Optional[OutputConfig] = None):
    """Add output formatting arguments.

    Args:
        parser: ArgumentParser to add arguments to.
        config: OutputConfig with argument specifications.

    Returns:
        The parser for chaining.
    """
    if config is None:
        config = OutputConfig()

    output_formats = config.formats if config.formats is not None else ["text", "json", "yaml", "table"]

    parser.add_argument(
        "--output", "-o",
        choices=output_formats,
        default=config.default_format,
        help=f"Output format (default: {config.default_format})",
    )
    if config.include_verbose:
        parser.add_argument(
            "--verbose", "-v",
            action="store_true",
            help="Enable verbose output",
        )
    if config.include_quiet:
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


def add_date_range_args(parser, config: Optional[DateRangeConfig] = None):
    """Add date range arguments.

    Args:
        parser: ArgumentParser to add arguments to.
        config: DateRangeConfig with argument specifications.

    Returns:
        The parser for chaining.
    """
    if config is None:
        config = DateRangeConfig()

    parser.add_argument(
        "--from-date",
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--to-date",
        help="End date (YYYY-MM-DD)",
    )
    if config.include_days_back:
        parser.add_argument(
            "--days-back",
            type=int,
            default=config.default_days_back,
            help=f"Days to look back (default: {config.default_days_back})",
        )
    if config.include_days_forward:
        parser.add_argument(
            "--days-forward",
            type=int,
            default=config.default_days_forward,
            help=f"Days to look forward (default: {config.default_days_forward})",
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
