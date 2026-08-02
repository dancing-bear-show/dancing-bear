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
import re
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
from .cli_suggestions import suggest_command, suggest_flags


T = TypeVar("T")
CommandFunc = Callable[[argparse.Namespace], int]


class _HelpfulArgumentParser(argparse.ArgumentParser):
    """ArgumentParser subclass that adds 'did you mean' suggestions on error."""

    def error(self, message: str) -> None:  # type: ignore[override]
        """Override error() to append ranked suggestions before exiting.

        Usage is not printed here — super().error() prints usage itself
        before the message, so printing it twice would duplicate output.
        """
        for line in self._suggestions_for_error(message):
            self.error_output(f"hint: {line}")
        super().error(message)

    def _suggestions_for_error(self, message: str) -> list[str]:
        """Return ranked hint lines for a known argparse error message shape."""
        if "invalid choice:" in message and "choose from" in message:
            return self._suggest_for_invalid_choice(message)
        if "unrecognized arguments" in message:
            return self._suggest_for_unrecognized_flags(message)
        return []

    def _subparsers_choices(self) -> list[str]:
        """Return the subcommand names registered via add_subparsers(), if any."""
        for act in self._actions:
            if isinstance(act, argparse._SubParsersAction):
                return list(act.choices.keys())
        return []

    def _suggest_for_invalid_choice(self, message: str) -> list[str]:
        """Suggest subcommands for an 'invalid choice' subcommand error.

        Restricted to the parser's subparsers action so an invalid subcommand
        is never compared against unrelated flag `choices=` values (e.g.
        --agentic-format's text/yaml/json).
        """
        m = re.search(r"invalid choice:\s*'?([^',)]+)'?", message)
        if not m:
            return []
        query = m.group(1).strip()
        choices = self._subparsers_choices()
        suggestions = suggest_command(query, choices)
        if not suggestions:
            return []
        return [f"Did you mean: {', '.join(suggestions)}?"]

    def _suggest_for_unrecognized_flags(self, message: str) -> list[str]:
        """Suggest known flags for each unrecognized flag-like token."""
        tokens = re.findall(r"(--?[\w-]+)", message)
        all_flags: list[str] = []
        for act in self._actions:
            all_flags.extend(act.option_strings)
        lines: list[str] = []
        for token in tokens:
            flag_suggestions = suggest_flags(token, all_flags)
            if flag_suggestions:
                lines.append(f"Unknown flag '{token}'. Did you mean: {', '.join(flag_suggestions)}?")
        return lines

    def error_output(self, msg: str) -> None:
        """Print a hint line to stderr."""
        print(f"{self.prog}: {msg}", file=sys.stderr)


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
            result = 0
        else:
            try:
                result = int(cmd_func(args))
            except CLIError as e:
                result = handle_error(e, verbose=getattr(args, "verbose", False))
            except KeyboardInterrupt:
                print("\nInterrupted.", file=sys.stderr)
                result = ExitCode.INTERRUPTED
            except Exception as e:
                result = handle_error(e, verbose=getattr(args, "verbose", False))
        return result

    def run(
        self,
        argv: Optional[Sequence[str]] = None,
        *,
        on_no_command: Optional[Callable[[], int]] = None,
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
