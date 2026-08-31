"""Argparse command group and all subcommands for the telemetry CLI.

Ported from Click to CLIApp. All business logic is unchanged; only the CLI
wiring is replaced.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from rich.console import Console
from rich.table import Table

from core.assistant import BaseAssistant
from core.cli_errors import CLIError
from core.cli_framework import CLIApp
from core.cli_output import emit_one
from core.date_utils import now_utc
from telemetry.cli_formatters import (
    _AGENT_SORT_KEYS,
    _breakdown_by_agent,
    _breakdown_by_day,
    _build_agents_table,
    _build_breakdown_table,
    _build_sessions_table,
    _parse_since_cli,
    _print_agents_csv,
    _print_agents_json,
    _print_cost_csv,
    _sessions_json_payload,
    _truncate_id,
)
from telemetry.meta import META

console = Console()

app = CLIApp(
    "telemetry",
    "telemetry — Claude Code session analysis TUI",
    add_common_args=False,
)

assistant = BaseAssistant(META.app_id, META.agentic_fallback)


@lru_cache(maxsize=1)
def _lazy_agentic():
    from telemetry import agentic as _agentic
    return _agentic.emit_agentic_context


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


@app.command("live", help="Live TUI dashboard that refreshes continuously.")
@app.argument("--session", default=None, help="Session ID to monitor (auto-detects if omitted).")
@app.argument("--refresh", type=float, default=2.0, help="Refresh interval in seconds.")
@app.argument("--rules", dest="rules_path", default=None, help="Path to custom rules YAML.")
def cmd_live(args: argparse.Namespace) -> int:
    try:
        from telemetry.tui import run_live
    except ImportError as exc:
        raise CLIError(
            "textual is required for `telemetry live`: pip install 'personal-assistants[tui]'"
        ) from exc
    run_live(session_id=args.session, refresh=args.refresh, rules_path=args.rules_path)
    return 0


@app.command("stats", help="Live stats panel — compact real-time session metrics.")
@app.argument("--session", default=None, help="Session ID (auto-detects if omitted).")
@app.argument("--refresh", type=float, default=2.0, help="Refresh interval in seconds.")
@app.argument("--compact", action="store_true", help="Single-line compact format.")
@app.argument("--rules", dest="rules_path", default=None, help="Path to custom rules YAML.")
def cmd_stats(args: argparse.Namespace) -> int:
    from telemetry.tui import run_stats
    run_stats(session_id=args.session, refresh=args.refresh, compact=args.compact, rules_path=args.rules_path)
    return 0


@app.command("summary", help="Print a one-shot session summary.")
@app.argument("--session", default=None, help="Session ID to summarise (auto-detects if omitted).")
@app.argument("--rules", dest="rules_path", default=None, help="Path to custom rules YAML.")
def cmd_summary(args: argparse.Namespace) -> int:
    from telemetry.tui import print_summary
    print_summary(session_id=args.session, rules_path=args.rules_path)
    return 0


@app.command("history", help="List recent sessions in a Rich table.")
@app.argument("-d", "--days", type=int, default=7, help="Number of past days to include.")
def cmd_history(args: argparse.Namespace) -> int:  # NOSONAR S3516
    from telemetry.providers.transcript import TranscriptProvider

    since = now_utc() - timedelta(days=args.days)
    transcript = TranscriptProvider()
    sessions = transcript.get_sessions(since=since)

    if not sessions:
        console.print(f"[dim]No sessions found in the last {args.days} day(s).[/]")
        return 0

    table = Table(show_header=True, header_style="bold", title=f"Sessions (last {args.days}d)")
    table.add_column("Session ID", style="cyan", no_wrap=True)
    table.add_column("Project", no_wrap=True)
    table.add_column("Model")
    table.add_column("Start", justify="right")
    table.add_column("Events", justify="right")
    table.add_column("Cost", justify="right")

    for s in sessions:
        table.add_row(
            _truncate_id(s.session_id),
            (s.project_path or "—")[-30:],
            (s.model or "—").split("/")[-1],
            s.start_time.strftime("%m-%d %H:%M"),
            str(s.total_events),
            f"${s.total_cost:.3f}",
        )

    console.print(table)
    return 0


@app.command("sessions", help="List sessions with cost and token breakdown, parsed from JSONL transcripts.")
@app.argument("--since", default="7d", help="Time window (e.g. 2d, 7d, 24h).")
@app.argument("--format", dest="fmt", default="table", choices=["table", "json"], help="Output format.")
@app.argument("--limit", type=int, default=0, help="Show only top N sessions by cost (0 = all).")
@app.argument("--errors-only", action="store_true", help="Show only sessions that spawned at least one subagent.")
@app.argument("--projects-dir", default=None, help="Override ~/.claude/projects directory.")
def cmd_sessions(args: argparse.Namespace) -> int:  # NOSONAR S3516
    from telemetry.providers.transcript import TranscriptProvider

    since_dt = _parse_since_cli(args.since)
    provider = TranscriptProvider(
        projects_dir=Path(args.projects_dir).expanduser() if args.projects_dir else None,
    )
    all_sessions = provider.get_sessions(since=since_dt)
    all_sessions = [s for s in all_sessions if s.total_events > 0 or s.total_cost > 0]
    if args.errors_only:
        all_sessions = [s for s in all_sessions if s.agents]
    all_sessions.sort(key=lambda s: s.total_cost, reverse=True)
    if args.limit > 0:
        all_sessions = all_sessions[:args.limit]

    if args.fmt == "json":
        emit_one(_sessions_json_payload(all_sessions), fmt="json")
        return 0

    if not all_sessions:
        console.print("[dim]No sessions found.[/]")
        return 0

    console.print(_build_sessions_table(all_sessions, args.since))
    return 0


@dataclass(frozen=True)
class AgentQueryRequest:
    """Parameters for the agents CLI query."""

    since: str
    limit: int
    model: str | None
    sort: str
    projects_dir: str | None


def _run_agents(request: AgentQueryRequest, fmt: str) -> None:
    """Execute agents query and emit results in the requested format."""
    from telemetry.providers.transcript import TranscriptProvider

    since_dt = _parse_since_cli(request.since)
    provider = TranscriptProvider(
        projects_dir=Path(request.projects_dir).expanduser() if request.projects_dir else None,
    )
    all_rows = provider.aggregate_agents(since=since_dt)

    if request.model:
        all_rows = [r for r in all_rows if any(request.model.lower() in m.lower() for m in r.models)]

    all_rows.sort(key=_AGENT_SORT_KEYS[request.sort], reverse=True)
    rows = all_rows[:request.limit] if request.limit > 0 else all_rows

    if fmt == "json":
        _print_agents_json(all_rows, rows, request.since)
        return

    if fmt == "csv":
        _print_agents_csv(rows)
        return

    if not rows:
        console.print("[dim]No agent data found.[/]")
        return

    console.print(_build_agents_table(all_rows, rows, request.since))


@app.command("agents", help="Per-agent token and cost breakdown.")
@app.argument("--since", default="7d", help="Time window (e.g. 2d, 7d, 24h).")
@app.argument("--format", dest="fmt", default="table", choices=["table", "json", "csv"], help="Output format.")
@app.argument("--limit", type=int, default=0, help="Show only top N agents (0 = all).")
@app.argument("--model", default=None, help="Filter to agents that used this model (substring match).")
@app.argument(
    "--sort", default="cost", choices=list(_AGENT_SORT_KEYS), help="Sort column.",
)
@app.argument("--projects-dir", default=None, help="Override ~/.claude/projects directory.")
def cmd_agents(args: argparse.Namespace) -> int:
    _run_agents(
        AgentQueryRequest(
            since=args.since,
            limit=args.limit,
            model=args.model,
            sort=args.sort,
            projects_dir=args.projects_dir,
        ),
        args.fmt,
    )
    return 0


def _rules_init(config_path: Path) -> None:
    import yaml

    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        console.print(f"[yellow]Already exists:[/] {config_path}")
        return
    starter = {
        "avoidable": {
            "bash-as-grep": {"enabled": True},
            "bash-as-read": {"enabled": True},
            "bash-as-glob": {"enabled": True},
            "bash-as-write": {"enabled": True},
            "redundant-read": {"enabled": True, "window_seconds": 60},
            "rapid-re-edit": {"enabled": True, "window_seconds": 30},
        },
        "review": {
            "abandoned-search": {"enabled": True, "consecutive_reads": 3},
            "fruitless-agent": {"enabled": True, "window_seconds": 300},
        },
        "custom_rules": [],
    }
    config_path.write_text(yaml.safe_dump(starter, default_flow_style=False))
    console.print(f"[green]Created:[/] {config_path}")


def _rules_validate() -> None:
    from telemetry.rules import load_rules, validate_rules

    loaded = load_rules()
    errors = validate_rules(loaded)
    if errors:
        console.print("[red]Validation errors:[/]")
        for err in errors:
            console.print(f"  [red]•[/] {err}")
        raise SystemExit(1)
    console.print("[green]No errors — rules are valid.[/]")


def _rules_explain(name: str) -> None:
    from telemetry.rules import load_rules

    loaded = load_rules()
    for category in ("avoidable", "review"):
        rule_cfg = loaded.get(category, {}).get(name)
        if rule_cfg is None:
            continue
        console.print(f"[bold cyan]{name}[/]  ([dim]{category}[/])")
        console.print(f"  Config: {rule_cfg}")
        fix_hints = loaded.get("fix_hints", {}).get(name, {})
        if fix_hints:
            console.print("  Fix hints:")
            for level, hint in fix_hints.items():
                console.print(f"    [dim]{level}:[/] {hint}")
        return
    console.print(f"[yellow]Rule not found:[/] {name}")
    console.print("[dim]Use 'telemetry rules' to list all rules.[/]")


def _add_rule_row(table: Table, category: str, rule_name: str, cfg: dict) -> None:
    """Add one rule's row to the rules table."""
    enabled = cfg.get("enabled", True)
    enabled_str = "[green]yes[/]" if enabled else "[dim]no[/]"
    config_items = {
        k: v for k, v in cfg.items()
        if k != "enabled" and not isinstance(v, list)
    }
    config_str = "  ".join(f"{k}={v}" for k, v in config_items.items())
    table.add_row(rule_name, category, enabled_str, config_str or "—")


def _add_category_rows(table: Table, category: str, cat_rules: dict) -> None:
    """Add all rule rows for one category (avoidable/review) to the table."""
    for rule_name, cfg in cat_rules.items():
        if isinstance(cfg, dict):
            _add_rule_row(table, category, rule_name, cfg)


def _rules_list() -> None:
    from telemetry.rules import load_rules

    loaded = load_rules()
    table = Table(show_header=True, header_style="bold", title="Telemetry Rules")
    table.add_column("Name", style="cyan")
    table.add_column("Category")
    table.add_column("Enabled", justify="center")
    table.add_column("Config")

    for category in ("avoidable", "review"):
        _add_category_rows(table, category, loaded.get(category, {}))

    custom = loaded.get("custom_rules", [])
    for i, rule in enumerate(custom):
        rule_name = rule.get("reason", f"custom-{i}")
        table.add_row(rule_name, "custom", "[green]yes[/]", str(rule.get("tool", "any")))

    console.print(table)


@app.command("rules", help="Manage telemetry classification rules.")
@app.argument("--init", dest="do_init", action="store_true", help="Scaffold ~/.telemetry-transcripts/rules.yaml.")
@app.argument("--validate", dest="do_validate", action="store_true", help="Validate rules and report errors.")
@app.argument("--explain", default=None, metavar="NAME", help="Show config + fix hint for a rule.")
def cmd_rules(args: argparse.Namespace) -> int:
    config_path = Path.home() / ".telemetry-transcripts" / "rules.yaml"

    if args.do_init:
        _rules_init(config_path)
    elif args.do_validate:
        _rules_validate()
    elif args.explain:
        _rules_explain(args.explain)
    else:
        _rules_list()
    return 0


@app.command("cost-breakdown", help="Per-agent or per-day cost breakdown.", aliases=["cost"])
@app.argument("--since", default="7d", help="Time window (e.g. 2d, 7d, 24h).")
@app.argument("--format", dest="fmt", default="table", choices=["table", "json", "csv"], help="Output format.")
@app.argument("--group-by", dest="group_by", default="agent", choices=["agent", "day"], help="Group by agent or day.")
@app.argument("--limit", type=int, default=0, help="Top N entries (0 = all).")
@app.argument("--projects-dir", default=None, help="Override ~/.claude/projects directory.")
def cmd_cost_breakdown(args: argparse.Namespace) -> int:  # NOSONAR S3516
    from telemetry.providers.transcript import TranscriptProvider

    since_dt = _parse_since_cli(args.since)
    provider = TranscriptProvider(
        projects_dir=Path(args.projects_dir).expanduser() if args.projects_dir else None,
    )

    if args.group_by == "agent":
        rows = _breakdown_by_agent(provider.aggregate_agents(since=since_dt))
    else:
        rows = _breakdown_by_day(provider.get_sessions(since=since_dt))

    if args.limit > 0:
        rows = rows[:args.limit]

    if args.fmt == "json":
        emit_one({"group_by": args.group_by, "since": args.since, "rows": rows}, fmt="json")
        return 0

    if args.fmt == "csv":
        _print_cost_csv(rows, args.group_by)
        return 0

    if not rows:
        console.print("[dim]No cost data found.[/]")
        return 0

    console.print(_build_breakdown_table(rows, args.group_by, args.since))
    return 0


@app.command("parse-transcripts", help="Pre-parse JSONL transcripts into a structured JSON index.")
@app.argument("--since", default="all", help="Time window to process (e.g. 7d, 30d, all).")
@app.argument("--projects-dir", default=None, help="Override ~/.claude/projects.")
@app.argument("--index-dir", default=None, help="Override default index dir (~/.config/dancing-bear/work/prompt-index/).")
@app.argument("--force", action="store_true", default=False, help="Reprocess all files, ignoring high-water marks.")
@app.argument("--format", dest="fmt", default="table", choices=["json", "table"], help="Output format.")
@app.argument("--limit", type=int, default=0, help="Process at most N sessions (0 = all).")
def cmd_parse_transcripts(args: argparse.Namespace) -> int:
    from telemetry.parse_transcripts import (
        TranscriptParseRequest,
        _run_parse_transcripts,
    )
    from telemetry.parse_transcripts_io import DEFAULT_INDEX_DIR

    request = TranscriptParseRequest(
        since=args.since,
        projects_dir=Path(args.projects_dir).expanduser() if args.projects_dir else None,
        index_dir=Path(args.index_dir).expanduser() if args.index_dir else DEFAULT_INDEX_DIR,
        force=args.force,
        limit=args.limit,
    )
    _run_parse_transcripts(request, args.fmt)
    return 0


# otel stub — the actual dispatch happens in main() via early intercept
@app.command(
    "otel",
    help="Query and manage local OTEL telemetry data (~/.config/otel/). Run 'telemetry otel <subcommand> --help' for subcommand options.",
)
def cmd_otel_stub(args: argparse.Namespace) -> int:  # pragma: no cover
    # Never reached — otel is intercepted in main() before parse_args
    from telemetry.otel.cli import main as otel_main
    return otel_main([])


# ---------------------------------------------------------------------------
# on_no_command helper
# ---------------------------------------------------------------------------

_parser_ref: list[argparse.ArgumentParser] = []


def _post_build(parser: argparse.ArgumentParser) -> None:
    _parser_ref.clear()
    _parser_ref.append(parser)


def _on_no_command() -> int:
    """Print help and exit 0 on a bare invocation (rule A7).

    Click exited 2 here. That was incidental to the parser, not a chosen
    interface, so the argparse port aligns it with run_with_assistant's default
    and the other 15 apps. worker and workflow keep their non-zero codes: those
    are documented, print a one-line usage to stderr, and are load-bearing.
    """
    if _parser_ref:
        _parser_ref[0].print_help()
    return 0


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the telemetry CLI."""
    raw_argv = list(argv) if argv is not None else sys.argv[1:]

    # Special-case otel: intercept before CLIApp parses, so all remaining args
    # (including --help, --format, etc.) are forwarded verbatim to otel's own
    # parser.
    #
    # Strip only a LEADING bare "--", and only to reveal `otel` in position 0.
    # normalize_argv is the wrong tool here: it removes the first bare "--"
    # ANYWHERE in argv, which would swallow a later end-of-options guard that
    # belongs to otel. Measured:
    #   ["otel", "query", "--", "--raw"]
    #     normalize_argv -> forwards ["query", "--raw"]      (guard lost)
    #     leading-only   -> forwards ["query", "--", "--raw"] (correct)
    probe = raw_argv[1:] if raw_argv and raw_argv[0] == "--" else raw_argv
    if probe and probe[0] == "otel":
        from telemetry.otel.cli import main as otel_main
        return otel_main(probe[1:])

    # Pass RAW argv, not `probe`. run_with_assistant normalizes internally, and
    # normalize_argv is not idempotent by design: it strips the first bare "--"
    # on every call, so normalizing twice also eats a LATER "--" that the POSIX
    # end-of-options contract requires be preserved. Measured:
    #   ["sessions", "--", "--", "x"] -> once ["sessions", "--", "x"]
    #                                 -> twice ["sessions", "x"]   (wrong)
    return app.run_with_assistant(
        assistant,
        emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact),
        argv=raw_argv,
        post_build_hook=_post_build,
        on_no_command=_on_no_command,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
