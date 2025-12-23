"""Standardized CLI error codes and error handling.

Provides consistent error codes across all assistant CLIs.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, NoReturn


class ExitCode(IntEnum):
    """Standard CLI exit codes."""
    SUCCESS = 0
    ERROR = 1
    USAGE = 2
    CONFIG_ERROR = 3
    AUTH_ERROR = 4
    NETWORK_ERROR = 5
    NOT_FOUND = 6
    PERMISSION_DENIED = 7
    INTERRUPTED = 130  # Standard for Ctrl+C


@dataclass
class CLIError(Exception):
    """CLI error with exit code and message."""
    message: str
    code: ExitCode = ExitCode.ERROR
    hint: Optional[str] = None

    def __str__(self) -> str:
        return self.message


class ConfigError(CLIError):
    """Configuration-related error."""
    def __init__(self, message: str, hint: Optional[str] = None):
        super().__init__(message, ExitCode.CONFIG_ERROR, hint)


class AuthError(CLIError):
    """Authentication-related error."""
    def __init__(self, message: str, hint: Optional[str] = None):
        super().__init__(message, ExitCode.AUTH_ERROR, hint)


class NetworkError(CLIError):
    """Network-related error."""
    def __init__(self, message: str, hint: Optional[str] = None):
        super().__init__(message, ExitCode.NETWORK_ERROR, hint)


class NotFoundError(CLIError):
    """Resource not found error."""
    def __init__(self, message: str, hint: Optional[str] = None):
        super().__init__(message, ExitCode.NOT_FOUND, hint)


class UsageError(CLIError):
    """Usage/argument error."""
    def __init__(self, message: str, hint: Optional[str] = None):
        super().__init__(message, ExitCode.USAGE, hint)


def handle_error(error: Exception, verbose: bool = False) -> int:
    """Handle an exception and return appropriate exit code.

    Args:
        error: The exception to handle.
        verbose: If True, print stack trace for unexpected errors.

    Returns:
        Exit code to use.
    """
    if isinstance(error, CLIError):
        print(f"Error: {error.message}", file=sys.stderr)
        if error.hint:
            print(f"Hint: {error.hint}", file=sys.stderr)
        return error.code

    if isinstance(error, KeyboardInterrupt):
        print("\nInterrupted.", file=sys.stderr)
        return ExitCode.INTERRUPTED

    # Unexpected error
    print(f"Error: {error}", file=sys.stderr)
    if verbose:
        import traceback
        traceback.print_exc()
    return ExitCode.ERROR


def die(message: str, code: ExitCode = ExitCode.ERROR, hint: Optional[str] = None) -> NoReturn:
    """Print error message and exit.

    Args:
        message: Error message to print.
        code: Exit code to use.
        hint: Optional hint for fixing the error.
    """
    print(f"Error: {message}", file=sys.stderr)
    if hint:
        print(f"Hint: {hint}", file=sys.stderr)
    sys.exit(code)
