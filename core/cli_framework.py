"""CLI application framework for assistant modules.

Provides a declarative way to build CLI applications with:
- Command registration via decorators
- Automatic argument parsing
- Consistent error handling
- Output formatting
- Common arguments (--profile, --dry-run, --verbose, --output)
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    TypeVar,
)

from .cli_errors import CLIError, ExitCode, handle_error
from .cli_output import OutputConfig, OutputFormat, OutputWriter


T = TypeVar("T")
CommandFunc = Callable[[argparse.Namespace], int]


@dataclass
class Argument:
    """Definition of a CLI argument."""
    name_or_flags: tuple
    kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandDef:
    """Definition of a CLI command."""
    name: str
    func: CommandFunc
    help: str = ""
    description: str = ""
    arguments: List[Argument] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    parent: Optional[str] = None  # For nested commands like "outlook add"


class CLIApp:
    """Base class for CLI applications.

    Example usage:
        app = CLIApp("my-assistant", "My assistant CLI")

        @app.command("list", help="List items")
        @app.argument("--filter", "-f", help="Filter pattern")
        def cmd_list(args):
            print(f"Listing with filter: {args.filter}")
            return 0

        if __name__ == "__main__":
            app.run()
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        *,
        version: Optional[str] = None,
        epilog: Optional[str] = None,
        add_common_args: bool = True,
    ):
        """Initialize the CLI application.

        Args:
            name: Program name (used in help text).
            description: Program description.
            version: Optional version string.
            epilog: Optional text to display after help.
            add_common_args: Whether to add common args (--verbose, --output, etc.).
        """
        self.name = name
        self.description = description
        self.version = version
        self.epilog = epilog
        self.add_common_args = add_common_args

        self._commands: Dict[str, CommandDef] = {}
        self._groups: Dict[str, "CommandGroup"] = {}
        self._parser: Optional[argparse.ArgumentParser] = None
        self._pending_arguments: List[Argument] = []

    def command(
        self,
        name: str,
        *,
        help: str = "",
        description: str = "",
        aliases: Optional[List[str]] = None,
        parent: Optional[str] = None,
    ) -> Callable[[CommandFunc], CommandFunc]:
        """Decorator to register a command.

        Args:
            name: Command name (can include parent like "outlook.add" or "outlook add").
            help: Short help text for the command.
            description: Longer description for command help.
            aliases: Alternative names for the command.
            parent: Parent command group (alternative to dot notation in name).

        Returns:
            Decorator function.
        """
        def decorator(func: CommandFunc) -> CommandFunc:
            # Collect any pending arguments from @argument decorators
            arguments = list(reversed(self._pending_arguments))
            self._pending_arguments.clear()

            # Parse parent from name if not provided
            cmd_name = name
            cmd_parent = parent
            if "." in name and not parent:
                parts = name.split(".", 1)
                cmd_parent = parts[0]
                cmd_name = parts[1]
            elif " " in name and not parent:
                parts = name.split(" ", 1)
                cmd_parent = parts[0]
                cmd_name = parts[1]

            cmd_def = CommandDef(
                name=cmd_name,
                func=func,
                help=help,
                description=description or help,
                arguments=arguments,
                aliases=aliases or [],
                parent=cmd_parent,
            )

            # Store with full path for lookup
            full_name = f"{cmd_parent}.{cmd_name}" if cmd_parent else cmd_name
            self._commands[full_name] = cmd_def

            return func
        return decorator

    def argument(
        self,
        *name_or_flags: str,
        **kwargs: Any,
    ) -> Callable[[CommandFunc], CommandFunc]:
        """Decorator to add an argument to the next command.

        Must be used BEFORE the @command decorator (decorators apply bottom-up).

        Args:
            *name_or_flags: Argument name(s) like "--verbose" or "-v", "--verbose".
            **kwargs: Keyword arguments passed to argparse.add_argument().

        Returns:
            Decorator function.
        """
        def decorator(func: CommandFunc) -> CommandFunc:
            self._pending_arguments.append(Argument(name_or_flags, kwargs))
            return func
        return decorator

    def group(
        self,
        name: str,
        *,
        help: str = "",
        description: str = "",
    ) -> "CommandGroup":
        """Create a command group for nested commands.

        Args:
            name: Group name.
            help: Short help text.
            description: Longer description.

        Returns:
            CommandGroup for registering sub-commands.
        """
        group = CommandGroup(self, name, help=help, description=description)
        self._groups[name] = group
        return group

    def build_parser(self) -> argparse.ArgumentParser:
        """Build the argument parser."""
        parser = argparse.ArgumentParser(
            prog=self.name,
            description=self.description,
            epilog=self.epilog,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

        if self.version:
            parser.add_argument(
                "--version", "-V",
                action="version",
                version=f"%(prog)s {self.version}",
            )

        if self.add_common_args:
            self._add_common_arguments(parser)

        # Add subparsers if we have commands
        if self._commands or self._groups:
            subparsers = parser.add_subparsers(dest="command", metavar="<command>")

            # Add command groups
            for group_name, group in self._groups.items():
                group_parser = subparsers.add_parser(
                    group_name,
                    help=group.help,
                    description=group.description,
                )
                group._build_subparsers(group_parser)

            # Add top-level commands (those without a parent)
            for full_name, cmd_def in self._commands.items():
                if cmd_def.parent is None:
                    cmd_parser = subparsers.add_parser(
                        cmd_def.name,
                        help=cmd_def.help,
                        description=cmd_def.description,
                        aliases=cmd_def.aliases,
                    )
                    self._add_command_arguments(cmd_parser, cmd_def)
                    cmd_parser.set_defaults(_cmd_func=cmd_def.func)

        self._parser = parser
        return parser

    def _add_common_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add common arguments to the parser."""
        parser.add_argument(
            "--profile", "-p",
            help="Credentials profile name",
        )
        parser.add_argument(
            "--verbose", "-v",
            action="store_true",
            help="Enable verbose output",
        )
        parser.add_argument(
            "--quiet", "-q",
            action="store_true",
            help="Suppress non-essential output",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without applying them",
        )
        parser.add_argument(
            "--output", "-o",
            choices=["text", "json", "yaml", "table"],
            default="text",
            help="Output format (default: text)",
        )

    def _add_command_arguments(
        self,
        parser: argparse.ArgumentParser,
        cmd_def: CommandDef,
    ) -> None:
        """Add command-specific arguments to the parser."""
        for arg in cmd_def.arguments:
            parser.add_argument(*arg.name_or_flags, **arg.kwargs)

    def run_with_assistant(
        self,
        assistant: Any,
        emit_func: Callable[[str, bool], int],
        argv: Optional[Sequence[str]] = None,
        *,
        pre_run_hook: Optional[Callable[[], None]] = None,
        post_build_hook: Optional[Callable[[argparse.ArgumentParser], None]] = None,
    ) -> int:
        """Run the CLI application with agentic flag support.

        This method builds the parser, adds agentic flags from the assistant,
        and handles --agentic output before running commands.

        Args:
            assistant: BaseAssistant instance for agentic flag handling.
            emit_func: Function to emit agentic output (fmt, compact) -> int.
            argv: Command-line arguments (defaults to sys.argv[1:]).
            pre_run_hook: Optional function to call before parsing (e.g., output masking).
            post_build_hook: Optional function to customize parser after build (e.g., add args).

        Returns:
            Exit code.
        """
        # Run pre-run hook if provided (e.g., install output masking)
        if pre_run_hook:
            try:
                pre_run_hook()
            except Exception as e:  # nosec B110 - best-effort hook, safe to continue
                print(f"Warning: Pre-run hook failed ({type(e).__name__}), continuing", file=sys.stderr)

        # Build parser and add agentic flags
        parser = self.build_parser()
        if post_build_hook:
            post_build_hook(parser)
        assistant.add_agentic_flags(parser)

        args = parser.parse_args(argv)

        # Handle agentic output if requested
        agentic_result = assistant.maybe_emit_agentic(args, emit_func=emit_func)
        if agentic_result is not None:
            return int(agentic_result)

        # Get the command function
        cmd_func = getattr(args, "_cmd_func", None)
        if cmd_func is None:
            parser.print_help()
            return 0

        # Run the command with error handling
        try:
            return int(cmd_func(args))
        except CLIError as e:
            return handle_error(e, verbose=getattr(args, "verbose", False))
        except KeyboardInterrupt:
            print("\nInterrupted.", file=sys.stderr)
            return ExitCode.INTERRUPTED
        except Exception as e:
            return handle_error(e, verbose=getattr(args, "verbose", False))

    def run(self, argv: Optional[Sequence[str]] = None) -> int:
        """Run the CLI application.

        Args:
            argv: Command-line arguments (defaults to sys.argv[1:]).

        Returns:
            Exit code.
        """
        parser = self._parser
        if parser is None:
            parser = self.build_parser()
        args = parser.parse_args(argv)

        # Set up output writer
        output_format = OutputFormat(getattr(args, "output", "text"))
        output_config = OutputConfig(
            format=output_format,
            verbose=getattr(args, "verbose", False),
            quiet=getattr(args, "quiet", False),
        )
        args._output = OutputWriter(output_config)

        # Get the command function
        cmd_func = getattr(args, "_cmd_func", None)
        if cmd_func is None:
            self._parser.print_help()
            return ExitCode.USAGE

        # Run the command with error handling
        try:
            return cmd_func(args)
        except CLIError as e:
            return handle_error(e, verbose=getattr(args, "verbose", False))
        except KeyboardInterrupt:
            print("\nInterrupted.", file=sys.stderr)
            return ExitCode.INTERRUPTED
        except Exception as e:
            return handle_error(e, verbose=getattr(args, "verbose", False))

    def main(self, argv: Optional[Sequence[str]] = None) -> None:
        """Run the CLI and exit with the return code."""
        sys.exit(self.run(argv))


class CommandGroup:
    """A group of related commands (e.g., "outlook" containing "add", "list", etc.)."""

    def __init__(
        self,
        app: CLIApp,
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
) -> CLIApp:
    """Create a simple CLI app quickly.

    Args:
        name: Program name.
        description: Program description.
        **kwargs: Additional arguments to CLIApp.

    Returns:
        CLIApp instance.
    """
    return CLIApp(name, description, **kwargs)
