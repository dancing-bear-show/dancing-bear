"""Click command group and all subcommands for the telemetry CLI.

Extracted from telemetry/cli.py as part of the decompose-sweep refactor.
telemetry/cli.py is now a thin shim that re-exports everything from here
and from telemetry/cli_formatters.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from core.cli_output import emit_one
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

console = Console()


@click.group()
def main() -> None:
    """telemetry — Claude Code session analysis TUI."""


@main.command()
@click.option("--session", default=None, help="Session ID to monitor (auto-detects if omitted).")
@click.option("--refresh", default=2.0, show_default=True, help="Refresh interval in seconds.")
@click.option("--rules", "rules_path", default=None, help="Path to custom rules YAML.")
def live(session: str | None, refresh: float, rules_path: str | None) -> None:
    """Live TUI dashboard that refreshes continuously."""
    try:  # pragma: no cover
        from telemetry.tui import run_live  # pragma: no cover
    except ImportError:  # pragma: no cover
        raise click.ClickException("textual is required for TUI commands: pip install textual")  # pragma: no cover
    run_live(session_id=session, refresh=refresh, rules_path=rules_path)  # pragma: no cover


@main.command()
@click.option("--session", default=None, help="Session ID (auto-detects if omitted).")
@click.option("--refresh", default=2.0, show_default=True, help="Refresh interval in seconds.")
@click.option("--compact", is_flag=True, help="Single-line compact format.")
@click.option("--rules", "rules_path", default=None, help="Path to custom rules YAML.")
def stats(session: str | None, refresh: float, compact: bool, rules_path: str | None) -> None:
    """Live stats panel — compact real-time session metrics."""
    try:  # pragma: no cover
        from telemetry.tui import run_stats  # pragma: no cover
    except ImportError:  # pragma: no cover
        raise click.ClickException("textual is required for TUI commands: pip install textual")  # pragma: no cover
    run_stats(session_id=session, refresh=refresh, compact=compact, rules_path=rules_path)  # pragma: no cover


@main.command()
@click.option("--session", default=None, help="Session ID to summarise (auto-detects if omitted).")
@click.option("--rules", "rules_path", default=None, help="Path to custom rules YAML.")
def summary(session: str | None, rules_path: str | None) -> None:
    """Print a one-shot session summary."""
    from telemetry.tui import print_summary  # pragma: no cover
    print_summary(session_id=session, rules_path=rules_path)  # pragma: no cover


@main.command()
@click.option("-d", "--days", default=7, show_default=True, help="Number of past days to include.")
def history(days: int) -> None:
    """List recent sessions in a Rich table."""
    from telemetry.providers.transcript import TranscriptProvider

    since = datetime.now(tz=timezone.utc) - timedelta(days=days)
    transcript = TranscriptProvider()
    sessions = transcript.get_sessions(since=since)

    if not sessions:
        console.print(f"[dim]No sessions found in the last {days} day(s).[/]")
        return

    table = Table(show_header=True, header_style="bold", title=f"Sessions (last {days}d)")
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


@main.command("sessions")
@click.option("--since", default="7d", show_default=True, help="Time window (e.g. 2d, 7d, 24h).")
@click.option("--format", "fmt", default="table", type=click.Choice(["table", "json"]), show_default=True)
@click.option("--limit", default=0, help="Show only top N sessions by cost (0 = all).")
@click.option("--errors-only", is_flag=True, help="Show only sessions that spawned at least one subagent.")
@click.option("--projects-dir", default=None, help="Override ~/.claude/projects directory.")
def sessions(since: str, fmt: str, limit: int, errors_only: bool, projects_dir: str | None) -> None:
    """List sessions with cost and token breakdown, parsed from JSONL transcripts."""
    from telemetry.providers.transcript import TranscriptProvider

    since_dt = _parse_since_cli(since)

    provider = TranscriptProvider(projects_dir=Path(projects_dir).expanduser() if projects_dir else None)
    all_sessions = provider.get_sessions(since=since_dt)
    all_sessions = [s for s in all_sessions if s.total_events > 0 or s.total_cost > 0]
    if errors_only:
        all_sessions = [s for s in all_sessions if s.agents]
    all_sessions.sort(key=lambda s: s.total_cost, reverse=True)
    if limit > 0:
        all_sessions = all_sessions[:limit]

    if fmt == "json":
        emit_one(_sessions_json_payload(all_sessions), fmt="json")
        return

    if not all_sessions:
        console.print("[dim]No sessions found.[/]")
        return

    console.print(_build_sessions_table(all_sessions, since))


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


@main.command("agents")
@click.option("--since", default="7d", show_default=True, help="Time window (e.g. 2d, 7d, 24h).")
@click.option(
    "--format", "fmt", default="table",
    type=click.Choice(["table", "json", "csv"]), show_default=True,
)
@click.option("--limit", default=0, show_default=True, help="Show only top N agents (0 = all).")
@click.option("--model", default=None, help="Filter to agents that used this model (substring match).")
@click.option(
    "--sort", default="cost", show_default=True,
    type=click.Choice(list(_AGENT_SORT_KEYS)), help="Sort column.",
)
@click.option("--projects-dir", default=None, help="Override ~/.claude/projects directory.")
def agents(since: str, fmt: str, limit: int, model: str | None, sort: str, projects_dir: str | None) -> None:
    """Per-agent token and cost breakdown."""
    _run_agents(AgentQueryRequest(since=since, limit=limit, model=model, sort=sort, projects_dir=projects_dir), fmt)


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


def _rules_list() -> None:
    from telemetry.rules import load_rules

    loaded = load_rules()
    table = Table(show_header=True, header_style="bold", title="Telemetry Rules")
    table.add_column("Name", style="cyan")
    table.add_column("Category")
    table.add_column("Enabled", justify="center")
    table.add_column("Config")

    for category in ("avoidable", "review"):
        cat_rules = loaded.get(category, {})
        for rule_name, cfg in cat_rules.items():
            if not isinstance(cfg, dict):
                continue
            enabled = cfg.get("enabled", True)
            enabled_str = "[green]yes[/]" if enabled else "[dim]no[/]"
            config_items = {
                k: v for k, v in cfg.items()
                if k != "enabled" and not isinstance(v, list)
            }
            config_str = "  ".join(f"{k}={v}" for k, v in config_items.items())
            table.add_row(rule_name, category, enabled_str, config_str or "—")

    custom = loaded.get("custom_rules", [])
    for i, rule in enumerate(custom):
        rule_name = rule.get("reason", f"custom-{i}")
        table.add_row(rule_name, "custom", "[green]yes[/]", str(rule.get("tool", "any")))

    console.print(table)


@main.command()
@click.option("--init", "do_init", is_flag=True, help="Scaffold ~/.telemetry-transcripts/rules.yaml.")
@click.option("--validate", "do_validate", is_flag=True, help="Validate rules and report errors.")
@click.option("--explain", default=None, metavar="NAME", help="Show config + fix hint for a rule.")
def rules(do_init: bool, do_validate: bool, explain: str | None) -> None:
    """Manage telemetry classification rules."""
    config_path = Path.home() / ".telemetry-transcripts" / "rules.yaml"

    if do_init:
        _rules_init(config_path)
    elif do_validate:
        _rules_validate()
    elif explain:
        _rules_explain(explain)
    else:
        _rules_list()


@main.command("cost-breakdown")
@click.option("--since", default="7d", show_default=True, help="Time window (e.g. 2d, 7d, 24h).")
@click.option(
    "--format", "fmt", default="table",
    type=click.Choice(["table", "json", "csv"]), show_default=True,
)
@click.option(
    "--group-by", "group_by", default="agent",
    type=click.Choice(["agent", "day"]), show_default=True,
)
@click.option("--limit", default=0, show_default=True, help="Top N entries (0 = all).")
@click.option("--projects-dir", default=None, help="Override ~/.claude/projects directory.")
def cost_breakdown(since: str, fmt: str, group_by: str, limit: int, projects_dir: str | None) -> None:
    """Per-agent or per-day cost breakdown."""
    from telemetry.providers.transcript import TranscriptProvider

    since_dt = _parse_since_cli(since)
    provider = TranscriptProvider(projects_dir=Path(projects_dir).expanduser() if projects_dir else None)

    if group_by == "agent":
        rows = _breakdown_by_agent(provider.aggregate_agents(since=since_dt))
    else:
        rows = _breakdown_by_day(provider.get_sessions(since=since_dt))

    if limit > 0:
        rows = rows[:limit]

    if fmt == "json":
        emit_one({"group_by": group_by, "since": since, "rows": rows}, fmt="json")
        return

    if fmt == "csv":
        _print_cost_csv(rows, group_by)
        return

    if not rows:
        console.print("[dim]No cost data found.[/]")
        return

    console.print(_build_breakdown_table(rows, group_by, since))


from telemetry.parse_transcripts import parse_transcripts  # noqa: E402

main.add_command(parse_transcripts)

# Backwards-compatible alias: `telemetry cost` → `telemetry cost-breakdown`
main.add_command(cost_breakdown, name="cost")


@main.command(
    "otel",
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
        "allow_interspersed_args": False,
    },
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def otel_cmd(args: tuple[str, ...]) -> None:
    """Query and manage local OTEL telemetry data (~/.config/otel/).

    Run 'telemetry otel <subcommand> --help' for subcommand options.
    """
    from telemetry.otel.cli import main as otel_main

    raise SystemExit(otel_main(list(args)))


if __name__ == "__main__":  # pragma: no cover
    main()
