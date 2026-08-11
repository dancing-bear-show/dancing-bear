"""Command grouping for nested CLI subcommands.

Split out of cli_framework.py to keep that module focused on CLIApp.
"""
from __future__ import annotations

import argparse
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    TYPE_CHECKING,
)

from .cli_framework_types import CommandDef, CommandFunc

if TYPE_CHECKING:
    from .cli_framework import CLIApp


class CommandGroup:
    """A group of related commands (e.g., "outlook" containing "add", "list", etc.)."""

    def __init__(
        self,
        app: "CLIApp",
        name: str,
        *,
        help: str = "",
        description: str = "",
    ):
        self.app = app
        self.name = name
        self.help = help
        self.description = description or help
        self._commands: Dict[str, CommandDef] = {}

    def command(
        self,
        name: str,
        *,
        help: str = "",
        description: str = "",
        aliases: Optional[List[str]] = None,
    ) -> Callable[[CommandFunc], CommandFunc]:
        """Decorator to register a command in this group.

        Args:
            name: Command name.
            help: Short help text.
            description: Longer description.
            aliases: Alternative names.

        Returns:
            Decorator function.
        """
        def decorator(func: CommandFunc) -> CommandFunc:
            # Collect pending arguments
            arguments = list(reversed(self.app._pending_arguments))
            self.app._pending_arguments.clear()

            cmd_def = CommandDef(
                name=name,
                func=func,
                help=help,
                description=description or help,
                arguments=arguments,
                aliases=aliases or [],
                parent=self.name,
            )
            self._commands[name] = cmd_def

            # Also register in the app's command dict
            full_name = f"{self.name}.{name}"
            self.app._commands[full_name] = cmd_def

            return func
        return decorator

    def argument(
        self,
        *name_or_flags: str,
        **kwargs: Any,
    ) -> Callable[[CommandFunc], CommandFunc]:
        """Decorator to add an argument. Delegates to app."""
        return self.app.argument(*name_or_flags, **kwargs)

    def _build_subparsers(self, parser: argparse.ArgumentParser) -> None:
        """Build subparsers for this group's commands."""
        if self.app.add_common_args:
            self.app._add_common_arguments(parser)

        subparsers = parser.add_subparsers(dest=f"{self.name}_cmd", metavar="<subcommand>")

        for cmd_name, cmd_def in self._commands.items():
            cmd_parser = subparsers.add_parser(
                cmd_name,
                help=cmd_def.help,
                description=cmd_def.description,
                aliases=cmd_def.aliases,
            )
            self.app._add_command_arguments(cmd_parser, cmd_def)
            cmd_parser.set_defaults(_cmd_func=cmd_def.func)


# Convenience function for simple scripts
def quick_cli(
    name: str,
    description: str = "",
    **kwargs: Any,
) -> "CLIApp":
    """Create a simple CLI app quickly.

    Args:
        name: Program name.
        description: Program description.
        **kwargs: Additional arguments to CLIApp.

    Returns:
        CLIApp instance.
    """
    from .cli_framework import CLIApp

    return CLIApp(name, description, **kwargs)
