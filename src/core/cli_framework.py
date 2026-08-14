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
from typing import Any, Callable, Sequence, TypeVar

from .cli_errors import CLIError, ExitCode, handle_error
from .cli_framework_group import CommandGroup
from .cli_framework_parser import _HelpfulArgumentParser
from .cli_framework_types import Argument, CommandDef, CommandFunc
from .cli_help_text import (
    HELP_DRY_RUN,
    HELP_OUTPUT,
    HELP_PROFILE,
    HELP_QUIET,
    HELP_VERBOSE,
)
from .cli_output import OutputConfig, OutputFormat, OutputWriter


T = TypeVar("T")


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
        version: str | None = None,
        epilog: str | None = None,
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

        self._commands: dict[str, CommandDef] = {}
        self._groups: dict[str, "CommandGroup"] = {}
        self._parser: argparse.ArgumentParser | None = None
        self._pending_arguments: list[Argument] = []

    @staticmethod
    def _split_command_name(name: str, parent: str | None) -> tuple[str | None, str]:
        """Split a "parent.name" or "parent name" command name into (parent, name).

        If parent is already given explicitly, name is returned unsplit.
        Returns (cmd_parent, cmd_name).
        """
        if parent:
            return parent, name
        if "." in name:
            parts = name.split(".", 1)
            return parts[0], parts[1]
        if " " in name:
            parts = name.split(" ", 1)
            return parts[0], parts[1]
        return None, name

    def command(
        self,
        name: str,
        *,
        help: str = "",
        description: str = "",
        aliases: list[str] | None = None,
        parent: str | None = None,
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

            cmd_parent, cmd_name = self._split_command_name(name, parent)

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
        parser = _HelpfulArgumentParser(
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
            help=HELP_PROFILE,
        )
        parser.add_argument(
            "--verbose", "-v",
            action="store_true",
            help=HELP_VERBOSE,
        )
        parser.add_argument(
            "--quiet", "-q",
            action="store_true",
            help=HELP_QUIET,
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=HELP_DRY_RUN,
        )
        parser.add_argument(
            "--output", "-o",
            choices=["text", "json", "yaml", "table"],
            default="text",
            help=HELP_OUTPUT,
        )

    def _add_command_arguments(
        self,
        parser: argparse.ArgumentParser,
        cmd_def: CommandDef,
    ) -> None:
        """Add command-specific arguments to the parser."""
        for arg in cmd_def.arguments:
            parser.add_argument(*arg.name_or_flags, **arg.kwargs)

    @staticmethod
    def normalize_argv(argv: Sequence[str]) -> list[str]:
        """Strip the first bare '--' used as the optional subcommand/flag separator.

        CLAUDE.md documents '--' as optional (not required) for CLIApp-based
        CLIs: ``foo bar -- --flag value`` and ``foo bar --flag value`` should
        behave identically. This strips only the *first* bare '--' token so
        that pattern works without a required separator.

        A '--' is preserved everywhere else, since POSIX '--' also means "end
        of options, treat the rest as positional" — e.g. a later '--' guarding
        a positional value that itself starts with '-' (``foo bar --config --
        --literal-value``) must not be stripped, or that value would be
        misparsed as an unrecognized flag. A trailing '--' (nothing follows)
        carries no such information here and is also left untouched.
        """
        argv_list = list(argv)
        try:
            idx = argv_list.index("--")  # nosec B105 - not a password; '--' is the POSIX arg separator
        except ValueError:
            return argv_list
        if idx == len(argv_list) - 1:
            return argv_list
        return argv_list[:idx] + argv_list[idx + 1:]

    @staticmethod
    def _run_cmd_func_with_error_handling(
        cmd_func: CommandFunc,
        args: argparse.Namespace,
        *,
        coerce_int: bool,
    ) -> int:
        """Invoke cmd_func(args), converting known exceptions to exit codes.

        coerce_int mirrors run_with_assistant's `int(cmd_func(args))` wrapping
        (kept optional so run()'s return value is unchanged for callers that
        already return a plain exit code without it).
        """
        try:
            result = cmd_func(args)
            return int(result) if coerce_int else result
        except CLIError as e:
            return handle_error(e, verbose=getattr(args, "verbose", False))
        except KeyboardInterrupt:
            print("\nInterrupted.", file=sys.stderr)
            return ExitCode.INTERRUPTED
        except Exception as e:
            return handle_error(e, verbose=getattr(args, "verbose", False))

    def run_with_assistant(
        self,
        assistant: Any,
        emit_func: Callable[[str, bool], int],
        argv: Sequence[str] | None = None,
        *,
        pre_run_hook: Callable[[], None] | None = None,
        post_build_hook: Callable[[argparse.ArgumentParser], None] | None = None,
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

        _argv = self.normalize_argv(argv if argv is not None else sys.argv[1:])
        args = parser.parse_args(_argv)

        # Handle agentic output if requested
        agentic_result = assistant.maybe_emit_agentic(args, emit_func=emit_func, parser=parser)
        if agentic_result is not None:
            return int(agentic_result)

        # Resolve and run the command
        cmd_func = getattr(args, "_cmd_func", None)
        if cmd_func is None:
            parser.print_help()
            return 0
        return self._run_cmd_func_with_error_handling(cmd_func, args, coerce_int=True)

    def run(
        self,
        argv: Sequence[str] | None = None,
        *,
        on_no_command: Callable[[], int] | None = None,
    ) -> int:
        """Run the CLI application.

        Args:
            argv: Command-line arguments (defaults to sys.argv[1:]).
            on_no_command: Optional callback invoked instead of the default
                "print full help, return ExitCode.USAGE" behavior when no
                subcommand is given. Lets a caller preserve a legacy
                one-line usage message/exit code without pre-parsing argv
                itself (which would otherwise normalize+parse it twice).

        Returns:
            Exit code.
        """
        parser = self._parser
        if parser is None:
            parser = self.build_parser()
        _argv = self.normalize_argv(argv if argv is not None else sys.argv[1:])
        args = parser.parse_args(_argv)

        # Set up output writer. args.output only means "output format" when
        # this app added the common --output flag itself (_add_common_arguments);
        # with add_common_args=False a CLI's own --output may hold unrelated
        # data (e.g. a file path), so OutputFormat(...) would raise on it.
        if self.add_common_args:
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
            if on_no_command is not None:
                return on_no_command()
            self._parser.print_help()
            return ExitCode.USAGE

        # Run the command with error handling
        return self._run_cmd_func_with_error_handling(cmd_func, args, coerce_int=False)

    def main(self, argv: Sequence[str] | None = None) -> None:
        """Run the CLI and exit with the return code."""
        sys.exit(self.run(argv))
