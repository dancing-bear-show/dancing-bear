"""Agentic capsule for the telemetry CLI.

Emits a compact, LLM-consumable summary of the CLI surface. Follows the same
shape as ``qlty.agentic`` and the argparse siblings: ``agentic:`` header,
``purpose:``, ``commands:``, ``notes:``.

The telemetry CLI is Click-based (see ``telemetry.cli_sessions.main``), so it
does not use the shared ``CLIApp.run_with_assistant`` scaffolding. This module
hand-authors the capsule; the ``--agentic-format json`` path emits a compact,
introspection-derived JSON schema by walking the Click group directly.
"""
from __future__ import annotations

import json
from typing import Any


APP_ID = "telemetry"
PURPOSE = "Claude Code session telemetry: cost, tokens, TUI, and OTel queries"

_COMMANDS: list[tuple[str, str]] = [
    ("live TUI dashboard", "./bin/telemetry live"),
    ("compact live stats", "./bin/telemetry stats --compact"),
    ("one-shot session summary", "./bin/telemetry summary"),
    ("recent sessions table", "./bin/telemetry history --days 7"),
    ("session cost/token table", "./bin/telemetry sessions --since 7d"),
    ("per-agent breakdown", "./bin/telemetry agents --since 7d"),
    ("cost by agent or day", "./bin/telemetry cost --since 7d --group-by agent"),
    ("classification rules", "./bin/telemetry rules --list"),
    ("pre-parse transcripts", "./bin/telemetry parse-transcripts --since 7d"),
    ("query local OTel data", "./bin/telemetry otel --help"),
]

_NOTES: list[str] = [
    "`telemetry live` needs the [tui] extra (textual); stats/summary render via Rich and do not",
    "`cost` is an alias for `cost-breakdown`",
    "JSON output on sessions/agents/cost via --format json (parseable, stdout only)",
    "`otel` forwards remaining argv to telemetry.otel.cli; run `telemetry otel --help` for its subcommands",
]


def build_agentic_capsule() -> str:
    """Return the text/yaml capsule body."""
    lines: list[str] = []
    lines.append(f"agentic: {APP_ID}")
    lines.append(f"purpose: {PURPOSE}")
    lines.append("commands:")
    for label, cmd in _COMMANDS:
        lines.append(f"  - {label}: {cmd}")
    lines.append("notes:")
    for note in _NOTES:
        lines.append(f"  - {note}")
    return "\n".join(lines)


def build_agentic_capsule_compact() -> str:
    """Return a smaller capsule: drop the notes list."""
    lines: list[str] = []
    lines.append(f"agentic: {APP_ID}")
    lines.append(f"purpose: {PURPOSE}")
    lines.append("commands:")
    for label, cmd in _COMMANDS:
        lines.append(f"  - {label}: {cmd}")
    return "\n".join(lines)


def build_agentic_json(compact: bool = False) -> dict[str, Any]:
    """Return a structured JSON schema derived from the Click group.

    Introspection lives here (not in the group definition) so the capsule can
    be regenerated deterministically without invoking any subcommand.
    """
    # Local import: keeps the Click group import graph clean and avoids
    # circular imports when telemetry.cli_sessions is being decorated.
    from telemetry.cli_sessions import main as click_group

    schema: dict[str, Any] = {
        "app_id": APP_ID,
        "purpose": PURPOSE,
        "prog": "telemetry",
        "commands": _describe_click_group(click_group, compact=compact),
    }
    if not compact:
        schema["notes"] = list(_NOTES)
    return schema


def _describe_click_group(group: Any, compact: bool) -> list[dict[str, Any]]:
    """Walk a click.Group and describe its subcommands."""
    import click

    commands: list[dict[str, Any]] = []
    # group.commands is a dict[str, click.Command]; sort for stable output.
    for name in sorted(group.commands.keys()):
        cmd = group.commands[name]
        entry: dict[str, Any] = {
            "name": name,
            "help": (cmd.short_help or cmd.help or "").strip(),
        }
        if not compact:
            entry["options"] = _describe_click_options(cmd)
            if isinstance(cmd, click.Group):
                entry["subcommands"] = _describe_click_group(cmd, compact=compact)
        commands.append(entry)
    return commands


def _describe_click_options(cmd: Any) -> list[dict[str, Any]]:
    """Describe a click Command's user-facing options."""
    import click

    out: list[dict[str, Any]] = []
    for param in cmd.params:
        if isinstance(param, click.Option):
            out.append(
                {
                    "flags": list(param.opts),
                    "help": (param.help or "").strip(),
                    "default": _jsonable(param.default),
                    "is_flag": bool(param.is_flag),
                    "choices": _choices(param),
                }
            )
        elif isinstance(param, click.Argument):
            out.append(
                {
                    "argument": param.name,
                    "nargs": param.nargs,
                }
            )
    return out


def _choices(param: Any) -> list[str] | None:
    import click

    if isinstance(param.type, click.Choice):
        return list(param.type.choices)
    return None


def _jsonable(value: Any) -> Any:
    """Coerce Click defaults to JSON-safe primitives."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def emit_agentic_context(fmt: str = "text", compact: bool = False) -> int:
    """Print the agentic capsule in the requested format and return exit code."""
    if fmt == "json":
        print(json.dumps(build_agentic_json(compact=compact), indent=2, default=str))
        return 0
    # text and yaml share the same hand-authored body — YAML-valid by construction.
    if compact:
        print(build_agentic_capsule_compact())
    else:
        print(build_agentic_capsule())
    return 0
