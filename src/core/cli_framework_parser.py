"""ArgumentParser subclass that adds 'did you mean' suggestions on error.

Split out of cli_framework.py to keep that module focused on CLIApp.
"""
from __future__ import annotations

import argparse
import re
import sys

from .cli_suggestions import suggest_command, suggest_flags


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
