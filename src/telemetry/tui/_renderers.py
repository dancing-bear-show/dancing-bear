"""Rich renderers — used by both Textual widgets and static print_summary."""

from collections.abc import Callable
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from telemetry.models import (
    AgentSummary,
    SessionEvent,
    SessionSummary,
    Tip,
    ToolStats,
)
from telemetry.tui._constants import (
    _CLASS_COLORS,
    _CLASS_SYMBOLS,
    _WASTE_TAGS,
)
from telemetry.tui._formatters import (
    _bar,
    _event_desc,
    _format_cost,
    _format_tokens,
)


# ---------------------------------------------------------------------------
# Header / tips text renderers
# ---------------------------------------------------------------------------

def _render_header_text(summary: SessionSummary) -> str:
    mode = "LIVE" if summary.end_time is None else "HISTORY"
    if summary.end_time:
        delta = (summary.end_time - summary.start_time).total_seconds()
    else:
        delta = (datetime.now(timezone.utc) - summary.start_time).total_seconds()
    mins, secs = divmod(int(delta), 60)
    hours, mins = divmod(mins, 60)
    dur = f"{hours:02d}:{mins:02d}:{secs:02d}"

    model_short = summary.model.split("/")[-1] if summary.model else "unknown"
    cost_str = _format_cost(summary.total_cost, summary.cost_is_estimated)
    in_tok = _format_tokens(summary.input_tokens)
    out_tok = _format_tokens(summary.output_tokens)
    eff_bar = _bar(summary.efficiency_score / 100.0, width=10)
    cache_str = (
        f"{summary.cache_hit_rate * 100:.0f}%"
        if summary.cache_hit_rate is not None else "n/a"
    )
    est = " [estimated]" if summary.cost_is_estimated else ""

    s = _CLASS_SYMBOLS
    return (
        f"[bold cyan]{mode}[/]  [bold]{model_short}[/]  {dur}{est}\n"
        f"Session: {summary.session_id[:16]}  "
        f"Path: {summary.project_path or '-'}\n"
        f"Cost: {cost_str}   In: {in_tok}  Out: {out_tok}\n"
        f"Efficiency: {eff_bar} {summary.efficiency_score:.0f}%"
        f"   Cache: {cache_str}\n"
        f"[green]{s['productive']}[/] {summary.productive_count} prod  "
        f"[dim]{s['neutral']}[/] {summary.neutral_count} neut  "
        f"[red]{s['avoidable']}[/] {summary.avoidable_count} avoid  "
        f"[yellow]{s['review']}[/] {summary.review_count} review"
    )


def _render_tips_text(tips: list[Tip]) -> str:
    if not tips:
        return "[dim]No tips — session looks clean![/]"
    lines: list[str] = []
    for tip in tips:
        icon = "[red]✗[/]" if tip.severity == "avoidable" else "[yellow]⚠[/]"
        lines.append(f"{icon} {tip.message}")
        lines.append(f"  [dim]→ {tip.fix_hint}[/]")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Detail text builders
# ---------------------------------------------------------------------------

def _tool_event_detail(evt: SessionEvent) -> str:
    """Build detail text for a tool event."""
    cls = evt.classification or "neutral"
    sym = _CLASS_SYMBOLS.get(cls, "○")
    color = _CLASS_COLORS.get(cls, "dim")

    lines = [
        f"[bold]{evt.tool_name}[/]  [{color}]{sym} {cls}[/]",
        f"Time: {evt.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Model: {evt.model or '-'}",
        "",
    ]

    if evt.tool_input:
        lines.append("[bold]Input:[/]")
        for k, v in evt.tool_input.items():
            val = str(v)
            if len(val) > 500:
                val = val[:500] + "…"
            lines.append(f"  [cyan]{k}:[/] {val}")
        lines.append("")

    if evt.cost_usd is not None:
        est = " (estimated)" if evt.cost_is_estimated else ""
        lines.append(f"[bold]Cost:[/] ${evt.cost_usd:.4f}{est}")

    if evt.waste_reason:
        tag = _WASTE_TAGS.get(evt.waste_reason, evt.waste_reason)
        lines.append(
            f"[bold]Reason:[/] [{color}]{evt.waste_reason}[/] ({tag})"
        )

    if evt.blame_target:
        bt = evt.blame_target
        lines.append(f"[bold]Blame:[/] {bt.level} → {bt.name}")
        lines.append(f"[bold]Fix:[/] [dim]{bt.fix_hint}[/]")

    return "\n".join(lines)


def _file_path_input_detail(inp: dict) -> str:
    """Extract a shortened file_path (last 2 path segments) from tool input."""
    path = inp.get("file_path", "")
    if "/" in path:
        parts = path.split("/")
        path = "/".join(parts[-2:])
    return path


# tool_name -> (inp -> untruncated detail string). Each entry handles one
# tool's input shape; Read/Edit/Write/MultiEdit share the file_path handler.
_INPUT_DETAIL_BUILDERS: dict[str, Callable[[dict], str]] = {
    "Bash": lambda inp: inp.get("command", ""),
    "Read": _file_path_input_detail,
    "Edit": _file_path_input_detail,
    "Write": _file_path_input_detail,
    "MultiEdit": _file_path_input_detail,
    "Grep": lambda inp: f'"{inp.get("pattern", "")}" in {inp.get("path", ".")}',
    "Glob": lambda inp: inp.get("pattern", ""),
    "Agent": lambda inp: inp.get("description", ""),
    "Skill": lambda inp: inp.get("skill", ""),
}


def _event_input_detail(tool_name: str, evt: SessionEvent) -> str:
    """Extract a short display string for an event's tool input, by tool type."""
    inp = evt.tool_input or {}
    builder = _INPUT_DETAIL_BUILDERS.get(tool_name)
    detail = builder(inp) if builder is not None else _event_desc(evt)
    return detail[:60]


def _render_cls_group(
    cls: str, group: list[SessionEvent], tool_name: str
) -> list[str]:
    """Render one classification group as markup lines for _tool_stat_detail."""
    sym = _CLASS_SYMBOLS.get(cls, "○")
    color = _CLASS_COLORS.get(cls, "dim")
    lines = [f"[{color}]{sym} {cls}[/] ({len(group)}):"]
    for e in group:
        cost = f"${e.cost_usd:.4f}" if e.cost_usd else ""
        tag = f" [{_WASTE_TAGS.get(e.waste_reason, '')}]" if e.waste_reason else ""
        detail = _event_input_detail(tool_name, e)
        lines.append(
            f"  [dim]{e.timestamp.strftime('%H:%M:%S')}[/]"
            f" {detail}  [dim]{cost}[/][{color}]{tag}[/]"
        )
    lines.append("")
    return lines


def _tool_stat_detail(
    stat: ToolStats, events: list[SessionEvent]
) -> str:
    """Build detail text for a tool stat, with per-call breakdown."""
    tool_events = [
        e for e in events
        if e.event_type == "tool_use" and e.tool_name == stat.tool_name
    ]

    lines = [
        f"[bold]{stat.tool_name}[/]  ({stat.count} calls, ${stat.cost:.2f})",
        f"Avoidable: {stat.avoidable_count}   Review: {stat.review_count}",
        "",
    ]

    by_cls: dict[str, list[SessionEvent]] = {}
    for e in tool_events:
        cls = e.classification or "neutral"
        by_cls.setdefault(cls, []).append(e)

    for cls in ("avoidable", "review", "productive", "neutral"):
        group = by_cls.get(cls, [])
        if group:
            lines.extend(_render_cls_group(cls, group, stat.tool_name))

    return "\n".join(lines)


def _tip_detail(tip: Tip) -> str:
    """Build detail text for a tip."""
    icon = "✗" if tip.severity == "avoidable" else "⚠"
    color = "red" if tip.severity == "avoidable" else "yellow"
    lines = [
        f"[{color}]{icon}[/] [bold]{tip.waste_reason}[/]  ({tip.severity})",
        "",
        f"[bold]Occurrences:[/] {tip.count}",
        f"[bold]Cost impact:[/] ${tip.cost_impact:.4f}",
        "",
        f"[bold]Blame:[/] {tip.blame_target.level} → {tip.blame_target.name}",
        "",
        "[bold]Fix:[/]",
        f"  {tip.fix_hint}",
    ]
    return "\n".join(lines)


def _agent_detail(agent: AgentSummary) -> str:
    """Build detail text for an agent."""
    lines = [
        f"[bold]{agent.description}[/]",
        "",
        f"Agent ID: {agent.agent_id}",
        f"Type: {agent.agent_type}",
        f"Model: {agent.model}",
        f"Duration: {agent.duration_ms / 1000:.1f}s",
        f"Tool calls: {agent.total_tool_uses}",
        f"Total tokens: {_format_tokens(agent.total_tokens)}",
        f"Cost: {_format_cost(agent.cost_usd, agent.cost_is_estimated)}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Static console print helpers
# ---------------------------------------------------------------------------

def _print_tool_stats_panel(console: Console, summary: SessionSummary) -> None:
    """Print the tool breakdown panel to console, if any stats exist."""
    if not summary.tool_stats:
        return
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1), expand=True)
    table.add_column("Tool", style="cyan", no_wrap=True)
    table.add_column("Calls", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Rel. Cost", no_wrap=True)
    table.add_column("Avoid", justify="right")
    sorted_stats = sorted(summary.tool_stats.values(), key=lambda s: s.cost, reverse=True)[:6]
    max_cost = sorted_stats[0].cost if sorted_stats else 1.0
    for stat in sorted_stats:
        frac = stat.cost / max_cost if max_cost > 0 else 0.0
        avoid_str = str(stat.avoidable_count) if stat.avoidable_count else "—"
        table.add_row(
            stat.tool_name, str(stat.count), f"${stat.cost:.3f}", _bar(frac, 8), avoid_str,
        )
    console.print(Panel(table, title="[bold]Tool Breakdown[/]", border_style="magenta"))


def _print_agents_panel(console: Console, agents: list[AgentSummary]) -> None:
    """Print the agents panel to console, if any agents exist."""
    if not agents:
        return
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1), expand=True)
    table.add_column("Description", style="cyan", max_width=25)
    table.add_column("Type")
    table.add_column("Model")
    table.add_column("Duration", justify="right")
    table.add_column("Tools", justify="right")
    table.add_column("Cost", justify="right")
    for a in agents:
        desc = (a.description[:25] if a.description else "—")
        model_short = a.model.split("/")[-1] if a.model else "—"
        table.add_row(
            desc, a.agent_type, model_short,
            f"{a.duration_ms / 1000:.1f}s",
            str(a.total_tool_uses),
            _format_cost(a.cost_usd, a.cost_is_estimated),
        )
    console.print(Panel(table, title="[bold]Agents[/]", border_style="yellow"))


def _render_timeline_line(evt: SessionEvent) -> str:
    """Format a single tool event as a timeline markup line."""
    ts = evt.timestamp.strftime("%H:%M:%S")
    cls = evt.classification or "neutral"
    sym = _CLASS_SYMBOLS.get(cls, "○")
    color = _CLASS_COLORS.get(cls, "dim")
    tool = (evt.tool_name or "")[:10]
    desc = _event_desc(evt)
    cost_str = f"${evt.cost_usd:.4f}" if evt.cost_usd else ""
    tag = _WASTE_TAGS.get(evt.waste_reason, evt.waste_reason[:4].upper()) if evt.waste_reason else ""
    tag_str = f" [{tag}]" if tag else ""
    return (
        f"[dim]{ts}[/] [{color}]{sym}[/] [cyan]{tool:<10}[/]"
        f" {desc:<30} [dim]{cost_str}[/][{color}]{tag_str}[/]"
    )


# ---------------------------------------------------------------------------
# Stats panel renderers
# ---------------------------------------------------------------------------

def _stats_duration_str(summary: SessionSummary) -> str:
    """Format elapsed duration as HH:MM:SS."""
    if summary.end_time:
        delta = (summary.end_time - summary.start_time).total_seconds()
    else:
        delta = (datetime.now(timezone.utc) - summary.start_time).total_seconds()
    mins, secs = divmod(int(delta), 60)
    hours, mins = divmod(mins, 60)
    return f"{hours:02d}:{mins:02d}:{secs:02d}"


def _stats_session_label(summary: SessionSummary) -> str:
    """Extract a short session label from project path or session ID."""
    if summary.project_path:
        parts = [p for p in summary.project_path.split("/") if p]
        if parts:
            return parts[-1][:24]
    return summary.session_id[:16]


def _efficiency_color(score: float) -> str:
    """Map an efficiency score to a Rich color name."""
    if score >= 75:
        return "green"
    if score >= 50:
        return "yellow"
    return "red"


def _render_stats_panel(summary: SessionSummary) -> Panel:
    """Render a bordered multi-line stats panel using Rich."""
    model_short = summary.model.split("/")[-1] if summary.model else "unknown"
    duration = _stats_duration_str(summary)
    cost_str = _format_cost(summary.total_cost, summary.cost_is_estimated)
    cache_str = (
        f"{summary.cache_hit_rate * 100:.0f}%"
        if summary.cache_hit_rate is not None else "n/a"
    )
    session_label = _stats_session_label(summary)
    in_tok = _format_tokens(summary.input_tokens)
    out_tok = _format_tokens(summary.output_tokens)
    eff_bar = _bar(summary.efficiency_score / 100.0, width=10)
    eff_color = _efficiency_color(summary.efficiency_score)

    row1 = (
        f"  [bold]Model:[/] {model_short}"
        f"   [bold]Duration:[/] {duration}"
        f"   [bold]Cost:[/] {cost_str}"
        f"   [bold]Cache:[/] {cache_str}"
    )
    row2 = (
        f"  [bold]In:[/] {in_tok}"
        f"  [bold]Out:[/] {out_tok}"
        f"   [bold]Efficiency:[/] [{eff_color}]{eff_bar}[/] {summary.efficiency_score:.0f}%"
        f"   [green]✓[/] {summary.productive_count} prod"
        f"  [red]✗[/] {summary.avoidable_count} avoid"
        f"  [dim]○[/] {summary.neutral_count} neut"
    )
    body = row1 + "\n" + row2
    title = f"[bold]Session:[/] {session_label}"
    return Panel(body, title=title, border_style="cyan")


def _render_stats_compact(summary: SessionSummary) -> str:
    """Render a single-line compact stats string."""
    model_short = summary.model.split("/")[-1] if summary.model else "unknown"
    duration = _stats_duration_str(summary)
    cost_str = _format_cost(summary.total_cost, summary.cost_is_estimated)
    in_tok = _format_tokens(summary.input_tokens)
    out_tok = _format_tokens(summary.output_tokens)
    cache_str = (
        f"{summary.cache_hit_rate * 100:.0f}%↑"
        if summary.cache_hit_rate is not None else "n/a"
    )
    eff_bar = _bar(summary.efficiency_score / 100.0, width=8)
    eff_color = _efficiency_color(summary.efficiency_score)
    return (
        f"[bold]{model_short}[/] {cost_str}"
        f" | {in_tok} in {out_tok} out {cache_str}"
        f" | eff:[{eff_color}]{eff_bar}[/] {summary.efficiency_score:.0f}%"
        f" | [green]✓[/]{summary.productive_count}"
        f" [red]✗[/]{summary.avoidable_count}"
        f" | {duration}"
    )
