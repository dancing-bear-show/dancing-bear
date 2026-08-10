"""Shared argument and command definitions for the CLI framework.

Split out of cli_framework.py so CLIApp and CommandGroup can share these
without a circular import.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

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
